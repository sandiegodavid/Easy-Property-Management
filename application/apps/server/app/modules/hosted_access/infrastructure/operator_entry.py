"""Installed Operator authentication listener with protected workspace and source bindings."""

import argparse
from contextlib import contextmanager
from ipaddress import IPv4Address
import os
from pathlib import Path
from time import time_ns
from typing import Annotated, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field
from sqlalchemy import text
from starlette.responses import Response

from app.bootstrap.api import create_app
from app.hosted_candidates.runtime import inspect
from app.modules.host_agent.infrastructure.backup_proxy import UnixBackupProxyClient
from app.modules.hosted_access.api.managed_business import ManagedBusinessInputs
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.identity_setup import HttpsOrigin
from app.modules.hosted_access.infrastructure.admin_bootstrap import private_file
from app.modules.hosted_access.infrastructure.free_storage_admission import (
    FreeStorageAdmission,
    PhysicalQuotaHeadroom,
)
from app.modules.hosted_access.infrastructure.handoff_channel import CentralHandoffClient
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner
from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
    OperatorIdentityInputs,
    create_minimal_recovery_app,
)
from app.modules.hosted_access.infrastructure.usage_accounting import UsageAccountingStore
from app.modules.hosted_recovery.infrastructure.alerting import (
    DeduplicatingAlertEmitter,
    StructuredLogAlertSink,
)
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.modules.workspace.application.service import WorkspacePaths
from app.modules.workspace.infrastructure.hosted_recovery import HostedWorkspaceRecoveryService
from app.modules.hosted_access.infrastructure.shared_identity_entry import (
    Uid,
    owned_identity_socket,
    read_private,
)
from app.modules.hosted_access.infrastructure.tls_candidate import run_identity_tls
from app.modules.hosted_access.infrastructure.firebase_tokens import unique_json
from app.platform.config import application_root
from app.platform.hosted_contracts.values import Contract, EmailAddress, Reference
from app.platform.hosted_schema import validate_schema
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine


class OperatorDeployment(Contract):
    version: Literal[1] = 1
    binding: IdentityBinding
    workspace_configuration: Path
    writer_lock: Path
    access_database: Path
    signing_key: Path
    signing_key_id: Reference
    central_origin: HttpsOrigin
    central_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    central_key_id: Reference
    central_relay: Path
    relay_uid: Uid
    socket_directory: Path
    gateway_address: IPv4Address
    listen_address: IPv4Address
    scratch_directory: Path | None = None
    support_contact: EmailAddress | None = None
    recovery_database: Path | None = None
    backup_proxy_socket: Path | None = None
    backup_proxy_uid: Uid | None = None
    release_ref: Reference = "rel-hosted-mvp"
    business_schema_revision: Reference = "20260401_0001"
    access_schema_revision: Reference = "access_0001_initial"

    def check_private_network(self):
        if any(
            address.is_unspecified or not address.is_private
            for address in (self.gateway_address, self.listen_address)
        ):
            raise ValueError("Use the protected private peers.")


class TrustedSourceHTTP:
    def __init__(self, app, gateway):
        self.app = app
        self.gateway = str(gateway)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and (
            scope["scheme"] != "https"
            or (scope.get("client") or ("",))[0] != self.gateway
            or [value for key, value in scope["headers"] if key == b"x-forwarded-proto"]
            != [b"https"]
            or any(
                key in {b"forwarded", b"x-forwarded-host", b"x-forwarded-for"}
                for key, _ in scope["headers"]
            )
        ):
            await Response(status_code=421)(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def _live_business_readiness(access_engine, recovery_service) -> bool:
    """Section 6 H05.7 live readiness check; fails closed on any missing proof or error."""
    if recovery_service is None:
        return False
    try:
        with access_engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT effective_access, maintenance_operation_id FROM access_meta")
                )
                .mappings()
                .one_or_none()
            )
        if row is None or row["effective_access"] != "enabled":
            return False
        if row["maintenance_operation_id"] is not None:
            return False
        if recovery_service.detect_runtime_mode().mode != "normal":
            return False
        protection = recovery_service.read_protection_status()
        return (
            protection.last_point_id is not None
            and protection.last_verified_at is not None
            and protection.protection_state in {"healthy", "unchanged"}
        )
    except Exception:
        return False


def _read_physical_headroom(workspace: Path, control: Path, scratch: Path) -> PhysicalQuotaHeadroom:
    ws_stat = os.statvfs(workspace)
    ctrl_stat = os.statvfs(control)
    scratch_stat = os.statvfs(scratch)
    return PhysicalQuotaHeadroom(
        workspace_available_bytes=ws_stat.f_bavail * ws_stat.f_frsize,
        workspace_available_inodes=ws_stat.f_favail,
        control_available_bytes=ctrl_stat.f_bavail * ctrl_stat.f_frsize,
        control_available_inodes=ctrl_stat.f_favail,
        scratch_available_bytes=scratch_stat.f_bavail * scratch_stat.f_frsize,
        scratch_available_inodes=scratch_stat.f_favail,
    )


