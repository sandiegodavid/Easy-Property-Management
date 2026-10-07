"""Privacy policy for evidence retained by INGEST-001."""

from __future__ import annotations

from typing import Any, Mapping

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class IntakeActivityPolicy(DefaultAuditSnapshotPolicy):
    _hidden = frozenset(
        {
            "body",
            "subject",
            "participants",
            "addresses",
            "accountScopeHash",
            "accountDisplayHint",
            "externalSourceId",
            "conversationRef",
            "contentFingerprint",
            "idempotencyKey",
            "actorReference",
            "correctionReason",
            "attachment",
            "attachmentHash",
            "fileLinkId",
        }
    )

    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None

        def visit(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: ("[redacted]" if key in self._hidden else visit(child))
                    for key, child in value.items()
                }
            if isinstance(value, list):
                return [visit(item) for item in value]
            return value

        return visit(dict(snapshot))

    def redact_reason(self, reason: str | None) -> str | None:
        return None if reason is None else "[redacted]"

    def redact_actor_reference(self, actor_kind: str, actor_reference: str | None) -> str | None:
        return None if actor_reference is None else "[redacted]"

    def redact_entity_id(self, entity_id: str, *args: object) -> str:
        return "[redacted]"


INTAKE_ACTIVITY_POLICY = IntakeActivityPolicy()
