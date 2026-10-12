"""Pending verification metadata; reports are provenance, never rent receipts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import literal, select

from app.modules.owner_accounting.infrastructure.sqlalchemy_models import OwnerRentReportModel
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations
from app.platform.attention_reads import (
    AttentionFact,
    AttentionKey,
    AttentionPage,
    AttentionReasonFact,
)
from app.platform.sql_attention_reads import attention_rows


class SQLiteOwnerReportAttentionReader:
    def __init__(self, locations: PortfolioLocationRelations):
        self.locations = locations

    def facts(self, connection, window):
        if (
            window.source_kind not in (None, "owner_rent_report")
            or window.collection != "needs_action"
        ):
            raise ValueError("Owner reports require the pending-verification action collection.")
        r, p = OwnerRentReportModel.__table__, self.locations.properties()
        statement = (
            select(
                r.c.id,
                r.c.report_revision.label("revision"),
                r.c.status,
                r.c.owner_party_id,
                r.c.owner_display_name_snapshot,
                r.c.property_id,
                r.c.space_id,
                r.c.lease_id,
                p.c.time_zone,
                p.c.property_state,
                r.c.reported_at_utc.label("recorded_at"),
                literal("needs_action").label("collection"),
                literal(3).label("sort_priority"),
                literal("review").label("priority_band"),
                r.c.reported_at_utc.label("sort_at"),
                literal(None).label("next_transition"),
                literal(True).label("pending_verification"),
            )
            .select_from(r.join(p, r.c.property_id == p.c.property_id))
            .where(r.c.status == "pending")
        )
        if window.property_id is not None:
            statement = statement.where(r.c.property_id == str(window.property_id))
        return statement.subquery("owner_report_attention")

    def attention(self, connection, window):
        counts, rows = attention_rows(
            connection,
            self.facts(connection, window),
            window,
            "owner_rent_report",
            ("pending_verification",),
        )
        page = AttentionPage(
            counts["total"],
            tuple(_fact(row) for row in rows),
            priority_counts=(("review", counts["total"]),) if counts["total"] else (),
            reason_counts=(("pending_verification", counts["total"]),) if counts["total"] else (),
        )
        page.validate_window(window)
        return page


def _fact(row):
    return AttentionFact(
        AttentionKey(3, datetime.fromisoformat(row["sort_at"]), "owner_rent_report", row["id"]),
        str(row["revision"]),
        row["status"],
        "Owner rent report awaiting verification",
        (
            AttentionReasonFact(
                "pending_verification", "review", "owner_rent_report", UUID(row["id"])
            ),
        ),
        property_id=UUID(row["property_id"]),
        space_id=UUID(row["space_id"]),
        lease_id=UUID(row["lease_id"]),
        time_zone=row["time_zone"],
        property_archived=row["property_state"] == "archived",
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        owner_party_id=UUID(row["owner_party_id"]),
        owner_display_name_snapshot=row["owner_display_name_snapshot"],
    )
