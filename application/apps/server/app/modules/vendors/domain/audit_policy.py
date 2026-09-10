"""Activity-feed redaction for provider internal context."""

from collections.abc import Mapping
from typing import Any

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class ProviderActivitySnapshotPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        presented = super().redact(snapshot)
        if presented is None:
            return None
        for field in ("selectionReason", "notes", "outcomeNotes", "email", "phone"):
            if field in presented:
                presented[field] = "[redacted]"
        return presented


PROVIDER_ACTIVITY_SNAPSHOT_POLICY = ProviderActivitySnapshotPolicy()
