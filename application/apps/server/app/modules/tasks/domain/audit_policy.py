"""General activity projection for TASK-001 records."""

from __future__ import annotations

from typing import Any, Mapping

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class TaskActivitySnapshotPolicy(DefaultAuditSnapshotPolicy):
    """Keep ordinary tasks visible while hiding sensitive follow-up linkage."""

    @staticmethod
    def _sensitive_follow_up(snapshot: Mapping[str, Any] | None) -> bool:
        return bool(snapshot and snapshot.get("relatedEntityType") in {"communication", "maintenance_issue"})

    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        value = super().redact(snapshot)
        if value is None or not self._sensitive_follow_up(snapshot):
            return value
        for key in ("id", "relatedEntityId", "relatedLabel", "notes"):
            if key in value:
                value[key] = "[redacted]"
        return value

    def redact_entity_id(
        self,
        entity_id: str,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
    ) -> str:
        return "[redacted]" if self._sensitive_follow_up(after or before) else entity_id


TASK_ACTIVITY_POLICY = TaskActivitySnapshotPolicy()
