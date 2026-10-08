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
