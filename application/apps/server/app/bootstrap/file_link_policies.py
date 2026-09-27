"""Application-composition root for FILE-001 owning-domain policies.

This module deliberately lives outside ``files``: it adapts each owner’s
small fact port to the caller-owned connection without making the files
module import another bounded context’s models or repositories.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import text

from app.modules.files.application.ports import FileLinkPolicyRegistry
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.finance.application.deposit_file_links import DepositFileLinkValidator
from app.modules.finance.application.file_links import ExpenseFileLinkValidator
from app.modules.inspections.application.file_links import ConditionObservationFileLinkValidator
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator
from app.modules.leases.application.file_links import LeaseFileLinkValidator
from app.modules.maintenance.application.file_links import MaintenanceFileLinkValidator
from app.modules.owner_accounting.application.file_links import OwnerRentReportFileLinkValidator


class _TargetFacts:
    _tables = {
        "lease": "leases", "lease_termination_case": "lease_termination_cases",
        "expense": "expenses", "security_deposit_receipt": "security_deposit_receipts",
        "security_deposit_deduction": "security_deposit_deductions", "security_deposit_refund": "security_deposit_refunds",
        "security_deposit_settlement": "security_deposit_settlements", "maintenance_issue": "maintenance_issues",
        "maintenance_appointment": "maintenance_appointments", "maintenance_cost_context": "maintenance_cost_contexts",
        "maintenance_quote": "maintenance_quotes", "maintenance_assignment": "maintenance_assignments",
        "maintenance_work_journal_entry": "maintenance_work_journal_entries", "owner_rent_report": "owner_rent_reports",
    }

    @classmethod
    def exists(cls, connection, entity_type: str, entity_id: str) -> bool:
        table = cls._tables[entity_type]
        return connection.execute(text(f"SELECT 1 FROM {table} WHERE id = :id LIMIT 1"), {"id": entity_id}).first() is not None

    def file_link_target_exists(self, connection, entity_type: str, entity_id: str) -> bool:
        return self.exists(connection, entity_type, entity_id)

    def work_journal_effective_kind(self, connection, entry_id: str):
        row = connection.execute(text(
            "SELECT entry_kind, corrected_entry_kind FROM maintenance_work_journal_entries "
            "WHERE id=:id AND NOT EXISTS (SELECT 1 FROM maintenance_work_journal_entries c WHERE c.corrects_entry_id=:id)"
        ), {"id": entry_id}).mappings().first()
        return None if row is None else row["corrected_entry_kind"] or row["entry_kind"]


class _ExpenseFacts:
    def __init__(self, targets: _TargetFacts, links: SQLiteFileLinkReader) -> None: self.targets, self.links = targets, links
    def expense_exists(self, connection, entity_id: str) -> bool: return self.targets.exists(connection, "expense", entity_id)
    def active_link_count(self, connection, entity_id: str) -> int: return self.links.active_link_count(connection, "expense", entity_id)


class _DepositFacts:
    def __init__(self, targets: _TargetFacts, links: SQLiteFileLinkReader) -> None: self.targets, self.links = targets, links
    def exists(self, connection, entity_type: str, entity_id: str) -> bool: return self.targets.exists(connection, entity_type, entity_id)
    def active_link_count(self, connection, entity_type: str, entity_id: str) -> int: return self.links.active_link_count(connection, entity_type, entity_id)


class _MaintenanceFacts(_DepositFacts):
    def work_journal_effective_kind(self, connection, entry_id: str): return self.targets.work_journal_effective_kind(connection, entry_id)


class _OwnerReportFacts:
    def __init__(self, targets: _TargetFacts, links: SQLiteFileLinkReader) -> None: self.targets, self.links = targets, links
    def exists(self, connection, entity_id: str) -> bool: return self.targets.exists(connection, "owner_rent_report", entity_id)
    def report(self, connection, report_id: str):
        row = connection.execute(text("SELECT * FROM owner_rent_reports WHERE id = :id"), {"id": report_id}).mappings().first()
        return SimpleNamespace(**dict(row)) if row is not None else None
    def active_link_count(self, connection, entity_type: str, entity_id: str) -> int: return self.links.active_link_count(connection, entity_type, entity_id)
    def active_available_count(self, connection, report_id: str) -> int: return self.links.active_available_link_count(connection, "owner_rent_report", report_id)
    def link_is_active_available(self, connection, link_id: str) -> bool: return self.links.link_is_active_available(connection, link_id)


def build_file_link_policy_registry() -> FileLinkPolicyRegistry:
    targets, links = _TargetFacts(), SQLiteFileLinkReader()
    return FileLinkPolicyRegistry((
        LeaseFileLinkValidator(targets), ExpenseFileLinkValidator(_ExpenseFacts(targets, links)),
        DepositFileLinkValidator(_DepositFacts(targets, links)), MaintenanceFileLinkValidator(_MaintenanceFacts(targets, links)),
        OwnerRentReportFileLinkValidator(_OwnerReportFacts(targets, links)),
        ConditionObservationFileLinkValidator(), IntakeSourceFileLinkValidator(),
    ))
