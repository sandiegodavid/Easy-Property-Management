"""Transaction-bound audit recording port."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.modules.audit.domain.models import ActorKind, AuditEvent, AuditSnapshotPolicy, DEFAULT_SNAPSHOT_POLICY


class AuditEventRepository(Protocol):
    """Persistence port; domain use cases do not depend on SQLite."""
    def append(self, connection: Any, event: AuditEvent) -> None: ...
    def append_many(self, connection: Any, events: list[AuditEvent]) -> None: ...


class AuditHistoryRepository(Protocol):
    """Read port for record and global activity history."""
    def history(self, entity_type: str | None = None, entity_id: str | None = None, **filters: Any) -> list[AuditEvent]: ...


class AuditRecorder:
    def __init__(self, repository: AuditEventRepository, snapshot_policy: AuditSnapshotPolicy = DEFAULT_SNAPSHOT_POLICY) -> None:
        self.repository = repository
        self.snapshot_policy = snapshot_policy

    def record_change(
        self,
        connection: Any,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        actor_kind: ActorKind = "local_operator",
        reason: str | None = None,
        actor_reference: str | None = None,
        correlation_id: str | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        event = AuditEvent.change(
            entity_type=entity_type, entity_id=entity_id, action=action, before_snapshot=before,
            after_snapshot=after, actor_kind=actor_kind, reason=reason, actor_reference=actor_reference,
            correlation_id=correlation_id, snapshot_policy=self.snapshot_policy,
            event_id=event_id, occurred_at=occurred_at,
        )
        self.repository.append(connection, event)
        return event

    def record_many(self, connection: Any, changes: list[dict[str, Any]], *, correlation_id: str,
                    summary_entity_type: str, summary_entity_id: str, reason: str | None = None) -> list[AuditEvent]:
        """Record a bounded bulk operation plus one event per affected record."""
        if len(changes) > 500:
            raise ValueError("An audit bulk operation may contain at most 500 record changes.")
        events = [AuditEvent.change(correlation_id=correlation_id, snapshot_policy=self.snapshot_policy, **change) for change in changes]
        summary = AuditEvent.change(entity_type=summary_entity_type, entity_id=summary_entity_id,
            action="operation_summary", before_snapshot=None, after_snapshot={"changedRecordCount": len(events)},
            actor_kind="system", reason=reason, correlation_id=correlation_id, snapshot_policy=self.snapshot_policy)
        self.repository.append_many(connection, [*events, summary])
        return [*events, summary]
