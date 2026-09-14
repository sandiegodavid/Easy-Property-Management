"""Contextual COM history remains readable; generalized activity is deliberately sparse."""

from __future__ import annotations

from typing import Any, Mapping

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class CommunicationActivitySnapshotPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None: return None
        hidden = {"id", "subject", "body", "correctionReason", "partyId", "partyContactMethodId", "partyDisplayName", "contactDisplayValue", "entityId", "relatedEntityId", "taskId", "notes", "idempotencyKey", "reason"}
        def walk(value: Any) -> Any:
            if isinstance(value, dict): return {key: ("[redacted]" if key in hidden else walk(child)) for key, child in value.items()}
            if isinstance(value, list): return [walk(item) for item in value]
            return value
        return walk(dict(snapshot))

    def redact_entity_id(self, entity_id: str, *args: object) -> str:
        return "[redacted]"


COMMUNICATION_ACTIVITY_POLICY = CommunicationActivitySnapshotPolicy()
