"""Presentation policy for shared-identity contact data."""

from collections.abc import Mapping
from typing import Any

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class PartyActivitySnapshotPolicy(DefaultAuditSnapshotPolicy):
    """Hide contact details in generalized activity while preserving party history."""

    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        presented = super().redact(snapshot)
        if presented is None:
            return None
        for field in ("email", "phone"):
            if field in presented:
                presented[field] = "[redacted]"
        return presented


PARTY_ACTIVITY_SNAPSHOT_POLICY = PartyActivitySnapshotPolicy()
