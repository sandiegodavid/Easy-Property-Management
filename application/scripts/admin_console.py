"""Private Admin composition. Install beside the protected Slice 1 inventory tools."""

import argparse
from getpass import getpass
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
from uuid import NAMESPACE_URL, UUID, uuid5
from types import SimpleNamespace

from app.modules.hosted_access.application.admin_commands import (
    AccessCommand,
    AccessResult,
    AccessStatus,
)
from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.broker import Broker, MAX_FRAME, rpc
from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations
from app.modules.hosted_admin.infrastructure.qualification import QualificationService
from app.modules.hosted_admin.infrastructure.verified_reports import VerifiedReports
from app.modules.hosted_admin.infrastructure.console import ConsoleReads
from app.modules.hosted_admin.application.operations import fingerprint
from app.modules.hosted_admin.infrastructure.setup import SetupService, SetupWorker
from app.modules.hosted_admin.infrastructure.provisioning import (
    ProvisioningHost,
    ProvisioningDependencies,
)
from app.modules.hosted_admin.infrastructure.linux_provisioning import LinuxProvisioning
from app.modules.hosted_admin.infrastructure.pre_enrollment import PreEnrollmentRecovery
from app.modules.hosted_admin.infrastructure.onboarding import OnboardingRecovery
from app.modules.hosted_admin.infrastructure.onboarding_verifier import OnboardingVerifier
from app.modules.hosted_admin.infrastructure.edge_denial import EdgeDenial

if __package__:
    from .admin_lifecycle import AccessCutover
    from .admin_observations import HostConsoleInventory
    from .host_admin import (
        HostPaths,
        HostDiscovery,
        lock_host,
        protected,
        read_json,
        publish_baseline as save_baseline,
    )
    from .host_inventory import HostInventory, InventoryError, Instance
