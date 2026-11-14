"""Installed Admin identity entry point using protected deployment files."""

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from time import time_ns

import uvicorn
from pydantic import BaseModel, ConfigDict

from app.modules.hosted_access.api.admin_identity import build_admin_identity_app
from app.modules.hosted_access.application.identity_setup import IdentitySetup
from app.modules.hosted_access.application.managed_provider import ProviderUnavailable
from app.modules.hosted_access.infrastructure.admin_bootstrap import private_file
from app.modules.hosted_access.infrastructure.admin_sessions import AdminSessions
from app.modules.hosted_access.infrastructure.mail_rate_store import SQLiteMailRateStore
from app.modules.hosted_access.infrastructure.provider_configuration import build_central_provider
from app.platform.hosted_schema import validate_schema
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


def load_deployment(configuration: Path):
    private_file(configuration)
    deployment = AdminDeployment.model_validate_json(configuration.read_bytes())
    for path in (
        deployment.database,
        deployment.setup,
        deployment.bearer_file,
        deployment.mail_key_file,
    ):
        private_file(path)
    setup = IdentitySetup.model_validate_json(deployment.setup.read_bytes())
    return deployment, setup


def build_resources(deployment, setup, *, proxy=None):
    engine = create_sqlite_engine(deployment.database)
    try:
        with engine.connect() as connection:
            validate_schema(
                connection,
                HostedStore.ADMIN,
                application_directory=deployment.application_directory,
            )

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
            bearer=bearer,
            rate_admission=rate,
            proxy=proxy,
        )
        return engine, provider
    except BaseException:
        engine.dispose()
        raise


def create_app(configuration: Path):
    deployment, setup = load_deployment(configuration)
    ui = Path(__file__).resolve().parents[3] / "admin_build" / "dist"
    if not (ui / "index.html").is_file():
        raise ValueError("Build and package the Admin UI before starting this entry point.")
    engine, provider = build_resources(deployment, setup)
    try:
        sessions = AdminSessions(engine, provider, clock=lambda: time_ns() // 1_000_000)
        web = {
            "firebase": {
                "apiKey": provider.api_key.get_secret_value(),
                "authDomain": setup.origins.central.removeprefix("https://"),
                "projectId": setup.realm.project_id,
            },
            "supportContact": deployment.support_contact,
        }
        app = build_admin_identity_app(sessions, web_config=web, ui_directory=ui)

        @asynccontextmanager
        async def lifespan(_app):
            try:
                with HostedWriterLock(deployment.writer_lock):
                    yield
            finally:
                engine.dispose()

        app.router.lifespan_context = lifespan
        return app
    except BaseException:
        engine.dispose()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--tls-certificate", type=Path, required=True)
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.configuration),
        host="127.0.0.1",
        port=args.port,
        proxy_headers=False,
        access_log=False,
        ssl_keyfile=str(args.tls_key),
        ssl_certfile=str(args.tls_certificate),
    )


if __name__ == "__main__":
    main()
