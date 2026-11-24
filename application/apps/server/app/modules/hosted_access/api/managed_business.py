"""Admission for business routes on a managed Operator source."""

from contextlib import contextmanager
from dataclasses import dataclass
import re
from typing import Callable
from uuid import UUID

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import compile_path

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.middleware import (
    BUSINESS_ROOTS,
    FORBIDDEN_PREFIXES,
    SAFE_METHODS,
    SENSITIVE_HEADERS,
)
from app.modules.hosted_access.api.request_body import MAX_BODY_BYTES, bounded_body
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.domain.models import HostedAccessError
from app.platform.actor_context import OperatorActor, operator_actor_scope
from app.platform.attempt_fences import PreparedEditRequired
from app.platform.hosted_security_headers import (
    API_SECURITY_HEADER_NAMES_LOWER,
    API_SECURITY_HEADERS,
    API_SECURITY_HEADERS_ASGI,
)
from app.modules.hosted_access.infrastructure.draft_leases import conflict
from app.platform.sqlite_engine import workspace_mutation_scope

DRAFT_LEASE = re.compile(r"/api/hosted/drafts/[0-9a-f-]{36}/lease")
EDIT_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
COOKIE = IdentityCookiePolicy().operator
SMALL_BODY = 1024 * 1024


@dataclass(frozen=True)
class ManagedBusinessInputs:
    readiness: Callable[[], bool]
    storage: object
    files: bool = False
    maintenance_active: Callable[[], bool] | None = None


class ManagedSessionLost(RuntimeError):
    """The source withdrew authority before the workspace commit."""


def business_error(error):
    if isinstance(error, PreparedEditRequired):
        error = conflict()
    elif isinstance(error, (ProviderDenied, ManagedSessionLost)):
        error = HostedAccessError("hosted_session_expired", "Sign in again to this workspace.")
    elif isinstance(error, ProviderUnavailable):
        error = HostedAccessError(
            "hosted_session_unavailable", "Workspace access is unavailable.", 503
        )
    return JSONResponse(
        {"detail": {"code": error.code, "message": str(error)}},
        status_code=error.status,
        headers=API_SECURITY_HEADERS,
    )


