"""Portfolio-wide coverage classification before counts, continuation and LIMIT."""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, func, literal, union_all, case, and_, or_, literal_column

from app.modules.operator.application.coverage_sources import CoverageSources
from app.modules.operator.application.coverage_models import coverage_view
from app.modules.operator.infrastructure.sqlalchemy_models import OperatorCoverageReviewModel
from app.modules.portfolio.application.coverage_ports import CoverageLocation
from app.platform.coverage import CoverageSubject, CoverageFacts, CoverageResolution
from app.platform.attention_reads import (
    AttentionFact,
    AttentionKey,
    AttentionPage,
    AttentionReasonFact,
)
from app.platform.sql_coverage import register_json_function, json_fields


class SQLiteCoverageAttentionReader:
    def __init__(self, sources: CoverageSources):
        self.sources = sources

    def facts(self, connection, window):
        locations = self.sources.portfolio.portfolio_facts(
            connection, as_of=window.as_of, property_id=window.property_id
        )
        contexts = self.sources.leases.context_relation(connection, locations)
        financial = self.sources.finance.fact_relation(connection, contexts)
        properties = select(locations.c.property_id).distinct().subquery()
        maintenance = self.sources.maintenance.revision_relation(connection, properties)
        reviews = OperatorCoverageReviewModel.__table__
        ranked = (
            select(
                reviews,
                func.row_number()
                .over(
                    partition_by=(reviews.c.subject_kind, reviews.c.subject_id, reviews.c.area),
                    order_by=literal_column("operator_coverage_reviews.rowid").desc(),
                )
                .label("position"),
            )
            .select_from(
                reviews.join(
                    locations,
                    and_(
                        reviews.c.subject_kind == locations.c.subject_kind,
                        reviews.c.subject_id == locations.c.id,
                    ),
                )
            )
            .subquery()
        )
        latest = select(ranked).where(ranked.c.position == 1).subquery()
        register_json_function(connection, "coverage_review_projection", 8, _projection)
        selections = []
        for area in ("maintenance", "occupancy", "lease", "rent", "deposit"):
            review = case(
                (
                    latest.c.id.is_not(None),
                    json_fields(latest.c, ("evidence_revision", "next_review_on", "created_at")),
                )
            )
            source = financial.outerjoin(
                maintenance, maintenance.c.property_id == financial.c.property_id
            ).outerjoin(
                latest,
                and_(
                    latest.c.subject_kind == financial.c.subject_kind,
                    latest.c.subject_id == financial.c.id,
                    latest.c.area == area,
                ),
            )
            view = func.coverage_review_projection(
                func.json_quote(area),
                financial.c.location,
                financial.c.lease_context,
                financial.c.finance_facts,
                maintenance.c.revision,
                review,
                func.json_quote(window.as_of.isoformat()),
                func.json_quote(financial.c.id),
            )
            selections.append(
                select(
                    financial.c.id,
                    financial.c.subject_kind,
                    financial.c.property_id,
                    financial.c.property_state,
                    financial.c.title,
                    financial.c.time_zone,
                    financial.c.next_transition,
                    literal(area).label("area"),
                    view.label("view"),
                )
                .select_from(source)
                .where(
                    financial.c.subject_kind == ("property" if area == "maintenance" else "space")
                )
            )
        views = union_all(*selections).cte("portfolio_coverage_views")
        return select(
            views,
            func.json_extract(views.c.view, "$.state").label("state"),
            func.json_extract(views.c.view, "$.applicability").label("applicability"),
            case(
                (func.json_extract(views.c.view, "$.state") == "missing_required_information", 0),
                else_=1,
            ).label("priority"),
            (
                views.c.property_id
                + literal(":")
                + views.c.subject_kind
                + literal(":")
                + views.c.id
                + literal(":")
                + views.c.area
            ).label("identity"),
        ).cte("classified_coverage")

    def attention(self, connection, window):
        if window.collection != "information_review" or window.source_kind not in (
            None,
            "coverage",
        ):
            return AttentionPage(0, ())
        facts = self.facts(connection, window)
        f = facts.c
        matching = f.state.in_(("missing_required_information", "needs_review"))
        counts = (
            connection.execute(
                select(
                    func.count().filter(matching).label("total"),
                    func.count().filter(f.applicability == "applicable").label("applicable"),
                    func.count()
                    .filter(f.applicability == "not_applicable")
                    .label("not_applicable"),
                    func.count().filter(f.state == "missing_required_information").label("missing"),
                    func.count().filter(f.state == "needs_review").label("review"),
                    func.min(f.next_transition).label("next_transition"),
                ).select_from(facts)
            )
            .mappings()
            .one()
        )
        statement = select(facts).where(matching)
        if window.after is not None:
            key = window.after
            statement = statement.where(
                or_(
                    f.priority > key.priority,
                    and_(
                        f.priority == key.priority,
                        literal(window.as_of.isoformat()) > key.at.isoformat(),
                    ),
                    and_(
                        f.priority == key.priority,
                        literal(window.as_of.isoformat()) == key.at.isoformat(),
                        literal("coverage") > key.source_kind,
                    ),
                    and_(
                        f.priority == key.priority,
                        literal(window.as_of.isoformat()) == key.at.isoformat(),
                        literal("coverage") == key.source_kind,
                        f.identity > key.source_id,
                    ),
                )
            )
        rows = connection.execute(
            statement.order_by(f.priority, f.identity).limit(window.limit + 1)
        ).mappings()
        candidates = tuple(_fact(row, window) for row in rows)
        page = AttentionPage(
            counts["total"],
            candidates,
            datetime.fromisoformat(counts["next_transition"])
            if counts["next_transition"]
            else None,
            reason_counts=(
                ("missing_required", counts["missing"]),
                ("needs_review", counts["review"]),
            ),
            applicable_count=counts["applicable"],
            not_applicable_count=counts["not_applicable"],
        )
        page.validate_window(window)
        return page


def _projection(area, location, lease, finance, maintenance, review, captured, subject_id):
    location = CoverageLocation(**location)
    facts = CoverageSources.derive(area, location, lease, {location.property_id: maintenance})
    if facts is None:
        facts = CoverageFacts(**finance[area])
    subject = CoverageSubject("property" if area == "maintenance" else "space", subject_id)
    return coverage_view(subject, facts, review, datetime.fromisoformat(captured))


def _fact(row, window):
    view = json.loads(row["view"])
    subject = UUID(row["id"])
    target = CoverageResolution(row["subject_kind"], subject, row["area"])
    return AttentionFact(
        key=AttentionKey(row["priority"], window.as_of, "coverage", row["identity"]),
        source_revision=view["evidenceRevision"],
        status=view["state"],
        title=row["title"][:500],
        reasons=(
            AttentionReasonFact(
                "missing_required" if row["priority"] == 0 else "needs_review",
                "information",
                "coverage",
                subject,
            ),
        ),
        property_id=UUID(row["property_id"]),
        space_id=subject if row["subject_kind"] == "space" else None,
        time_zone=row["time_zone"],
        property_archived=row["property_state"] == "archived",
        subject_kind=row["subject_kind"],
        coverage_area=row["area"],
        coverage_causes=tuple(view["causes"]),
        coverage_resolution=target,
        recorded_at=datetime.fromisoformat(view["lastManualReviewAt"])
        if view["lastManualReviewAt"]
        else None,
    )