@contextmanager
def candidate(configuration):
    configuration.check_private_network()
    business = unique_json(read_private(configuration.workspace_configuration))
    if set(business) != {"localWorkspacePath"}:
        raise ValueError("Authentication candidates accept only an owned workspace mount.")
    binding = configuration.binding
    control = configuration.access_database.parent
    workspace = Path(business["localWorkspacePath"])
    if (
        not workspace.is_absolute()
        or workspace.resolve(strict=True) != workspace
        or workspace == control
        or workspace in control.parents
        or control in workspace.parents
    ):
        raise ValueError("Use separate protected access and workspace mounts.")
    signer = IdentitySigner(
        configuration.signing_key_id,
        Ed25519PrivateKey.from_private_bytes(read_private(configuration.signing_key, 32)),
    )
    central_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(configuration.central_key))
    private_file(configuration.access_database)
    engine = create_sqlite_engine(configuration.access_database)
    try:
        with engine.connect() as connection:
            validate_schema(
                connection, HostedStore.HOSTED_ACCESS, application_directory=application_root()
            )
            if connection.execute(
                text(
                    "SELECT deployment_id, operator_id, workspace_id, binding_id, resource_generation FROM access_meta"
                )
            ).all() != [
                (
                    binding.deployment_id,
                    binding.scope.operator_id,
                    binding.scope.workspace_id,
                    binding.binding_id,
                    binding.resource_generation,
                )
            ]:
                raise ValueError("The retained access store does not match the protected binding.")

        def current_binding():
            # Track post-restore access_epoch advancement when backed by a verified restore_binding receipt (#10).
            try:
                with engine.connect() as conn:
                    live_epoch = conn.execute(
                        text("SELECT access_epoch FROM access_meta WHERE id = 1")
                    ).scalar_one_or_none()
                    if live_epoch is not None and int(live_epoch) > binding.access_epoch:
                        has_restore_receipt = conn.execute(
                            text(
                                "SELECT 1 FROM source_receipts "
                                "WHERE kind = 'verify_restore_binding' AND state = 'applied' "
                                "LIMIT 1"
                            )
                        ).first()
                        if has_restore_receipt is not None:
                            return binding.model_copy(update={"access_epoch": int(live_epoch)})
            except Exception:
                pass
            return binding

        def clock():
            return time_ns() // 1_000_000

        scratch = (
            configuration.scratch_directory
            if configuration.scratch_directory is not None
            else (Path("/scratch") if Path("/scratch").is_dir() else control)
        )
        recovery_engine = None
        recovery_service = None
        live_business_engine_holder: list[object] = []
        startup_recovery_mode = os.environ.get("EPM_RECOVERY_MODE_REQUIRED") == "1"
        if configuration.recovery_database is not None:
            private_file(configuration.recovery_database)
            recovery_engine = create_sqlite_engine(configuration.recovery_database)
            with recovery_engine.connect() as rec_conn:
                validate_schema(
                    rec_conn, HostedStore.RECOVERY, application_directory=application_root()
                )
                # Verify recovery_meta matches configuration.binding (#18a).
                rec_meta = (
                    rec_conn.execute(
                        text("SELECT deployment_ref, workspace_id FROM recovery_meta WHERE id = 1")
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    rec_meta is None
                    or rec_meta["workspace_id"] != binding.scope.workspace_id
                    or rec_meta["deployment_ref"] != f"dep:{binding.deployment_id}"
                ):
                    raise ValueError(
                        "The retained recovery store does not match the protected binding."
                    )
            if (
                configuration.backup_proxy_socket is not None
                and configuration.backup_proxy_uid is not None
            ):
                transport = UnixBackupProxyClient(
                    configuration.backup_proxy_socket,
                    expected_proxy_uid=configuration.backup_proxy_uid,
                )
                backup_engine = ChunkedAeadBackupEngine(transport)

                def _close_business_connections() -> None:
                    for active_eng in list(live_business_engine_holder):
                        active_eng.dispose()

                recovery_service = HostedWorkspaceRecoveryService(
                    recovery_engine=recovery_engine,
                    access_engine=engine,
                    backup_engine=backup_engine,
                    operator_id=binding.scope.operator_id,
                    workspace_id=binding.scope.workspace_id,
                    deployment_id=binding.deployment_id,
                    workspace_root=workspace,
                    scratch_root=scratch,
                    release_ref=configuration.release_ref,
                    business_schema_revision=configuration.business_schema_revision,
                    access_schema_revision=configuration.access_schema_revision,
                    clock=clock,
                    alert_emitter=DeduplicatingAlertEmitter([StructuredLogAlertSink()]),
                    summary_signer_key=getattr(signer, "key", None),
                    summary_key_id=configuration.signing_key_id,
                    close_business_connections=_close_business_connections,
                )
                recovery_service.reconcile_startup()
                startup = recovery_service.detect_startup_mode(
                    force_recovery_mode=startup_recovery_mode
                )
                startup_recovery_mode = startup.mode == "recovery"

        try:
            with owned_identity_socket(
                configuration.socket_directory, binding.scope.operator_id
            ) as listener:
                if startup_recovery_mode:
                    app = create_minimal_recovery_app(
                        OperatorIdentityInputs(
                            engine=engine,
                            binding=current_binding,
                            signer=signer,
                            central_key=lambda scope, issuer, kid: (
                                central_key
                                if (scope, issuer, kid)
                                == (binding, "central_identity", configuration.central_key_id)
                                else None
                            ),
                            central=CentralHandoffClient(
                                configuration.central_relay,
                                configuration.relay_uid,
                                current_binding,
                            ),
                            clock=clock,
                            listener=listener,
                            relay_uid=configuration.relay_uid,
                            source_origin=binding.target_origin,
                            central_origin=configuration.central_origin,
                            support_contact=configuration.support_contact,
                            business=None,
                            writer_lock=None,
                            usage_reader=lambda: None,
                            protection_reader=(
                                recovery_service.protection_section
                                if recovery_service is not None
                                else None
                            ),
                            recovery_service=recovery_service,
                            recovery_mode=True,
                        )
                    )
                    yield TrustedSourceHTTP(app, configuration.gateway_address)
                else:
                    active_workspace = (
                        recovery_service.active_business_directory()
                        if recovery_service is not None
                        else workspace
                    )
                    runtime_ws_config = configuration.workspace_configuration
                    if active_workspace != workspace:
                        runtime_ws_config = control / "active-workspace-config.json"
                        runtime_ws_config.write_text(
                            f'{{"localWorkspacePath": "{active_workspace}"}}\n',
                            encoding="utf-8",
                        )
                        os.chmod(runtime_ws_config, 0o600)
                    business_engine = create_sqlite_engine(
                        WorkspacePaths(root=active_workspace).database
                    )
                    live_business_engine_holder.append(business_engine)
                    try:
                        usage_store = UsageAccountingStore(engine, business_engine, clock=clock)
                        storage_admission = FreeStorageAdmission(
                            usage_store,
                            physical_headroom=lambda: _read_physical_headroom(
                                workspace, control, scratch
                            ),
                        )
                        app = create_app(
                            runtime_ws_config,
                            operator_identity_inputs=OperatorIdentityInputs(
                                engine=engine,
                                binding=current_binding,
                                signer=signer,
                                central_key=lambda scope, issuer, kid: (
                                    central_key
                                    if (scope, issuer, kid)
                                    == (binding, "central_identity", configuration.central_key_id)
                                    else None
                                ),
                                central=CentralHandoffClient(
                                    configuration.central_relay,
                                    configuration.relay_uid,
                                    current_binding,
                                ),
                                clock=clock,
                                listener=listener,
                                relay_uid=configuration.relay_uid,
                                source_origin=binding.target_origin,
                                central_origin=configuration.central_origin,
                                support_contact=configuration.support_contact,
                                business=ManagedBusinessInputs(
                                    readiness=lambda: _live_business_readiness(
                                        engine, recovery_service
                                    ),
                                    storage=storage_admission,
                                    files=True,
                                ),
                                writer_lock=HostedWriterLock(configuration.writer_lock),
                                usage_reader=usage_store.read_usage,
                                protection_reader=(
                                    recovery_service.protection_section
                                    if recovery_service is not None
                                    else None
                                ),
                                recovery_service=recovery_service,
                                recovery_mode=False,
                            ),
                        )
                        yield TrustedSourceHTTP(app, configuration.gateway_address)
                    finally:
                        business_engine.dispose()
        finally:
            if recovery_engine is not None:
                recovery_engine.dispose()
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--tls-certificate", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        inspect("operator")
        configuration = OperatorDeployment.model_validate_json(read_private(args.configuration))
        with candidate(configuration) as app:
            run_identity_tls(app, configuration.listen_address, args)
    except Exception:
        parser.exit(3, "The protected Operator authentication candidate is unavailable.\n")


if __name__ == "__main__":
    main()
