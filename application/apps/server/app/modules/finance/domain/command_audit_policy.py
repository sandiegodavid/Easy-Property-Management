"""Keep financial command payloads and identities out of general activity."""

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy


class FinanceCommandActivityPolicy(DefaultAuditSnapshotPolicy):
    def redact(self, snapshot):
        if snapshot is None:
            return None
        return {
            key: value
            for key, value in snapshot.items()
            if key
            not in {
                "request_json",
                "response_json",
                "idempotency_key",
                "request_fingerprint",
                "response_fingerprint",
                "target_id",
                "scope_id",
            }
        }


FINANCE_COMMAND_ACTIVITY_POLICY = FinanceCommandActivityPolicy()
