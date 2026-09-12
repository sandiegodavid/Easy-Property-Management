"""Exact current FIN-001 schema validation."""
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect, text

from app.modules.finance.infrastructure.sqlalchemy_models import (
    ExpenseCategoryModel, ExpenseModel, ExpenseRefundModel,
    RentExpectationModel, RentExpectationTimelinessReviewModel,
    RentReceiptModel, RentReceiptAllocationModel,
    SecurityDepositAccountModel, SecurityDepositReceiptModel,
    SecurityDepositSettlementModel, SecurityDepositSettlementReceiptModel,
    SecurityDepositDeductionModel, SecurityDepositDeductionSourceModel,
    SecurityDepositCreditModel, SecurityDepositRefundModel,
)
from app.platform.migration_errors import MigrationSchemaError

MODELS = (
    RentExpectationModel, RentExpectationTimelinessReviewModel,
    RentReceiptModel, RentReceiptAllocationModel,
    ExpenseCategoryModel, ExpenseModel, ExpenseRefundModel,
    SecurityDepositAccountModel, SecurityDepositReceiptModel,
    SecurityDepositSettlementModel, SecurityDepositSettlementReceiptModel,
    SecurityDepositDeductionModel, SecurityDepositDeductionSourceModel,
    SecurityDepositCreditModel, SecurityDepositRefundModel,
)

def validate_finance_schema(connection):
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__
        if not inspector.has_table(table.name): raise MigrationSchemaError("Finance schema is missing.")
        actual_columns = {item["name"]: item for item in inspector.get_columns(table.name)}
        if set(actual_columns) != {column.name for column in table.columns}: raise MigrationSchemaError("Finance columns are incompatible.")
        for expected in table.columns:
            actual = actual_columns[expected.name]
            if bool(actual["primary_key"]) != expected.primary_key or bool(actual["nullable"]) != expected.nullable:
                raise MigrationSchemaError("Finance column nullability or primary keys are incompatible.")
            expected_type = str(expected.type).upper()
            actual_type = str(actual["type"]).upper()
            if ("INT" in expected_type and "INT" not in actual_type) or ("INT" not in expected_type and not ("TEXT" in actual_type or "CHAR" in actual_type)):
                raise MigrationSchemaError("Finance column types are incompatible.")
        expected_fks = {(tuple(element.parent.name for element in item.elements), item.elements[0].column.table.name, tuple(element.column.name for element in item.elements)) for item in table.constraints if isinstance(item, ForeignKeyConstraint)}
        actual_fks = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table.name)}
        if actual_fks != expected_fks: raise MigrationSchemaError("Finance foreign keys are incompatible.")
        expected_indexes = {item.name: (tuple(column.name for column in item.columns), bool(item.unique), _where(item.dialect_options["sqlite"].get("where"))) for item in table.indexes}
        actual_indexes = {item["name"]: (tuple(item["column_names"]), bool(item.get("unique")), _where(item.get("dialect_options", {}).get("sqlite_where"))) for item in inspector.get_indexes(table.name)}
        if actual_indexes != expected_indexes: raise MigrationSchemaError("Finance indexes are incompatible.")
        expected_unique = {tuple(column.name for column in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)}
        actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        if actual_unique != expected_unique: raise MigrationSchemaError("Finance unique constraints are incompatible.")
        expected_checks = {_normalise(item.sqltext.text) for item in table.constraints if isinstance(item, CheckConstraint)}
        actual_checks = {_normalise(item.get("sqltext") or "") for item in inspector.get_check_constraints(table.name)}
        if actual_checks != expected_checks: raise MigrationSchemaError("Finance checks are incompatible.")


