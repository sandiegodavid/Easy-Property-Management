from collections.abc import Mapping
from typing import Any
from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy

class InspectionActivityPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None):
        value = super().redact(snapshot)
        if value:
            for key in ("notes", "generalNotes", "operatorNotes", "correctionReason", "timingExceptionReason"):
                if key in value: value[key] = "[redacted]"
        return value

INSPECTION_ACTIVITY_POLICY = InspectionActivityPolicy()
