"""Local containerized Operator server with synthetic auth and seeded demo workspace.

Runs the real Operator FastAPI app + compiled Operator React UI backed by real
schema-validated `property-management.sqlite` and `hosted-access.sqlite` stores,
skipping Caddy, Cloudflare Tunnel, Firebase, backup-proxy, egress-proxy, and host-guardian.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
from secrets import token_urlsafe
import socket
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
import uvicorn

from app.bootstrap.api import create_app
from app.platform.testing_client import LocalApiClient
from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.managed_business import ManagedBusinessInputs
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.infrastructure.destination_identity import DestinationIdentity
from app.modules.hosted_access.infrastructure.free_storage_admission import (
    FreeStorageAdmission,
    PhysicalQuotaHeadroom,
)
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner
from app.modules.hosted_access.infrastructure.health_probes import internal_health_server
from app.modules.hosted_access.infrastructure.maintenance_notice import read_maintenance_notice
from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
    OperatorIdentityInputs,
)
from app.modules.hosted_access.infrastructure.usage_accounting import UsageAccountingStore
from app.modules.hosted_admin.infrastructure.policy_bootstrap import FREE_V1_USABLE_BYTES
from app.modules.workspace.application.service import WorkspacePaths, WorkspaceService
from app.platform.hosted_contracts.reads import Freshness, FreshnessState
from app.platform.hosted_contracts.ui_states import Protection, Section
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import initialize_store
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

from common import (
    BINDING_ID,
    CENTRAL_ORIGIN,
    DEPLOYMENT_ID,
    OPERATOR_EMAIL,
    OPERATOR_ID,
    OPERATOR_ORIGIN,
    OPERATOR_SLUG,
    OPERATOR_SUBJECT,
    REALM_ALIAS,
    SESSION_COOKIE_LENGTH,
    SUPPORT_CONTACT,
    WORKSPACE_ID,
    LocalBrowserBridge,
    LocalSessionHooks,
    now_ms,
)

APPLICATION_DIR = Path(os.environ.get("EPM_APPLICATION_DIR", "/opt/epm/app"))
DATA_DIR = Path(os.environ.get("EPM_DATA_DIR", "/data"))
WEB_BUILD_DIR = APPLICATION_DIR / "apps/web/dist"
POLICY_ID = "05038762-822b-5aa1-8906-99c94decabbc"


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _ensure_seeded_workspace(workspace_root: Path, config_path: Path) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(
            json.dumps({"localWorkspacePath": str(workspace_root)}, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(config_path, 0o600)

    marker = workspace_root / ".local-seeded"
    if marker.exists():
        return

    service = WorkspaceService.from_local_config(config_path)
    if not (workspace_root / "workspace.json").exists():
        service.initialize()

    # Align workspaceId with the deterministic local test binding.
    ws_json_path = workspace_root / "workspace.json"
    ws_data = json.loads(ws_json_path.read_text(encoding="utf-8"))
    ws_data["workspaceId"] = WORKSPACE_ID
    ws_json_path.write_text(json.dumps(ws_data, indent=2) + "\n", encoding="utf-8")

    biz_engine = create_sqlite_engine(WorkspacePaths(root=workspace_root).database)
    try:
        with immediate_transaction(biz_engine) as conn:
            conn.execute(
                text("UPDATE workspace_metadata SET workspace_id = :ws_id"),
                {"ws_id": WORKSPACE_ID},
            )
    finally:
        biz_engine.dispose()

    if os.environ.get("EPM_LOCAL_SEED_DEMO", "1") == "1":
        demo_dir = APPLICATION_DIR / "demo"
        if str(demo_dir) not in sys.path:
            sys.path.insert(0, str(demo_dir))
        demo_seed = importlib.import_module("seed")

        journal = DATA_DIR / "control/demo-seed-journal.json"
        journal.parent.mkdir(parents=True, exist_ok=True)
        plan = json.loads((demo_dir / "dataset.json").read_text(encoding="utf-8"))
        as_of = datetime.now(ZoneInfo(demo_seed.TIMEZONE)).date()
        with LocalApiClient(create_app(config_path)) as client:
            seeder = demo_seed.Seeder(client, journal, as_of)
            seeder.owners(plan)
            seeder.providers(plan)
            for item in plan["properties"]:
                seeder.property(item)
            seeder.expenses()
            for item in plan["issues"]:
                seeder.issue(item)
            seeder.communications(plan)
            seeder.inspection()
            seeder.rent_follow_up()
    marker.write_text("seeded\n", encoding="utf-8")


def _ensure_access_database(access_db_path: Path) -> None:
    if access_db_path.exists():
        return
    access_db_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(access_db_path.parent, 0o700)
    initialize_store(
        HostedStore.HOSTED_ACCESS,
        access_db_path,
        application_directory=APPLICATION_DIR,
    )
    engine = create_sqlite_engine(access_db_path)
    now = now_ms()
    try:
        with immediate_transaction(engine) as conn:
            conn.execute(
                text(
                    "INSERT INTO main.access_meta ("
                    "id, deployment_id, operator_id, workspace_id, binding_id, "
                    "resource_generation, issuer, subject, email_key, effective_access, "
                    "access_epoch, session_generation, not_before, effective_policy_id, "
                    "usable_bytes, policy_revision, maintenance_operation_id, "
                    "restore_generation, revision"
                    ") VALUES ("
                    "1, :dep_id, :op_id, :ws_id, :bind_id, "
                    "1, :issuer, NULL, :email, 'disabled', "
                    "1, 1, :not_before, :policy_id, "
                    ":usable_bytes, 1, NULL, 1, 1"
                    ")"
                ),
                {
                    "dep_id": DEPLOYMENT_ID,
                    "op_id": OPERATOR_ID,
                    "ws_id": WORKSPACE_ID,
                    "bind_id": BINDING_ID,
                    "issuer": REALM_ALIAS,
                    "email": f"{REALM_ALIAS}:{OPERATOR_EMAIL}",
                    "not_before": now - 60_000,
                    "policy_id": POLICY_ID,
                    "usable_bytes": FREE_V1_USABLE_BYTES,
                },
            )
            conn.execute(
                text(
                    "UPDATE main.access_meta "
                    "SET subject = :subject, effective_access = 'enabled', revision = 2 "
                    "WHERE id = 1"
                ),
                {"subject": OPERATOR_SUBJECT},
            )
    finally:
        engine.dispose()


def _mint_operator_session(access_engine) -> tuple[str, int]:
    now = now_ms()
    session_secret = token_urlsafe(32)
    csrf_secret = DestinationIdentity.csrf_token(session_secret)
    ttl_ms = 8 * 60 * 60 * 1000
    expires_at = now + ttl_ms
    with immediate_transaction(access_engine) as conn:
        meta = conn.execute(text("SELECT * FROM main.access_meta WHERE id = 1")).mappings().one()
        conn.execute(
            text(
                "INSERT INTO main.access_sessions ("
                "session_hash, csrf_hash, actor_subject, handoff_id, generation, access_epoch, "
                "issued_at, expires_at, managed_valid_until, last_seen_at, revoked_at, "
                "session_id, managed_session_id, managed_observation_revision, "
                "revocation_valid_until, remembered_until, remembered, display_label, "
                "renewed_from_session_id"
                ") VALUES ("
                ":session_hash, :csrf_hash, :subject, :handoff_id, :gen, :epoch, "
                ":issued_at, :expires_at, :managed_valid_until, :last_seen_at, NULL, "
                ":session_id, :managed_session_id, 1, "
                ":revocation_valid_until, :remembered_until, 1, 'Local Test Browser', NULL"
                ")"
            ),
            {
                "session_hash": _digest(session_secret),
                "csrf_hash": _digest(csrf_secret),
                "subject": meta["subject"],
                "handoff_id": str(uuid4()),
                "gen": meta["session_generation"],
                "epoch": meta["access_epoch"],
                "issued_at": now,
                "expires_at": expires_at,
                "managed_valid_until": expires_at,
                "last_seen_at": now,
                "session_id": str(uuid4()),
                "managed_session_id": str(uuid4()),
                "revocation_valid_until": expires_at,
                "remembered_until": expires_at,
            },
        )
    return session_secret, ttl_ms // 1000


def _revoke_operator_session(access_engine, cookie_value: str) -> None:
    if len(cookie_value) != SESSION_COOKIE_LENGTH:
        return
    with immediate_transaction(access_engine) as conn:
        conn.execute(
            text(
                "UPDATE main.access_sessions SET revoked_at = :now "
                "WHERE session_hash = :hash AND revoked_at IS NULL"
            ),
            {"now": now_ms(), "hash": _digest(cookie_value)},
        )


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


class _NoopCentralClient:
    """Stub central relay client when central-login container/Unix relay is skipped."""

    def __getattr__(self, _name: str):
        raise RuntimeError("Central identity relay is skipped in local container test mode.")


def _synthetic_protection_section() -> Section[Protection]:
    now = now_ms()
    return Section[Protection](
        state="ready",
        data=Protection(
            status="protected",
            state="healthy",
            last_verified_at=now,
            point_age_ms=0,
            proof_ref="local-synthetic-point-1",
        ),
        freshness=Freshness(
            state=FreshnessState.KNOWN,
            as_of=now,
            source_revision="local-synthetic:1",
        ),
    )


def build_local_operator_app():
    workspace_root = DATA_DIR / "workspace"
    control_root = DATA_DIR / "control"
    scratch_root = DATA_DIR / "scratch"
    socket_dir = DATA_DIR / "sockets"
    for directory in (workspace_root, control_root, scratch_root, socket_dir):
        directory.mkdir(parents=True, exist_ok=True)
    os.chmod(socket_dir, 0o700)

    ws_config = control_root / "workspace-config.json"
    _ensure_seeded_workspace(workspace_root, ws_config)

    access_db_path = control_root / "hosted-access.sqlite"
    _ensure_access_database(access_db_path)

    access_engine = create_sqlite_engine(access_db_path)
    business_engine = create_sqlite_engine(WorkspacePaths(root=workspace_root).database)

    usage_store = UsageAccountingStore(access_engine, business_engine, clock=now_ms)
    usage_store.refresh_usage_state()
    storage_admission = FreeStorageAdmission(
        usage_store,
        physical_headroom=lambda: _read_physical_headroom(
            workspace_root, control_root, scratch_root
        ),
    )

    binding = IdentityBinding(
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=OPERATOR_ID, workspace_id=WORKSPACE_ID),
        binding_id=BINDING_ID,
        access_epoch=1,
        resource_generation=1,
        assignment_revision=1,
        registered_origin_id="00000000-0000-4000-8000-000000009007",
        target_origin=OPERATOR_ORIGIN,
        issuer=REALM_ALIAS,
        subject=OPERATOR_SUBJECT,
    )
    signer = IdentitySigner("local-op-key-1", Ed25519PrivateKey.generate())
    central_public = Ed25519PrivateKey.generate().public_key()

    sock_path = socket_dir / f"{OPERATOR_ID}.sock"
    if sock_path.exists():
        sock_path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(sock_path))
    os.chmod(sock_path, 0o600)

    writer_lock_path = control_root / "writer.lock"
    if not writer_lock_path.exists():
        writer_lock_path.write_bytes(b"")
    os.chmod(writer_lock_path, 0o600)

    maintenance_path = control_root / "maintenance-notice.json"
    inner_app = create_app(
        ws_config,
        web_build_path=WEB_BUILD_DIR,
        operator_identity_inputs=OperatorIdentityInputs(
            engine=access_engine,
            binding=lambda: binding,
            signer=signer,
            central_key=lambda *_args: central_public,
            central=_NoopCentralClient(),  # type: ignore[arg-type]
            clock=now_ms,
            listener=listener,
            relay_uid=os.geteuid(),
            source_origin=OPERATOR_ORIGIN,
            central_origin=CENTRAL_ORIGIN,
            support_contact=SUPPORT_CONTACT,
            business=ManagedBusinessInputs(
                readiness=lambda: True,
                storage=storage_admission,
                files=True,
                maintenance_active=lambda: False,
            ),
            writer_lock=HostedWriterLock(writer_lock_path),
            usage_reader=usage_store.read_usage,
            protection_reader=_synthetic_protection_section,
            maintenance_reader=lambda: read_maintenance_notice(maintenance_path, clock=now_ms),
            recovery_service=None,
            recovery_mode=False,
        ),
    )

    hooks = LocalSessionHooks(
        component="operator",
        canonical_origin=OPERATOR_ORIGIN,
        cookie_name=IdentityCookiePolicy().operator,
        mint_session=lambda: _mint_operator_session(access_engine),
        revoke_current=lambda cookie_val: _revoke_operator_session(access_engine, cookie_val),
        extra_status=lambda: {
            "deploymentId": DEPLOYMENT_ID,
            "operatorId": OPERATOR_ID,
            "workspaceId": WORKSPACE_ID,
            "slug": OPERATOR_SLUG,
            "operatorEmail": OPERATOR_EMAIL,
        },
    )
    return LocalBrowserBridge(inner_app, hooks)


def main() -> None:
    app = build_local_operator_app()
    port = int(os.environ.get("PORT", "8000"))
    health_port = int(os.environ.get("HEALTH_PORT", "8081"))
    with internal_health_server(lambda: True, port=health_port):
        uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=False)


if __name__ == "__main__":
    main()
