"""Set-based relevant lease context, capped at two rows per selected Space."""

from collections import defaultdict
from sqlalchemy import select, case, func
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseTermModel
from app.platform.coverage import bounded_subjects


class SQLiteLeaseCoverageReader:
    def relevant_context(self, connection, space_id, on):
        return self.relevant_contexts(connection, {space_id: on}).get(space_id)

    def relevant_contexts(self, connection, dates):
        bounded_subjects(dates)
        if not dates:
            return {}
        lease, term = LeaseModel.__table__, LeaseTermModel.__table__
        on = case(dates, value=lease.c.space_id)
        latest_term = (
            select(term.c.id)
            .where(term.c.lease_id == lease.c.id)
            .order_by(
                case((term.c.effective_on <= on, 0), else_=1),
                case((term.c.effective_on <= on, term.c.effective_on)).desc(),
                term.c.effective_on,
                term.c.id,
            )
            .correlate(lease)
            .limit(1)
            .scalar_subquery()
        )
        ranked = (
            select(
                lease.c.space_id,
                lease.c.id.label("lease_id"),
                lease.c.status,
                lease.c.actual_move_out_on,
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
                    partition_by=lease.c.space_id,
                    order_by=(
                        case((lease.c.status == "executed", 0), else_=1),
                        lease.c.occupancy_starts_on.desc(),
                        lease.c.id,
                    ),
                )
                .label("position"),
            )
            .select_from(lease.outerjoin(term, term.c.id == latest_term))
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
