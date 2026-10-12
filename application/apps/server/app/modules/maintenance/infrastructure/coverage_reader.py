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
from app.platform.sql_coverage import json_fields, register_json_function


class SQLiteMaintenanceCoverageReader:
    def revision_relation(self, connection, properties):
        register_json_function(
            connection,
            "coverage_maintenance_revision",
            2,
            lambda states, marker: fingerprint(
                {"states": sorted(states, key=lambda row: row["status"]), "marker": marker}
            ),
        )
        issue, journal = MaintenanceIssueModel.__table__, MaintenanceWorkJournalEntryModel.__table__
        ids = select(properties.c.property_id)
        states = (
            select(
                issue.c.property_id,
                issue.c.status,
                func.count().label("count"),
                func.max(issue.c.updated_at).label("updated_at"),
            )
            .where(issue.c.property_id.in_(ids))
            .group_by(issue.c.property_id, issue.c.status)
            .subquery()
        )
        grouped = (
            select(
                states.c.property_id,
                func.json_group_array(
                    func.json(json_fields(states.c, ("status", "count", "updated_at")))
                ).label("states"),
            )
            .group_by(states.c.property_id)
            .subquery()
        )
        refs = union_all(
            select(
                literal("maintenance_issue").label("entity_type"),
                issue.c.id.label("entity_id"),
                issue.c.property_id.label("group_id"),
            ).where(issue.c.property_id.in_(ids)),
            select(literal("maintenance_work_journal_entry"), journal.c.id, issue.c.property_id)
            .join(issue, journal.c.issue_id == issue.c.id)
            .where(issue.c.property_id.in_(ids)),
        ).subquery()
        markers = self.marker.grouped_markers(refs)
        return (
            select(
                properties.c.property_id,
                func.coverage_maintenance_revision(
                    func.coalesce(grouped.c.states, "[]"),
                    func.json_quote(func.cast(func.coalesce(markers.c.marker, 0), issue.c.id.type)),
                ).label("revision"),
            )
            .select_from(
                properties.outerjoin(
                    grouped, grouped.c.property_id == properties.c.property_id
                ).outerjoin(markers, markers.c.group_id == properties.c.property_id)
            )
            .subquery("coverage_maintenance_revisions")
        )

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
