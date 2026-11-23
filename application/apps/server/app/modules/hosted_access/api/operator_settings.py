"""Authenticated Operator hosted Settings endpoint (Free pilot usage & protection)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.application.ui_contracts import Settings
from app.modules.hosted_access.infrastructure.source_sessions import SessionExpired
from app.modules.hosted_access.infrastructure.usage_accounting import UsageSnapshot
from app.platform.hosted_contracts.reads import Freshness, FreshnessState
from app.platform.hosted_contracts.ui_states import (
    ActionState,
    FreeUsage,
    MaintenanceNotice,
    Protection,
    Section,
    UIAction,
)
from app.platform.hosted_contracts.values import EmailAddress

_EMAIL_ADAPTER = TypeAdapter(EmailAddress)

SETTINGS_ROUTE = "/api/hosted/settings"
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _read_session_cookie(request: Request, *, origin: str, cookie_name: str) -> str:
    if (
        str(request.base_url).rstrip("/") != origin
        or request.scope.get("raw_path") != request.url.path.encode("ascii")
        or request.url.query
        or any(len(request.headers.getlist(key)) > 1 for key in ("host", "origin", "cookie"))
    ):
        raise PermissionError("origin_denied")
    cookies = [
        entry.strip().split("=", 1)
        for entry in request.headers.get("cookie", "").split(";")
        if "=" in entry
    ]
    values = [value for key, value in cookies if key == cookie_name]
    if len(values) != 1:
        raise ProviderDenied()
    return values[0]


@dataclass(frozen=True)
class OperatorSettingsInputs:
    origin: str
    usage_reader: Callable[[], UsageSnapshot | None]
    support_contact: str
    protection_reader: Callable[[], Section[Protection]] | None = None
    maintenance_reader: Callable[[], Section[MaintenanceNotice]] | None = None

    def __post_init__(self) -> None:
        _EMAIL_ADAPTER.validate_python(self.support_contact)


def operator_settings_router(sessions, inputs: OperatorSettingsInputs) -> APIRouter:
    """Expose GET /api/hosted/settings returning the validated H04 Settings contract."""
    router = APIRouter(include_in_schema=False)
    cookie_name = IdentityCookiePolicy().operator

    @router.get(SETTINGS_ROUTE)
    def read_settings(request: Request) -> JSONResponse:
        try:
            cookie = _read_session_cookie(request, origin=inputs.origin, cookie_name=cookie_name)
            sessions.authorize_with_restore(cookie, csrf=None, write=False)
            scope = sessions.destination.binding().scope
        except PermissionError:
            return JSONResponse({"state": "rejected"}, status_code=403, headers=HEADERS)
        except ProviderUnavailable:
            return JSONResponse({"state": "unavailable"}, status_code=503, headers=HEADERS)
        except SessionExpired:
            return JSONResponse({"state": "renewal_required"}, status_code=401, headers=HEADERS)
        except ProviderDenied:
            return JSONResponse({"state": "signed_out"}, status_code=401, headers=HEADERS)

        snapshot = inputs.usage_reader()
        if snapshot is not None:
            usage_section = Section[FreeUsage](
                state="ready",
                data=FreeUsage(used_bytes=snapshot.used_bytes),
                freshness=Freshness(
                    state=FreshnessState.KNOWN,
                    as_of=snapshot.observed_at,
                    source_revision=f"usage:{snapshot.revision}",
                ),
            )
            breakdown = {
                "committedDbBytes": snapshot.committed_db_bytes,
                "retainedFileBytes": snapshot.retained_file_bytes,
                "reservedBytes": snapshot.reserved_bytes,
                "remainingBytes": snapshot.remaining_bytes,
                "measurementVersion": snapshot.measurement_version,
            }
        else:
            usage_section = Section[FreeUsage](
                state="unavailable",
                freshness=Freshness(
                    state=FreshnessState.UNAVAILABLE,
                    error_code="usage_accounting_unavailable",
                ),
            )
            breakdown = None

        protection_section = (
            inputs.protection_reader()
            if inputs.protection_reader is not None
            else Section[Protection](
                state="unavailable",
                freshness=Freshness(
                    state=FreshnessState.UNAVAILABLE,
                    error_code="backup_protection_unavailable",
                ),
            )
        )
        maintenance_section = (
            inputs.maintenance_reader()
            if inputs.maintenance_reader is not None
            else Section[MaintenanceNotice](
                state="unavailable",
                freshness=Freshness(
                    state=FreshnessState.UNAVAILABLE,
                    error_code="no_announced_maintenance",
                ),
            )
        )
        settings = Settings(
            scope=scope,
            usage=usage_section,
            protection=protection_section,
            support_contact=inputs.support_contact,
            maintenance=maintenance_section,
            actions=(ActionState(action=UIAction.READ_SETTINGS, enabled=True),),
        )
        payload = settings.model_dump(mode="json")
        payload["usageBreakdown"] = breakdown
        return JSONResponse(payload, headers=HEADERS)

    return router
