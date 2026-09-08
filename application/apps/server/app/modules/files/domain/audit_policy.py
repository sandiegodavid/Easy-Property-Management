"""General-activity privacy policy for managed files."""

from collections.abc import Mapping
from typing import Any

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class FileActivitySnapshotPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        presented = super().redact(snapshot)
        if presented is not None and "originalName" in presented:
            presented["originalName"] = "[redacted]"
        return presented


FILE_ACTIVITY_SNAPSHOT_POLICY = FileActivitySnapshotPolicy()