class ManagedBusiness:
    def __init__(self, app, sessions, lock, inputs, database, leases, namespaces):
        self.sessions, self.lock, self.inputs, self.database = sessions, lock, inputs, database
        self.leases = leases
        self.namespaces = {}
        for form, table in namespaces.items():
            self.namespaces.setdefault(table, []).append(form)
        self.routes = tuple(
            (method.upper(), compile_path(path)[0])
            for path, operations in app.openapi()["paths"].items()
            for method in operations
            if method in {"get", "head", "post", "put", "patch", "delete"}
        )

    def capabilities(self):
        if not self.inputs.readiness():
            return []
        return (
            ["records.read", "records.write", "files.read", "files.write"]
            if self.inputs.files
            else ["records.read", "records.write"]
        )

    def _request(self, scope, origin):
        path, method = scope["path"], scope["method"]
        root = path.split("/")[2]
        lease = method == "POST" and DRAFT_LEASE.fullmatch(path)
        if not lease and (
            root not in BUSINESS_ROOTS
            or any(path == prefix or path.startswith(prefix + "/") for prefix in FORBIDDEN_PREFIXES)
            or not any(method == verb and pattern.fullmatch(path) for verb, pattern in self.routes)
        ):
            raise HostedAccessError("hosted_route_forbidden", "Route is unavailable.", 403)
        if not path.isascii() or scope.get("raw_path", path.encode()) != path.encode():
            raise HostedAccessError("hosted_route_forbidden", "Route is unavailable.", 403)
        headers = {}
        for label, value in scope["headers"]:
            name = label.decode("latin1")
            if name in headers and name in SENSITIVE_HEADERS | {
                "content-type",
                "transfer-encoding",
                "x-epm-prepared-form",
            }:
                raise HostedAccessError(
                    "hosted_headers_rejected", "Ambiguous request headers.", 403
                )
            headers[name] = value.decode("latin1")
        write = method not in SAFE_METHODS
        if headers.get("origin", origin) != origin or (write and "origin" not in headers):
            raise HostedAccessError("hosted_csrf_rejected", "Request verification failed.", 403)
        cookies = [item.strip().partition("=") for item in headers.get("cookie", "").split(";")]
        matches = [value for name, _, value in cookies if name == COOKIE]
        if len(matches) != 1:
            raise HostedAccessError("hosted_session_required", "Sign in to this workspace.")
        edit = headers.get("x-epm-draft-lease")
        if edit is not None and not EDIT_TOKEN.fullmatch(edit):
            raise HostedAccessError("hosted_headers_rejected", "Invalid edit authority.", 403)
        prepared = headers.get("x-epm-prepared-form")
        if prepared is not None:
            try:
                if not write or str(UUID(prepared)) != prepared:
                    raise ValueError()
            except ValueError as error:
                raise HostedAccessError(
                    "hosted_headers_rejected", "Invalid prepared form.", 403
                ) from error
        multipart = headers.get("content-type", "").lower().startswith("multipart/")
        uses_files = root in {"files", "file-links"} or multipart
        limit = MAX_BODY_BYTES if multipart else SMALL_BODY
        declared = headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or len(declared) > 10):
            raise HostedAccessError("hosted_body_rejected", "Invalid request size.", 400)
        if declared is not None and "transfer-encoding" in headers:
            raise HostedAccessError("hosted_body_rejected", "Ambiguous request size.", 400)
        size = int(declared) if declared is not None else limit if write else 0
        if size > (limit if write else 0):
            raise HostedAccessError("request_payload_too_large", "Request exceeds its limit.", 413)
        return matches[0], headers.get("x-epm-csrf"), write, uses_files, size, edit, prepared

    async def dispatch(self, app, scope, receive, send, origin):
        response_started = False
        try:
            cookie, csrf, write, files, size, edit, prepared = self._request(scope, origin)

            def admit():
                if self.inputs.maintenance_active is not None and self.inputs.maintenance_active():
                    raise HostedAccessError(
                        "maintenance_in_progress", "Updating your workspace.", 503
                    )
                capabilities = self.capabilities()
                if not capabilities:
                    raise ProviderUnavailable()
                if files and ("files.write" if write else "files.read") not in capabilities:
                    raise HostedAccessError(
                        "hosted_capability_forbidden", "File action unavailable.", 403
                    )
                session, restore = self.sessions.authorize_with_restore(
                    cookie, csrf=csrf, write=write
                )
                return session, restore, self.sessions.destination.binding().scope

            session, restore, identity = await run_in_threadpool(admit)
            actor = OperatorActor(
                identity.operator_id, identity.workspace_id, session.session_hash, edit, restore
            )

            def validate_commit():
                try:
                    current, current_restore, current_identity = admit()
                    if (
                        current.session_id != session.session_id
                        or current.access_epoch != session.access_epoch
                        or current_restore != restore
                        or current_identity != identity
                    ):
                        raise ProviderDenied()
                    recovery = self.leases.current_recovery.get()
                    if recovery and prepared and recovery != prepared:
                        raise PreparedEditRequired()
                    edit_form = recovery or prepared
                    if edit_form:
                        self.leases.verify(edit_form, actor)
                except ProviderDenied as error:
                    raise ManagedSessionLost() from error
                except HostedAccessError as error:
                    if error.code != "hosted_draft_lease_conflict":
                        raise
                    raise PreparedEditRequired() from error

            @contextmanager
            def commit_guard():
                with self.lock:
                    validate_commit()
                    yield validate_commit

            reservation_outcome = None

            async def private_send(message):
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                    if reservation_outcome is not None:
                        reservation_outcome.status_code = message["status"]
                    headers = [
                        (name, value)
                        for name, value in message["headers"]
                        if name.lower() not in API_SECURITY_HEADER_NAMES_LOWER
                    ]
                    message["headers"] = [*headers, *API_SECURITY_HEADERS_ASGI]
                await send(message)

            if hasattr(self.inputs.storage, "reserve_request"):
                storage_context = self.inputs.storage.reserve_request(
                    size,
                    write=write,
                    source_epoch=session.access_epoch,
                    purpose="file_upload" if files else "business_write",
                )
            else:
                storage_context = self.inputs.storage.reserve(size, write=write)

            with storage_context as outcome_handle:
                reservation_outcome = outcome_handle
                async with bounded_body(receive, max_bytes=size) as replay:
                    with (
                        operator_actor_scope(actor),
                        workspace_mutation_scope(
                            self.database,
                            commit_guard,
                            namespaces=self.namespaces,
                            prepared_form=prepared,
                        ),
                    ):
                        await app(scope, replay, private_send)
        except (ProviderDenied, ProviderUnavailable, HostedAccessError) as error:
            if response_started:
                raise
            await business_error(error)(scope, receive, send)
