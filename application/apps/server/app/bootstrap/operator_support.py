"""Explicit OPS composition without initializing or opening the workspace."""

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.communications.infrastructure.receipt_reader import (
    SQLiteCommunicationReceiptReader,
)
from app.modules.maintenance.infrastructure.receipt_reader import SQLiteIssueCommandReceiptReader
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.infrastructure.unit_of_work import (
    SQLiteOperatorUnitOfWork,
    OperatorReadSources,
)
from app.modules.operator.application.directory_service import OperatorDirectoryService
from app.modules.parties.infrastructure.identity_relations import SQLitePartyIdentityRelations
from app.modules.leases.infrastructure.participant_relations import SQLiteLeaseParticipantRelations
from app.modules.portfolio.infrastructure.directory_reader import SQLitePortfolioDirectoryReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.finance.infrastructure.money_context_reader import SQLiteMoneyContextReader
from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
from app.modules.tasks.infrastructure.creation_receipt_reader import SQLiteTaskCreationReceiptReader
from app.modules.operator.application.overview_service import OperatorOverviewService
from app.modules.operator.infrastructure.overview_sources import OverviewSources
from app.modules.portfolio.infrastructure.owner_context_reader import SQLiteOwnerContextReader
from app.modules.leases.infrastructure.summary_reader import SQLiteLeaseSummaryReader
from app.modules.maintenance.infrastructure.summary_reader import SQLiteIssueSummaryReader
from app.modules.communications.infrastructure.summary_reader import (
    SQLiteCommunicationSummaryReader,
)
from app.modules.tasks.infrastructure.summary_reader import SQLiteTaskSummaryReader
from app.modules.owner_management.infrastructure.summary_reader import (
    SQLiteOwnerConcernSummaryReader,
)
from app.modules.finance.infrastructure.context_relations import SQLiteFinanceContextRelations
from app.bootstrap.operator_search import compose_metadata_search
from app.modules.operator.application.search_service import OperatorSearchService
from app.bootstrap.operator_coverage import compose_coverage_sources
from app.modules.operator.application.coverage_service import OperatorCoverageService


def compose_operator(workspace, runtime, recorder, sources):
    def identity():
        state = "ready" if runtime.ready else "unavailable"
        if runtime.startup_attempted and not runtime.writer_lock_acquired:
            state = "busy"
        return RuntimeIdentity(
            state,
            runtime.workspace_id if runtime.ready else None,
            runtime.read_epoch,
            runtime.ready and runtime.can_write,
            None if runtime.ready else "workspace_" + state,
        )

    references = OperatorRecoveryReferences(
        RecoverySourcePorts(sources.portfolio, sources.parties, sources.contexts),
        SQLiteIssueCommandReceiptReader(),
        SQLiteCommunicationReceiptReader(),
        SQLiteTaskCreationReceiptReader(),
        commands=compose_recovery_bindings(),
    )
    locations = SQLitePortfolioLocationRelations()
    marker = SQLiteAuditReadMarker()
    lease_locations = SQLiteLeaseLocationRelation(locations)
    unit_of_work = SQLiteOperatorUnitOfWork(
        workspace.paths.database,
        recorder,
        references,
        marker,
        sources=OperatorReadSources(
            coverage=compose_coverage_sources(),
            search=compose_metadata_search(),
            directory=SQLitePortfolioDirectoryReader(
                SQLitePartyIdentityRelations(), SQLiteLeaseParticipantRelations()
            ),
            money=SQLiteMoneyContextReader(
                locations, SQLiteLeaseLocationRelation(locations), marker
            ),
            tasks=SQLiteTaskContextReader(),
            overview=OverviewSources(
                portfolio=SQLiteOwnerContextReader(SQLitePartyIdentityRelations()),
                locations=locations,
                lease_locations=lease_locations,
                leases=SQLiteLeaseSummaryReader(lease_locations),
                issues=SQLiteIssueSummaryReader(),
                communications=SQLiteCommunicationSummaryReader(),
                tasks=SQLiteTaskSummaryReader(),
                concerns=SQLiteOwnerConcernSummaryReader(),
                finance_references=SQLiteFinanceContextRelations(lease_locations),
            ),
        ),
    )
    return (
        OperatorService(
            unit_of_work,
            runtime=identity,
            capabilities=(
                "operator.preferences",
                "operator.recovery",
                "operator.property-directory",
                "operator.owner-directory",
                "operator.context-overviews",
                "operator.metadata-search",
                "operator.coverage",
            ),
        ),
        OperatorDirectoryService(unit_of_work, runtime=identity),
        OperatorOverviewService(unit_of_work, runtime=identity),
        OperatorSearchService(unit_of_work, runtime=identity),
        OperatorCoverageService(unit_of_work, runtime=identity),
    )
