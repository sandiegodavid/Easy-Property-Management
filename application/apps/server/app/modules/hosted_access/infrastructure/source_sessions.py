"""Source-owned request authorization, signed status application and recent authorization."""

from dataclasses import dataclass
from hmac import compare_digest
import re
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import text

from app.modules.hosted_access.application.handoff_channel import RecentChallengeObservation
from app.modules.hosted_access.application.identity_evidence import (
    RecentAuthGrant,
    RenewalLineage,
    SessionObservationGrant,
)
from app.modules.hosted_access.application.identity_setup import MINUTE
from app.modules.hosted_access.application.identity_states import AccessSessionState
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.modules.hosted_access.infrastructure.handoff_signing import verify_evidence
from app.platform.hosted_contracts.values import RequestHash
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.operations import OperationOutcome
from app.modules.hosted_access.application.source_contracts import SourceResult

_COOKIE = re.compile(r"[A-Za-z0-9_-]{43}")
MAX_RECENT_CHALLENGES = 8


@dataclass(frozen=True)
class LogoutResult:
    source: OperationOutcome[SourceResult]
    central_reconciled: bool


class SessionExpired(ProviderDenied):
    code = "session_expired"


class SessionLimitReached(ProviderDenied):
    code = "session_limit_reached"


def session_hash(cookie):
    if not isinstance(cookie, str) or not _COOKIE.fullmatch(cookie):
        raise ProviderDenied()
    return digest(cookie)


def session_row(connection, cookie, meta, now, *, lineage=False, allow_stale=False):
    row = (
        connection.execute(
            text("SELECT * FROM main.access_sessions WHERE session_hash=:hash"),
            {"hash": session_hash(cookie)},
        )
        .mappings()
        .one_or_none()
    )
    return check_session_row(row, meta, now, lineage=lineage, allow_stale=allow_stale)


def check_session_row(row, meta, now, *, lineage=False, allow_stale=False):
    if row is None or (
        row["revoked_at"] is not None
        or row["generation"] != meta["session_generation"]
        or row["access_epoch"] != meta["access_epoch"]
        or row["actor_subject"] != meta["subject"]
        or not meta["not_before"] <= row["issued_at"] <= now < row["remembered_until"]
    ):
        raise ProviderDenied()
    if not lineage:
        if now >= min(row["expires_at"], row["managed_valid_until"]):
            raise SessionExpired()
        if not allow_stale and now >= row["revocation_valid_until"]:
            raise ProviderUnavailable()
    return row


def device_rows(connection, meta, now):
    return (
        connection.execute(
            text("""
        SELECT session_id, display_label, last_seen_at
        FROM main.access_sessions WHERE generation=:generation AND access_epoch=:epoch
          AND actor_subject=:subject AND revoked_at IS NULL AND expires_at>:now AND issued_at<=:now
        ORDER BY last_seen_at DESC, session_id LIMIT 32
    """),
            {
                "generation": meta["session_generation"],
                "epoch": meta["access_epoch"],
                "subject": meta["subject"],
                "now": now,
            },
        )
        .mappings()
        .all()
    )


def check_csrf(row, csrf):
    if (
        not isinstance(csrf, str)
        or not _COOKIE.fullmatch(csrf)
        or not compare_digest(row["csrf_hash"], digest(csrf))
    ):
        raise ProviderDenied()


def renewal_lineage(row):
    return RenewalLineage(
        session_id=row["session_id"],
        managed_session_id=row["managed_session_id"],
        session_generation=row["generation"],
        remembered_until=row["remembered_until"],
        remembered=bool(row["remembered"]),
    )


def observation_hash(session_id, managed_id):
    return digest("source-status:" + session_id + ":" + managed_id)


