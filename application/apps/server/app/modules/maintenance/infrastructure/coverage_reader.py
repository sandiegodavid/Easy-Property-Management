"""Maintenance changes only; unrelated workspace writes do not invalidate reviews."""

from sqlalchemy import select, func, literal, union_all
from app.modules.maintenance.infrastructure.sqlalchemy_models import (
    MaintenanceIssueModel,
    MaintenanceWorkJournalEntryModel,
)
from app.modules.audit.application.read_marker import AuditEntityReadMarker
from app.platform.coverage import evidence_revision as fingerprint
from app.platform.coverage import bounded_subjects
from collections import defaultdict


class SQLiteMaintenanceCoverageReader:
    def __init__(self, marker: AuditEntityReadMarker):
        self.marker = marker

    def evidence_revision(self, connection, property_id):
        return self.evidence_revisions(connection, [property_id])[property_id]

    def evidence_revisions(self, connection, property_ids):
        property_ids = bounded_subjects(property_ids)
        if not property_ids:
            return {}
        issue = MaintenanceIssueModel.__table__
        rows = (
            connection.execute(
                select(
                    issue.c.property_id,
                    issue.c.status,
                    func.count().label("count"),
                    func.max(issue.c.updated_at).label("updated_at"),
                )
                .where(issue.c.property_id.in_(property_ids))
                .group_by(issue.c.property_id, issue.c.status)
                .order_by(issue.c.status)
            )
            .mappings()
            .all()
        )
        journal = MaintenanceWorkJournalEntryModel.__table__
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["property_id"]].append(
                {key: value for key, value in row.items() if key != "property_id"}
            )
        references = union_all(
            select(
                literal("maintenance_issue").label("entity_type"),
                issue.c.id.label("entity_id"),
                issue.c.property_id.label("group_id"),
            ).where(issue.c.property_id.in_(property_ids)),
            select(literal("maintenance_work_journal_entry"), journal.c.id, issue.c.property_id)
            .join(issue, journal.c.issue_id == issue.c.id)
            .where(issue.c.property_id.in_(property_ids)),
        ).subquery("maintenance_coverage_references")
        markers = self.marker.markers_for_groups(connection, references)
        return {
            key: fingerprint({"states": grouped[key], "marker": markers.get(key, "0")})
            for key in property_ids
        }
