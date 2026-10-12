"""Set-based count and bounded selection for classified source SQL facts."""

from sqlalchemy import and_, case, func, literal, or_, select

PRIORITY_BANDS = ("urgent", "overdue", "today", "review", "waiting", "future")


def attention_rows(connection, facts, window, source_kind, reason_codes):
    """Facts own policy; this helper only applies aggregate and cursor mechanics."""
    f = facts.c
    matching = f.collection == window.collection
    counts = (
        connection.execute(
            select(
                func.coalesce(func.sum(case((matching, 1), else_=0)), 0).label("total"),
                func.min(f.next_transition).label("next_transition"),
                *(
                    func.coalesce(
                        func.sum(case((and_(matching, f.priority_band == band), 1), else_=0)), 0
                    ).label(f"band_{band}")
                    for band in PRIORITY_BANDS
                ),
                *(
                    func.coalesce(func.sum(case((and_(matching, f[code]), 1), else_=0)), 0).label(
                        f"reason_{code}"
                    )
                    for code in reason_codes
                ),
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
                f.sort_priority > key.priority,
                and_(f.sort_priority == key.priority, f.sort_at > key.at.isoformat()),
                and_(
                    f.sort_priority == key.priority,
                    f.sort_at == key.at.isoformat(),
                    literal(source_kind) > key.source_kind,
                ),
                and_(
                    f.sort_priority == key.priority,
                    f.sort_at == key.at.isoformat(),
                    literal(source_kind) == key.source_kind,
                    f.id > key.source_id,
                ),
            )
        )
    rows = (
        connection.execute(
            statement.order_by(f.sort_priority, f.sort_at, f.id).limit(window.limit + 1)
        )
        .mappings()
        .all()
    )
    return counts, rows