class SourceSessions:
    def __init__(self, destination):
        self.destination = destination
        self.engine, self.mutation, self.clock = (
            destination.engine,
            destination.mutation,
            destination.clock,
        )

    def logout(self, lifecycle, central, cookie, csrf, command):
        """Commit local denial first, then check the original central acknowledgement."""
        binding = self.destination.binding()
        actor = ServiceAuthority(
            deployment_id=binding.deployment_id,
            scope=binding.scope,
            service="source",
            authenticated_channel_ref="operator-session",
        )
        result = lifecycle.execute(actor, command, cookie=cookie, csrf=csrf)
        try:
            central.reconcile_revocation(command)
        except ProviderUnavailable, ProviderDenied, TimeoutError:
            return LogoutResult(result, central_reconciled=False)
        return LogoutResult(result, central_reconciled=True)

    def authorize(self, cookie, *, csrf=None, write=False):
        return self.authorize_with_restore(cookie, csrf=csrf, write=write)[0]

    def authorize_with_restore(self, cookie, *, csrf=None, write=False):
        """Read indexed local authority and its restore fence in one snapshot."""
        with self.engine.connect() as connection:
            snapshot = (
                connection.execute(
                    text("""
                SELECT s.*, m.deployment_id, m.operator_id, m.workspace_id, m.binding_id,
                    m.resource_generation, m.issuer, m.subject, m.effective_access,
                    m.access_epoch AS source_epoch, m.session_generation, m.not_before,
                    m.maintenance_operation_id, m.restore_generation
                FROM main.access_sessions s
                JOIN main.access_meta m ON m.id=1
                WHERE s.session_hash=:hash
            """),
                    {"hash": session_hash(cookie)},
                )
                .mappings()
                .one_or_none()
            )
        if snapshot is None:
            raise ProviderDenied()
        session_data = {
            key: snapshot[key] for key in AccessSessionState.model_fields if key in snapshot
        }
        session_data["remembered"] = bool(snapshot["remembered"])
        meta = dict(snapshot) | {"access_epoch": snapshot["source_epoch"]}
        self.destination.check_current(meta, enabled=True)
        check_session_row(session_data, meta, self.clock())
        if write:
            check_csrf(session_data, csrf)
        return AccessSessionState.model_validate(session_data), snapshot["restore_generation"]

    def refresh(self, cookie, fetch):
        """Fetch a scoped observation outside the writer; apply only to the same live row."""
        with self.engine.connect() as connection, connection.begin():
            binding, meta = self.destination._current(connection, enabled=True)
            row = session_row(connection, cookie, meta, self.clock(), allow_stale=True)
            if self.clock() < row["revocation_valid_until"]:
                return False
            session_id, managed_id = row["session_id"], row["managed_session_id"]
        signed = fetch(binding, session_id, managed_id)
        self.apply_observation(cookie, signed)
        return True

    def apply_observation(self, cookie, signed):
        grant = verify_evidence(
            signed, SessionObservationGrant, self.destination.central_key, now=self.clock()
        )
        with self.mutation() as connection:
            binding, meta = self.destination._current(connection, enabled=True)
            now = self.clock()
            row = session_row(connection, cookie, meta, now, allow_stale=True)
            managed = grant.managed
            if (
                not grant.issued_at <= now < grant.expires_at
                or grant.binding != binding
                or managed.managed_session_id != row["managed_session_id"]
                or grant.request_hash
                != observation_hash(row["session_id"], row["managed_session_id"])
                or managed.provider_valid_until != row["managed_valid_until"]
                or managed.remembered_until != row["remembered_until"]
                or managed.revoked is False
                and managed.authenticated_at < meta["not_before"]
            ):
                raise ProviderDenied()
            revision = row["managed_observation_revision"]
            if managed.revision < revision or managed.valid_until < row["revocation_valid_until"]:
                raise ProviderDenied()
            if managed.revision == revision:
                if managed.revoked or managed.valid_until != row["revocation_valid_until"]:
                    raise ProviderDenied()
                return
            connection.execute(
                text("""
                UPDATE main.access_sessions SET managed_observation_revision=:revision,
                    revocation_valid_until=:until, revoked_at=:revoked
                WHERE session_hash=:hash
            """),
                {
                    "revision": managed.revision,
                    "until": managed.valid_until,
                    "revoked": now if managed.revoked else None,
                    "hash": row["session_hash"],
                },
            )

    def begin_recent(self, cookie, csrf, request_hash):
        """One-use exact-request challenge. The caller still owns the sensitive action."""
        TypeAdapter(RequestHash).validate_python(request_hash)
        with self.mutation() as connection:
            _, meta = self.destination._current(connection, enabled=True)
            now = self.clock()
            row = session_row(connection, cookie, meta, now)
            check_csrf(row, csrf)
            selected = {"session": row["session_id"], "now": now}
            count = connection.scalar(
                text("""
                SELECT count(*) FROM main.source_recent_challenges
                WHERE session_id=:session AND consumed_at IS NULL AND expires_at>:now
            """),
                selected,
            )
            if count >= MAX_RECENT_CHALLENGES:
                raise ProviderDenied()
            challenge = str(uuid4())
            deadline = min(now + 5 * MINUTE, row["expires_at"])
            connection.execute(
                text("""
                INSERT INTO main.source_recent_challenges
                    (challenge_id,session_id,request_hash,created_at,expires_at)
                VALUES (:id,:session,:hash,:now,:expires)
            """),
                selected | {"id": challenge, "hash": request_hash, "expires": deadline},
            )
            return challenge, deadline

    def observe_recent(self, challenge_id):
        """Private owner observation for central signing after fresh provider verification."""
        with self.engine.connect() as connection, connection.begin():
            binding, meta = self.destination._current(connection, enabled=True)
            row = (
                connection.execute(
                    text("""
                SELECT c.*, s.managed_session_id, s.generation, s.access_epoch, s.revoked_at,
                    s.revocation_valid_until, s.expires_at AS session_expires
                FROM main.source_recent_challenges c
                JOIN main.access_sessions s ON s.session_id=c.session_id
                WHERE c.challenge_id=:id
            """),
                    {"id": challenge_id},
                )
                .mappings()
                .one_or_none()
            )
            now = self.clock()
            if row is None or (
                row["consumed_at"] is not None
                or row["revoked_at"] is not None
                or row["generation"] != meta["session_generation"]
                or row["access_epoch"] != meta["access_epoch"]
                or not row["created_at"]
                <= now
                < min(row["expires_at"], row["session_expires"], row["revocation_valid_until"])
            ):
                raise ProviderDenied()
            return RecentChallengeObservation(
                binding=binding,
                **{
                    field: row[field]
                    for field in (
                        "challenge_id",
                        "session_id",
                        "managed_session_id",
                        "request_hash",
                        "created_at",
                        "expires_at",
                    )
                },
            )

    def consume_recent(self, connection, cookie, csrf, request_hash, signed, *, require_mfa=False):
        """Consume inside the sensitive action's source transaction, including rollback."""
        raw = connection.connection.driver_connection
        if (
            not connection.in_transaction()
            or not raw.in_transaction
            or connection.engine is not self.engine
        ):
            raise ValueError("Recent authentication requires its owning source transaction.")
        binding, meta = self.destination._current(connection, enabled=True)
        now = self.clock()
        row = session_row(connection, cookie, meta, now)
        check_csrf(row, csrf)
        grant = verify_evidence(signed, RecentAuthGrant, self.destination.central_key, now=now)
        if (
            grant.binding != binding
            or grant.session_id != row["session_id"]
            or grant.request_hash != request_hash
            or grant.nonce_hash != digest(grant.operation_id)
            or grant.managed.managed_session_id == row["managed_session_id"]
            or grant.managed.authenticated_at < meta["not_before"]
            or (require_mfa and grant.managed.mfa_verified_at is None)
        ):
            raise ProviderDenied()
        changed = connection.execute(
            text("""
            UPDATE main.source_recent_challenges SET consumed_at=:now
            WHERE challenge_id=:id AND session_id=:session AND request_hash=:hash
                AND consumed_at IS NULL AND created_at<=:auth AND expires_at>:now
        """),
            {
                "id": grant.operation_id,
                "session": row["session_id"],
                "hash": request_hash,
                "auth": grant.managed.authenticated_at,
                "now": now,
            },
        )
        if changed.rowcount != 1:
            raise ProviderDenied()
