"""AI records are intentionally terse in generalized activity history."""
from __future__ import annotations
from typing import Any, Mapping
from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy

AI_AUDIT_HIDDEN_FIELDS = frozenset({
    "governedInput", "governed_input_json", "draftPayload", "draft_payload",
    "confidence", "operatorNote", "operator_note", "errorDetail",
    "error_detail", "providerRequest", "verificationEvidence",
})


def ai_audit_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Canonical, recursively safe representation for AI audit persistence."""
    if snapshot is None:
        return None

    def redact(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): "[redacted]" if key in AI_AUDIT_HIDDEN_FIELDS else redact(child)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [redact(child) for child in value]
        return value

    return redact(dict(snapshot))


class AiActivityPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        return ai_audit_snapshot(snapshot)


AI_ACTIVITY_POLICY = AiActivityPolicy()
