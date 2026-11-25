"""Local containerized Admin server with synthetic auth and seeded Pilot 0 state.

Runs the real Admin-lite FastAPI app + compiled Admin React UI backed by a real
schema-validated `admin.sqlite` store, skipping Caddy, Cloudflare Tunnel, Firebase,
backup-proxy, egress-proxy, and host-guardian.
"""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import text
import uvicorn

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.host_agent.application.capacity import (
    CandidateCapacityProfile,
    CapacitySnapshot,
    OperatorBudget,
    Resources,
)
from app.modules.host_agent.application.dispatch import ResourceLimits, TreeLimits
from app.modules.hosted_access.api.admin_identity import build_admin_identity_app
from app.modules.hosted_access.application.identity_setup import (
    DAY,
    HOUR,
    DependencyPin,
    IdentityOrigins,
    IdentityRealm,
    IdentitySetup,
)
from app.modules.hosted_access.application.identity_states import (
    AdminSessionState,
    ManagedIdentitySessionState,
)
from app.modules.hosted_access.infrastructure.admin_principals import change_admin_principal
from app.modules.hosted_access.infrastructure.admin_sessions import AdminSessions
from app.modules.hosted_access.infrastructure.health_probes import internal_health_server
from app.modules.hosted_access.infrastructure.provider_status import RevocationCache, UserStatus
from app.modules.hosted_admin.infrastructure.admin_control import (
    AdminControlService,
    SourceObservationReading,
)
from app.modules.hosted_admin.infrastructure.capacity_store import (
    record_capacity_snapshot,
    register_capacity_profile,
)
from app.modules.hosted_admin.infrastructure.policy_bootstrap import (
    FREE_V1_USABLE_BYTES,
    bootstrap_free_v1_policy,
)
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

from common import (
    ADMIN_EMAIL,
    ADMIN_ORIGIN,
    ADMIN_SUBJECT,
    BASE_DOMAIN,
    CENTRAL_ORIGIN,
    DEPLOYMENT_ID,
    MIB,
    OPERATOR_EMAIL,
    OPERATOR_ID,
    OPERATOR_SLUG,
    PROJECT_ID,
    REALM_ALIAS,
    RELEASE_ID,
    SESSION_COOKIE_LENGTH,
    SUPPORT_CONTACT,
    WORKSPACE_ID,
    LocalBrowserBridge,
    LocalSessionHooks,
    now_ms,
)

APPLICATION_DIR = Path(os.environ.get("EPM_APPLICATION_DIR", "/opt/epm/app"))
DATA_DIR = Path(os.environ.get("EPM_DATA_DIR", "/data"))
ADMIN_UI_DIR = APPLICATION_DIR / "apps/server/app/admin_build/dist"


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _build_identity_setup() -> IdentitySetup:
    pin = DependencyPin(version="1.0.0", sha256="a" * 64)
    return IdentitySetup(
        revision=1,
        configuration_state="verified",
        realm=IdentityRealm(
            alias=REALM_ALIAS,
            project_id=PROJECT_ID,
            tenant_id=None,
            issuer=f"https://securetoken.google.com/{PROJECT_ID}",
            audience=PROJECT_ID,
        ),
        origins=IdentityOrigins(
            central=CENTRAL_ORIGIN,
            admin=ADMIN_ORIGIN,
            google_callback=f"{CENTRAL_ORIGIN}/__/auth/handler",
            email_callback=f"{CENTRAL_ORIGIN}/auth/email/continue",
        ),
        firebase_web=pin,
        firebase_admin=pin,
        provider_config_ref="local-provider-config-v1",
        provider_config_sha256="b" * 64,
        central_signing_key_ref="local-central-key-1",
        source_signing_key_registry_ref="local-source-registry-1",
        rate_key_ref="local-rate-key-1",
        rate_key_rotation_ms=DAY,
        rate_retention_ms=DAY + HOUR,
        deployment_sends_per_day=90,
        provider_sends_per_day=100,
    )


