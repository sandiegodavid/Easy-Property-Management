"""Privacy-safe inventory receipt activity."""

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class InventoryActivityPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot):
        if snapshot is None:
            return None
        return {
            key: value
            for key, value in snapshot.items()
            if key not in {"idempotency_key", "request_fingerprint", "response_fingerprint"}
        }


INVENTORY_ACTIVITY_POLICY = InventoryActivityPolicy()
