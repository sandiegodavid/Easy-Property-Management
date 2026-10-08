"""Static source-owned metadata registry; no workspace access during composition."""

from app.modules.operator.application.search_ports import (
    MetadataSearchRegistry,
    SearchDefinition,
    SearchRegistration,
)
from app.modules.portfolio.infrastructure.search_reader import (
    SQLiteLocationSearchReader,
    SQLiteOwnerSearchReader,
)
from app.modules.portfolio.infrastructure.owner_context_reader import SQLiteOwnerContextReader
from app.modules.parties.infrastructure.identity_relations import SQLitePartyIdentityRelations
from app.modules.tenants.infrastructure.search_reader import SQLiteTenantSearchReader
from app.modules.leases.infrastructure.search_reader import SQLiteLeaseSearchReader
from app.modules.communications.infrastructure.search_reader import SQLiteCommunicationSearchReader
from app.modules.maintenance.infrastructure.search_reader import SQLiteIssueSearchReader
from app.modules.tasks.infrastructure.search_reader import SQLiteTaskSearchReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation


def compose_metadata_search():
    locations, parties = SQLitePortfolioLocationRelations(), SQLitePartyIdentityRelations()
    definitions = (
        ("properties", "portfolio", "property", SQLiteLocationSearchReader("property")),
        ("spaces", "portfolio", "space", SQLiteLocationSearchReader("space")),
        (
            "owners",
            "portfolio",
            "owner",
            SQLiteOwnerSearchReader(SQLiteOwnerContextReader(parties)),
        ),
        ("tenants", "tenants", "tenant", SQLiteTenantSearchReader(parties)),
        (
            "leases",
            "leases",
            "lease",
            SQLiteLeaseSearchReader(SQLiteLeaseLocationRelation(locations)),
        ),
        ("communications", "communications", "communication", SQLiteCommunicationSearchReader()),
        ("maintenance", "maintenance", "maintenance_issue", SQLiteIssueSearchReader(locations)),
        ("tasks", "tasks", "task", SQLiteTaskSearchReader()),
    )
    return MetadataSearchRegistry(
        tuple(
            SearchRegistration(SearchDefinition(kind, source, entity), reader)
            for kind, source, entity, reader in definitions
        )
    )
