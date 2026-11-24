"""Source-authenticated async ingest for Admin workspace_recovery_status (H05.3 / D12)."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import socket
import threading
import time
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import model_validator
from sqlalchemy import Engine, text

from app.modules.host_agent.infrastructure.unix_transport import peer_uid
from app.modules.hosted_recovery.domain.models import HostedRecoveryError
from app.platform.hosted_contracts.semantic import SemanticRequest, canonical_bytes
from app.platform.hosted_contracts.values import (
    CanonicalId,
    EpochMillis,
    Reference,
    Revision,
)
from app.platform.sqlite_engine import immediate_transaction

SUMMARY_DOMAIN = b"epm:workspace-protection-summary:v1\0"
MAX_SUMMARY_TOKEN_CHARS = 8192
_TOKEN_PART = re.compile(r"[A-Za-z0-9_-]+")


class RecoverySummaryDenied(HostedRecoveryError):
    code = "recovery_summary_denied"


class WorkspaceProtectionSummary(SemanticRequest):
    """Signed bounded protection summary emitted asynchronously by an Operator service."""

    operator_id: CanonicalId
    workspace_id: CanonicalId
    source_epoch: Revision
    source_revision: Revision
    latest_point_ref: Reference | None = None
    captured_at: EpochMillis | None = None
    verified_at: EpochMillis | None = None
    checked_at: EpochMillis
    dirty_since: EpochMillis | None = None
    protection_state: Literal["healthy", "unchanged", "overdue", "unavailable", "unknown"]
    active_operation_ref: Reference | None = None
    key_id: Reference
    issued_at: EpochMillis
    expires_at: EpochMillis

    @model_validator(mode="after")
    def _validate_times(self) -> WorkspaceProtectionSummary:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be strictly greater than issued_at.")
        if self.verified_at is not None:
            if self.latest_point_ref is None or self.captured_at is None:
                raise ValueError("verified_at requires latest_point_ref and captured_at.")
            if self.verified_at < self.captured_at:
                raise ValueError("verified_at cannot precede captured_at.")
        return self


@dataclass(frozen=True)
class IngestOutcome:
    applied: bool
    reason: Literal["inserted", "updated", "stale_epoch", "stale_revision"]
    operator_id: str
    source_epoch: int
    source_revision: int


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    if not _TOKEN_PART.fullmatch(value):
        raise ValueError("Invalid base64url segment.")
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64_encode(raw) != value:
        raise ValueError("Non-canonical base64url encoding.")
    return raw


def sign_protection_summary(
    summary: WorkspaceProtectionSummary,
    *,
    private_key: Ed25519PrivateKey,
) -> str:
    """Sign a canonical WorkspaceProtectionSummary with the Operator's Ed25519 private key."""
    raw = canonical_bytes(summary)
    signature = private_key.sign(SUMMARY_DOMAIN + raw)
    token = f"{_b64_encode(raw)}.{_b64_encode(signature)}"
    if len(token) > MAX_SUMMARY_TOKEN_CHARS:
        raise RecoverySummaryDenied("Signed protection summary exceeds size bound.")
    return token


def verify_protection_summary(
    token: str,
    *,
    resolve_public_key: Callable[[str, str, str], Ed25519PublicKey | None],
    now: int,
) -> WorkspaceProtectionSummary:
    """Verify Ed25519 signature, canonical encoding, and freshness window."""
    if not isinstance(token, str) or len(token) > MAX_SUMMARY_TOKEN_CHARS:
        raise RecoverySummaryDenied("Malformed protection summary token.")
    try:
        parts = token.split(".")
        if len(parts) != 2:
            raise ValueError("Expected two dot-separated segments.")
        raw = _b64_decode(parts[0])
        sig = _b64_decode(parts[1])
        summary = WorkspaceProtectionSummary.model_validate_json(raw)
        if canonical_bytes(summary) != raw:
            raise ValueError("Non-canonical summary payload.")
        if not summary.issued_at <= now < summary.expires_at:
            raise ValueError("Summary token outside validity window.")
        public_key = resolve_public_key(summary.operator_id, summary.workspace_id, summary.key_id)
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("Unknown summary signing key.")
        public_key.verify(sig, SUMMARY_DOMAIN + raw)
        return summary
    except (ValueError, binascii.Error, InvalidSignature, RecursionError) as error:
        raise RecoverySummaryDenied("Protection summary signature or freshness invalid.") from error


