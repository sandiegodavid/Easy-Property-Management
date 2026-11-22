"""Protected composition of destination HTTP and private dispatch in the Operator process."""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
import socket
from threading import RLock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI
from pydantic import TypeAdapter
from sqlalchemy import Engine
from starlette.responses import JSONResponse

from app.modules.host_agent.infrastructure.identity_relay import SourceIdentityDispatch
from app.modules.hosted_access.api.destination_identity import destination_router
from app.modules.hosted_access.api.draft_leases import build_draft_lease_router
from app.modules.hosted_access.api.managed_business import (
    ManagedBusiness,
    ManagedBusinessInputs,
    ManagedSessionLost,
    business_error,
)
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.managed_draft_leases import ManagedDraftLeases
from app.platform.web_delivery import browser_route
from app.modules.hosted_access.api.operator_security import (
    SECURITY_ROUTES,
    operator_security_router,
)
from app.modules.hosted_access.api.operator_settings import (
    SETTINGS_ROUTE,
    OperatorSettingsInputs,
    operator_settings_router,
)
from app.modules.hosted_access.infrastructure.operator_security import OperatorSecurity
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.identity_setup import HttpsOrigin
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.destination_identity import DestinationIdentity
from app.modules.hosted_access.infrastructure.handoff_channel import (
    CentralHandoffClient,
    DestinationDispatch,
    own_identity_listener,
)
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner
from app.modules.hosted_access.infrastructure.source_lifecycle import SourceLifecycle
from app.modules.hosted_access.infrastructure.source_sessions import SourceSessions
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.sqlite_engine import immediate_transaction
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.attempt_fences import PreparedEditRequired

AUTH_PATHS = frozenset({"/auth/start", "/auth/complete", "/auth/status"})


@dataclass(frozen=True)
class OperatorIdentityInputs:
    engine: Engine
    binding: Callable[[], IdentityBinding]
    signer: IdentitySigner
    central_key: Callable[[IdentityBinding, str, str], Ed25519PublicKey | None]
    central: CentralHandoffClient
    clock: Callable[[], int]
    listener: socket.socket
    relay_uid: int
    source_origin: str
    central_origin: str
    lifecycle_proof_owner: object | None = None
    support_contact: str | None = None
    business: ManagedBusinessInputs | None = None
    writer_lock: HostedWriterLock | None = None
    usage_reader: Callable | None = None


def managed_entry_metadata(inputs):
    if inputs is None:
        return None
    metadata = {"epm-deployment": "hosted_managed"}
    if inputs.support_contact is not None:
        metadata["epm-administrator-contact"] = inputs.support_contact
    return metadata


