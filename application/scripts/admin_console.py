"""Private Admin composition. Install beside the protected Slice 1 inventory tools."""

import argparse
from dataclasses import asdict
from functools import partial
import json
import hashlib
import uvicorn
import os
from pathlib import Path
import pwd
import stat
import signal
import subprocess
import sys

from app.modules.hosted_access.application.admin_commands import (
    AccessCommand,
    AccessResult,
    AccessStatus,
)
from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.broker import Broker, MAX_FRAME, rpc

if __package__:
    from .host_admin import HostPaths, HostDiscovery, lock_host, protected, read_json
    from .host_inventory import HostInventory, InventoryError
else:
    directory = Path(__file__).absolute().parent
    for item in (
        directory,
        *directory.parents,
        directory / "host_admin.py",
        directory / "host_inventory.py",
    ):
        info = item.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise SystemExit("Install the Admin tooling in a protected root-owned directory.")
    sys.path.insert(0, str(directory))
    from host_admin import HostPaths, HostDiscovery, lock_host, protected, read_json
    from host_inventory import HostInventory, InventoryError


def source_process(argv, **options):
    """Terminate the source process group before releasing authority/maintenance locks."""
    timeout, input_text = options.pop("timeout"), options.pop("input")
    options.pop("capture_output")
    options.pop("check")
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        **options,
    ) as process:
        try:
            stdout, stderr = process.communicate(input_text, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise AdminError("admin_source_command_unavailable", 503) from error
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


class SourceRunner:
    def __init__(self, paths, inventory, run=source_process):
        self.paths, self.inventory, self.run = paths, inventory, run

    def prepare(self, key):
        instance = self.inventory.get(key)
        config = self.paths.configs / f"hosted-{instance.key}.json"
        deployment = read_json(config, self.paths)
        local = read_json(Path(instance.local_config), self.paths)
        if any(
            deployment[field] != expected
            for field, expected in {
                "operator_id": instance.operator_id,
                "workspace_id": instance.workspace_id,
                "administration_database": instance.access_database,
                "allowed_email": instance.email,
                "deployment_mode": "hosted_demo",
            }.items()
        ):
            raise AdminError("admin_source_binding_changed", 409)
        return {
            "instance": asdict(instance),
            "deployment_digest": hashlib.sha256(config.read_bytes()).hexdigest(),
            "local_digest": hashlib.sha256(json.dumps(local, sort_keys=True).encode()).hexdigest(),
        }

    def status(self, key):
        descriptor = lock_host(self.inventory)
        try:
            instance = self.prepare(key)["instance"]
            return AccessStatus.model_validate(
                self._transport(instance, {"query": "status"})
            ).model_dump()
        finally:
            os.close(descriptor)

    def __call__(self, payload):
        descriptor = lock_host(self.inventory)
        try:
            reference = self.prepare(payload["instance"])
            original = payload.get("source_reference", {}).get("instance", {})
            identity_fields = (
                "instance_id",
                "allocation_id",
                "operator_id",
                "workspace_id",
                "access_database",
                "user",
            )
            if any(original.get(key) != reference["instance"][key] for key in identity_fields):
                raise AdminError("admin_source_binding_changed", 409)
            command = self._command(payload)
            receipt = self._transport(
                reference["instance"], {"query": "receipt", "command": command.model_dump()}
            )
            if receipt.get("found"):
                return AccessResult.model_validate(receipt["result"]).model_dump()
            if payload.get("source_reference") != reference:
                raise AdminError("admin_source_binding_changed", 409)
            with self.inventory.connection() as connection:
                if connection.execute(
                    "SELECT 1 FROM maintenance WHERE state != 'reconciled'"
                ).fetchone():
                    raise AdminError("admin_private_maintenance_pending", 409)
            if command.action not in {"disable", "revoke"}:
                HostDiscovery(self.paths).source_command_ready(
                    self.inventory.get(payload["instance"])
                )
            return self._run(payload, reference["instance"])
        finally:
            os.close(descriptor)

    def _run(self, payload, instance):
        return AccessResult.model_validate(
            self._transport(instance, self._command(payload).model_dump())
        ).model_dump()

    @staticmethod
    def _command(payload):
        return AccessCommand.model_validate(
            {
                key: value
                for key, value in payload.items()
                if key not in {"instance", "confirmed", "source_reference"}
            }
        )

    def _transport(self, instance, request):
        executable = self.paths.releases / instance["release"] / "venv/bin/python"
        # Installed Python executables may be symlinks to system Python; qualify the
        # resolved binary and every directory, never accept a browser executable.
        protected(executable.resolve(strict=True), self.paths)
        protected(executable.parent, self.paths, regular=False)
        config = self.paths.configs / f"hosted-{instance['key']}.json"
        result = self.run(
            [
                "/usr/sbin/runuser",
                "-u",
                instance["user"],
                "--",
                str(executable),
                "-I",
                "-m",
                "app.modules.hosted_access.infrastructure.command_cli",
                str(config),
                instance["local_config"],
            ],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
            cwd="/",
        )
        if result.returncode != 0 or len(result.stdout.encode()) > MAX_FRAME:
            raise AdminError("admin_source_command_failed", 503)
        value = json.loads(result.stdout)
        if "error" in value:
            raise AdminError(value["error"], value["status"])
        return value


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "action",
        choices=(
            "initialize",
            "broker",
            "serve",
            "bootstrap",
            "action-grant",
            "revoke-identity",
            "restore-identity",
        ),
    )
    value.add_argument("--identity")
    value.add_argument("--port", type=int)
    return value


