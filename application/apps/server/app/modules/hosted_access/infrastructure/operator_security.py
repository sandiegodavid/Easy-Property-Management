"""Operator-facing session projections and receipt-backed sign-out."""

from hmac import compare_digest
import json

from pydantic import TypeAdapter
from sqlalchemy import text

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.application.source_contracts import (
    Revoke,
    SourceCommand,
    SourceResult,
)
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.modules.hosted_access.infrastructure.source_sessions import (
    check_csrf,
    device_rows,
    session_hash,
    session_row,
)
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import CanonicalId

COMMAND_INTENT = TypeAdapter(SourceCommand.model_fields["intent"].annotation)
CHECK_WINDOW = 15 * 60 * 1000
LAST_SEEN_INTERVAL = 60 * 1000


def _command(binding, operation, key, revision, target):
    payload = Revoke(session_reference=target, all_devices=target is None)
    intent = COMMAND_INTENT.validate_python(
        {
            "deployment_id": binding.deployment_id,
            "scope": binding.scope,
            "kind": "revoke",
            "expected_revision": revision,
            "access_epoch": binding.access_epoch,
            "payload": payload,
        }
    )
    return SourceCommand(
        operation_id=operation,
        idempotency_key=key,
        intent=intent,
        request_hash=semantic_hash(intent),
    )


class OperatorSecurity:
    def __init__(
        self,
        owner,
        sessions,
        lifecycle,
        central,
        *,
        support_contact=None,
        business_capabilities=None,
    ):
        self.owner, self.sessions, self.lifecycle, self.central = (
            owner,
            sessions,
            lifecycle,
            central,
        )
        self.support = support_contact
        self.business_capabilities = business_capabilities or (lambda: [])

    def session(self, cookie):
        binding = self.owner.binding()
        row = self.sessions.authorize(cookie)
        self._observe_activity(cookie, row)
        # Opaque equality marker. Provider subject, issuer and fence values stay private.
        marker = digest(
            json.dumps(
                (binding.deployment_id, binding.scope.workspace_id, binding.issuer, binding.subject)
            )
        )
        return {
            "identity": marker,
            "sessionId": row.session_id,
            "expiresAt": row.expires_at,
            "renewAfter": min(row.expires_at, row.revocation_valid_until),
            "csrfToken": self.owner.csrf_token(cookie),
            "supportContact": self.support,
            "capabilities": ["identity.security", *self.business_capabilities()],
        }

    def _observe_activity(self, cookie, row):
        now = self.owner.clock()
        if now - row.last_seen_at < LAST_SEEN_INTERVAL:
            return
        with self.owner.mutation() as connection:
            _, meta = self.owner._current(connection, enabled=True)
            current = session_row(connection, cookie, meta, now)
            connection.execute(
                text("""
                UPDATE main.access_sessions SET last_seen_at=:now
                WHERE session_id=:id AND last_seen_at<=:before
            """),
                {"id": current["session_id"], "now": now, "before": now - LAST_SEEN_INTERVAL},
            )

    def refresh_csrf(self, cookie):
        # A stale status pauses business authority. Only the scoped refresh
        # endpoint may use this token until the provider observation succeeds.
        with self.owner.engine.connect() as connection, connection.begin():
            _, meta = self.owner._current(connection, enabled=True)
            row = session_row(connection, cookie, meta, self.owner.clock(), allow_stale=True)
            csrf = self.owner.csrf_token(cookie)
            check_csrf(row, csrf)
            return csrf

    def refresh(self, cookie, csrf):
        expected = self.refresh_csrf(cookie)
        if not compare_digest(expected, csrf if isinstance(csrf, str) and csrf.isascii() else ""):
            raise ProviderDenied()
        self.sessions.refresh(cookie, self.central.refresh_status)

    def devices(self, cookie):
        with self.owner.engine.connect() as connection, connection.begin():
            _, meta = self.owner._current(connection, enabled=True)
            now = self.owner.clock()
            current = session_row(connection, cookie, meta, now)
            return [
                {
                    "sessionId": row["session_id"],
                    "label": row["display_label"],
                    "lastSeenAt": row["last_seen_at"],
                    "current": row["session_id"] == current["session_id"],
                }
                for row in device_rows(connection, meta, now)
            ]

    def sign_out(self, cookie, csrf, operation, proof, *, selection, device=None):
        operation = TypeAdapter(CanonicalId).validate_python(operation)
        key = session_hash(proof)
        with self.owner.engine.connect() as connection, connection.begin():
            binding, meta = self.owner._current(connection, enabled=True)
            row = session_row(
                connection, cookie, meta, self.owner.clock(), lineage=selection != "other"
            )
            check_csrf(row, csrf)
            if selection == "other":
                if device == row["session_id"]:
                    raise ProviderDenied()
                target = TypeAdapter(CanonicalId).validate_python(device)
            elif selection == "current":
                target = row["session_id"]
            else:
                target = None
            command = _command(binding, operation, key, meta["revision"], target)
        if selection == "other":
            self.lifecycle.execute(
                ServiceAuthority(
                    deployment_id=binding.deployment_id,
                    scope=binding.scope,
                    service="source",
                    authenticated_channel_ref="operator-session",
                ),
                command,
                cookie=cookie,
                csrf=csrf,
                other_device=True,
            )
            return self._finish(command)
        return self.sessions.logout(
            self.lifecycle, self.central, cookie, csrf, command
        ).central_reconciled

    def check_sign_out(self, operation, proof, *, cookie=None, device=None, selection):
        key = session_hash(proof)
        with self.owner.engine.connect() as connection:
            binding = self.owner.binding()
            row = (
                connection.execute(
                    text("""
                SELECT * FROM main.access_receipts WHERE operation_id=:id
                   AND kind='revoke_sessions' AND idempotency_key=:key
            """),
                    {"id": operation, "key": key},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return "unknown", False
            if (
                row["access_epoch"] != binding.access_epoch
                or not row["recorded_at"] <= self.owner.clock() < row["recorded_at"] + CHECK_WINDOW
            ):
                raise ProviderDenied()
            result = SourceResult.model_validate_json(row["result_json"])
            if result.revocation is None:
                raise ProviderDenied()
            target = device if selection == "other" else None
            if selection == "current":
                target = result.revocation.session_id
            command = _command(binding, operation, key, row["source_revision"] - 1, target)
            if command.request_hash != row["request_hash"]:
                raise ProviderDenied()
            clear = False
            if cookie is not None and selection != "other":
                session = (
                    connection.execute(
                        text("""
                    SELECT session_id, issued_at, access_epoch FROM main.access_sessions
                    WHERE session_hash=:hash
                """),
                        {"hash": session_hash(cookie)},
                    )
                    .mappings()
                    .one_or_none()
                )
                clear = (
                    session is not None
                    and session["access_epoch"] == row["access_epoch"]
                    and (
                        session["session_id"] == target
                        if target is not None
                        else session["issued_at"] < result.revocation.not_before
                    )
                )
        return ("confirmed" if self._finish(command) else "pending"), clear

    def _finish(self, command):
        try:
            self.central.reconcile_revocation(command)
        except ProviderUnavailable, ProviderDenied, TimeoutError:
            return False
        return True
