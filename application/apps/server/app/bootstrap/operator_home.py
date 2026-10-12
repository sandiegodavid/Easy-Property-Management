"""Compose DASH source readers without opening or initializing a workspace."""

from app.bootstrap.operator_coverage import compose_coverage_sources
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.finance.infrastructure.attention_reader import SQLiteRentAttentionReader
from app.modules.finance.infrastructure.money_context_reader import SQLiteMoneyContextReader
from app.modules.finance.infrastructure.task_attention_locations import SQLiteFinanceTaskLocations
from app.modules.communications.infrastructure.task_attention_locations import (
    SQLiteCommunicationTaskLocations,
)
from app.modules.leases.infrastructure.attention_reader import SQLiteLeaseAttentionReader
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.maintenance.infrastructure.attention_reader import (
    SQLiteMaintenanceAttentionReader,
    SQLiteIssueTaskLocations,
)
from app.modules.operator.application.home_ports import HomeSources
from app.modules.operator.infrastructure.coverage_attention_reader import (
    SQLiteCoverageAttentionReader,
)
from app.modules.operator.infrastructure.home_task_relations import HomeTaskRelations
from app.modules.owner_accounting.infrastructure.attention_reader import (
    SQLiteOwnerReportAttentionReader,
)
from app.modules.owner_management.infrastructure.attention_reader import (
    SQLiteOwnerConcernAttentionReader,
    SQLiteConcernTaskLocations,
)
from app.modules.portfolio.infrastructure.attention_reader import SQLitePortfolioAttentionReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.tasks.infrastructure.attention_reader import SQLiteTaskAttentionReader


def compose_home_sources():
    locations = SQLitePortfolioLocationRelations()
    leases = SQLiteLeaseLocationRelation(locations)
    portfolio = SQLitePortfolioAttentionReader()
    issue_locations, concern_locations = (
        SQLiteIssueTaskLocations(locations),
        SQLiteConcernTaskLocations(locations),
    )
    finance_locations = SQLiteFinanceTaskLocations(leases)
    references = HomeTaskRelations(
        locations, leases, issue_locations, concern_locations, additional=(finance_locations,)
    )
    tasks = SQLiteTaskAttentionReader(
        HomeTaskRelations(
            locations,
            leases,
            issue_locations,
            concern_locations,
            additional=(finance_locations, SQLiteCommunicationTaskLocations(references)),
        )
    )
    issues = SQLiteMaintenanceAttentionReader(locations, tasks)
    concerns = SQLiteOwnerConcernAttentionReader(locations, tasks)
    return HomeSources(
        tasks,
        issues,
        SQLiteRentAttentionReader(leases),
        SQLiteLeaseAttentionReader(leases, portfolio),
        SQLiteOwnerReportAttentionReader(locations),
        concerns,
        SQLiteCoverageAttentionReader(compose_coverage_sources()),
        portfolio,
        SQLiteMoneyContextReader(locations, leases, SQLiteAuditReadMarker()),
    )