def validate_finance_data(connection):
    """Reject cross-row and cross-module FIN-008 corruption after restore/open."""
    if connection.execute(text("PRAGMA foreign_key_check")).first() is not None:
        raise MigrationSchemaError("Workspace contains broken foreign-key references.")
    checks = (
        """SELECT 1 FROM security_deposit_settlement_receipts captured
            JOIN security_deposit_settlements settlement ON settlement.id = captured.settlement_id
            JOIN security_deposit_receipts receipt ON receipt.id = captured.receipt_id
            WHERE settlement.account_id != receipt.account_id LIMIT 1""",
        """SELECT 1 FROM security_deposit_refunds refund
            JOIN security_deposit_settlements settlement ON settlement.id = refund.authorized_by_settlement_id
            WHERE refund.account_id != settlement.account_id LIMIT 1""",
        """SELECT 1 FROM security_deposit_receipts replacement
            JOIN security_deposit_receipts original ON original.id = replacement.replaces_receipt_id
            WHERE replacement.account_id != original.account_id OR original.voided_at IS NULL LIMIT 1""",
        """SELECT 1 FROM security_deposit_settlements replacement
            JOIN security_deposit_settlements original ON original.id = replacement.replaces_settlement_id
            WHERE replacement.account_id != original.account_id OR original.status != 'voided' LIMIT 1""",
        """SELECT 1 FROM security_deposit_refunds replacement
            JOIN security_deposit_refunds original ON original.id = replacement.replaces_refund_id
            WHERE replacement.account_id != original.account_id OR original.voided_at IS NULL LIMIT 1""",
        """WITH RECURSIVE chain(start_id, next_id, path) AS (
                SELECT id, replaces_receipt_id, id || ',' FROM security_deposit_receipts
                UNION ALL
                SELECT chain.start_id, receipt.replaces_receipt_id, chain.path || receipt.id || ','
                FROM chain JOIN security_deposit_receipts receipt ON receipt.id = chain.next_id
                WHERE instr(chain.path, receipt.id || ',') = 0
            )
            SELECT 1 FROM chain JOIN security_deposit_receipts receipt ON receipt.id = chain.next_id
            WHERE instr(chain.path, receipt.id || ',') > 0 LIMIT 1""",
        """WITH RECURSIVE chain(start_id, next_id, path) AS (
                SELECT id, replaces_settlement_id, id || ',' FROM security_deposit_settlements
                UNION ALL
                SELECT chain.start_id, settlement.replaces_settlement_id, chain.path || settlement.id || ','
                FROM chain JOIN security_deposit_settlements settlement ON settlement.id = chain.next_id
                WHERE instr(chain.path, settlement.id || ',') = 0
            )
            SELECT 1 FROM chain JOIN security_deposit_settlements settlement ON settlement.id = chain.next_id
            WHERE instr(chain.path, settlement.id || ',') > 0 LIMIT 1""",
        """WITH RECURSIVE chain(start_id, next_id, path) AS (
                SELECT id, replaces_refund_id, id || ',' FROM security_deposit_refunds
                UNION ALL
                SELECT chain.start_id, refund.replaces_refund_id, chain.path || refund.id || ','
                FROM chain JOIN security_deposit_refunds refund ON refund.id = chain.next_id
                WHERE instr(chain.path, refund.id || ',') = 0
            )
            SELECT 1 FROM chain JOIN security_deposit_refunds refund ON refund.id = chain.next_id
            WHERE instr(chain.path, refund.id || ',') > 0 LIMIT 1""",
        """SELECT 1 FROM security_deposit_settlements settlement
            WHERE settlement.status IN ('approved', 'completed') AND (
                SELECT COALESCE(SUM(refund.amount_minor), 0) FROM security_deposit_refunds refund
                WHERE refund.account_id = settlement.account_id AND refund.voided_at IS NULL
            ) > settlement.refund_due_minor LIMIT 1""",
        """SELECT 1 FROM security_deposit_settlements settlement
            WHERE settlement.approved_at IS NOT NULL AND (
                settlement.receipt_total_minor != COALESCE((
                    SELECT SUM(receipt.amount_minor)
                    FROM security_deposit_settlement_receipts captured
                    JOIN security_deposit_receipts receipt ON receipt.id = captured.receipt_id
                    WHERE captured.settlement_id = settlement.id
                ), 0)
                OR settlement.credit_total_minor != COALESCE((
                    SELECT SUM(credit.amount_minor) FROM security_deposit_credits credit
                    WHERE credit.settlement_id = settlement.id
                ), 0)
                OR settlement.deduction_total_minor != COALESCE((
                    SELECT SUM(deduction.amount_minor) FROM security_deposit_deductions deduction
                    WHERE deduction.settlement_id = settlement.id
                ), 0)
                OR settlement.refund_due_minor != settlement.receipt_total_minor + settlement.credit_total_minor - settlement.deduction_total_minor
            ) LIMIT 1""",
        """SELECT 1 FROM security_deposit_settlements settlement
            WHERE settlement.status = 'completed' AND settlement.refund_due_minor != COALESCE((
                SELECT SUM(refund.amount_minor) FROM security_deposit_refunds refund
                WHERE refund.account_id = settlement.account_id AND refund.voided_at IS NULL
            ), 0) LIMIT 1""",
        """SELECT 1 FROM security_deposit_deduction_sources source
            WHERE (source.source_kind = 'rent_expectation' AND NOT EXISTS (SELECT 1 FROM rent_expectations target WHERE target.id = source.source_id))
               OR (source.source_kind = 'expense' AND NOT EXISTS (SELECT 1 FROM expenses target WHERE target.id = source.source_id))
               OR (source.source_kind = 'inspection_comparison' AND NOT EXISTS (SELECT 1 FROM condition_comparisons target WHERE target.id = source.source_id))
               OR (source.source_kind = 'inspection_observation' AND NOT EXISTS (SELECT 1 FROM condition_observations target WHERE target.id = source.source_id))
            LIMIT 1""",
        """SELECT 1
            FROM security_deposit_deductions deduction
            JOIN security_deposit_settlements settlement ON settlement.id = deduction.settlement_id
            JOIN security_deposit_accounts account ON account.id = settlement.account_id
            WHERE settlement.approved_at IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM security_deposit_deduction_sources source
                WHERE source.deduction_id = deduction.id AND (
                    (source.source_kind = 'rent_expectation' AND EXISTS (
                        SELECT 1 FROM rent_expectations expectation
                        WHERE expectation.id = source.source_id
                          AND expectation.lease_id = account.lease_id
                    )) OR
                    (source.source_kind = 'expense' AND EXISTS (
                        SELECT 1 FROM expenses expense
                        WHERE expense.id = source.source_id
                          AND expense.property_id = account.property_id
                          AND (expense.space_id IS NULL OR expense.space_id = account.space_id)
                    )) OR
                    (source.source_kind = 'inspection_observation' AND EXISTS (
                        SELECT 1 FROM condition_observations observation
                        JOIN condition_areas area ON area.id = observation.condition_area_id
                        JOIN condition_reports report ON report.id = area.condition_report_id
                        WHERE observation.id = source.source_id AND report.lease_id = account.lease_id
                    )) OR
                    (source.source_kind = 'inspection_comparison' AND EXISTS (
                        SELECT 1 FROM condition_comparisons comparison
                        JOIN condition_reports pre_report ON pre_report.id = comparison.pre_report_id
                        JOIN condition_reports post_report ON post_report.id = comparison.post_report_id
                        WHERE comparison.id = source.source_id AND comparison.lease_id = account.lease_id
                    ))
                )
              )
              AND NOT EXISTS (
                SELECT 1 FROM file_links link
                JOIN file_content_locations location ON location.file_id = link.file_id
                WHERE link.entity_type = 'security_deposit_deduction'
                  AND link.entity_id = deduction.id
                  AND link.archived_at IS NULL
                  AND location.storage_state = 'available'
              )
            LIMIT 1""",
        """SELECT 1
            FROM security_deposit_deduction_sources source
            JOIN security_deposit_deductions deduction ON deduction.id = source.deduction_id
            JOIN security_deposit_settlements settlement ON settlement.id = deduction.settlement_id
            WHERE settlement.approved_at IS NOT NULL
              AND ((source.source_kind = 'rent_expectation' AND source.outstanding_amount_minor IS NULL)
                OR (source.source_kind != 'rent_expectation' AND source.outstanding_amount_minor IS NOT NULL))
            LIMIT 1""",
        """SELECT 1
            FROM security_deposit_deduction_sources source
            JOIN security_deposit_deductions deduction ON deduction.id = source.deduction_id
            JOIN security_deposit_settlements settlement ON settlement.id = deduction.settlement_id
            WHERE source.source_kind = 'expense'
              AND settlement.approved_at IS NOT NULL
            GROUP BY source.source_id
            HAVING COUNT(DISTINCT settlement.id) > 1
               AND COUNT(DISTINCT CASE WHEN source.duplicate_use_confirmed = 0 THEN settlement.id END) > 1
            LIMIT 1""",
    )
    for query in checks:
        if connection.execute(text(query)).first() is not None:
            raise MigrationSchemaError("FIN-008 data integrity is incompatible.")

def _normalise(value: str) -> str:
    parts = value.split("'")
    return "'".join(part if index % 2 else "".join(part.lower().split()) for index, part in enumerate(parts))


def _where(value) -> str | None:
    return None if value is None else _normalise(str(value))
