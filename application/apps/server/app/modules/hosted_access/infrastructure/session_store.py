"""Private per-workspace sessions; ordinary authentication performs one indexed SELECT."""

from datetime import datetime
import os
import stat
from typing import Mapping

from sqlalchemy import MetaData, Table, delete, func, select, update

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.schema import REVISION, initialize_schema
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

MAX_ENROLLMENTS = 16
MAX_SESSIONS = 32


class SQLiteHostedSessionStore:
    def __init__(self, deployment: HostedDeployment):
        self.deployment = deployment
        path = deployment.administration_database
        if not path.is_file() or path.is_symlink():
            raise HostedAccessError("hosted_store_missing", "Initialize hosted access first.", 503)
        if os.name == "posix" and (
            path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) & 0o077
        ):
            raise HostedAccessError("hosted_store_invalid", "Hosted store must be private.", 503)
        self.engine = create_sqlite_engine(path)
        metadata = MetaData()
        metadata.reflect(self.engine)
        expected = {
            "hosted_operator",
            "hosted_enrollment",
            "hosted_session",
            "hosted_blocked_assertion",
            "hosted_draft_lease",
            "alembic_version",
        }
        if set(metadata.tables) != expected:
            raise HostedAccessError("hosted_store_invalid", "Hosted access schema is invalid.", 503)
        self.operator = metadata.tables["hosted_operator"]
        self.enrollment = metadata.tables["hosted_enrollment"]
        self.sessions = metadata.tables["hosted_session"]
        self.blocked = metadata.tables["hosted_blocked_assertion"]
        with self.engine.connect() as connection:
            revisions = connection.execute(select(metadata.tables["alembic_version"])).all()
            operator = connection.execute(select(self.operator)).mappings().one_or_none()
        if revisions != [(REVISION,)] or not self._matches(operator):
            raise HostedAccessError(
                "hosted_store_invalid", "Hosted access binding is invalid.", 503
            )

    def _matches(self, operator) -> bool:
        return operator is not None and all(
            operator[key] == value
            for key, value in {
                "id": str(self.deployment.operator_id),
                "workspace_id": str(self.deployment.workspace_id),
                "issuer": self.deployment.identity_issuer,
                "email": self.deployment.allowed_email,
            }.items()
        )

    @staticmethod
    def initialize(deployment: HostedDeployment) -> None:
        path = deployment.administration_database
        # Exclusive reservation refuses replacement, including existing symlinks.
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("xb"):
            pass
        path.chmod(0o600)
        engine = create_sqlite_engine(path)
        try:
            with immediate_transaction(engine) as connection:
                initialize_schema(connection)
                operator = Table("hosted_operator", MetaData(), autoload_with=connection)
                connection.execute(
                    operator.insert().values(
                        id=str(deployment.operator_id),
                        workspace_id=str(deployment.workspace_id),
                        issuer=deployment.identity_issuer,
                        email=deployment.allowed_email,
                        subject=None,
                        active=False,
                        generation=0,
                        not_before=0,
                        restore_marker=None,
                    )
                )
        finally:
            engine.dispose()

    def enrollments(self) -> list[Mapping[str, object]]:
        with self.engine.connect() as connection:
            return list(connection.execute(select(self.enrollment)).mappings())

    def recovery_reference(self):
        """Allowlist identity references only, never usable session/generation rows."""
        with self.engine.connect() as connection:
            approved = connection.scalar(select(self.operator.c.subject))
            pending = list(connection.scalars(select(self.enrollment.c.subject)))
        return {"approvedSubjectReference": approved, "pendingSubjectReferences": pending}

    def bind_restore_marker(self, marker: str, now: datetime) -> None:
        """Restoring business history requires new enrollment, never restored sessions."""
        with immediate_transaction(self.engine) as connection:
            operator = connection.execute(select(self.operator)).mappings().one()
            previous = operator["restore_marker"]
            if previous == marker:
                return
            values = {"restore_marker": marker}
            if previous is not None:
                values.update(
                    subject=None,
                    active=False,
                    generation=operator["generation"] + 1,
                    not_before=now.timestamp(),
                )
                connection.execute(delete(self.sessions))
                connection.execute(delete(self.enrollment))
                connection.execute(delete(self.blocked))
                leases = Table("hosted_draft_lease", MetaData(), autoload_with=connection)
                connection.execute(delete(leases))
            connection.execute(update(self.operator).values(**values))

    def activate(self, subject: str) -> None:
        with immediate_transaction(self.engine) as connection:
            candidate = (
                connection.execute(
                    select(self.enrollment).where(self.enrollment.c.subject == subject)
                )
                .mappings()
                .one_or_none()
            )
            if candidate is None or candidate["email"] != self.deployment.allowed_email:
                raise HostedAccessError(
                    "hosted_enrollment_missing", "Verified enrollment required.", 409
                )
            existing = connection.execute(select(self.operator)).mappings().one()
            if existing["subject"] is not None and existing["subject"] != subject:
                raise HostedAccessError(
                    "hosted_rebinding_required", "Explicit rebinding is required.", 409
                )
            connection.execute(update(self.operator).values(subject=subject, active=True))

    def disable(self, now: datetime) -> None:
        with immediate_transaction(self.engine) as connection:
            connection.execute(
                update(self.operator).values(
                    active=False,
                    generation=self.operator.c.generation + 1,
                    not_before=now.timestamp(),
                )
            )

    def revoke_all(self, now: datetime) -> None:
        with immediate_transaction(self.engine) as connection:
            connection.execute(
                update(self.operator).values(
                    generation=self.operator.c.generation + 1, not_before=now.timestamp()
                )
            )

    def begin_session(self, values: Mapping[str, object]) -> None:
        pending = False
        with immediate_transaction(self.engine) as connection:
            operator = connection.execute(select(self.operator)).mappings().one()
            if operator["subject"] is None or (
                not operator["active"] and operator["subject"] != values["subject"]
            ):
                self._enroll(connection, values)
                pending = True
            else:
                self._require_eligible(connection, operator, values)
                connection.execute(
                    delete(self.sessions).where(self.sessions.c.expires_at <= values["now"])
                )
                connection.execute(delete(self.sessions).where(self.sessions.c.revoked.is_(True)))
                connection.execute(
                    delete(self.blocked).where(self.blocked.c.expires_at <= values["now"])
                )
                count = connection.scalar(select(func.count()).select_from(self.sessions))
                if count >= MAX_SESSIONS:
                    raise HostedAccessError("hosted_session_limit", "Session limit reached.", 429)
                session_values = {
                    key: values[key]
                    for key in (
                        "token_hash",
                        "csrf_hash",
                        "assertion_hash",
                        "assertion_expiry",
                        "expires_at",
                    )
                }
                connection.execute(
                    self.sessions.insert().values(
                        **session_values,
                        operator_id=operator["id"],
                        generation=operator["generation"],
                        revoked=False,
                    )
                )
        if pending:
            raise HostedAccessError(
                "hosted_enrollment_pending", "Administrator approval required.", 403
            )

    def _enroll(self, connection, values) -> None:
        subject = values["subject"]
        existing = connection.scalar(
            select(self.enrollment.c.subject).where(self.enrollment.c.subject == subject)
        )
        if existing is None:
            count = connection.scalar(select(func.count()).select_from(self.enrollment))
            if count >= MAX_ENROLLMENTS:
                raise HostedAccessError("hosted_enrollment_limit", "Enrollment limit reached.", 429)
            connection.execute(
                self.enrollment.insert().values(
                    subject=subject, email=values["email"], received_at=values["now"]
                )
            )

    def rebind(self, subject: str, now: datetime) -> None:
        with immediate_transaction(self.engine) as connection:
            operator = connection.execute(select(self.operator)).mappings().one()
            candidate = (
                connection.execute(
                    select(self.enrollment).where(self.enrollment.c.subject == subject)
                )
                .mappings()
                .one_or_none()
            )
            if operator["active"] or candidate is None:
                raise HostedAccessError(
                    "hosted_rebinding_required",
                    "Disable access and verify the new subject first.",
                    409,
                )
            connection.execute(
                update(self.operator).values(
                    subject=subject,
                    generation=self.operator.c.generation + 1,
                    not_before=now.timestamp(),
                )
            )

    def _require_eligible(self, connection, operator, values) -> None:
        blocked = connection.scalar(
            select(self.blocked.c.fingerprint).where(
                self.blocked.c.fingerprint == values["assertion_hash"],
                self.blocked.c.expires_at > values["now"],
            )
        )
        if (
            not operator["active"]
            or operator["subject"] != values["subject"]
            or values["issued_at"] <= operator["not_before"]
            or blocked
        ):
            raise HostedAccessError(
                "hosted_reauthentication_required", "Fresh sign-in required.", 403
            )

    def session(self, token_hash: str) -> Mapping[str, object] | None:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(
                        self.sessions,
                        self.operator.c.workspace_id,
                        self.operator.c.issuer,
                        self.operator.c.email,
                        self.operator.c.subject,
                        self.operator.c.active,
                        self.operator.c.not_before,
                        self.operator.c.generation.label("current_generation"),
                    )
                    .join(self.operator)
                    .where(self.sessions.c.token_hash == token_hash)
                )
                .mappings()
                .one_or_none()
            )

    def revoke(
        self,
        token_hash: str,
        now: datetime,
        *,
        assertion_hash: str,
        assertion_expiry: float,
        all_devices: bool,
    ) -> None:
        with immediate_transaction(self.engine) as connection:
            row = (
                connection.execute(
                    select(self.sessions).where(self.sessions.c.token_hash == token_hash)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return
            connection.execute(
                update(self.sessions)
                .where(self.sessions.c.token_hash == token_hash)
                .values(revoked=True)
            )
            for fingerprint, expiry in (
                (row["assertion_hash"], row["assertion_expiry"]),
                (assertion_hash, assertion_expiry),
            ):
                existing = connection.scalar(
                    select(self.blocked.c.expires_at).where(
                        self.blocked.c.fingerprint == fingerprint
                    )
                )
                if existing is None:
                    connection.execute(
                        self.blocked.insert().values(fingerprint=fingerprint, expires_at=expiry)
                    )
                elif expiry > existing:
                    connection.execute(
                        update(self.blocked)
                        .where(self.blocked.c.fingerprint == fingerprint)
                        .values(expires_at=expiry)
                    )
            if all_devices:
                connection.execute(
                    update(self.operator).values(
                        generation=self.operator.c.generation + 1, not_before=now.timestamp()
                    )
                )
