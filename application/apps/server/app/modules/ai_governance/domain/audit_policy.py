"""AI records are intentionally terse in generalized activity history."""
from __future__ import annotations
from typing import Any, Mapping
from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class AiActivityPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        hidden = {"governedInput", "governed_input_json", "draftPayload", "draft_payload", "confidence", "operatorNote", "operator_note", "errorDetail", "error_detail", "providerRequest", "verificationEvidence"}
        def walk(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {str(key): "[redacted]" if key in hidden else walk(child) for key, child in value.items()}
            if isinstance(value, list): return [walk(child) for child in value]
            return value
        return walk(dict(snapshot))


AI_ACTIVITY_POLICY = AiActivityPolicy()
