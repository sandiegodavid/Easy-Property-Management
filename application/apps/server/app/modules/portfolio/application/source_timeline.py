"""Portfolio policy for source-owned occupancy timeline changes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from json import dumps, loads
from typing import Any, Mapping, Protocol
from uuid import uuid4

from app.modules.portfolio.application.ports import PortfolioConflictError
from app.modules.portfolio.application.status_read_model import space_status_snapshot
from app.modules.portfolio.domain.models import Space, SpaceOccupancyPeriod


@dataclass(frozen=True)
class SourceTimelineChangeSet:
    """One complete source-owned occupancy transition and its concurrency contract."""

    space_id: str
    replacements: tuple[SpaceOccupancyPeriod, ...]
    inserts: tuple[SpaceOccupancyPeriod, ...]
    source_kind: str
    source_id: str
    action: str
    expected_revision: int
    idempotency_key: str
    correlation_id: str
    committed_at: str
    request_context: Mapping[str, object]
    authorized_replacement_ids: frozenset[str] = frozenset()

    def fingerprint(self) -> str:
        """Hash semantic timeline facts; generated IDs/timestamps cannot affect replay."""
        insert_positions = {item.id: index for index, item in enumerate(self.inserts)}

        def fact(item: SpaceOccupancyPeriod, *, replacement: bool) -> dict[str, object]:
            result: dict[str, object] = {
                "occupancy_status": item.occupancy_status,
                "starts_on": item.starts_on,
                "ends_on": item.ends_on,
                "record_state": item.record_state,
                "source_kind": item.source_kind,
                "source_id": item.source_id,
                "note": item.note,
                "superseded_by": (
                    None if item.superseded_by_id is None else
                    {"insert_index": insert_positions[item.superseded_by_id]}
                    if item.superseded_by_id in insert_positions else
                    {"period_id": item.superseded_by_id}
                ),
            }
            if replacement:
                result["id"] = item.id
            return result

        payload = {
            "space_id": self.space_id,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "action": self.action,
            "expected_revision": self.expected_revision,
            "request_context": self.request_context,
            "replacements": [fact(item, replacement=True) for item in self.replacements],
            "inserts": [fact(item, replacement=False) for item in self.inserts],
            "authorized_replacement_ids": sorted(self.authorized_replacement_ids),
        }
        return sha256(dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SourceTimelineStore(Protocol):
    """Persistence primitives; policy stays in :class:`PortfolioSourceTimelineService`."""

    def space(self, connection: Any, space_id: str) -> Space | None: ...
    def property(self, connection: Any, property_id: str): ...
    def occupancy_periods(self, connection: Any, space_id: str) -> list[SpaceOccupancyPeriod]: ...
    def availability(self, connection: Any, space_id: str): ...
    def status_operation(self, connection: Any, idempotency_key: str) -> dict[str, object] | None: ...
    def replace_occupancy_period(self, connection: Any, period: SpaceOccupancyPeriod) -> None: ...
    def insert_occupancy_period(self, connection: Any, period: SpaceOccupancyPeriod) -> None: ...
    def replace_space(self, connection: Any, space: Space) -> None: ...
    def insert_status_operation(self, connection: Any, operation: dict[str, object]) -> None: ...


class PortfolioSourceTimelineService:
    """Applies a source transition in one caller-owned transaction."""

    def apply(
        self, store: SourceTimelineStore, connection: Any, changes: SourceTimelineChangeSet,
    ) -> dict[str, object]:
        self._validate_request(changes)
        fingerprint = changes.fingerprint()
        existing = store.status_operation(connection, changes.idempotency_key)
        if existing is not None:
            if (existing["request_fingerprint"] != fingerprint
                    or existing["space_id"] != changes.space_id):
                raise PortfolioConflictError(
                    "Portfolio source idempotency key was reused with a different request."
                )
            return dict(loads(str(existing["result_snapshot"])))

        space = store.space(connection, changes.space_id)
        if space is None:
            raise KeyError(changes.space_id)
        current = {item.id: item for item in store.occupancy_periods(connection, changes.space_id)}
        if space.status_revision != changes.expected_revision:
            property = store.property(connection, space.property_id)
            if property is None:
                raise KeyError(space.property_id)
            raise PortfolioConflictError(
                "Portfolio source status revision is stale.",
                current_status=space_status_snapshot(
                    space, property, list(current.values()), store.availability(connection, space.id),
                    datetime.fromisoformat(changes.committed_at),
                ),
            )
        self._validate_changes(current, changes)

        inserted_ids = {item.id for item in changes.inserts}
        linked = tuple(item for item in changes.replacements if item.superseded_by_id in inserted_ids)
        for item in linked:
            store.replace_occupancy_period(connection, replace(item, superseded_by_id=None))
        for item in changes.replacements:
            if item not in linked:
                store.replace_occupancy_period(connection, item)
        for item in changes.inserts:
            store.insert_occupancy_period(connection, item)
        for item in linked:
            store.replace_occupancy_period(connection, item)

        revised = replace(space, status_revision=space.status_revision + 1, updated_at=changes.committed_at)
        store.replace_space(connection, revised)
        operation_id = str(uuid4())
        result = {
            "operationId": operation_id,
            "spaceId": changes.space_id,
            "revision": revised.status_revision,
            "updatedAt": revised.updated_at,
            "sourceId": changes.source_id,
            "sourceKind": changes.source_kind,
            "action": changes.action,
            "correlationId": changes.correlation_id,
            "requestContext": dict(changes.request_context),
        }
        store.insert_status_operation(connection, {
            "id": operation_id,
            "space_id": changes.space_id,
            "idempotency_key": changes.idempotency_key,
            "request_fingerprint": fingerprint,
            "result_revision": revised.status_revision,
            "result_snapshot": dumps(result, sort_keys=True),
            "created_at": changes.committed_at,
        })
        return result

    @staticmethod
    def _validate_request(changes: SourceTimelineChangeSet) -> None:
        if type(changes.expected_revision) is not int or changes.expected_revision < 0:
            raise PortfolioConflictError("Expected revision must be a non-negative integer.")
        if (not isinstance(changes.idempotency_key, str)
                or not changes.idempotency_key.strip()
                or len(changes.idempotency_key) > 200):
            raise PortfolioConflictError("Idempotency key must be a nonblank value of at most 200 characters.")
        if not isinstance(changes.source_kind, str) or not changes.source_kind.strip():
            raise PortfolioConflictError("Source kind is required.")
        if not isinstance(changes.source_id, str) or not changes.source_id.strip():
            raise PortfolioConflictError("Source ID is required.")

    @staticmethod
    def _validate_changes(
        current: dict[str, SpaceOccupancyPeriod], changes: SourceTimelineChangeSet,
    ) -> None:
        replacement_ids = {item.id for item in changes.replacements}
        inserted_ids = {item.id for item in changes.inserts}
        if len(replacement_ids) != len(changes.replacements) or len(inserted_ids) != len(changes.inserts):
            raise PortfolioConflictError("A source timeline change cannot contain duplicate periods.")
        if replacement_ids & inserted_ids:
            raise PortfolioConflictError("A source timeline period cannot be both replaced and inserted.")
        for item in changes.replacements:
            previous = current.get(item.id)
            if previous is None or item.space_id != changes.space_id:
                raise PortfolioConflictError("A source timeline replacement no longer exists.")
            if ((previous.source_kind, previous.source_id) != (changes.source_kind, changes.source_id)
                    and item.id not in changes.authorized_replacement_ids):
                raise PortfolioConflictError("Another source owns an affected occupancy period.")
            if (item.source_kind, item.source_id) != (previous.source_kind, previous.source_id):
                raise PortfolioConflictError("A source timeline change cannot transfer period ownership.")
            current[item.id] = item
        for item in changes.inserts:
            if item.id in current or item.space_id != changes.space_id:
                raise PortfolioConflictError("A source timeline insert is invalid.")
            if (item.source_kind, item.source_id) != (changes.source_kind, changes.source_id):
                raise PortfolioConflictError("A source action can only create its own occupancy periods.")
            current[item.id] = item
        PortfolioSourceTimelineService._validate_timeline(current.values())

    @staticmethod
    def _validate_timeline(periods: Iterable[SpaceOccupancyPeriod]) -> None:
        valid = sorted((item for item in periods if item.record_state == "valid"), key=lambda item: (item.starts_on, item.id))
        open_period = False
        previous_end = None
        for item in valid:
            if item.ends_on is not None and item.ends_on <= item.starts_on:
                raise PortfolioConflictError("The proposed occupancy timeline contains an invalid period.")
            if open_period or (previous_end is not None and item.starts_on < previous_end):
                raise PortfolioConflictError("The proposed occupancy timeline contains overlapping periods.")
            if item.ends_on is None:
                open_period = True
                previous_end = None
            else:
                previous_end = item.ends_on
