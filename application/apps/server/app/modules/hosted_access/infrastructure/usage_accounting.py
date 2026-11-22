"""Logical Free storage accounting and durable usage reservations in access.sqlite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import Engine, text

from app.modules.hosted_access.domain.models import HostedAccessError
from app.platform.hosted_contracts.operations import SemanticConflict
from app.platform.sqlite_engine import immediate_transaction

MEASUREMENT_VERSION = "logical-v1"


@dataclass(frozen=True)
class LogicalUsageMeasurement:
    committed_db_bytes: int
    retained_file_bytes: int
    business_revision: str

    @property
    def used_bytes(self) -> int:
        return self.committed_db_bytes + self.retained_file_bytes


@dataclass(frozen=True)
class UsageSnapshot:
    usable_bytes: int
    committed_db_bytes: int
    retained_file_bytes: int
    reserved_bytes: int
    observed_at: int
    business_revision: str
    measurement_version: str
    revision: int

    @property
    def used_bytes(self) -> int:
        return self.committed_db_bytes + self.retained_file_bytes

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.usable_bytes - self.used_bytes - self.reserved_bytes)


@dataclass(frozen=True)
class UsageReservation:
    reservation_id: str
    operation_id: str
    request_hash: str
    reserved_bytes: int
    purpose: str
    source_epoch: int
    state: str


def measure_logical_usage(business_engine: Engine) -> LogicalUsageMeasurement:
    """Measure live committed SQLite pages plus deduplicated retained local file bytes (D6)."""
    with business_engine.connect() as connection:
        page_count = int(connection.exec_driver_sql("PRAGMA main.page_count").scalar_one())
        freelist_count = int(connection.exec_driver_sql("PRAGMA main.freelist_count").scalar_one())
        page_size = int(connection.exec_driver_sql("PRAGMA main.page_size").scalar_one())
        data_version = int(connection.exec_driver_sql("PRAGMA main.data_version").scalar_one())
        committed_db_bytes = max(0, page_count - freelist_count) * page_size

        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM main.sqlite_master WHERE type = 'table' "
                "AND name IN ('file_records', 'file_content_locations')"
            ).all()
        }
        if tables == {"file_records", "file_content_locations"}:
            retained_file_bytes = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(SUM(blob_bytes), 0) FROM ("
                        "  SELECT fr.content_sha256, MAX(fr.size_bytes) AS blob_bytes "
                        "  FROM main.file_records fr "
                        "  JOIN main.file_content_locations fcl ON fcl.file_id = fr.id "
                        "  WHERE fcl.storage_provider = 'local' "
                        "    AND fcl.storage_state = 'available' "
                        "  GROUP BY fr.content_sha256"
                        ")"
                    )
                ).scalar_one()
            )
        else:
            retained_file_bytes = 0

    return LogicalUsageMeasurement(
        committed_db_bytes=committed_db_bytes,
        retained_file_bytes=retained_file_bytes,
        business_revision=f"sqlite:{data_version}:{page_count}:{freelist_count}",
    )


class UsageAccountingStore:
    """Durable logical storage admission and settlement backed by access.sqlite."""

    def __init__(
        self,
        access_engine: Engine,
        business_engine: Engine,
        *,
        clock: Callable[[], int],
        measurement_version: str = MEASUREMENT_VERSION,
    ) -> None:
        self.access_engine = access_engine
        self.business_engine = business_engine
        self.clock = clock
        self.measurement_version = measurement_version

    def read_usage(self) -> UsageSnapshot | None:
        with self.access_engine.connect() as connection:
            meta = (
                connection.execute(text("SELECT usable_bytes FROM main.access_meta WHERE id = 1"))
                .mappings()
                .one_or_none()
            )
            state = (
                connection.execute(text("SELECT * FROM main.usage_state WHERE id = 1"))
                .mappings()
                .one_or_none()
            )
            if meta is None or state is None:
                return None
            reserved = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(SUM(reserved_bytes), 0) "
                        "FROM main.usage_reservations "
                        "WHERE state IN ('held', 'unknown')"
                    )
                ).scalar_one()
            )
            return UsageSnapshot(
                usable_bytes=meta["usable_bytes"],
                committed_db_bytes=state["committed_db_bytes"],
                retained_file_bytes=state["retained_file_bytes"],
                reserved_bytes=reserved,
                observed_at=state["observed_at"],
                business_revision=state["business_revision"],
                measurement_version=state["measurement_version"],
                revision=state["revision"],
            )

    def refresh_usage_state(self, *, business_revision: str | None = None) -> UsageSnapshot:
        """Re-measure business DB + retained files outside the access lock, then commit."""
        measured = measure_logical_usage(self.business_engine)
        rev_label = business_revision or measured.business_revision
        with immediate_transaction(self.access_engine) as connection:
            now = self.clock()
            meta = (
                connection.execute(text("SELECT usable_bytes FROM main.access_meta WHERE id = 1"))
                .mappings()
                .one_or_none()
            )
            if meta is None:
                raise HostedAccessError(
                    "hosted_storage_unavailable",
                    "Workspace storage policy is not initialized.",
                    503,
                )
            existing = (
                connection.execute(text("SELECT revision FROM main.usage_state WHERE id = 1"))
                .mappings()
                .one_or_none()
            )
            next_rev = 1 if existing is None else existing["revision"] + 1
            params = {
                "business_revision": rev_label,
                "committed_db_bytes": measured.committed_db_bytes,
                "retained_file_bytes": measured.retained_file_bytes,
                "observed_at": now,
                "measurement_version": self.measurement_version,
                "revision": next_rev,
            }
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO main.usage_state ("
                        "id, business_revision, committed_db_bytes, retained_file_bytes, "
                        "observed_at, measurement_version, revision"
                        ") VALUES ("
                        "1, :business_revision, :committed_db_bytes, :retained_file_bytes, "
                        ":observed_at, :measurement_version, :revision"
                        ")"
                    ),
                    params,
                )
            else:
                connection.execute(
                    text(
                        "UPDATE main.usage_state SET "
                        "business_revision = :business_revision, "
                        "committed_db_bytes = :committed_db_bytes, "
                        "retained_file_bytes = :retained_file_bytes, "
                        "observed_at = :observed_at, "
                        "measurement_version = :measurement_version, "
                        "revision = :revision "
                        "WHERE id = 1"
                    ),
                    params,
                )
            reserved = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(SUM(reserved_bytes), 0) "
                        "FROM main.usage_reservations "
                        "WHERE state IN ('held', 'unknown')"
                    )
                ).scalar_one()
            )
            return UsageSnapshot(
                usable_bytes=meta["usable_bytes"],
                committed_db_bytes=measured.committed_db_bytes,
                retained_file_bytes=measured.retained_file_bytes,
                reserved_bytes=reserved,
                observed_at=now,
                business_revision=rev_label,
                measurement_version=self.measurement_version,
                revision=next_rev,
            )

    def reserve(
        self,
        operation_id: str,
        request_hash: str,
        *,
        reserved_bytes: int,
        purpose: str,
        source_epoch: int,
    ) -> UsageReservation:
        """Atomically admit and record a logical storage reservation."""
        if type(reserved_bytes) is not int or reserved_bytes <= 0:
            raise HostedAccessError("hosted_storage_unavailable", "Invalid reservation size.", 503)
        with immediate_transaction(self.access_engine) as connection:
            existing = (
                connection.execute(
                    text(
                        "SELECT reservation_id, operation_id, request_hash, reserved_bytes, "
                        "purpose, source_epoch, state "
                        "FROM main.usage_reservations WHERE operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise SemanticConflict()
                return UsageReservation(**dict(existing))

            meta = (
                connection.execute(
                    text("SELECT usable_bytes, access_epoch FROM main.access_meta WHERE id = 1")
                )
                .mappings()
                .one_or_none()
            )
            state = (
                connection.execute(
                    text(
                        "SELECT committed_db_bytes, retained_file_bytes "
                        "FROM main.usage_state WHERE id = 1"
                    )
                )
                .mappings()
                .one_or_none()
            )
            if meta is None or state is None:
                raise HostedAccessError(
                    "hosted_storage_unavailable",
                    "Workspace storage accounting is unavailable; contact the administrator.",
                    503,
                )
            if meta["access_epoch"] != source_epoch:
                raise HostedAccessError(
                    "hosted_session_expired", "Sign in again to this workspace.", 401
                )
            used = state["committed_db_bytes"] + state["retained_file_bytes"]
            active_reserved = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(SUM(reserved_bytes), 0) "
                        "FROM main.usage_reservations "
                        "WHERE state IN ('held', 'unknown')"
                    )
                ).scalar_one()
            )
            if used + active_reserved + reserved_bytes > meta["usable_bytes"]:
                raise HostedAccessError(
                    "hosted_storage_quota_exceeded",
                    "Free pilot storage limit (50 MB) would be exceeded. "
                    "Keep your input and contact the administrator.",
                    507,
                )
            now = self.clock()
            reservation_id = str(uuid4())
            connection.execute(
                text(
                    "INSERT INTO main.usage_reservations ("
                    "reservation_id, operation_id, request_hash, reserved_bytes, "
                    "purpose, source_epoch, state, created_at, updated_at, result_revision"
                    ") VALUES ("
                    ":res_id, :op_id, :req_hash, :bytes, :purpose, :epoch, "
                    "'held', :now, :now, NULL"
                    ")"
                ),
                {
                    "res_id": reservation_id,
                    "op_id": operation_id,
                    "req_hash": request_hash,
                    "bytes": reserved_bytes,
                    "purpose": purpose,
                    "epoch": source_epoch,
                    "now": now,
                },
            )
            return UsageReservation(
                reservation_id=reservation_id,
                operation_id=operation_id,
                request_hash=request_hash,
                reserved_bytes=reserved_bytes,
                purpose=purpose,
                source_epoch=source_epoch,
                state="held",
            )

    def settle_commit(
        self, reservation_id: str, *, result_revision: str | None = None
    ) -> UsageSnapshot:
        """Re-measure post-commit logical usage and mark the reservation committed."""
        measured = measure_logical_usage(self.business_engine)
        rev_label = result_revision or measured.business_revision
        with immediate_transaction(self.access_engine) as connection:
            now = self.clock()
            meta = (
                connection.execute(text("SELECT usable_bytes FROM main.access_meta WHERE id = 1"))
                .mappings()
                .one()
            )
            state_rev = connection.execute(
                text("SELECT revision FROM main.usage_state WHERE id = 1")
            ).scalar_one()
            next_rev = state_rev + 1
            connection.execute(
                text(
                    "UPDATE main.usage_state SET "
                    "business_revision = :business_revision, "
                    "committed_db_bytes = :committed_db_bytes, "
                    "retained_file_bytes = :retained_file_bytes, "
                    "observed_at = :observed_at, "
                    "measurement_version = :measurement_version, "
                    "revision = :revision "
                    "WHERE id = 1"
                ),
                {
                    "business_revision": rev_label,
                    "committed_db_bytes": measured.committed_db_bytes,
                    "retained_file_bytes": measured.retained_file_bytes,
                    "observed_at": now,
                    "measurement_version": self.measurement_version,
                    "revision": next_rev,
                },
            )
            connection.execute(
                text(
                    "UPDATE main.usage_reservations SET "
                    "state = 'committed', updated_at = :now, result_revision = :rev "
                    "WHERE reservation_id = :res_id AND state IN ('held', 'unknown')"
                ),
                {"now": now, "rev": rev_label, "res_id": reservation_id},
            )
            reserved = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(SUM(reserved_bytes), 0) "
                        "FROM main.usage_reservations "
                        "WHERE state IN ('held', 'unknown')"
                    )
                ).scalar_one()
            )
            return UsageSnapshot(
                usable_bytes=meta["usable_bytes"],
                committed_db_bytes=measured.committed_db_bytes,
                retained_file_bytes=measured.retained_file_bytes,
                reserved_bytes=reserved,
                observed_at=now,
                business_revision=rev_label,
                measurement_version=self.measurement_version,
                revision=next_rev,
            )

    def release(self, reservation_id: str) -> None:
        with immediate_transaction(self.access_engine) as connection:
            connection.execute(
                text(
                    "UPDATE main.usage_reservations SET state = 'released', updated_at = :now "
                    "WHERE reservation_id = :res_id AND state = 'held'"
                ),
                {"now": self.clock(), "res_id": reservation_id},
            )

    def mark_unknown(self, reservation_id: str) -> None:
        with immediate_transaction(self.access_engine) as connection:
            connection.execute(
                text(
                    "UPDATE main.usage_reservations SET state = 'unknown', updated_at = :now "
                    "WHERE reservation_id = :res_id AND state = 'held'"
                ),
                {"now": self.clock(), "res_id": reservation_id},
            )

    def reconcile_unknown(self, *, include_held: bool = False) -> tuple[UsageSnapshot, int]:
        """Re-measure actual logical usage and release uncertain reservations safely."""
        measured = measure_logical_usage(self.business_engine)
        target_states = "('held', 'unknown')" if include_held else "('unknown')"
        with immediate_transaction(self.access_engine) as connection:
            now = self.clock()
            meta = (
                connection.execute(text("SELECT usable_bytes FROM main.access_meta WHERE id = 1"))
                .mappings()
                .one()
            )
            state_rev = connection.execute(
                text("SELECT revision FROM main.usage_state WHERE id = 1")
            ).scalar_one()
            next_rev = state_rev + 1
            connection.execute(
                text(
                    "UPDATE main.usage_state SET "
                    "business_revision = :business_revision, "
                    "committed_db_bytes = :committed_db_bytes, "
                    "retained_file_bytes = :retained_file_bytes, "
                    "observed_at = :observed_at, "
                    "measurement_version = :measurement_version, "
                    "revision = :revision "
                    "WHERE id = 1"
                ),
                {
                    "business_revision": measured.business_revision,
                    "committed_db_bytes": measured.committed_db_bytes,
                    "retained_file_bytes": measured.retained_file_bytes,
                    "observed_at": now,
                    "measurement_version": self.measurement_version,
                    "revision": next_rev,
                },
            )
            updated = connection.execute(
                text(
                    "UPDATE main.usage_reservations SET state = 'released', updated_at = :now "
                    f"WHERE state IN {target_states}"
                ),
                {"now": now},
            )
            reserved = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(SUM(reserved_bytes), 0) "
                        "FROM main.usage_reservations "
                        "WHERE state IN ('held', 'unknown')"
                    )
                ).scalar_one()
            )
            return (
                UsageSnapshot(
                    usable_bytes=meta["usable_bytes"],
                    committed_db_bytes=measured.committed_db_bytes,
                    retained_file_bytes=measured.retained_file_bytes,
                    reserved_bytes=reserved,
                    observed_at=now,
                    business_revision=measured.business_revision,
                    measurement_version=self.measurement_version,
                    revision=next_rev,
                ),
                updated.rowcount,
            )
