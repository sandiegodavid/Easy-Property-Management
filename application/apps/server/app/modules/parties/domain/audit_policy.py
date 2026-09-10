"""Presentation policy for shared-identity contact methods."""

from collections.abc import Mapping
from typing import Any

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class PartyContactActivitySnapshotPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        presented = super().redact(snapshot)
        if presented is None:
            return None
        for field in ("displayValue", "normalizedValue", "extension"):
            if field in presented:
                presented[field] = "[redacted]"
        return presented


PARTY_CONTACT_SNAPSHOT_POLICY = PartyContactActivitySnapshotPolicy()
