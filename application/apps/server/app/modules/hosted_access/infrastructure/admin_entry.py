"""Installed Admin identity entry point using protected deployment files."""

import argparse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
from time import time_ns

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.modules.host_agent.infrastructure.backup_proxy import UnixBackupProxyClient
from app.modules.hosted_access.api.admin_identity import build_admin_identity_app
from app.modules.hosted_access.application.identity_setup import IdentitySetup
from app.modules.hosted_access.application.managed_provider import ProviderUnavailable
from app.modules.hosted_access.infrastructure.admin_bootstrap import private_file
from app.modules.hosted_access.infrastructure.admin_sessions import AdminSessions
from app.modules.hosted_access.infrastructure.mail_rate_store import SQLiteMailRateStore
from app.modules.hosted_access.infrastructure.provider_configuration import build_central_provider
from app.modules.hosted_access.infrastructure.tls_candidate import run_identity_tls
from app.modules.hosted_admin.infrastructure.admin_control import AdminControlService
from app.modules.hosted_admin.infrastructure.admin_recovery import (
    AdminControlRecoveryService,
    build_bootstrap_recovery_authenticator,
    create_admin_recovery_app,
)
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.platform.hosted_schema import HostedSchemaError, validate_schema
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine


class AdminDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: Path
    writer_lock: Path
    setup: Path
    provider_configuration: Path
    bearer_file: Path
    mail_key_file: Path
    deployment_id: str
    application_directory: Path
    support_contact: str
    admin_recovery_database: Path | None = None
    bootstrap_authority: Path | None = None
    control_root: Path | None = None
    scratch_root: Path | None = None
    backup_proxy_socket: Path | None = None
    backup_proxy_uid: int | None = None
    release_ref: str = "rel-hosted-mvp"

    def has_recovery_config(self) -> bool:
        return all(
            value is not None
            for value in (
                self.admin_recovery_database,
                self.bootstrap_authority,
                self.control_root,
                self.scratch_root,
                self.backup_proxy_socket,
                self.backup_proxy_uid,
            )
        )


class _RecoveryModeMailRateDenied:
    """Fail-closed mail rate admission used when admin.sqlite is unavailable in recovery mode."""

    def reserve_email(self, *_args, **_kwargs):
        raise ProviderUnavailable()


@dataclass(frozen=True)
class AdminRuntimeBundle:
    app: FastAPI
    engine: Engine | None
    admin_recovery_engine: Engine | None
    provider: object
    web_config: dict[str, object]
    recovery_mode: bool
    admin_recovery: object | None = None


def _bearer_reader(deployment: AdminDeployment):
    def bearer():
        try:
            private_file(deployment.bearer_file)
            with deployment.bearer_file.open() as source:
                raw = source.read(16385)
            value = raw.strip()
            if len(raw) > 16384 or not value or "\n" in value or "\r" in value:
                raise ValueError()
            return value
        except OSError, ValueError:
            raise ProviderUnavailable() from None

    return bearer


def load_deployment(configuration: Path):
    private_file(configuration)
    deployment = AdminDeployment.model_validate_json(configuration.read_bytes())
    required_paths = [deployment.setup, deployment.bearer_file, deployment.mail_key_file]
    if not deployment.has_recovery_config() or deployment.database.exists():
        required_paths.insert(0, deployment.database)
    for path in required_paths:
        private_file(path)
    setup = IdentitySetup.model_validate_json(deployment.setup.read_bytes())
    return deployment, setup


def build_resources(deployment, setup, *, proxy=None):
    private_file(deployment.database)
    engine = create_sqlite_engine(deployment.database)
    try:
        with engine.connect() as connection:
            validate_schema(
                connection,
                HostedStore.ADMIN,
                application_directory=deployment.application_directory,
            )

        rate = SQLiteMailRateStore(
            engine,
            deployment.deployment_id,
            keys=(deployment.mail_key_file.read_bytes(),),
            daily_limit=setup.deployment_sends_per_day,
        )
        provider = build_central_provider(
            deployment.provider_configuration,
            setup,
            component="central_identity",
            bearer=_bearer_reader(deployment),
            rate_admission=rate,
            proxy=proxy,
        )
        return engine, provider
    except BaseException:
        engine.dispose()
        raise


