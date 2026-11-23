"""Deduplicated external alerting for stale, failed, or unknown backup protection (H05.3 / D10)."""

from __future__ import annotations

from ipaddress import ip_address
import json
import logging
import ssl
from typing import Literal, Protocol
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from pydantic import Field

from app.platform.hosted_contracts.values import Contract

logger = logging.getLogger("epm.hosted_recovery.alerts")

_FORBIDDEN_WEBHOOK_HOSTS = frozenset({"localhost", "metadata.google.internal", "metadata"})


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("HTTP redirects are not allowed for alert webhooks.")


def _validate_webhook_url(webhook_url: str) -> str:
    parsed = urlsplit(webhook_url)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if parsed.scheme != "https" or not host or host in _FORBIDDEN_WEBHOOK_HOSTS:
        raise ValueError("Alert webhook URL must use HTTPS to a public non-local host.")
    try:
        addr = ip_address(host)
    except ValueError:
        return webhook_url
    if addr.is_loopback or addr.is_link_local or addr.is_private or addr.is_unspecified:
        raise ValueError("Alert webhook URL cannot target loopback, link-local, or private IPs.")
    return webhook_url


AlertKind = Literal["backup_failed", "backup_overdue", "backup_unknown", "backup_recovered"]
ProtectionState = Literal["healthy", "unchanged", "overdue", "unavailable", "unknown"]


class RecoveryAlert(Contract):
    """Operator-safe external alert payload; never contains secrets or business content."""

    deployment_id: str = Field(min_length=1, max_length=128)
    operator_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    alert_kind: AlertKind
    protection_state: ProtectionState
    recorded_at: int = Field(ge=0)
    consecutive_failures: int = Field(ge=0)
    last_error_code: str | None = None
    last_verified_at: int | None = None
    dirty_since: int | None = None


class AlertSink(Protocol):
    def emit(self, alert: RecoveryAlert) -> None: ...


class StructuredLogAlertSink:
    """Emit structured JSON alert records to the host/container log stream."""

    def __init__(self, target_logger: logging.Logger | None = None):
        self._logger = target_logger or logger

    def emit(self, alert: RecoveryAlert) -> None:
        payload = alert.model_dump(mode="json")
        level = logging.INFO if alert.alert_kind == "backup_recovered" else logging.WARNING
        self._logger.log(level, "hosted_recovery_alert %s", json.dumps(payload, sort_keys=True))


class WebhookAlertSink:
    """Best-effort HTTPS webhook sink for GCP Cloud Monitoring / Pilot 0 alerting."""

    def __init__(self, webhook_url: str, *, timeout_seconds: float = 5.0, opener=None):
        self.webhook_url = _validate_webhook_url(webhook_url)
        self.timeout_seconds = timeout_seconds
        self._ssl_context = ssl.create_default_context()
        self._opener = opener

    def emit(self, alert: RecoveryAlert) -> None:
        data = alert.model_dump_json().encode("utf-8")
        request = Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            if self._opener is not None:
                self._opener(request, self.timeout_seconds)
            else:
                http_opener = build_opener(
                    HTTPSHandler(context=self._ssl_context), _NoRedirectHandler()
                )
                with http_opener.open(request, timeout=self.timeout_seconds) as resp:
                    resp.read(256)
        except URLError, OSError:
            logger.warning("Failed to deliver hosted recovery webhook alert.")


class DeduplicatingAlertEmitter:
    """Deduplicates alerts per (operator_id, alert_kind) and emits explicit recovery notices."""

    def __init__(self, sinks: list[AlertSink] | tuple[AlertSink, ...]):
        self._sinks = tuple(sinks)
        self._active: dict[str, set[AlertKind]] = {}

    def _deliver(self, alert: RecoveryAlert) -> None:
        for sink in self._sinks:
            try:
                sink.emit(alert)
            except Exception:
                logger.warning("Alert sink raised an unexpected error.")

    def notify_incident(self, alert: RecoveryAlert) -> bool:
        """Emit an incident alert if not already active for (operator_id, alert_kind)."""
        if alert.alert_kind == "backup_recovered":
            raise ValueError("Use notify_recovered for recovery notices.")
        active_for_op = self._active.setdefault(alert.operator_id, set())
        if alert.alert_kind in active_for_op:
            return False
        active_for_op.add(alert.alert_kind)
        self._deliver(alert)
        return True

    def notify_recovered(
        self,
        *,
        deployment_id: str,
        operator_id: str,
        workspace_id: str,
        protection_state: Literal["healthy", "unchanged"],
        recorded_at: int,
        last_verified_at: int | None,
    ) -> bool:
        """Emit a single backup_recovered notice if any incident was active for operator_id."""
        active_for_op = self._active.get(operator_id)
        if not active_for_op:
            return False
        active_for_op.clear()
        self._deliver(
            RecoveryAlert(
                deployment_id=deployment_id,
                operator_id=operator_id,
                workspace_id=workspace_id,
                alert_kind="backup_recovered",
                protection_state=protection_state,
                recorded_at=recorded_at,
                consecutive_failures=0,
                last_error_code=None,
                last_verified_at=last_verified_at,
                dirty_since=None,
            )
        )
        return True

    def active_kinds(self, operator_id: str) -> frozenset[AlertKind]:
        return frozenset(self._active.get(operator_id, ()))