class RecoveryStatusIngestService:
    """Fences and upserts source-authenticated workspace_recovery_status rows in admin.sqlite."""

    def __init__(
        self,
        admin_engine: Engine,
        *,
        resolve_public_key: Callable[[str, str, str], Ed25519PublicKey | None],
        clock: Callable[[], int],
    ):
        self.admin_engine = admin_engine
        self.resolve_public_key = resolve_public_key
        self.clock = clock

    def ingest_signed(self, token: str) -> IngestOutcome:
        now = self.clock()
        summary = verify_protection_summary(
            token,
            resolve_public_key=self.resolve_public_key,
            now=now,
        )
        return self._apply_verified(summary, now=now)

    def _apply_verified(
        self,
        summary: WorkspaceProtectionSummary,
        *,
        now: int,
    ) -> IngestOutcome:
        observed_at = max(now, summary.checked_at)
        with immediate_transaction(self.admin_engine) as conn:
            op_row = (
                conn.execute(
                    text(
                        "SELECT operator_id, workspace_id, access_epoch "
                        "FROM operators WHERE operator_id = :operator_id"
                    ),
                    {"operator_id": summary.operator_id},
                )
                .mappings()
                .first()
            )
            if op_row is None or op_row["workspace_id"] != summary.workspace_id:
                raise RecoverySummaryDenied(
                    "Summary does not match a registered operator/workspace."
                )
            current_epoch = int(op_row["access_epoch"])
            if summary.source_epoch < current_epoch:
                return IngestOutcome(
                    applied=False,
                    reason="stale_epoch",
                    operator_id=summary.operator_id,
                    source_epoch=summary.source_epoch,
                    source_revision=summary.source_revision,
                )
            if summary.source_epoch > current_epoch:
                raise RecoverySummaryDenied(
                    "Summary source_epoch exceeds registered operator epoch."
                )

            existing = (
                conn.execute(
                    text(
                        "SELECT source_epoch, source_revision, revision "
                        "FROM workspace_recovery_status WHERE operator_id = :operator_id"
                    ),
                    {"operator_id": summary.operator_id},
                )
                .mappings()
                .first()
            )
            params = {
                "operator_id": summary.operator_id,
                "workspace_id": summary.workspace_id,
                "source_epoch": summary.source_epoch,
                "source_revision": summary.source_revision,
                "latest_point_ref": summary.latest_point_ref,
                "captured_at": summary.captured_at,
                "verified_at": summary.verified_at,
                "checked_at": summary.checked_at,
                "observed_at": observed_at,
                "dirty_since": summary.dirty_since,
                "protection_state": summary.protection_state,
                "active_operation_ref": summary.active_operation_ref,
            }
            if existing is None:
                conn.execute(
                    text(
                        "INSERT INTO workspace_recovery_status ("
                        "operator_id, workspace_id, source_epoch, source_revision, "
                        "latest_point_ref, captured_at, verified_at, checked_at, observed_at, "
                        "dirty_since, protection_state, active_operation_ref, revision"
                        ") VALUES ("
                        ":operator_id, :workspace_id, :source_epoch, :source_revision, "
                        ":latest_point_ref, :captured_at, :verified_at, :checked_at, :observed_at, "
                        ":dirty_since, :protection_state, :active_operation_ref, 1"
                        ")"
                    ),
                    params,
                )
                return IngestOutcome(
                    applied=True,
                    reason="inserted",
                    operator_id=summary.operator_id,
                    source_epoch=summary.source_epoch,
                    source_revision=summary.source_revision,
                )

            existing_epoch = int(existing["source_epoch"])
            existing_src_rev = int(existing["source_revision"])
            if (
                summary.source_epoch == existing_epoch
                and summary.source_revision <= existing_src_rev
            ):
                return IngestOutcome(
                    applied=False,
                    reason="stale_revision",
                    operator_id=summary.operator_id,
                    source_epoch=summary.source_epoch,
                    source_revision=summary.source_revision,
                )

            params["revision"] = int(existing["revision"]) + 1
            conn.execute(
                text(
                    "UPDATE workspace_recovery_status SET "
                    "source_epoch = :source_epoch, "
                    "source_revision = :source_revision, "
                    "latest_point_ref = :latest_point_ref, "
                    "captured_at = :captured_at, "
                    "verified_at = :verified_at, "
                    "checked_at = :checked_at, "
                    "observed_at = :observed_at, "
                    "dirty_since = :dirty_since, "
                    "protection_state = :protection_state, "
                    "active_operation_ref = :active_operation_ref, "
                    "revision = :revision "
                    "WHERE operator_id = :operator_id"
                ),
                params,
            )
            return IngestOutcome(
                applied=True,
                reason="updated",
                operator_id=summary.operator_id,
                source_epoch=summary.source_epoch,
                source_revision=summary.source_revision,
            )