else:
    directory = Path(__file__).absolute().parent
    for item in (
        directory,
        *directory.parents,
        directory / "host_admin.py",
        directory / "host_inventory.py",
        directory / "admin_observations.py",
        directory / "admin_lifecycle.py",
    ):
        info = item.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise SystemExit("Install the Admin tooling in a protected root-owned directory.")
    sys.path.insert(0, str(directory))
    from host_admin import (
        HostPaths,
        HostDiscovery,
        lock_host,
        protected,
        read_json,
        publish_baseline as save_baseline,
    )
    from host_inventory import HostInventory, InventoryError, Instance
    from admin_observations import HostConsoleInventory
    from admin_lifecycle import AccessCutover


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
            "deployment": deployment,
        }

    def prepare_command(self, command):
        try:
            return self.prepare(command.instance)
        except OSError, ValueError, KeyError:
            if command.action not in {"disable", "revoke"}:
                raise
            return {"instance": asdict(self.inventory.get(command.instance)), "containment": True}

    def status(self, key):
        return self.access_snapshot(key)[1]

    def access_snapshot(self, key):
        descriptor = lock_host(self.inventory)
        try:
            instance = self.prepare(key)["instance"]
            deployment = read_json(self.paths.configs / f"hosted-{key}.json", self.paths)
            status = AccessStatus.model_validate(
                self._transport(instance, {"query": "status"})
            ).model_dump()
            return deployment, status
        finally:
            os.close(descriptor)

    def __call__(self, payload):
        if payload.get("source_reference", {}).get("containment"):
            self.emergency_contain(payload)
            # Service denial is observed, but a missing source receipt or edge
            # fence is not success. Keep the durable job pending remediation.
            raise AdminError("admin_containment_pending", 503)
        if payload["action"] in {"renew", "replace_email"}:
            return self.cutover(payload)
        activation = None
        if payload["action"] in {"enable", "complete_onboarding"} and hasattr(self, "recovery"):
            # Receipt lookup comes first: a lost response must reconcile even
            # after the evidence expires or a later binding is installed.
            prior = self.reconcile(payload)
            if prior is not None:
                self.recovery.completed(payload, prior)
                return prior
            activation = self.recovery.activation(payload)
        try:
            return self.execute_source(payload, activation)
        except (OSError, ValueError) as error:
            self.contain_unavailable(payload, error)
            raise

    def contain_unavailable(self, payload, error):
        if payload["action"] not in {"disable", "revoke"} or (
            isinstance(error, AdminError)
            and error.code
            not in {"admin_source_command_failed", "admin_source_command_unavailable"}
        ):
            return
        # A stopped unit is containment, not a source receipt. Keep the durable
        # operation pending until the private administrator repairs/reconciles it.
        self.emergency_contain(payload)
        raise AdminError("admin_containment_pending", 503) from error

    def execute_source(self, payload, activation=None):
        descriptor = lock_host(self.inventory)
        try:
            reference = self.checked_reference(payload)
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
                if hasattr(self, "grant_check"):
                    self.grant_check(payload["instance"])
                HostDiscovery(self.paths).source_command_ready(
                    self.inventory.get(payload["instance"])
                )
            if activation is not None:
                result = AccessResult.model_validate(
                    self._transport(
                        reference["instance"], command.model_dump() | {"activation": activation}
                    )
                ).model_dump()
            else:
                result = self._run(payload, reference["instance"])
            if hasattr(self, "recovery"):
                self.recovery.completed(payload, result)
            return result
        finally:
            os.close(descriptor)

    def checked_reference(self, payload):
        reference = self.prepare(payload["instance"])
        original = payload.get("source_reference", {}).get("instance", {})
        fields = (
            "instance_id",
            "allocation_id",
            "operator_id",
            "workspace_id",
            "access_database",
            "user",
        )
        if any(original.get(key) != reference["instance"][key] for key in fields):
            raise AdminError("admin_source_binding_changed", 409)
        return reference

    def reconcile(self, payload):
        """Read the exact original receipt, even after later source revisions."""
        try:
            return self.reconcile_source(payload)
        except (OSError, ValueError) as error:
            self.contain_unavailable(payload, error)
            raise

    def reconcile_source(self, payload):
        if payload.get("source_reference", {}).get("containment"):
            return None
        if payload["action"] in {"renew", "replace_email"}:
            return self.cutover.lookup(payload)
        descriptor = lock_host(self.inventory)
        try:
            current = self.checked_reference(payload)
            receipt = self._transport(
                current["instance"],
                {"query": "receipt", "command": self._command(payload).model_dump()},
            )
            result = (
                AccessResult.model_validate(receipt["result"]).model_dump()
                if receipt.get("found")
                else None
            )
            if result is not None and hasattr(self, "recovery"):
                self.recovery.completed(payload, result)
            return result
        finally:
            os.close(descriptor)

    def contain(self, payload):
        """A stale in-flight grant is contained through the owning access command."""
        if payload.get("source_reference", {}).get("containment"):
            return self.emergency_contain(payload)
        descriptor = lock_host(self.inventory)
        try:
            current = self.checked_reference(payload)
            status = AccessStatus.model_validate(
                self._transport(current["instance"], {"query": "status"})
            )
            if not status.active:
                return True
            command = AccessCommand(
                operation_id=str(uuid5(NAMESPACE_URL, payload["operation_id"] + ":contain")),
                action="disable",
                expected_revision=status.admin_revision,
                expected_binding_revision=status.binding_revision,
                fence=status.admin_fence,
                authority_reference=payload["authority_reference"],
                reason="Contain fenced administration operation",
            )
            result = AccessResult.model_validate(
                self._transport(current["instance"], command.model_dump())
            )
            return not result.active
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
            "operations",
            "verify-pre-enrollment",
            "verify-onboarding",
            "verify-edge-denial",
        ),
    )
    value.add_argument("--operation")
    value.add_argument("--handoff")
    value.add_argument("--identity")
    value.add_argument("--port", type=int)
    return value


MIN_PORT = 1024
MAX_PORT = 65535


def private_request(action, path):
    if action == "operations":
        raw = sys.stdin.read(MAX_FRAME + 1)
        if len(raw.encode()) > MAX_FRAME:
            raise AdminError("admin_request_too_large", 413)
        print(json.dumps(rpc(path, {"method": "private_operations", "request": json.loads(raw)})))
        return True
    if action in {"bootstrap", "action-grant", "revoke-identity", "restore-identity"}:
        method = {
            "bootstrap": "bootstrap",
            "action-grant": "action_grant",
            "revoke-identity": "revoke_identity",
            "restore-identity": "restore_identity",
        }[action]
        payload = {"method": method}
        if action == "action-grant":
            payload["command"] = json.loads(sys.stdin.read(MAX_FRAME + 1))
        result = rpc(path, payload)
        print(result["credential"] if "credential" in result else json.dumps(result))
        return True
    return False


