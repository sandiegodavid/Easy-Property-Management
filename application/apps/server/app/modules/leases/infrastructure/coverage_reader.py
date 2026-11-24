"""Set-based relevant lease context, capped at two rows per selected Space."""

from collections import defaultdict
from sqlalchemy import select, case, func, literal
from app.platform.sql_coverage import json_fields, register_json_function
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseTermModel
from app.platform.coverage import bounded_subjects


class SQLiteLeaseCoverageReader:
    def context_relation(self, connection, locations):
        register_json_function(connection, "coverage_lease_context", 1, _context)
        lease, term = LeaseModel.__table__, LeaseTermModel.__table__
        on = locations.c.local_date
        ranked_terms = (
            select(
                term.c.lease_id,
                term.c.id.label("term_id"),
                term.c.base_rent_minor,
                term.c.currency_code,
                term.c.payment_frequency,
                term.c.payment_due_day,
                term.c.agreed_security_deposit_minor,
                term.c.effective_on,
                term.c.ends_on,
                func.row_number()
                .over(
                    partition_by=term.c.lease_id,
                    order_by=(
                        case((term.c.effective_on <= on, 0), else_=1),
                        case((term.c.effective_on <= on, term.c.effective_on)).desc(),
                        term.c.effective_on,
                        term.c.id,
                    ),
                )
                .label("term_position"),
            )
            .select_from(
                term.join(lease, lease.c.id == term.c.lease_id).join(
                    locations,
                    (locations.c.subject_kind == "space") & (locations.c.id == lease.c.space_id),
                )
            )
            .where(lease.c.status.in_(("executed", "ended", "terminated")))
            .cte("coverage_ranked_lease_terms")
        )
        latest_terms = select(ranked_terms).where(ranked_terms.c.term_position == 1).subquery()
        ranked = (
            select(
                lease.c.space_id,
                lease.c.id.label("lease_id"),
                lease.c.status,
                lease.c.actual_move_out_on,
                latest_terms.c.term_id,
                latest_terms.c.base_rent_minor,
                latest_terms.c.currency_code,
                latest_terms.c.payment_frequency,
                latest_terms.c.payment_due_day,
                latest_terms.c.agreed_security_deposit_minor,
                latest_terms.c.effective_on,
                latest_terms.c.ends_on,
                func.row_number()
                .over(
                    partition_by=lease.c.space_id,
                    order_by=(
                        case((lease.c.status == "executed", 0), else_=1),
                        lease.c.occupancy_starts_on.desc(),
                        lease.c.id,
                    ),
                )
                .label("position"),
            )
            .select_from(
                lease.join(
                    locations,
                    (locations.c.subject_kind == "space") & (locations.c.id == lease.c.space_id),
                ).outerjoin(latest_terms, latest_terms.c.lease_id == lease.c.id)
            )
            .where(lease.c.status.in_(("executed", "ended", "terminated")))
            .cte("coverage_ranked_leases")
        )
        names = tuple(name for name in ranked.c.keys() if name not in ("space_id",))
        grouped = (
            select(
                ranked.c.space_id,
                func.json_group_array(func.json(json_fields(ranked.c, names))).label("rows"),
            )
            .where(ranked.c.position <= 2)
            .group_by(ranked.c.space_id)
            .subquery()
        )
        return (
            select(
                locations,
                func.coverage_lease_context(func.coalesce(grouped.c.rows, literal("[]"))).label(
                    "lease_context"
                ),
            )
            .select_from(locations.outerjoin(grouped, grouped.c.space_id == locations.c.id))
            .cte("coverage_lease_locations")
        )

    def relevant_context(self, connection, space_id, on):
        return self.relevant_contexts(connection, {space_id: on}).get(space_id)

    def relevant_contexts(self, connection, dates):
        bounded_subjects(dates)
        if not dates:
            return {}
        lease, term = LeaseModel.__table__, LeaseTermModel.__table__
        on = case(dates, value=lease.c.space_id)
        ranked_terms = (
            select(
                term.c.lease_id,
                term.c.id.label("term_id"),
                term.c.base_rent_minor,
                term.c.currency_code,
                term.c.payment_frequency,
                term.c.payment_due_day,
                term.c.agreed_security_deposit_minor,
                term.c.effective_on,
                term.c.ends_on,
                func.row_number()
                .over(
                    partition_by=term.c.lease_id,
                    order_by=(
                        case((term.c.effective_on <= on, 0), else_=1),
                        case((term.c.effective_on <= on, term.c.effective_on)).desc(),
                        term.c.effective_on,
                        term.c.id,
                    ),
                )
                .label("term_position"),
            )
            .select_from(term.join(lease, lease.c.id == term.c.lease_id))
            .where(
                lease.c.space_id.in_(dates), lease.c.status.in_(("executed", "ended", "terminated"))
            )
            .subquery()
        )
        latest_terms = select(ranked_terms).where(ranked_terms.c.term_position == 1).subquery()
        ranked = (
            select(
                lease.c.space_id,
                lease.c.id.label("lease_id"),
                lease.c.status,
                lease.c.actual_move_out_on,
                latest_terms.c.term_id,
                latest_terms.c.base_rent_minor,
                latest_terms.c.currency_code,
                latest_terms.c.payment_frequency,
                latest_terms.c.payment_due_day,
                latest_terms.c.agreed_security_deposit_minor,
                latest_terms.c.effective_on,
                latest_terms.c.ends_on,
                func.row_number()
                .over(
                    partition_by=lease.c.space_id,
                    order_by=(
                        case((lease.c.status == "executed", 0), else_=1),
                        lease.c.occupancy_starts_on.desc(),
                        lease.c.id,
                    ),
                )
                .label("position"),
            )
            .select_from(lease.outerjoin(latest_terms, latest_terms.c.lease_id == lease.c.id))
            .where(
                lease.c.space_id.in_(dates), lease.c.status.in_(("executed", "ended", "terminated"))
            )
            .subquery()
        )
        grouped = defaultdict(list)
        for row in connection.execute(
            select(ranked)
            .where(ranked.c.position <= 2)
            .order_by(ranked.c.space_id, ranked.c.position)
        ).mappings():
            grouped[row["space_id"]].append(
                {key: value for key, value in row.items() if key not in ("space_id", "position")}
            )
        return {
            key: {
                **rows[0],
                "ambiguous": len(rows) == 2
                and rows[0]["status"] == rows[1]["status"] == "executed",
            }
            for key, rows in grouped.items()
        }


def _context(rows):
    if not rows:
        return None
    rows.sort(key=lambda row: row["position"])
    result = {key: value for key, value in rows[0].items() if key != "position"}
    return {
        **result,
        "ambiguous": len(rows) == 2 and rows[0]["status"] == rows[1]["status"] == "executed",
    }