class SyntheticAdminProvider:
    """Offline stand-in for FirebaseRest so AdminSessions runs without external network calls."""

    def __init__(self, setup: IdentitySetup) -> None:
        self.setup = setup
        self.status_cache = RevocationCache(
            lambda subject: UserStatus(subject, False, 0),
            clock=lambda: now_ms() / 1000.0,
        )


def _free_budget() -> OperatorBudget:
    return OperatorBudget(
        trees=ResourceLimits(
            workspace=TreeLimits(byte_ceiling=128 * MIB, inode_ceiling=4096),
            control=TreeLimits(byte_ceiling=16 * MIB, inode_ceiling=1024),
            scratch=TreeLimits(byte_ceiling=64 * MIB, inode_ceiling=1024),
        ),
        memory_bytes=256 * MIB,
        cpu_millicores=500,
        pids=64,
        shared_memory_bytes=16 * MIB,
        log_bytes=4 * MIB,
        log_files=4,
        boot_metadata_bytes=4 * MIB,
        boot_metadata_inodes=256,
    )


def _capacity_profile() -> CandidateCapacityProfile:
    return CandidateCapacityProfile(
        reference="local-pilot0-free-v1",
        revision=1,
        measurement_sha256="a" * 64,
        source_sha256="b" * 64,
        runtime_policy_sha256="c" * 64,
        maximum_observation_age_ms=86_400_000,
        shared_reserve=Resources(
            memory_bytes=512 * MIB,
            cpu_millicores=500,
            pids=128,
            data_bytes=256 * MIB,
            data_inodes=4096,
            boot_bytes=256 * MIB,
            boot_inodes=2048,
        ),
        recovery_reserve=Resources(
            data_bytes=512 * MIB,
            data_inodes=8192,
            boot_bytes=64 * MIB,
            boot_inodes=512,
        ),
    )


