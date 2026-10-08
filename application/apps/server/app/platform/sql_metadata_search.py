"""Literal Unicode matching and bounded selection of source-approved metadata."""

from sqlalchemy import func, or_, select

from app.platform.sql_context_reads import bounded_page


def metadata_page(connection, selection, term, window):
    facts = selection.subquery()
    match = or_(
        func.instr(func.unicode_casefold(facts.c.label), term.text) > 0,
        func.instr(func.unicode_casefold(facts.c.context), term.text) > 0,
    )
    query = select(*facts.c, func.unicode_casefold(facts.c.label).label("sort_key")).where(match)
    if not term.include_archived:
        query = query.where(facts.c.archived == 0)
    return bounded_page(connection, query, window)
