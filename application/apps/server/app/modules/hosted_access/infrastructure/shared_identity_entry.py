"""Protected, installed Admin and central login composition on one TLS listener."""

import argparse
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from ipaddress import IPv4Address, ip_address, ip_network
import os
from pathlib import Path
import socket
import stat
from time import time_ns
from typing import Annotated, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import FastAPI
from pydantic import Field, model_validator
from sqlalchemy import text
from starlette.responses import Response

from app.hosted_candidates.runtime import inspect
from app.modules.hosted_access.api.central_identity import build_central_identity_app
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.infrastructure.admin_bootstrap import private_file
from app.modules.hosted_access.infrastructure.admin_entry import (
    build_admin_runtime,
    load_deployment,
)
from app.modules.hosted_access.infrastructure.central_attempts import CentralAttempts
from app.modules.hosted_access.infrastructure.central_handoffs import CentralHandoffs, PairingSource
from app.modules.hosted_access.infrastructure.central_login import CentralLogin
from app.modules.hosted_access.infrastructure.central_pairing import CentralPairing
from app.modules.hosted_access.infrastructure.central_session_authority import (
    CentralSessionAuthority,
)
from app.modules.hosted_access.infrastructure.firebase_helpers import FirebaseHelpers, HELPER_PATHS
from app.modules.hosted_access.infrastructure.firebase_rest import connect_proxy
from app.modules.hosted_access.infrastructure.handoff_channel import (
    CentralHandoffDispatch,
    SourceBrowserDirectory,
    own_identity_listener,
)
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner
from app.modules.hosted_access.infrastructure.health_probes import internal_health_server
from app.modules.hosted_access.infrastructure.tls_candidate import run_identity_tls
from app.modules.hosted_admin.infrastructure.recovery_status_ingest import (
    RecoveryStatusIngestService,
    RecoveryStatusRelayServer,
)
from app.modules.hosted_recovery.infrastructure.scheduler import AdminControlBackupScheduler
from app.platform.hosted_contracts.values import Contract, Reference
from app.platform.config import application_root
from app.platform.hosted_artifacts import load_manifest
from app.platform.hosted_writer_lock import HostedWriterLock

MAX_PRIVATE_INPUT = 256 * 1024
Uid = Annotated[int, Field(strict=True, ge=0)]


class SourcePeer(Contract):
    binding: IdentityBinding
    key_id: Reference
    public_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SharedDeployment(Contract):
    version: Literal[1] = 1
    admin_configuration: Path
    signing_key: Path
    signing_key_id: Reference
    source_registry: Path
    host_relay_socket: Path
    host_relay_uid: Uid
    socket_directory: Path
    gateway_address: IPv4Address
    listen_address: IPv4Address
    provider_proxy: str

    @model_validator(mode="after")
    def private_addresses(self):
        addresses = (self.gateway_address, self.listen_address)
        if any(not address.is_private or address.is_unspecified for address in addresses):
            raise ValueError("Use private identity and gateway peers.")
        connect_proxy(self.provider_proxy)
        return self


def read_private(path, limit=MAX_PRIVATE_INPUT):
    private_file(path)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Protected identity input is too large.")
    return raw


class SourceRegistry(Contract):
    sources: Annotated[tuple[SourcePeer, ...], Field(max_length=128)]

    @model_validator(mode="after")
    def unique_sources(self):
        bindings = [peer.binding for peer in self.sources]
        for key in (
            lambda binding: binding.scope.operator_id,
            lambda binding: binding.registered_origin_id,
            lambda binding: binding.target_origin,
        ):
            if len(set(map(key, bindings))) != len(bindings):
                raise ValueError("Source identity registrations must be unique.")
        return self

    def by_operator(self, identifier):
        return self._find(lambda binding: binding.scope.operator_id == identifier).binding

    def by_origin(self, identifier):
        return self._find(lambda binding: binding.registered_origin_id == identifier).binding

    def _find(self, matches):
        for source in self.sources:
            if matches(source.binding):
                return source
        raise ProviderDenied()

    def resolve_key(self, binding, issuer, key_id):
        peer = self._find(lambda candidate: candidate == binding)
        if issuer != "owning_source" or key_id != peer.key_id:
            raise ProviderDenied()
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(peer.public_key))


