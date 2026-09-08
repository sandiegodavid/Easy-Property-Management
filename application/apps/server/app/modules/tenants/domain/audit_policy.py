"""Tenant-owned presentation policy for contact audit snapshots."""

from collections.abc import Mapping
from typing import Any

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class TenantContactAuditSnapshotPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        presented = super().redact(snapshot)
        if presented is None:
            return None
        for field in ("displayValue", "normalizedValue"):
            if field in presented:
                presented[field] = "[redacted]"
        return presented


TENANT_CONTACT_SNAPSHOT_POLICY = TenantContactAuditSnapshotPolicy()