def build_admin_recovery_runtime(
    deployment: AdminDeployment,
    setup: IdentitySetup,
    *,
    provider=None,
    proxy=None,
    clock=None,
):
    """Build AdminControlRecoveryService and D5 bootstrap authenticator without admin.sqlite."""
    if not deployment.has_recovery_config():
        return None, None, None
    assert deployment.admin_recovery_database is not None
    assert deployment.bootstrap_authority is not None
    assert deployment.control_root is not None
    assert deployment.scratch_root is not None
    assert deployment.backup_proxy_socket is not None
    assert deployment.backup_proxy_uid is not None
    now_clock = clock or (lambda: time_ns() // 1_000_000)

    private_file(deployment.admin_recovery_database)
    private_file(deployment.bootstrap_authority)
    recovery_engine = create_sqlite_engine(deployment.admin_recovery_database)
    try:
        with recovery_engine.connect() as connection:
            validate_schema(
                connection,
                HostedStore.ADMIN_RECOVERY,
                application_directory=deployment.application_directory,
            )
        auth_provider = provider
        if auth_provider is None:
            auth_provider = build_central_provider(
                deployment.provider_configuration,
                setup,
                component="central_identity",
                bearer=_bearer_reader(deployment),
                rate_admission=_RecoveryModeMailRateDenied(),
                proxy=proxy,
            )
        transport = UnixBackupProxyClient(
            deployment.backup_proxy_socket,
            expected_proxy_uid=deployment.backup_proxy_uid,
        )
        backup_engine = ChunkedAeadBackupEngine(transport)
        admin_recovery = AdminControlRecoveryService(
            admin_recovery_engine=recovery_engine,
            backup_engine=backup_engine,
            bootstrap_authority_path=deployment.bootstrap_authority,
            control_root=deployment.control_root,
            scratch_root=deployment.scratch_root,
            deployment_id=deployment.deployment_id,
            release_ref=deployment.release_ref,
            admin_schema_revision="admin_0001_initial",
            inventory_schema_revision="host_inventory_0001_initial",
            application_directory=deployment.application_directory,
            clock=now_clock,
        )

        def _verify_firebase_token(token: str) -> dict[str, object]:
            primary = auth_provider.verifier.google(token, admin=True)
            auth_provider.lookup_status(primary)
            return {
                "iss": primary.realm,
                "sub": primary.subject,
                "mfa_verified_at": primary.mfa_verified_at,
                "revoked": False,
            }

        authenticate_recovery = build_bootstrap_recovery_authenticator(
            bootstrap_authority_path=deployment.bootstrap_authority,
            verify_firebase_token=_verify_firebase_token,
            expected_origin=setup.origins.admin,
            clock=now_clock,
        )
        return recovery_engine, admin_recovery, authenticate_recovery
    except BaseException:
        recovery_engine.dispose()
        raise


def build_admin_runtime(
    deployment: AdminDeployment,
    setup: IdentitySetup,
    *,
    ui_directory: Path,
    proxy=None,
    clock=None,
    source_inspector=None,
) -> AdminRuntimeBundle:
    """Build normal Admin app (with AdminControl + recovery) or D5 recovery-mode fallback."""
    now_clock = clock or (lambda: time_ns() // 1_000_000)
    try:
        engine, provider = build_resources(deployment, setup, proxy=proxy)
    except OSError, SQLAlchemyError, HostedSchemaError, ValueError:
        if not deployment.has_recovery_config():
            raise
        recovery_engine, admin_recovery, authenticate_recovery = build_admin_recovery_runtime(
            deployment,
            setup,
            proxy=proxy,
            clock=now_clock,
        )
        assert admin_recovery is not None
        recovery_app = create_admin_recovery_app(
            admin_recovery,
            authenticate_recovery=authenticate_recovery,
        )
        return AdminRuntimeBundle(
            app=recovery_app,
            engine=None,
            admin_recovery_engine=recovery_engine,
            provider=None,
            web_config={"supportContact": deployment.support_contact},
            recovery_mode=True,
            admin_recovery=admin_recovery,
        )

    recovery_engine = None
    try:
        admin_recovery = None
        authenticate_recovery = None
        if deployment.has_recovery_config():
            recovery_engine, admin_recovery, authenticate_recovery = build_admin_recovery_runtime(
                deployment,
                setup,
                provider=provider,
                proxy=proxy,
                clock=now_clock,
            )
        sessions = AdminSessions(engine, provider, clock=now_clock)
        admin_control = AdminControlService(
            engine,
            clock=now_clock,
            issuer=setup.realm.alias,
            application_directory=deployment.application_directory,
            source_inspector=source_inspector,
        )
        web = {
            "firebase": {
                "apiKey": provider.api_key.get_secret_value(),
                "authDomain": setup.origins.central.removeprefix("https://"),
                "projectId": setup.realm.project_id,
            },
            "supportContact": deployment.support_contact,
        }
        app = build_admin_identity_app(
            sessions,
            web_config=web,
            ui_directory=ui_directory,
            admin_control=admin_control,
            admin_recovery=admin_recovery,
            authenticate_recovery=authenticate_recovery,
        )
        return AdminRuntimeBundle(
            app=app,
            engine=engine,
            admin_recovery_engine=recovery_engine,
            provider=provider,
            web_config=web,
            recovery_mode=False,
            admin_recovery=admin_recovery,
        )
    except BaseException:
        if recovery_engine is not None:
            recovery_engine.dispose()
        engine.dispose()
        raise


def create_app(configuration: Path):
    deployment, setup = load_deployment(configuration)
    ui = Path(__file__).resolve().parents[3] / "admin_build" / "dist"
    if not (ui / "index.html").is_file():
        raise ValueError("Build and package the Admin UI before starting this entry point.")
    bundle = build_admin_runtime(deployment, setup, ui_directory=ui)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            with HostedWriterLock(deployment.writer_lock):
                yield
        finally:
            if bundle.admin_recovery_engine is not None:
                bundle.admin_recovery_engine.dispose()
            if bundle.engine is not None:
                bundle.engine.dispose()

    bundle.app.router.lifespan_context = lifespan
    return bundle.app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--tls-certificate", type=Path, required=True)
    args = parser.parse_args()
    run_identity_tls(create_app(args.configuration), IPv4Address("127.0.0.1"), args)


if __name__ == "__main__":
    main()
