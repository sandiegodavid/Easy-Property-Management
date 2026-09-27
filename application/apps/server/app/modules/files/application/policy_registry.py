"""Single FILE-001 policy composition used for write and retained checks."""
from __future__ import annotations

from sqlalchemy import text
from types import SimpleNamespace

from app.modules.files.application.ports import FileLinkPolicyRegistry
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.leases.application.file_links import LeaseFileLinkValidator
from app.modules.finance.application.file_links import ExpenseFileLinkValidator
from app.modules.finance.application.deposit_file_links import DepositFileLinkValidator
from app.modules.maintenance.application.file_links import MaintenanceFileLinkValidator
from app.modules.owner_accounting.application.file_links import OwnerRentReportFileLinkValidator
from app.modules.inspections.application.file_links import ConditionObservationFileLinkValidator
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator


class _Targets:
    """Connection-bound source facts used only while composing FILE policies.

    The public validators remain the sole owner of purposes and lifecycle
    rules.  This reader merely supplies their target-existence facts without
    opening a second connection during workspace validation.
    """
    _tables = {
        "lease": "leases", "lease_termination_case": "lease_termination_cases",
        "expense": "expenses", "security_deposit_receipt": "security_deposit_receipts",
        "security_deposit_deduction": "security_deposit_deductions", "security_deposit_refund": "security_deposit_refunds",
        "security_deposit_settlement": "security_deposit_settlements", "maintenance_issue": "maintenance_issues",
        "maintenance_appointment": "maintenance_appointments", "maintenance_cost_context": "maintenance_cost_contexts",
        "maintenance_quote": "maintenance_quotes", "maintenance_assignment": "maintenance_assignments",
        "maintenance_work_journal_entry": "maintenance_work_journal_entries", "owner_rent_report": "owner_rent_reports",
    }

    def file_link_target_exists(self, connection, entity_type, entity_id): return self.exists(connection, entity_type, entity_id)
    def expense_exists(self, connection, entity_id): return self.exists(connection, "expense", entity_id)
    def exists(self, connection, entity_type, entity_id):
        table = self._tables[entity_type]
        return connection.execute(text(f"SELECT 1 FROM {table} WHERE id = :id LIMIT 1"), {"id": entity_id}).first() is not None
    def report(self, connection, report_id):
        row = connection.execute(text("SELECT * FROM owner_rent_reports WHERE id = :id"), {"id": report_id}).mappings().first()
        return SimpleNamespace(**dict(row)) if row is not None else None
    def active_link_count(self, connection, entity_type, entity_id): return SQLiteFileLinkReader().active_link_count(connection, entity_type, entity_id)
    def active_available_count(self, connection, report_id): return SQLiteFileLinkReader().active_available_link_count(connection, "owner_rent_report", report_id)
    def link_is_active_available(self, connection, link_id): return SQLiteFileLinkReader().link_is_active_available(connection, link_id)
    def work_journal_effective_kind(self, connection, entry_id):
        row = connection.execute(text(
            "SELECT entry_kind, corrected_entry_kind FROM maintenance_work_journal_entries "
            "WHERE id=:id AND NOT EXISTS (SELECT 1 FROM maintenance_work_journal_entries c WHERE c.corrects_entry_id=:id)"
        ), {"id": entry_id}).mappings().first()
        return None if row is None else row["corrected_entry_kind"] or row["entry_kind"]


def build_file_link_policy_registry() -> FileLinkPolicyRegistry:
    """The policy set for both runtime mutation and current-format validation."""
    targets = _Targets()
    return FileLinkPolicyRegistry((
        LeaseFileLinkValidator(targets), ExpenseFileLinkValidator(targets),
        DepositFileLinkValidator(targets), MaintenanceFileLinkValidator(targets),
        OwnerRentReportFileLinkValidator(targets), ConditionObservationFileLinkValidator(),
        IntakeSourceFileLinkValidator(),
    ))