MIN_PORT = 1024
MAX_PORT = 65535


def main():
    args = parser().parse_args()
    path = "/run/epm-admin/broker.sock"
    if args.action == "serve":
        if os.geteuid() == 0 or os.geteuid() != pwd.getpwnam("epm-admin-http").pw_uid:
            raise AdminError("admin_http_identity_invalid")
        if args.port is None or not MIN_PORT <= args.port <= MAX_PORT:
            raise AdminError("admin_port_required")
        app = create_admin_app(f"http://epm-admin.localhost:{args.port}", partial(rpc, path))
        uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)
        return
    if os.geteuid() != 0:
        raise AdminError("admin_private_peer_required")
    if args.action in {"bootstrap", "action-grant", "revoke-identity", "restore-identity"}:
        method = {
            "bootstrap": "bootstrap",
            "action-grant": "action_grant",
            "revoke-identity": "revoke_identity",
            "restore-identity": "restore_identity",
        }[args.action]
        payload = {"method": method}
        if args.action == "action-grant":
            payload["command"] = json.loads(sys.stdin.read(MAX_FRAME + 1))
        result = rpc(path, payload)
        print(result["credential"] if "credential" in result else json.dumps(result))
        return
    store_path = Path("/var/lib/epm-admin/authority/authority.sqlite")
    paths = HostPaths()
    if args.action == "initialize":
        if not args.identity:
            raise AdminError("admin_identity_required")
        protected(store_path.parent, paths, regular=False, private=True)
        AuthorityStore.initialize(store_path, args.identity)
        return
    protected(store_path, paths, private=True)
    authority = AuthorityStore(store_path)
    inventory = HostInventory(paths.control / "inventory.sqlite")
    http = pwd.getpwnam("epm-admin-http")
    if any(pwd.getpwnam(instance.user).pw_uid == http.pw_uid for instance in inventory.list()):
        raise AdminError("admin_http_identity_not_isolated", 503)
    Broker(authority, http.pw_uid, SourceRunner(paths, inventory)).serve(path, http.pw_gid)


if __name__ == "__main__":
    try:
        main()
    except (AdminError, InventoryError, OSError, ValueError) as _error:
        raise SystemExit(
            "Admin command denied or unavailable; review the private installation."
        ) from None
