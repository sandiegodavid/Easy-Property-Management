"""Source-owned editing authority for managed Operator recovery."""

from contextlib import contextmanager
from contextvars import ContextVar
import hmac

from sqlalchemy import text

from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.application.service import token_hash
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.draft_leases import (
    LEASE_SECONDS,
    MAX_LEASES,
    RENEW_SECONDS,
    conflict,
)
from app.modules.hosted_access.infrastructure.source_sessions import check_session_row
from app.platform.actor_context import current_operator_actor


class ManagedDraftLeases:
    def __init__(self, owner, lock, revision):
        self.owner, self.lock, self.revision = owner, lock, revision
        self.current_recovery = ContextVar("managed_recovery_edit", default=None)

    def claim(self, record_id, actor, *, token, expected_revision, takeover=False, renew=False):
        with self.lock:
            # Recovery revisions live in a different store. Keep only the
            # process gate held across this read and the source lease change.
            if self.revision(record_id) != expected_revision:
                raise HostedAccessError(
                    "hosted_draft_revision_conflict", "Review the current saved form first.", 409
                )
            with self.owner.mutation() as connection:
                return self._claim(connection, record_id, actor, token_hash(token), takeover, renew)

    def _claim(self, connection, record_id, actor, proof, takeover, renew):
        _, meta = self.owner._current(connection, enabled=True)
        if meta["restore_generation"] != actor.restore_generation:
            raise ProviderDenied()
        now = self.owner.clock()
        session = self._session(connection, actor.session_reference, meta, now)
        row = self._lease(connection, record_id)
        live = self._live(row, meta, now)
        owns = live and self._owns(row, actor, proof)
        if live and not owns:
            try:
                self._session(connection, row["session_hash"], meta, now, allow_stale=True)
            except ProviderDenied:
                live = False
        if renew:
            if not owns or takeover:
                raise conflict()
            if now - row["renewed_at"] < RENEW_SECONDS * 1000:
                return self._times(row)
        elif owns:
            return self._times(row)
        elif live and not takeover:
            raise conflict()

        connection.execute(
            text("""
            DELETE FROM draft_leases WHERE expires_at<=:now OR access_epoch!=:epoch
                OR restore_generation!=:restore
                OR NOT EXISTS (
                    SELECT 1 FROM access_sessions s
                    WHERE s.session_hash=draft_leases.session_hash AND s.revoked_at IS NULL
                        AND s.generation=:generation AND s.expires_at>:now
                )
            """),
            {
                "now": now,
                "epoch": meta["access_epoch"],
                "restore": meta["restore_generation"],
                "generation": meta["session_generation"],
            },
        )
        if not live and self._lease(connection, record_id) is None:
            count = connection.scalar(text("SELECT count(*) FROM draft_leases"))
            if count >= MAX_LEASES:
                raise HostedAccessError(
                    "hosted_draft_lease_limit", "Close or let inactive edit claims expire.", 409
                )
        if connection.scalar(
            text(
                "SELECT record_id FROM draft_leases WHERE lease_token_hash=:token AND record_id!=:id"
            ),
            {"token": proof, "id": record_id},
        ):
            raise conflict()
        values = {
            "id": record_id,
            "session": session["session_hash"],
            "token": proof,
            "epoch": meta["access_epoch"],
            "restore": meta["restore_generation"],
            "renewed_at": now,
            "expires_at": min(now + LEASE_SECONDS * 1000, session["expires_at"]),
        }
        connection.execute(
            text("""
            INSERT INTO draft_leases (record_id, session_hash, lease_token_hash, access_epoch,
                restore_generation, expires_at, renewed_at) VALUES (:id, :session, :token, :epoch, :restore,
                :expires_at, :renewed_at)
            ON CONFLICT(record_id) DO UPDATE SET session_hash=:session, lease_token_hash=:token,
                access_epoch=:epoch, restore_generation=:restore, expires_at=:expires_at,
                renewed_at=:renewed_at
            """),
            values,
        )
        return self._times(values)

    @contextmanager
    def mutation(self, record_id):
        with self.lock:
            self.verify(record_id, current_operator_actor())
            token = self.current_recovery.set(record_id)
            try:
                yield
            finally:
                self.current_recovery.reset(token)

    def verify(self, record_id, actor):
        if actor is None or not actor.session_reference or not actor.edit_lease:
            raise conflict()
        with self.owner.engine.connect() as connection, connection.begin():
            _, meta = self.owner._current(connection, enabled=True)
            if meta["restore_generation"] != actor.restore_generation:
                raise ProviderDenied()
            now = self.owner.clock()
            self._session(connection, actor.session_reference, meta, now)
            row = self._lease(connection, record_id)
            if not self._live(row, meta, now) or not self._owns(
                row, actor, token_hash(actor.edit_lease)
            ):
                raise conflict()

    @staticmethod
    def _session(connection, reference, meta, now, *, allow_stale=False):
        row = (
            connection.execute(
                text("SELECT * FROM access_sessions WHERE session_hash=:ref"), {"ref": reference}
            )
            .mappings()
            .one_or_none()
        )
        return check_session_row(row, meta, now, allow_stale=allow_stale)

    @staticmethod
    def _lease(connection, record_id):
        return (
            connection.execute(
                text("SELECT * FROM draft_leases WHERE record_id=:id"), {"id": record_id}
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _live(row, meta, now):
        return (
            row is not None
            and row["expires_at"] > now
            and row["access_epoch"] == meta["access_epoch"]
            and row["restore_generation"] == meta["restore_generation"]
        )

    @staticmethod
    def _owns(row, actor, proof):
        return row["session_hash"] == actor.session_reference and hmac.compare_digest(
            row["lease_token_hash"], proof
        )

    @staticmethod
    def _times(row):
        return {key: row[key] / 1000 for key in ("expires_at", "renewed_at")}