class DestinationHTTP:
    def __init__(self, app, *, destination, source_origin, business):
        self.app, self.destination = app, destination
        self.business, self.origin = business, source_origin
        self.scheme, self.host = source_origin.split("://", 1)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and (
            scope["scheme"] != self.scheme
            or [value for name, value in scope["headers"] if name == b"host"]
            != [self.host.encode("ascii")]
        ):
            await JSONResponse({"state": "rejected"}, status_code=403)(scope, receive, send)
        elif scope["type"] == "http" and scope["path"] in AUTH_PATHS | SECURITY_ROUTES | {
            SETTINGS_ROUTE
        }:
            await self.destination(scope, receive, send)
        elif self.business and scope["type"] == "http" and scope["path"].startswith("/api/"):
            await self.business.dispatch(self.app, scope, receive, send, self.origin)
        elif scope["type"] == "http" and not (
            scope["method"] in {"GET", "HEAD"}
            and (
                scope["path"] == "/sign-in"
                or scope["path"].startswith("/assets/")
                or (self.business and browser_route(scope["path"]))
            )
        ):
            response = JSONResponse(
                {"message": "Workspace access is unavailable."}, status_code=503
            )
            await response(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await self.app(scope, receive, send)


def compose_operator_identity(
    app, runtime, inputs: OperatorIdentityInputs, *, database=None, namespaces=None
):
    """Add the auth-only paths and share the already owned runtime for both listeners."""

    origin = TypeAdapter(HttpsOrigin)
    source_origin = origin.validate_python(inputs.source_origin)
    central_origin = origin.validate_python(inputs.central_origin)
    if (
        source_origin == central_origin
        or inputs.listener.family != socket.AF_UNIX
        or not inputs.listener.getsockname()
    ):
        raise ValueError(
            "Managed identity requires distinct origins and a private listening socket."
        )

    inputs.listener.listen(8)

    def current_binding():
        if not runtime.ready or not runtime.can_write:
            raise ProviderUnavailable()
        binding = inputs.binding()
        if (
            binding.scope.workspace_id != runtime.workspace_id
            or binding.target_origin != source_origin
        ):
            raise ProviderDenied()
        return binding

    lock = RLock()

    @contextmanager
    def mutation():
        if not runtime.ready or not runtime.can_write:
            raise ProviderUnavailable()
        with lock, immediate_transaction(inputs.engine) as connection:
            yield connection

    owner = DestinationIdentity(
        inputs.engine,
        mutation=mutation,
        binding=current_binding,
        signer=inputs.signer,
        central_key=inputs.central_key,
        clock=inputs.clock,
    )
    sessions = SourceSessions(owner)
    app.state.hosted_source_sessions = sessions
    business = None
    if inputs.business is not None:
        if (
            not namespaces
            or database is None
            or inputs.engine.url.database == str(database.resolve())
        ):
            raise ValueError("Managed access requires separate source and workspace stores.")
        operator = app.state.operator_service
        leases = ManagedDraftLeases(owner, lock, operator.recovery_edit_revision)
        operator.recovery_authority = leases
        app.include_router(build_draft_lease_router(leases))
        business = ManagedBusiness(
            app, sessions, lock, inputs.business, database, leases, namespaces
        )

        async def handle_error(_request, error):
            return business_error(error)

        for error_type in (
            ProviderDenied,
            ProviderUnavailable,
            HostedAccessError,
            PreparedEditRequired,
            ManagedSessionLost,
        ):
            app.add_exception_handler(error_type, handle_error)

    def authenticate(call, *, deadline):
        # serve_identity authenticates the single configured Host Agent peer
        # before parsing. The scope comes from local protected registration.
        binding = current_binding()
        return ServiceAuthority(
            deployment_id=binding.deployment_id,
            scope=binding.scope,
            service="admin",
            authenticated_channel_ref="host-agent-identity",
        )

    lifecycle = SourceLifecycle(
        inputs.engine,
        mutation=mutation,
        binding=current_binding,
        clock=inputs.clock,
        proof_owner=inputs.lifecycle_proof_owner,
    )
    app.state.hosted_source_lifecycle = lifecycle
    dispatch = DestinationDispatch(
        owner,
        runtime=runtime,
        lifecycle=SourceIdentityDispatch(lifecycle, authenticate),
        sessions=sessions,
    )
    auth = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    auth.router.redirect_slashes = False
    auth.include_router(
        destination_router(
            owner,
            inputs.central,
            source_origin=source_origin,
            central_origin=central_origin,
        )
    )
    auth.include_router(
        operator_security_router(
            OperatorSecurity(
                owner,
                sessions,
                lifecycle,
                inputs.central,
                support_contact=inputs.support_contact,
                business_capabilities=business.capabilities if business else None,
            ),
            origin=source_origin,
        )
    )
    if inputs.usage_reader is not None and inputs.support_contact is not None:
        auth.include_router(
            operator_settings_router(
                sessions,
                OperatorSettingsInputs(
                    origin=source_origin,
                    usage_reader=inputs.usage_reader,
                    support_contact=inputs.support_contact,
                ),
            )
        )
    app.add_middleware(
        DestinationHTTP, destination=auth, source_origin=source_origin, business=business
    )
    return partial(
        own_identity_listener,
        inputs.listener,
        dispatch,
        peer_uid=inputs.relay_uid,
    )
