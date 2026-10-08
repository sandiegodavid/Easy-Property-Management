"""Compose source-owned relations/read ports; never query foreign ORM models."""

from dataclasses import dataclass
from sqlalchemy import literal, select, union_all

from app.modules.communications.application.summary_ports import CommunicationSummaryReader
from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.leases.application.summary_ports import LeaseSummaryReader
from app.modules.maintenance.application.summary_ports import IssueSummaryReader
from app.modules.owner_management.application.summary_ports import OwnerConcernSummaryReader
from app.modules.portfolio.application.owner_read_ports import OwnerContextReader
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations
from app.modules.tasks.application.summary_ports import TaskSummaryReader
from app.platform.context_reads import ContextScope
from app.modules.finance.application.context_relations import FinanceContextRelations


@dataclass(frozen=True)
class OverviewSources:
    portfolio: OwnerContextReader
    locations: PortfolioLocationRelations
    lease_locations: LeaseLocationRelation
    leases: LeaseSummaryReader
    issues: IssueSummaryReader
    communications: CommunicationSummaryReader
    tasks: TaskSummaryReader
    concerns: OwnerConcernSummaryReader
    finance_references: FinanceContextRelations

    def scope(self, connection, subject, instant):
        properties = self.portfolio.property_scope(connection, subject, as_of=instant)
        spaces, leases, issues, concerns = (
            self.locations.spaces(),
            self.lease_locations.locations(),
            self.issues.locations(),
            self.concerns.locations(),
        )
        queries = [
            select(
                literal("property").label("entity_type"),
                properties.c.property_id.label("entity_id"),
            )
        ]
        for kind, relation, id_column in (
            ("space", spaces, "space_id"),
            ("lease", leases, "lease_id"),
            ("maintenance_issue", issues, "issue_id"),
            ("owner_concern", concerns, "concern_id"),
        ):
            query = select(literal(kind), relation.c[id_column]).where(
                relation.c.property_id.in_(select(properties.c.property_id))
            )
            if kind == "owner_concern" and subject.kind == "owner":
                query = query.where(relation.c.owner_party_id == subject.id)
            queries.append(query)
        if subject.kind == "owner":
            queries.append(select(literal("party"), literal(subject.id)))
        for relation in (
            self.leases.references(properties),
            self.finance_references.references(properties),
        ):
            queries.append(select(relation.c.entity_type, relation.c.entity_id))
        refs = union_all(*queries).subquery("context_references")
        return ContextScope(properties, refs, subject.id if subject.kind == "owner" else None)

    def page(self, connection, section, subject, window):
        if section in {"properties", "relationships", "spaces"}:
            return getattr(self.portfolio, section)(connection, subject, window)
        readers = {
            "leases": self.leases,
            "maintenance": self.issues,
            "communications": self.communications,
            "tasks": self.tasks,
            "concerns": self.concerns,
        }
        scope = self.scope(connection, subject, window.as_of)
        if section in {"communications", "tasks"}:
            tasks = self.tasks.references(scope)
            references = union_all(select(scope.references), select(tasks)).subquery(
                "context_with_task_references"
            )
            scope = ContextScope(scope.properties, references, scope.party_id)
        if section == "tasks":
            communications = self.communications.references(scope)
            references = union_all(select(scope.references), select(communications)).subquery(
                "task_context_references"
            )
            scope = ContextScope(scope.properties, references, scope.party_id)
        return readers[section].page(connection, scope, window)
