"""Application-composition root for FILE-001 owning-domain policies.

This module deliberately lives outside ``files``: it adapts each owner’s
small fact port to the caller-owned connection without making the files
module import another bounded context’s models or repositories.
"""

from __future__ import annotations

from app.modules.files.application.ports import FileLinkPolicyRegistry
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.finance.application.deposit_file_links import DepositFileLinkValidator
from app.modules.finance.application.file_links import ExpenseFileLinkValidator
from app.modules.finance.infrastructure.file_link_facts import (
    SQLiteDepositFileLinkFacts,
    SQLiteExpenseFileLinkFacts,
)
from app.modules.inspections.application.file_links import ConditionObservationFileLinkValidator
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator
from app.modules.leases.application.file_links import LeaseFileLinkValidator
from app.modules.leases.infrastructure.file_link_facts import SQLiteLeaseFileLinkFacts
from app.modules.maintenance.application.file_links import MaintenanceFileLinkValidator
from app.modules.maintenance.infrastructure.file_link_facts import SQLiteMaintenanceFileLinkFacts
from app.modules.owner_accounting.application.file_links import OwnerRentReportFileLinkValidator
from app.modules.owner_accounting.infrastructure.file_link_facts import (
    SQLiteOwnerRentReportFileLinkFacts,
)


def build_file_link_policy_registry() -> FileLinkPolicyRegistry:
    links = SQLiteFileLinkReader()
    return FileLinkPolicyRegistry(
        (
            LeaseFileLinkValidator(SQLiteLeaseFileLinkFacts()),
            ExpenseFileLinkValidator(SQLiteExpenseFileLinkFacts(), links),
            DepositFileLinkValidator(SQLiteDepositFileLinkFacts(), links),
            MaintenanceFileLinkValidator(SQLiteMaintenanceFileLinkFacts(), links),
            OwnerRentReportFileLinkValidator(SQLiteOwnerRentReportFileLinkFacts(), links),
            ConditionObservationFileLinkValidator(),
            IntakeSourceFileLinkValidator(),
        )
    )
