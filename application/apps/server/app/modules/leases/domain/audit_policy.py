"""Privacy-safe Lease command receipt presentation."""

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class LeaseCommandActivityPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot):
        if snapshot is None:
            return None
        return {
            key: value
            for key, value in snapshot.items()
            if key not in {"idempotency_key", "request_fingerprint", "response_fingerprint"}
        }


LEASE_COMMAND_ACTIVITY_POLICY = LeaseCommandActivityPolicy()