INTERNAL_RECOVERY_STATUS_ROUTE = "/internal/recovery-status"
MAX_INTERNAL_REQUEST_BYTES = 16 * 1024
_RELAY_LOGGER = logging.getLogger("epm.hosted_recovery.summary_relay")


def _write_http_json(
    conn: socket.socket,
    status_code: int,
    reason: str,
    body: dict,
    *,
    deadline: float | None = None,
) -> None:
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Response deadline exceeded.")
        conn.settimeout(remaining)
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    response = (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        "Content-Type: application/json\r\n"
        "Cache-Control: no-store\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + payload
    conn.sendall(response)


def _read_bounded_http_request(
    conn: socket.socket, *, deadline: float
) -> tuple[str, str, bytes] | None:
    buf = bytearray()
    header_end = -1
    while header_end == -1:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        conn.settimeout(remaining)
        chunk = conn.recv(4096)
        if not chunk:
            return None
        buf.extend(chunk)
        if len(buf) > MAX_INTERNAL_REQUEST_BYTES:
            return None
        header_end = buf.find(b"\r\n\r\n")
    head = bytes(buf[:header_end]).decode("ascii", errors="strict")
    lines = head.split("\r\n")
    if not lines:
        return None
    parts = lines[0].split(" ")
    if len(parts) != 3:
        return None
    method, path, _version = parts
    content_length: int | None = None
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            key = k.strip().lower()
            if key == "transfer-encoding":
                return None
            if key == "content-length":
                if content_length is not None:
                    return None
                content_length = int(v.strip())
    effective_length = 0 if content_length is None else content_length
    if effective_length < 0 or effective_length > MAX_INTERNAL_REQUEST_BYTES:
        return None
    body = bytearray(buf[header_end + 4 :])
    while len(body) < effective_length:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        conn.settimeout(remaining)
        chunk = conn.recv(min(4096, effective_length - len(body)))
        if not chunk:
            return None
        body.extend(chunk)
    return method, path, bytes(body[:effective_length])


def handle_recovery_status_connection(
    conn: socket.socket,
    ingest: RecoveryStatusIngestService,
    *,
    allowed_uid: int | None = None,
    allowed_uids: frozenset[int] | set[int] | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Serve one SO_PEERCRED + Ed25519 authenticated POST /internal/recovery-status request."""
    deadline = time.monotonic() + timeout_seconds
    try:
        conn.settimeout(timeout_seconds)
        caller_uid = peer_uid(conn)
        permitted = (
            allowed_uids
            if allowed_uids is not None
            else ({allowed_uid} if allowed_uid is not None else None)
        )
        if permitted is not None and caller_uid not in permitted:
            _write_http_json(conn, 403, "Forbidden", {"code": "peer_uid_denied"}, deadline=deadline)
            return
        parsed = _read_bounded_http_request(conn, deadline=deadline)
        if parsed is None:
            _write_http_json(
                conn, 400, "Bad Request", {"code": "malformed_request"}, deadline=deadline
            )
            return
        method, path, body = parsed
        if method != "POST" or path != INTERNAL_RECOVERY_STATUS_ROUTE:
            _write_http_json(
                conn, 405, "Method Not Allowed", {"code": "route_denied"}, deadline=deadline
            )
            return
        payload = json.loads(body.decode("utf-8"))
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            _write_http_json(conn, 400, "Bad Request", {"code": "missing_token"}, deadline=deadline)
            return
        outcome = ingest.ingest_signed(token)
        _write_http_json(
            conn,
            200,
            "OK",
            {
                "applied": outcome.applied,
                "reason": outcome.reason,
                "operatorId": outcome.operator_id,
                "sourceEpoch": outcome.source_epoch,
                "sourceRevision": outcome.source_revision,
            },
            deadline=deadline,
        )
    except TimeoutError:
        return
    except RecoverySummaryDenied:
        try:
            _write_http_json(
                conn, 403, "Forbidden", {"code": RecoverySummaryDenied.code}, deadline=deadline
            )
        except OSError:
            pass
    except UnicodeDecodeError, ValueError:
        try:
            _write_http_json(
                conn, 400, "Bad Request", {"code": "malformed_json"}, deadline=deadline
            )
        except OSError:
            pass
    except Exception:
        try:
            _write_http_json(
                conn,
                503,
                "Service Unavailable",
                {"code": "ingest_unavailable"},
                deadline=deadline,
            )
        except OSError:
            pass


class RecoveryStatusRelayServer:
    """Private Unix-socket server for POST /internal/recovery-status (H06.3 / D7)."""

    def __init__(
        self,
        listener: socket.socket,
        ingest: RecoveryStatusIngestService,
        *,
        allowed_uid: int | None = None,
        allowed_uids: frozenset[int] | set[int] | None = None,
        max_workers: int = 4,
    ):
        self._listener = listener
        self._ingest = ingest
        self._allowed_uid = allowed_uid
        self._allowed_uids = frozenset(allowed_uids) if allowed_uids is not None else None
        self._max_workers = max(1, max_workers)
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []

    def start(self) -> None:
        self._listener.settimeout(0.2)
        self._workers = [
            threading.Thread(target=self._worker_loop, name=f"summary-relay-{idx}", daemon=True)
            for idx in range(self._max_workers)
        ]
        for worker in self._workers:
            worker.start()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                handle_recovery_status_connection(
                    conn,
                    self._ingest,
                    allowed_uid=self._allowed_uid,
                    allowed_uids=self._allowed_uids,
                )
            finally:
                conn.close()

    def stop(self) -> None:
        self._stop.set()
        for worker in self._workers:
            worker.join(timeout=5.0)
        self._workers.clear()


class UnixSummaryPublisher:
    """Best-effort, bounded-timeout publisher sending signed summaries to Admin over AF_UNIX."""

    def __init__(
        self,
        socket_path: Path,
        *,
        expected_peer_uid: int,
        timeout_seconds: float = 5.0,
    ):
        if not socket_path.is_absolute():
            raise ValueError("Recovery status socket_path must be absolute.")
        self.socket_path = socket_path
        self.expected_peer_uid = expected_peer_uid
        self.timeout_seconds = timeout_seconds

    def __call__(self, token: str) -> None:
        from app.modules.host_agent.application.dispatch import (
            HostAgentDenied,
            HostAgentUnavailable,
        )

        body = json.dumps({"token": token}, separators=(",", ":")).encode("utf-8")
        request = (
            f"POST {INTERNAL_RECOVERY_STATUS_ROUTE} HTTP/1.1\r\n"
            "Host: internal\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(self.timeout_seconds)
                conn.connect(str(self.socket_path))
                if peer_uid(conn) != self.expected_peer_uid:
                    _RELAY_LOGGER.warning("Recovery status relay peer UID mismatch; dropping.")
                    return
                conn.sendall(request)
                resp = conn.recv(2048)
                if not resp.startswith(b"HTTP/1.1 200"):
                    _RELAY_LOGGER.warning("Recovery status relay returned non-200 status.")
        except OSError, HostAgentDenied, HostAgentUnavailable:
            _RELAY_LOGGER.warning("Best-effort protection summary relay unavailable.")
