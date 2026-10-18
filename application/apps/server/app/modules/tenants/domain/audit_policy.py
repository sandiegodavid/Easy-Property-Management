"""Official identification is contextual data, not global activity content."""

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class TenantActivityPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot):
        result = super().redact(snapshot)
        if result is not None and "officialIds" in result:
            result["officialIds"] = "[redacted]"
        return result


TENANT_ACTIVITY_POLICY = TenantActivityPolicy()