def compose(authority, paths, inventory):
    dispatch = SourceRunner(paths, inventory)
    reports = VerifiedReports(
        paths.control / "qualification-reports",
        lambda: fingerprint([asdict(item) for item in inventory.list()]),
    )
    qualification = QualificationService(authority, reports.snapshot, reports.evidence)
    discovery = HostDiscovery(paths)
    platform = LinuxProvisioning(
        SimpleNamespace(
            paths=paths,
            inventory=inventory,
            source=dispatch,
            discovery=discovery,
            read_json=read_json,
            protected=protected,
            lock_host=lock_host,
            save_baseline=save_baseline,
            instance_type=Instance,
        ),
        source_process,
    )
    dispatch.cutover = AccessCutover(dispatch, platform)

    def emergency_contain(payload):
        item = inventory.get(payload["instance"])
        original = payload["source_reference"]["instance"]
        if any(
            getattr(item, name) != original[name]
            for name in ("instance_id", "allocation_id", "port", "user")
        ):
            raise AdminError("admin_source_binding_changed", 409)
        platform.call(["/usr/bin/systemctl", "stop", f"epm-hosted@{item.key}.service"])
        return platform.service_state(item.key) in {"inactive", "failed"}

    dispatch.emergency_contain = emergency_contain
    provisioning = ProvisioningHost(
        ProvisioningDependencies(
            authority,
            dispatch,
            discovery,
            qualification,
            reports,
            platform,
        )
    )
    setup = SetupService(authority, provisioning)
    recovery = OnboardingRecovery(authority, dispatch, reports)
    dispatch.recovery = recovery
    setup.recovery = recovery
    dispatch.grant_check = provisioning.check_grant
    dispatch.edge_denial = EdgeDenial(
        authority, dispatch, reports, lambda: setup.host.provider(setup.host.config())
    )
    worker = SetupWorker(setup)
    operations = PrivateOperations(authority, qualification, dispatch, provisioning)
    console = ConsoleReads(authority, HostConsoleInventory(dispatch, discovery, reports, recovery))
    return SimpleNamespace(
        setup=setup,
        reports=reports,
        platform=platform,
        dispatch=dispatch,
        worker=worker,
        operations=operations,
        console=console,
        recovery=recovery,
    )


def verify_pre_enrollment(services, operation):
    if not operation or str(UUID(operation)) != operation:
        raise AdminError("admin_operation_identity_required", 422)
    return PreEnrollmentRecovery(services.setup, services.reports, services.platform).verify(
        operation, getpass("Pre-enrollment recovery passphrase: ")
    )


def verify_onboarding(services, handoff, path):
    if not handoff or str(UUID(handoff)) != handoff:
        raise AdminError("admin_recovery_handoff_required", 422)

    def acceptance(key):
        services.dispatch.grant_check(key)
        item = services.dispatch.inventory.get(key)
        services.platform.h.discovery.observe(key)
        provider = services.setup.host.provider(services.setup.host.config())
        if provider.verify(item.hostname, item.email) is None:
            raise AdminError("admin_provider_enforcement_unverified", 409)
        services.platform.verify_ingress({"hostname": item.hostname, "port": item.port})

    return OnboardingVerifier(services.recovery, services.platform, acceptance).verify(
        handoff,
        getpass("Approved-binding recovery passphrase: "),
        lambda handoff, report: rpc(
            path,
            {
                "method": "private_operations",
                "request": {
                    "action": "recovery-register",
                    "identifier": handoff,
                    "report_id": report,
                },
            },
        ),
    )


def verify_private(args, services, path):
    if args.action == "verify-edge-denial":
        if not args.operation or str(UUID(args.operation)) != args.operation:
            raise AdminError("admin_operation_identity_required", 422)
        return services.dispatch.edge_denial.verify(args.operation)
    if args.action == "verify-pre-enrollment":
        return verify_pre_enrollment(services, args.operation)
    return verify_onboarding(services, args.handoff, path)


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
    if private_request(args.action, path):
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
    services = compose(authority, paths, inventory)
    if args.action in {"verify-pre-enrollment", "verify-onboarding", "verify-edge-denial"}:
        print(json.dumps(verify_private(args, services, path)))
        services.console.close()
        return
    worker = services.worker
    worker.start()
    try:
        Broker(
            authority,
            http.pw_uid,
            services.dispatch,
            operations=services.operations,
            console=services.console,
            setup=services.setup,
        ).serve(path, http.pw_gid)
    finally:
        worker.close()
        services.console.close()


if __name__ == "__main__":
    try:
        main()
    except (AdminError, InventoryError, OSError, ValueError) as _error:
        raise SystemExit(
            "Admin command denied or unavailable; review the private installation."
        ) from None
