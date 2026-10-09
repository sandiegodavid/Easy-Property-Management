"""Read-only OPS recovery projections for Finance command receipts."""

from json import loads

from sqlalchemy import select

from app.modules.finance.infrastructure.command_models import (
    FinanceCommandOperationModel,
    FinanceCommandRevisionModel,
)
from app.modules.finance.infrastructure.sqlalchemy_models import (
    PrepaidCheckModel,
    RentExpectationModel,
    RentReceiptModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteFinanceRecoveryReader:
    """Combines Finance-owned receipts with the injected Lease status reader."""

    def __init__(self, lease_reader):
        self.lease_reader = lease_reader

    def state(self, connection, source_id):
        lease = self.lease_reader.state(connection, source_id)
        if lease is None:
            return None
        revision = connection.scalar(
            select(FinanceCommandRevisionModel.revision).where(
                FinanceCommandRevisionModel.scope_kind == "rent_ledger",
                FinanceCommandRevisionModel.scope_id == source_id,
            )
        )
        return {**lease, "revision": 0 if revision is None else revision}

    def outcome(self, connection, key, *, family):
        if family != "finance":
            raise ValueError("Unsupported Finance recovery family.")
        row = (
            connection.execute(
                select(
                    FinanceCommandOperationModel.id,
                    FinanceCommandOperationModel.action,
                    FinanceCommandOperationModel.scope_id,
                    FinanceCommandOperationModel.target_id,
                    FinanceCommandOperationModel.request_fingerprint,
                    FinanceCommandOperationModel.response_json,
                    FinanceCommandOperationModel.result_revision,
                ).where(FinanceCommandOperationModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        result = loads(row["response_json"])
        target_id = (
            row["target_id"]
            if row["action"] == "synchronize_expectations"
            else result.get("id") or result.get("leaseId")
        )
        if target_id is None:
            raise ValueError("Finance recovery result has no stable target identity.")
        return CommandOutcome(
            row["id"],
            row["action"],
            row["scope_id"],
            row["request_fingerprint"],
            CommandResult(
                target_id,
                row["result_revision"],
                result.get("lifecycleStatus") or result.get("status"),
            ),
        )

    def related_state(self, connection, kind, target_id):
        if kind == "lease_term":
            return self.lease_reader.term_state(connection, target_id)
        if kind == "expectation":
            row = (
                connection.execute(
                    select(
                        RentExpectationModel.lease_id,
                        RentExpectationModel.voided_at,
                    ).where(RentExpectationModel.id == target_id)
                )
                .mappings()
                .first()
            )
        elif kind == "receipt":
            row = (
                connection.execute(
                    select(RentReceiptModel.lease_id, RentReceiptModel.voided_at).where(
                        RentReceiptModel.id == target_id
                    )
                )
                .mappings()
                .first()
            )
        elif kind == "prepaid_check":
            row = (
                connection.execute(
                    select(PrepaidCheckModel.lease_id, PrepaidCheckModel.status).where(
                        PrepaidCheckModel.id == target_id
                    )
                )
                .mappings()
                .first()
            )
        else:
            return None
        if row is None:
            return None
        status = row.get("status") or ("voided" if row.get("voided_at") else "active")
        return {
            "source_id": row["lease_id"],
            "status": status,
            "terminal_at": "terminal" if status in {"voided", "replaced", "returned"} else None,
        }

    def active_expectation_ids(self, connection, lease_id, expectation_ids):
        identities = set(expectation_ids)
        if not identities or len(identities) > 100:
            return set()
        rows = connection.execute(
            select(RentExpectationModel.id).where(
                RentExpectationModel.lease_id == lease_id,
                RentExpectationModel.id.in_(identities),
                RentExpectationModel.voided_at.is_(None),
            )
        )
        return set(rows.scalars())