class AdminWorkspaceReadiness:
    """Live H04/H05 workspace readiness backed by admin.sqlite and verified protection state."""

    def __init__(self, engine):
        self.engine = engine

    def ready(self, operator_id: str, access_epoch: int) -> bool:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT o.setup_state, o.desired_access, o.access_epoch, "
                        "       rec.protection_state "
                        "FROM main.operators o "
                        "LEFT JOIN main.workspace_recovery_status rec "
                        "  ON rec.operator_id = o.operator_id "
                        "WHERE o.operator_id = :operator_id"
                    ),
                    {"operator_id": operator_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return False
        return (
            row["desired_access"] == "enabled"
            and int(row["access_epoch"]) == int(access_epoch)
            and row["setup_state"] in {"ready_for_claim", "active"}
            and row["protection_state"] in {"healthy", "unchanged"}
        )


async def _recovery_mode_central_unavailable(scope, receive, send):
    await Response(
        content='{"code":"admin_recovery_mode_active","message":"Sign-in is unavailable during Admin recovery."}',
        status_code=503,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )(scope, receive, send)


@contextmanager
def owned_identity_socket(directory, scope_id):
    info = directory.stat()
    if (
        not directory.is_absolute()
        or directory.resolve(strict=True) != directory
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise ValueError("Use the private owned identity socket directory.")
    path = directory / (scope_id + ".sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        inode = path.lstat().st_ino
        try:
            path.chmod(0o600)
            listener.listen(8)
            yield listener
        finally:
            try:
                if path.lstat().st_ino == inode:
                    path.unlink()
            except FileNotFoundError:
                pass


def network_source(request):
    values = request.headers.getlist("x-epm-client-network")
    try:
        if len(values) != 1:
            return None
        address = ip_address(values[0])
        if str(address) != values[0] or not address.is_global:
            return None
        return str(ip_network((address, 24 if address.version == 4 else 64), strict=False))
    except ValueError:
        return None


class SharedIdentityHTTP:
    def __init__(self, admin, central, helpers, *, configuration, setup):
        self.admin, self.central, self.helpers = admin, central, helpers
        self.gateway = str(configuration.gateway_address)
        self.admin_host = setup.origins.admin.removeprefix("https://").encode("ascii")
        self.central_host = setup.origins.central.removeprefix("https://").encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = scope["headers"]
        hosts = [value for key, value in headers if key == b"host"]
        if (
            scope["scheme"] != "https"
            or (scope.get("client") or ("",))[0] != self.gateway
            or [value for key, value in headers if key == b"x-forwarded-proto"] != [b"https"]
            or any(
                key in {b"forwarded", b"x-forwarded-host", b"x-forwarded-for"} for key, _ in headers
            )
        ):
            await Response(status_code=421)(scope, receive, send)
            return
        if hosts == [self.admin_host]:
            await self.admin(scope, receive, send)
        elif hosts == [self.central_host]:
            handler = self.helpers if scope["path"] in HELPER_PATHS else self.central
            await handler(scope, receive, send)
        else:
            await Response(status_code=421)(scope, receive, send)


def create_app(config_path):
    configuration = SharedDeployment.model_validate_json(read_private(config_path))
    deployment, setup = load_deployment(configuration.admin_configuration)
    if configuration.signing_key_id != setup.central_signing_key_ref:
        raise ValueError("Central signing identity differs from the protected setup.")
    registry = SourceRegistry.model_validate_json(read_private(configuration.source_registry))
    if any(
        source.binding.deployment_id != deployment.deployment_id
        or source.binding.issuer != setup.realm.alias
        for source in registry.sources
    ):
        raise ValueError("Sources must belong to the registered deployment and realm.")
    key = Ed25519PrivateKey.from_private_bytes(read_private(configuration.signing_key, 32))
    signer = IdentitySigner(configuration.signing_key_id, key)
    root = Path(__file__).resolve().parents[3]
    ui = {component: root / f"{component}_build/dist" for component in ("admin", "central")}
    if not all((directory / "index.html").is_file() for directory in ui.values()):
        raise ValueError("Both identity builds are required.")

    def clock():
        return time_ns() // 1_000_000

    bundle = build_admin_runtime(
        deployment,
        setup,
        ui_directory=ui["admin"],
        proxy=configuration.provider_proxy,
        clock=clock,
    )
    engine = bundle.engine
    try:
        if bundle.recovery_mode:

            @asynccontextmanager
            async def recovery_lifespan(_app):
                try:
                    with HostedWriterLock(deployment.writer_lock):
                        yield
                finally:
                    if bundle.admin_recovery_engine is not None:
                        bundle.admin_recovery_engine.dispose()

            app = FastAPI(
                openapi_url=None, docs_url=None, redoc_url=None, lifespan=recovery_lifespan
            )
            app.mount(
                "/",
                SharedIdentityHTTP(
                    bundle.app,
                    _recovery_mode_central_unavailable,
                    _recovery_mode_central_unavailable,
                    configuration=configuration,
                    setup=setup,
                ),
            )
            return app, configuration

        assert engine is not None
        with engine.connect() as connection:
            if connection.execute(
                text("SELECT deployment_id, login_origin FROM control_meta")
            ).all() != [(deployment.deployment_id, setup.origins.central)]:
                raise ValueError("Current Admin registration differs from the deployed origin.")

        source = SourceBrowserDirectory(
            registry, configuration.host_relay_socket, relay_uid=configuration.host_relay_uid
        )
        attempts = CentralAttempts(engine, setup, source, clock=clock)
        login = CentralLogin(attempts, bundle.provider, deployment_id=deployment.deployment_id)
        handoffs = CentralHandoffs(
            attempts,
            signer,
            source,
            AdminWorkspaceReadiness(engine),
            deployment_id=deployment.deployment_id,
        )
        pairing = CentralPairing(
            attempts,
            PairingSource(registry.resolve_key, source.observe_pairing, clock=clock),
            deployment_id=deployment.deployment_id,
        )
        central = build_central_identity_app(
            login,
            web_config=bundle.web_config,
            ui_directory=ui["central"],
            network_source=network_source,
            pairing=pairing,
            handoffs=handoffs,
        )
        helper = FirebaseHelpers(
            setup, configuration.provider_proxy, public_config=bundle.web_config["firebase"]
        )

        def _resolve_summary_key(
            operator_id: str, workspace_id: str, key_id: str
        ) -> Ed25519PublicKey | None:
            for peer in registry.sources:
                if (
                    peer.binding.scope.operator_id == operator_id
                    and peer.binding.scope.workspace_id == workspace_id
                    and peer.key_id == key_id
                ):
                    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(peer.public_key))
            return None

        recovery_ingest = RecoveryStatusIngestService(
            engine,
            resolve_public_key=_resolve_summary_key,
            clock=clock,
        )
        admin_scheduler = (
            AdminControlBackupScheduler(
                bundle.admin_recovery,
                deployment_id=deployment.deployment_id,
                clock=clock,
            )
            if bundle.admin_recovery is not None
            else None
        )

        @asynccontextmanager
        async def lifespan(_app):
            stop_scheduler = asyncio.Event()
            scheduler_task = None
            relay_server = None
            try:
                with HostedWriterLock(deployment.writer_lock):
                    async with AsyncExitStack() as stack:
                        authority = CentralSessionAuthority(handoffs, bundle.provider)
                        for peer in registry.sources:
                            binding = peer.binding
                            listener = stack.enter_context(
                                owned_identity_socket(
                                    configuration.socket_directory, binding.scope.operator_id
                                )
                            )
                            await stack.enter_async_context(
                                own_identity_listener(
                                    listener,
                                    CentralHandoffDispatch(
                                        handoffs,
                                        lambda bound=binding: bound,
                                        session_authority=authority,
                                    ),
                                    peer_uid=configuration.host_relay_uid,
                                )
                            )
                        if registry.sources:
                            summary_listener = stack.enter_context(
                                owned_identity_socket(
                                    configuration.socket_directory, "recovery-status"
                                )
                            )
                            relay_server = RecoveryStatusRelayServer(
                                summary_listener,
                                recovery_ingest,
                                allowed_uid=configuration.host_relay_uid,
                            )
                            relay_server.start()
                        if admin_scheduler is not None:
                            scheduler_task = asyncio.create_task(
                                admin_scheduler.run_forever(stop_scheduler)
                            )
                        yield
            finally:
                stop_scheduler.set()
                if scheduler_task is not None:
                    scheduler_task.cancel()
                    try:
                        await scheduler_task
                    except asyncio.CancelledError:
                        pass
                if relay_server is not None:
                    relay_server.stop()
                if bundle.admin_recovery_engine is not None:
                    bundle.admin_recovery_engine.dispose()
                engine.dispose()

        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
        app.mount(
            "/",
            SharedIdentityHTTP(
                bundle.app, central, helper, configuration=configuration, setup=setup
            ),
        )
        return app, configuration
    except BaseException:
        if bundle.admin_recovery_engine is not None:
            bundle.admin_recovery_engine.dispose()
        if engine is not None:
            engine.dispose()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--tls-certificate", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--health-port", type=int, default=8081)
    args = parser.parse_args()
    try:
        inspect("admin")
        if load_manifest(application_root() / "hosted-candidate.json").ui != "compiled_identity":
            raise ValueError("Install the shared identity package.")
        app, configuration = create_app(args.configuration)
        with internal_health_server(lambda: True, port=args.health_port):
            run_identity_tls(app, configuration.listen_address, args)
    except Exception:
        parser.exit(3, "The protected shared identity candidate is unavailable.\n")


if __name__ == "__main__":
    main()
