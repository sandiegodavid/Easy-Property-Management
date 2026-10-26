"""One reviewed binding registry for runtime and retained-workspace validation."""

from app.bootstrap.operator_command_forms import compose_command_forms
from app.modules.communications.infrastructure.receipt_reader import (
    SQLiteCommunicationReceiptReader,
)
from app.modules.maintenance.infrastructure.receipt_reader import SQLiteIssueCommandReceiptReader
from app.modules.portfolio.infrastructure.recovery_reader import SQLitePortfolioStatusRecoveryReader
from app.modules.tasks.infrastructure.recovery_reader import SQLiteTaskRecoveryReader


def compose_recovery_bindings():
    return compose_command_forms(
        SQLiteTaskRecoveryReader(),
        SQLiteCommunicationReceiptReader(),
        SQLiteIssueCommandReceiptReader(),
        SQLitePortfolioStatusRecoveryReader(),
    )


def compose_attempt_namespaces(bindings=None):
    """Physical receipt namespaces are selected only at the composition boundary."""
    tables = {
        "ai": "ai_command_operations",
        "ai_external": "ai_external_operations",
        "communication": "communication_operations",
        "expense": "finance_command_operations",
        "deposit": "finance_command_operations",
        "finance": "finance_command_operations",
        "expense_category": "expense_category_command_operations",
        "file": "file_command_operations",
        "inspection": "inspection_command_operations",
        "intake": "intake_source_operations",
        "inventory": "portfolio_inventory_operations",
        "issue": "maintenance_command_receipts",
        "lease": "lease_command_operations",
        "mutation": "task_mutation_operations",
        "waiting": "task_waiting_operations",
        "owner_concern": "owner_concern_command_operations",
        "owner_rent_report": "owner_rent_report_operations",
        "party": "party_command_operations",
        "provider": "provider_command_operations",
        "provider_category": "provider_category_command_operations",
        "status": "space_status_operations",
        "tenant": "tenant_command_operations",
    }
    commands = compose_recovery_bindings() if bindings is None else bindings
    return {
        **{key: tables[binding.family] for key, binding in commands.items()},
        "task.create": "task_creation_operations",
        "maintenance.issue.create": "maintenance_command_receipts",
        "communication.record": "communication_operations",
        "coverage.review": "operator_coverage_reviews",
    }
