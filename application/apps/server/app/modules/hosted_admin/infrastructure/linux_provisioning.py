"""Fixed Linux effects for operation-owned synthetic instances. No arbitrary exec port."""

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import fnmatch
import json
import os
from pathlib import Path
import pwd
import socket
import tempfile
from uuid import NAMESPACE_URL, uuid5

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import Observation, canonical, fingerprint
from app.modules.hosted_access.application.admin_commands import (
    AccessCommand,
    AccessStatus,
    AccessResult,
)
from app.modules.hosted_access.application.configuration import HostedConfigurationError
from app.modules.hosted_access.infrastructure.storage_budget import validate_root_reserve

WORKSPACE_BYTES = 250 * 1024 * 1024


class LinuxProvisioning:
    def __init__(self, host, run):
        self.h, self.run = host, run

    def configuration(self):
        return self.h.read_json(self.h.paths.control / "provisioning/config.json", self.h.paths)

    def provider_token(self):
        path = self.h.paths.control / "provisioning/cloudflare.token"
        self.h.protected(path, self.h.paths, private=True)
        value = path.read_text().strip()
        if not 20 <= len(value) <= 256 or any(character.isspace() for character in value):
            raise AdminError("admin_provider_credential_unavailable", 503)
        return value

    def paths_for(self, key):
        home = self.h.paths.data / ("epm-" + key)
        return {
            "home": home,
            "volume": home / "volume",
            "image": self.h.paths.data / "epm-volumes" / ("epm-" + key + ".ext4"),
            "workspace": home / "volume/workspace",
            "local": home / "config.json",
            "access": home / "access/access.sqlite",
            "deployment": self.h.paths.configs / f"hosted-{key}.json",
            "unit": self.h.paths.systemd / f"epm-hosted@{key}.service",
            "marker": self.h.paths.control / "provisioning" / (key + ".json"),
        }

    @contextmanager
    def lock(self):
        descriptor = self.h.lock_host(self.h.inventory)
        try:
            with self.h.inventory.connection() as connection:
                if connection.execute(
                    "SELECT 1 FROM maintenance WHERE state!='reconciled'"
                ).fetchone():
                    raise AdminError("admin_private_maintenance_pending", 409)
            yield
        finally:
            os.close(descriptor)

    def preflight(self, plan, config):
        release = self.h.paths.releases / config.release
        evidence = self.h.discovery._release(release)
        if evidence["manifest_digest"] != config.release_digest:
            raise AdminError("admin_release_changed", 409)
        files = [release / "admin-seed/seed.py", release / "admin-seed/dataset.json"]
        for path in files:
            self.h.protected(path, self.h.paths)
        if (
            fingerprint([hashlib.sha256(path.read_bytes()).hexdigest() for path in files])
            != config.template_digest
        ):
            raise AdminError("admin_template_changed", 409)
        if plan["key"] in self.h.discovery.keys():
            raise AdminError("admin_allocation_conflict", 409)
        if any(path.exists() or path.is_symlink() for path in self.paths_for(plan["key"]).values()):
            raise AdminError("admin_allocation_conflict", 409)
        try:
            pwd.getpwnam("epm-" + plan["key"])
        except KeyError:
            pass
        else:
            raise AdminError("admin_allocation_conflict", 409)
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", plan["port"]))
            except OSError as error:
                raise AdminError("admin_port_in_use", 409) from error

    def call(self, argv, *, timeout=20):
        result = self.run(
            argv,
            input="",
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
            cwd="/",
        )
        if result.returncode or len(result.stdout.encode()) > 16384:
            raise AdminError("admin_setup_private_step_failed", 503)
        return result.stdout

    def owned(self, payload, *, create=False):
        plan = payload["setup"]["plan"]
        paths = self.paths_for(plan["key"])
        expected = {"operation_id": payload["operation_id"], "spec_hash": fingerprint(payload)}
        if not paths["marker"].exists():
            if not create:
                return False
            if any(
                path.exists() or path.is_symlink()
                for name, path in paths.items()
                if name != "marker"
            ):
                raise AdminError("admin_allocation_conflict", 409)
            self.publish(paths["marker"], canonical(expected).encode())
        if self.h.read_json(paths["marker"], self.h.paths) != expected:
            raise AdminError("admin_allocation_owner_conflict", 409)
        return True

    def publish(self, path, content, group=0):
        self.h.protected(path.parent, self.h.paths, regular=False)
        if path.exists() or path.is_symlink():
            self.h.protected(path, self.h.paths)
            if path.read_bytes() != content:
                raise AdminError("admin_setup_configuration_conflict", 409)
            return
        descriptor, temporary = tempfile.mkstemp(prefix=".setup-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                os.fchown(stream.fileno(), 0, group)
                os.fchmod(stream.fileno(), 0o640 if group else 0o600)
                stream.flush()
                os.fsync(stream.fileno())
            # Never replace a pre-existing destination, even after a crash/race.
            os.link(temporary, path, follow_symlinks=False)
            self.sync(path.parent)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def sync(path):
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def directory(self, path, uid=0, gid=0, mode=0o700):
        if not path.exists():
            self.h.protected(path.parent, self.h.paths, uid, regular=False)
            path.mkdir(mode=mode)
            os.chown(path, uid, gid)
        self.h.protected(path, self.h.paths, uid, regular=False)

    def inspect(self, payload, step, config):
        if not self.owned(payload):
            return Observation("absent")
        paths = self.paths_for(payload["target"])
        try:
            if step == "allocate":
                if not paths["image"].exists() or not os.path.ismount(paths["volume"]):
                    return Observation("absent")
                self.allocation_verified(payload)
            else:
                marker = paths["marker"].with_suffix(".workspace.json")
                if not marker.exists():
                    return Observation("absent")
                expected = {
                    "workspace_id": payload["setup"]["plan"]["workspace_id"],
                    "verified": True,
                }
                if self.h.read_json(marker, self.h.paths) != expected:
                    return Observation("conflict")
                if self.workspace(payload, config, "verify") != expected:
                    return Observation("conflict")
        except FileNotFoundError, KeyError:
            return Observation("absent")
        return Observation("verified", {"verified": True}, payload["target"])

    def allocation_verified(self, payload):
        paths = self.paths_for(payload["target"])
        identity = pwd.getpwnam("epm-" + payload["target"])
        if (
            identity.pw_gecos != "epm-setup:" + payload["operation_id"]
            or identity.pw_shell != "/usr/sbin/nologin"
        ):
            raise AdminError("admin_allocation_owner_conflict", 409)
        self.h.protected(paths["image"], self.h.paths, private=True)
        info = paths["image"].stat()
        if info.st_size != WORKSPACE_BYTES or info.st_blocks * 512 < WORKSPACE_BYTES:
            raise AdminError("admin_volume_allocation_incomplete", 409)
        self.h.discovery._mount(paths["volume"], paths["image"])
        try:
            validate_root_reserve(paths["volume"])
        except HostedConfigurationError as error:
            raise AdminError("admin_volume_reserve_incomplete", 409) from error
        self.h.protected(paths["volume"] / "tmp", self.h.paths, identity.pw_uid, regular=False)

    def apply(self, payload, step, config):
        self.owned(payload, create=True)
        if step == "allocate":
            self.allocate(payload)
        elif step == "workspace":
            result = self.workspace(payload, config, "prepare")
            marker = self.paths_for(payload["target"])["marker"].with_suffix(".workspace.json")
            self.publish(marker, canonical(result).encode())
        else:
            raise AdminError("admin_setup_step_invalid", 409)

    def allocate(self, payload):
        key = payload["target"]
        paths = self.paths_for(key)
        try:
            identity = pwd.getpwnam("epm-" + key)
        except KeyError:
            self.call(
                [
                    "/usr/sbin/useradd",
                    "--system",
                    "--user-group",
                    "--no-create-home",
                    "--home-dir",
                    str(paths["home"]),
                    "--shell",
                    "/usr/sbin/nologin",
                    "--comment",
                    "epm-setup:" + payload["operation_id"],
                    "epm-" + key,
                ]
            )
            identity = pwd.getpwnam("epm-" + key)
        if identity.pw_gecos != "epm-setup:" + payload["operation_id"]:
            raise AdminError("admin_allocation_owner_conflict", 409)
        self.directory(paths["home"], gid=identity.pw_gid, mode=0o750)
        self.directory(paths["access"].parent, identity.pw_uid, identity.pw_gid)
        self.directory(paths["image"].parent)
        self.directory(paths["volume"], identity.pw_uid, identity.pw_gid)
        self.image(payload)
        self.mount(payload)
        os.chown(paths["volume"], identity.pw_uid, identity.pw_gid)
        for child in ("tmp", "backups"):
            self.directory(paths["volume"] / child, identity.pw_uid, identity.pw_gid)
        self.publish(
            paths["local"],
            canonical({"localWorkspacePath": str(paths["workspace"])}).encode(),
            identity.pw_gid,
        )
        self.allocation_verified(payload)

    def image(self, payload):
        image = self.paths_for(payload["target"])["image"]
        if not image.exists():
            descriptor = os.open(image, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            try:
                os.posix_fallocate(descriptor, 0, WORKSPACE_BYTES)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self.h.protected(image, self.h.paths, private=True)
        if image.stat().st_size > WORKSPACE_BYTES:
            raise AdminError("admin_volume_identity_conflict", 409)
        if image.stat().st_size < WORKSPACE_BYTES or image.stat().st_blocks * 512 < WORKSPACE_BYTES:
            descriptor = os.open(image, os.O_WRONLY | os.O_NOFOLLOW)
            try:
                os.posix_fallocate(descriptor, 0, WORKSPACE_BYTES)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        # An owned but not formatted allocation can resume safely. Refuse a
        # different filesystem identity; never format existing unrelated bytes.
        desired = str(uuid5(NAMESPACE_URL, payload["operation_id"] + ":filesystem"))
        result = self.run(
            ["/usr/sbin/blkid", "-p", "-s", "UUID", "-o", "value", str(image)],
            input="",
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 2 and not result.stdout.strip():
            self.call(
                [
                    "/usr/sbin/mkfs.ext4",
                    "-q",
                    "-m",
                    "10",
                    "-E",
                    "nodiscard,lazy_itable_init=0,lazy_journal_init=0",
                    "-U",
                    desired,
                    str(image),
                ]
            )
        elif result.returncode or result.stdout.strip() != desired:
            raise AdminError("admin_volume_identity_conflict", 409)
        info = image.stat()
        if info.st_size != WORKSPACE_BYTES or info.st_blocks * 512 < WORKSPACE_BYTES:
            raise AdminError("admin_volume_allocation_incomplete", 409)

    def mount(self, payload):
        paths = self.paths_for(payload["target"])
        # fstab is shared: read the latest under the host lock and preserve every
        # unrelated entry. Never restore a saved whole-file snapshot.
        self.h.protected(self.h.paths.fstab, self.h.paths)
        current = self.h.paths.fstab.read_text()
        line = f"{paths['image']} {paths['volume']} ext4 loop,nodev,nosuid,noexec 0 0"
        related = [
            item
            for item in current.splitlines()
            if not item.lstrip().startswith("#")
            and any(str(path) in item.split()[:2] for path in (paths["image"], paths["volume"]))
        ]
        if related and related != [line]:
            raise AdminError("admin_mount_configuration_conflict", 409)
        if not related:
            descriptor, temporary = tempfile.mkstemp(dir=self.h.paths.fstab.parent)
            try:
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(current.rstrip("\n") + "\n" + line + "\n")
                    os.fchmod(stream.fileno(), 0o644)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.h.paths.fstab)
                self.sync(self.h.paths.fstab.parent)
            finally:
                Path(temporary).unlink(missing_ok=True)
        if not os.path.ismount(paths["volume"]):
            self.call(["/usr/bin/mount", str(paths["volume"])])
        self.h.discovery._mount(paths["volume"], paths["image"])

    def workspace(self, payload, config, action):
        self.allocation_verified(payload)
        plan = payload["setup"]["plan"]
        release = self.h.paths.releases / config.release
        executable = release / "venv/bin/python"
        self.h.protected(executable.resolve(strict=True), self.h.paths)
        argv = [
            "/usr/sbin/runuser",
            "-u",
            "epm-" + plan["key"],
            "--",
            str(executable),
            "-I",
            "-m",
            "app.modules.hosted_admin.infrastructure.prepare_workspace",
            action,
            str(self.paths_for(plan["key"])["local"]),
            plan["workspace_id"],
            payload["setup"]["data"]["template"],
            "--seed",
            str(release / "admin-seed/seed.py"),
        ]
        return json.loads(self.call(argv, timeout=180))

    def verify_ingress(self, plan, *, upgrading=None):
        # The first installation uses a protected JSON-formatted cloudflared
        # config (also valid YAML), qualified with the existing local tunnel.
        path = self.h.paths.configs / "cloudflared-admin.json"
        config = self.h.read_json(path, self.h.paths)
        routes = config.get("ingress", [])
        if not routes or routes[-1] != {"service": "http_status:404"}:
            raise AdminError("admin_tunnel_catchall_unverified", 409)
        matched = [route for route in routes if route.get("hostname") == plan["hostname"]]
        expected = {"hostname": plan["hostname"], "service": f"http://127.0.0.1:{plan['port']}"}
        if matched != [expected]:
            raise AdminError("admin_tunnel_route_unverified", 409)
        for route in routes[: routes.index(expected)]:
            if fnmatch.fnmatchcase(plan["hostname"], route.get("hostname", "*")):
                raise AdminError("admin_tunnel_route_shadowed", 409)
        for item in self.h.inventory.list():
            retained = {"hostname": item.hostname, "service": f"http://127.0.0.1:{item.port}"}
            if [route for route in routes if route.get("hostname") == item.hostname] != [retained]:
                raise AdminError("admin_existing_route_changed", 409)
            if item.key != upgrading:
                self.h.discovery.source_command_ready(item)
        self.call(["/usr/bin/cloudflared", "--config", str(path), "tunnel", "ingress", "validate"])
        effective = self.h.discovery.systemctl(
            "show", "epm-cloudflared.service", "--property=ExecStart", "--value"
        )
        if f"--config {path} " not in effective:
            raise AdminError("admin_tunnel_configuration_unverified", 409)

    def start(self, payload, deployment):
        plan, data = payload["setup"]["plan"], payload["setup"]["data"]
        paths = self.paths_for(plan["key"])
        identity = pwd.getpwnam("epm-" + plan["key"])
        deployment = deployment | {
            "administration_database": str(paths["access"]),
            "storage_volume": str(paths["volume"]),
            "storage_image": str(paths["image"]),
        }
        self.publish(paths["deployment"], canonical(deployment).encode(), identity.pw_gid)
        config = self.configuration()
        self.publish(paths["unit"], self.unit(plan, config).encode())
        self.call(["/usr/bin/systemctl", "daemon-reload"])
        self.call(["/usr/bin/systemctl", "enable", f"epm-hosted@{plan['key']}.service"])
        if self.service_state(plan["key"]) != "active":
            self.call(["/usr/bin/systemctl", "start", f"epm-hosted@{plan['key']}.service"])
        observed = self.h.discovery.observe(plan["key"])
        self.match_observation(observed, payload)
        known = [item for item in self.h.inventory.list() if item.key == plan["key"]]
        if not known:
            baseline = self.h.save_baseline(self.h.inventory, observed)
            fields = observed["fields"] | {
                "instance_id": plan["instance_id"],
                "allocation_id": plan["allocation_id"],
                "baseline_digest": baseline,
                "template": data["template"],
            }
            self.h.inventory.register(self.h.instance_type(**fields))
        self.source_status(plan["key"])

    def service_state(self, key):
        return self.h.discovery.systemctl(
            "show", f"epm-hosted@{key}.service", "--property=ActiveState", "--value"
        ).strip()

    def source_status(self, key):
        return self.h.source._transport(asdict(self.h.inventory.get(key)), {"query": "status"})

    def deployment_digest(self, plan):
        return hashlib.sha256(self.paths_for(plan["key"])["deployment"].read_bytes()).hexdigest()

    def backup(self, payload, phrase):
        plan = payload["setup"]["plan"]
        paths = self.paths_for(plan["key"])
        identity = pwd.getpwnam("epm-" + plan["key"])
        directory = self.h.paths.backups / ("epm-" + plan["key"])
        self.directory(directory, identity.pw_uid, identity.pw_gid)
        staging = directory / "staging"
        self.directory(staging, identity.pw_uid, identity.pw_gid)
        output = directory / (
            "pre-enrollment-" + uuid5(NAMESPACE_URL, payload["operation_id"]).hex + ".epm-backup"
        )
        # Preserve completed artifacts on failure/retry; use a fresh publication.
        if output.exists():
            from uuid import uuid4

            output = directory / ("pre-enrollment-" + uuid4().hex + ".epm-backup")
        self.call(["/usr/bin/systemctl", "stop", f"epm-hosted@{plan['key']}.service"])
        executable = self.h.paths.releases / payload["setup"]["data"]["release"] / "venv/bin/python"
        self.h.protected(executable.resolve(strict=True), self.h.paths)
        result = self.run(
            [
                "/usr/sbin/runuser",
                "-u",
                identity.pw_name,
                "--",
                str(executable),
                "-I",
                "-m",
                "app.modules.hosted_admin.infrastructure.pre_enrollment_source",
                str(paths["deployment"]),
                str(paths["local"]),
                plan["workspace_id"],
                str(output),
                str(staging),
            ],
            input=phrase,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "TMPDIR": str(paths["volume"] / "tmp"),
            },
            cwd="/",
        )
        if (
            result.returncode
            or len(result.stdout.encode()) > 16384
            or json.loads(result.stdout) != {"workspace_id": plan["workspace_id"], "verified": True}
        ):
            raise AdminError("admin_pre_enrollment_backup_failed", 503)
        return output

    def restart_pending(self, payload):
        if not self.source_status(payload["target"])["active"]:
            self.call(["/usr/bin/systemctl", "start", f"epm-hosted@{payload['target']}.service"])

    def unit(self, plan, config):
        paths = self.paths_for(plan["key"])
        user, release = "epm-" + plan["key"], self.h.paths.releases / config["release"]
        return f"""[Unit]
Description=EPM synthetic demo {plan["key"]}
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3
RequiresMountsFor={paths["volume"]}
[Service]
Type=simple
User={user}
Group={user}
WorkingDirectory={paths["home"]}
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=TMPDIR={paths["volume"]}/tmp
ExecStart={release}/venv/bin/python -m app --config {paths["local"]} serve-hosted --deployment {paths["deployment"]} --port {plan["port"]}
UMask=0077
NoNewPrivileges=true
CapabilityBoundingSet=
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictNamespaces=true
ReadWritePaths={paths["volume"]} {paths["access"].parent}
MemoryHigh={config["memory_bytes"]}
MemoryMax={config["memory_bytes"]}
CPUQuota=90%
Restart=on-failure
TimeoutStopSec=60
[Install]
WantedBy=multi-user.target
"""

    @staticmethod
    def match_observation(observation, payload):
        plan, data = payload["setup"]["plan"], payload["setup"]["data"]
        expected = {
            "operator_id": plan["operator_id"],
            "workspace_id": plan["workspace_id"],
            "email": data["email"],
            "hostname": plan["hostname"],
            "port": plan["port"],
            "release": data["release"],
        }
        if any(observation["fields"].get(key) != value for key, value in expected.items()):
            raise AdminError("admin_runtime_binding_conflict", 409)

    def readiness(self, payload, _deployment):
        known = [item for item in self.h.inventory.list() if item.key == payload["target"]]
        if not known:
            return Observation("absent")
        observed = self.h.discovery.observe(payload["target"])
        self.match_observation(observed, payload)
        self.h.discovery.source_command_ready(known[0])
        if self.source_status(payload["target"])["active"]:
            return Observation("conflict")
        return Observation("verified", {"verified": True}, payload["target"])

    def contain(self, payload):
        if not self.owned(payload):
            return True
        paths = self.paths_for(payload["target"])
        unit = f"epm-hosted@{payload['target']}.service"
        if paths["unit"].exists():
            self.call(["/usr/bin/systemctl", "stop", unit])
            if self.service_state(payload["target"]) not in {"inactive", "failed", "unknown"}:
                return False
        if paths["access"].exists():
            identity = pwd.getpwnam("epm-" + payload["target"])
            self.h.protected(paths["access"], self.h.paths, identity.pw_uid, private=True)
            instance = {
                "key": payload["target"],
                "user": identity.pw_name,
                "release": payload["setup"]["data"]["release"],
                "local_config": str(paths["local"]),
            }
            status = AccessStatus.model_validate(
                self.h.source._transport(instance, {"query": "status"})
            )
            if status.active:
                command = AccessCommand(
                    operation_id=str(uuid5(NAMESPACE_URL, payload["operation_id"] + ":contain")),
                    action="disable",
                    expected_revision=status.admin_revision,
                    expected_binding_revision=status.binding_revision,
                    fence=status.admin_fence,
                    authority_reference="provisioning-containment",
                    reason="Stop fenced setup and revoke access",
                )
                result = AccessResult.model_validate(
                    self.h.source._transport(instance, command.model_dump())
                )
                return not result.active
        return True