def _seed_admin_database(db_path: Path, setup: IdentitySetup) -> None:
    if db_path.exists():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(db_path.parent, 0o700)
    initialize_store(HostedStore.ADMIN, db_path, application_directory=APPLICATION_DIR)
    engine = create_sqlite_engine(db_path)
    now = now_ms()
    try:
        with immediate_transaction(engine) as connection:
            bind_deployment(
                connection,
                DeploymentMetadata(
                    deployment_id=DEPLOYMENT_ID,
                    public_base_domain=BASE_DOMAIN,
                    login_origin=CENTRAL_ORIGIN,
                    registry_generation=1,
                    created_at=now,
                ),
                application_directory=APPLICATION_DIR,
            )
            policy, _ = bootstrap_free_v1_policy(
                connection, created_at=now, application_directory=APPLICATION_DIR
            )
            connection.execute(
                text(
                    "INSERT INTO main.qualified_releases ("
                    "release_id, component, artifact_kind, artifact_digest, artifact_ref, "
                    "compatibility_manifest_ref, compatibility_manifest_sha256, "
                    "business_schema_revision, access_schema_revision, recovery_schema_revision, "
                    "qualification_ref, state, qualified_at, revision"
                    ") VALUES ("
                    ":id, 'operator', 'oci_image', :digest, 'epm-local-operator:dev', "
                    "'local-manifest-v1', :mhash, '20260401_0001', 'access_0001_initial', "
                    "'recovery_0001_initial', 'local-qual-v1', 'qualified', :now, 1"
                    ")"
                ),
                {"id": RELEASE_ID, "digest": "d" * 64, "mhash": "f" * 64, "now": now},
            )
            profile = _capacity_profile()
            budget = _free_budget()
            register_capacity_profile(connection, profile, budget, created_at=now)
            reservation = budget.reservation()
            total = profile.shared_reserve.plus(profile.recovery_reserve)
            for _ in range(6):
                total = total.plus(reservation)
            shared_observed = Resources(
                memory_bytes=128 * MIB,
                cpu_millicores=100,
                pids=32,
                data_bytes=64 * MIB,
                data_inodes=512,
                boot_bytes=64 * MIB,
                boot_inodes=256,
            )
            record_capacity_snapshot(
                connection,
                CapacitySnapshot(
                    revision=1,
                    observed_at=now,
                    complete=True,
                    profile_ref=profile.reference,
                    profile_revision=profile.revision,
                    total=total,
                    available=total.remaining(shared_observed),
                    shared_observed=shared_observed,
                ),
            )
            change_admin_principal(
                connection,
                realm=setup.realm,
                subject=ADMIN_SUBJECT,
                action="bootstrap",
                now=now,
            )
            component_deployment_id = "00000000-0000-4000-8000-000000009006"
            connection.execute(
                text(
                    "INSERT INTO main.operators ("
                    "operator_id, workspace_id, display_name, invited_email, email_key, "
                    "workspace_slug, issuer, subject, desired_policy_id, desired_access, "
                    "setup_state, support_contact, access_epoch, revision, "
                    "created_at, updated_at, retired_at"
                    ") VALUES ("
                    ":op_id, :ws_id, 'Local Demo Operator', :invited_email, :email_key, "
                    ":slug, :issuer, :subject, :policy_id, 'enabled', "
                    "'active', :support, 1, 1, :now, :now, NULL"
                    ")"
                ),
                {
                    "op_id": OPERATOR_ID,
                    "ws_id": WORKSPACE_ID,
                    "invited_email": OPERATOR_EMAIL,
                    "email_key": OPERATOR_EMAIL,
                    "slug": OPERATOR_SLUG,
                    "issuer": REALM_ALIAS,
                    "subject": "local-operator-subject",
                    "policy_id": policy.policy_id,
                    "support": SUPPORT_CONTACT,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO main.component_deployments ("
                    "component_deployment_id, deployment_id, component, scope_kind, "
                    "operator_id, workspace_id, desired_release_id, observed_release_id, "
                    "operation_id, state, observation_ref, observed_at, revision"
                    ") VALUES ("
                    ":cd_id, :dep_id, 'operator', 'workspace', "
                    ":op_id, :ws_id, :release_id, :release_id, "
                    "NULL, 'applied', 'local-obs-1', :now, 1"
                    ")"
                ),
                {
                    "cd_id": component_deployment_id,
                    "dep_id": DEPLOYMENT_ID,
                    "op_id": OPERATOR_ID,
                    "ws_id": WORKSPACE_ID,
                    "release_id": RELEASE_ID,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO main.workspace_recovery_status ("
                    "operator_id, workspace_id, source_epoch, source_revision, "
                    "latest_point_ref, captured_at, verified_at, checked_at, observed_at, "
                    "dirty_since, protection_state, active_operation_ref, revision"
                    ") VALUES ("
                    ":op_id, :ws_id, 1, 1, "
                    "'local-synthetic-point-1', :now, :now, :now, :now, "
                    "NULL, 'healthy', NULL, 1"
                    ")"
                ),
                {"op_id": OPERATOR_ID, "ws_id": WORKSPACE_ID, "now": now},
            )
    finally:
        engine.dispose()


def _mint_admin_session(engine, setup: IdentitySetup) -> tuple[str, int]:
    now = now_ms()
    session_secret = token_urlsafe(32)
    csrf_secret = AdminSessions.csrf_token(session_secret)
    ttl_ms = 8 * 60 * 60 * 1000
    expires_at = now + ttl_ms
    revocation_valid_until = now + 300_000
    with immediate_transaction(engine) as connection:
        principal = (
            connection.execute(
                text(
                    "SELECT principal_id, session_generation FROM main.admin_principals "
                    "WHERE issuer = :issuer AND subject = :subject AND enabled = 1"
                ),
                {"issuer": setup.realm.alias, "subject": ADMIN_SUBJECT},
            )
            .mappings()
            .one()
        )
        managed_id = str(uuid4())
        managed = ManagedIdentitySessionState(
            managed_session_id=managed_id,
            cookie_hash=_digest(token_urlsafe(32)),
            purpose="admin",
            operator_id=None,
            issuer=setup.realm.alias,
            subject=ADMIN_SUBJECT,
            email_key=f"{setup.realm.alias}:{ADMIN_EMAIL}",
            method="google_totp",
            authenticated_at=now,
            mfa_verified_at=now,
            provider_valid_until=expires_at,
            remembered_until=expires_at,
            revocation_checked_at=now,
            revocation_valid_until=revocation_valid_until,
            issued_at=now,
            revoked_at=None,
            revision=1,
        )
        admin_session = AdminSessionState(
            session_hash=_digest(session_secret),
            principal_id=principal["principal_id"],
            csrf_hash=_digest(csrf_secret),
            generation=principal["session_generation"],
            authenticated_at=now,
            mfa_verified_at=now,
            expires_at=expires_at,
            last_seen_at=now,
            revoked_at=None,
            managed_session_id=managed_id,
            managed_valid_until=expires_at,
            revocation_valid_until=revocation_valid_until,
        )
        connection.execute(
            text(
                "INSERT INTO main.managed_identity_sessions VALUES ("
                ":managed_session_id, :cookie_hash, :purpose, :operator_id, :issuer, "
                ":subject, :email_key, :method, :authenticated_at, :mfa_verified_at, "
                ":provider_valid_until, :remembered_until, :revocation_checked_at, "
                ":revocation_valid_until, :issued_at, :revoked_at, :revision)"
            ),
            managed.model_dump(),
        )
        connection.execute(
            text(
                "INSERT INTO main.admin_sessions VALUES ("
                ":session_hash, :principal_id, :csrf_hash, :generation, :authenticated_at, "
                ":mfa_verified_at, :expires_at, :last_seen_at, :revoked_at, "
                ":managed_session_id, :managed_valid_until, :revocation_valid_until)"
            ),
            admin_session.model_dump(),
        )
    return session_secret, ttl_ms // 1000


def _revoke_admin_session(engine, cookie_value: str) -> None:
    if len(cookie_value) != SESSION_COOKIE_LENGTH:
        return
    with immediate_transaction(engine) as connection:
        connection.execute(
            text(
                "UPDATE main.admin_sessions SET revoked_at = :now "
                "WHERE session_hash = :hash AND revoked_at IS NULL"
            ),
            {"now": now_ms(), "hash": _digest(cookie_value)},
        )


def build_local_admin_app():
    setup = _build_identity_setup()
    db_path = DATA_DIR / "admin.sqlite"
    _seed_admin_database(db_path, setup)
    engine = create_sqlite_engine(db_path)
    provider = SyntheticAdminProvider(setup)
    sessions = AdminSessions(engine, provider, clock=now_ms)
    admin_control = AdminControlService(
        engine,
        clock=now_ms,
        issuer=setup.realm.alias,
        application_directory=APPLICATION_DIR,
        source_inspector=lambda _op, _ws, _ep: SourceObservationReading(
            effective_enabled=True,
            usage_bytes=420_000,
            usable_bytes=FREE_V1_USABLE_BYTES,
            source_revision=1,
            observed_at=now_ms(),
        ),
    )
    web_config = {
        "firebase": {
            "apiKey": "local-synthetic-api-key",
            "authDomain": CENTRAL_ORIGIN.removeprefix("https://"),
            "projectId": PROJECT_ID,
        },
        "supportContact": SUPPORT_CONTACT,
    }
    inner_app = build_admin_identity_app(
        sessions,
        web_config=web_config,
        ui_directory=ADMIN_UI_DIR,
        admin_control=admin_control,
    )
    hooks = LocalSessionHooks(
        component="admin",
        canonical_origin=ADMIN_ORIGIN,
        cookie_name=IdentityCookiePolicy().admin,
        mint_session=lambda: _mint_admin_session(engine, setup),
        revoke_current=lambda cookie_val: _revoke_admin_session(engine, cookie_val),
        extra_status=lambda: {
            "deploymentId": DEPLOYMENT_ID,
            "seededOperatorId": OPERATOR_ID,
            "seededOperatorSlug": OPERATOR_SLUG,
            "adminEmail": ADMIN_EMAIL,
        },
    )
    return LocalBrowserBridge(inner_app, hooks)


def main() -> None:
    app = build_local_admin_app()
    port = int(os.environ.get("PORT", "8000"))
    health_port = int(os.environ.get("HEALTH_PORT", "8081"))
    with internal_health_server(lambda: True, port=health_port):
        uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=False)


if __name__ == "__main__":
    main()
