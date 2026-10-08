"""Count and limit source-supplied metadata selections on the caller connection."""

from sqlalchemy import and_, func, or_, select

from app.platform.context_reads import ReadPage


def bounded_page(connection, selection, window, *, descending=False):
    facts = selection.subquery()
    total = connection.execute(select(func.count()).select_from(facts)).scalar_one()
    query = select(facts)
    label, identifier = facts.c.sort_key, facts.c.id
    if window.after:
        key, row_id = window.after
        comparison = label < key if descending else label > key
        tie = identifier < row_id if descending else identifier > row_id
        query = query.where(or_(comparison, and_(label == key, tie)))
    ordering = (label.desc(), identifier.desc()) if descending else (label, identifier)
    rows = connection.execute(query.order_by(*ordering).limit(window.limit + 1)).mappings().all()
    selected = rows[: window.limit]
    continuation = (
        (selected[-1]["sort_key"], selected[-1]["id"]) if len(rows) > window.limit else None
    )
    return ReadPage(total, selected, continuation)
