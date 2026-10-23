"""Serialize takeover with owning recovery commits, without storing business payloads."""

from contextlib import contextmanager
import hmac

from sqlalchemy import MetaData, Table, delete, func, select, update
from sqlalchemy.exc import DBAPIError

from app.modules.hosted_access.application.service import token_hash
from app.modules.hosted_access.domain.models import HostedAccessError
from app.platform.actor_context import current_operator_actor
from app.platform.sqlite_engine import immediate_transaction

LEASE_SECONDS = 300
RENEW_SECONDS = 60
MAX_LEASES = 128


def conflict():
    return HostedAccessError(
        "hosted_draft_lease_conflict",
        "This editor no longer owns the saved form. Keep your input and explicitly claim or take over editing.",
        409,
    )


class SQLiteDraftLeaseStore:
    def __init__(self, sessions):
        self.sessions = sessions
        self.engine = sessions.engine
        self.table = Table("hosted_draft_lease", MetaData(), autoload_with=self.engine)

    @contextmanager
    def transaction(self):
        try:
            with immediate_transaction(self.engine) as connection:
                yield connection
        except DBAPIError as error:
            raise HostedAccessError(
                "hosted_draft_store_unavailable",
                "Edit authority is unavailable. Keep your input and retry explicitly.",
                503,
            ) from error

    def _session(self, connection, reference, now):
        sessions, operator = self.sessions.sessions, self.sessions.operator
        row = (
            connection.execute(
                select(
                    sessions.c.expires_at,
                    sessions.c.revoked,
                    sessions.c.generation,
                    operator.c.active,
                    operator.c.generation.label("current_generation"),
                )
                .join(operator)
                .where(sessions.c.token_hash == reference)
            )
            .mappings()
            .one_or_none()
        )
        if row is None or (
            row["revoked"]
            or not row["active"]
            or row["expires_at"] <= now
            or row["generation"] != row["current_generation"]
        ):
            raise HostedAccessError(
                "hosted_session_expired", "Sign in again before claiming edits."
            )
        return row

    def claim(self, record_id, actor, proof, *, now, takeover, renew, check_revision):
        tick = now.timestamp()
        table = self.table
        with self.transaction() as connection:
            session = self._session(connection, actor.session_reference, tick)
            check_revision()
            row = (
                connection.execute(select(table).where(table.c.record_id == record_id))
                .mappings()
                .one_or_none()
            )
            owns = (
                row
                and row["session_reference"] == actor.session_reference
                and hmac.compare_digest(row["token_hash"], proof)
            )
            live = row and row["expires_at"] > tick
            if live and not owns:
                try:
                    self._session(connection, row["session_reference"], tick)
                except HostedAccessError:
                    live = False
            if renew:
                if not owns or not live or takeover:
                    raise conflict()
                if tick - row["renewed_at"] < RENEW_SECONDS:
                    return dict(row)
            elif owns and live:
                return dict(row)  # Idempotent lost-response claim; never extends authority.
            elif live and not takeover:
                raise conflict()
            connection.execute(delete(table).where(table.c.expires_at <= tick))
            exists = connection.scalar(
                select(table.c.record_id).where(table.c.record_id == record_id)
            )
            if (
                not exists
                and connection.scalar(select(func.count()).select_from(table)) >= MAX_LEASES
            ):
                raise HostedAccessError(
                    "hosted_draft_lease_limit", "Close or let inactive edit claims expire.", 409
                )
            values = {
                "record_id": record_id,
                "session_reference": actor.session_reference,
                "token_hash": proof,
                "renewed_at": tick,
                "expires_at": min(tick + LEASE_SECONDS, session["expires_at"]),
            }
            if exists:
                connection.execute(
                    update(table).where(table.c.record_id == record_id).values(**values)
                )
            else:
                connection.execute(table.insert().values(**values))
            return values

    @contextmanager
    def guard(self, record_id, reference, token, now):
        with self.transaction() as connection:
            self._session(connection, reference, now.timestamp())
            row = (
                connection.execute(select(self.table).where(self.table.c.record_id == record_id))
                .mappings()
                .one_or_none()
            )
            if (
                not token
                or not row
                or (
                    row["session_reference"] != reference
                    or row["expires_at"] <= now.timestamp()
                    or not hmac.compare_digest(row["token_hash"], token_hash(token))
                )
            ):
                raise conflict()
            # Lock order: administrative reservation, then owning workspace write.
            # Claim/takeover waits for this complete business transaction to finish.
            yield


class HostedRecoveryAuthority:
    def __init__(self, store, now):
        self.store, self.now = store, now

    def mutation(self, record_id):
        actor = current_operator_actor()
        if actor is None or not actor.session_reference:
            raise conflict()
        return self.store.guard(record_id, actor.session_reference, actor.edit_lease, self.now())
