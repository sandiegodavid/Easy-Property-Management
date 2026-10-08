"""Set-based owner membership and capped Portfolio metadata on caller snapshots."""

from datetime import UTC
from dataclasses import dataclass

from sqlalchemy import and_, case, exists, func, literal, or_, select

from app.modules.parties.application.identity_relations import PartyIdentityRelations
from app.modules.portfolio.application.directory_ports import RECOGNITION_PREVIEW_LIMIT
from app.modules.portfolio.infrastructure.directory_reader import (
    SQLitePortfolioDirectoryReader,
    _local_day,
)
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    PropertyOwnershipModel,
)
from app.platform.context_reads import ReadPage
from app.platform.sql_context_reads import bounded_page


class SQLiteOwnerContextReader:
    def __init__(self, parties: PartyIdentityRelations):
        self.parties = parties

    @staticmethod
    def _prepare(connection):
        connection.connection.driver_connection.create_function(
            "portfolio_local_day", 2, _local_day, deterministic=True
        )

    def identity(self, connection, subject):
        if subject.kind == "property":
            p = PropertyModel.__table__
            return (
                connection.execute(
                    select(
                        p.c.id,
                        p.c.display_name,
                        p.c.status,
                        p.c.time_zone,
                        p.c.address_line_1,
                        p.c.city,
                        p.c.country_code,
                    ).where(p.c.id == subject.id)
                )
                .mappings()
                .first()
            )
        party = self.parties.identities()
        o = PropertyOwnershipModel.__table__
        return (
            connection.execute(
                select(
                    party.c.party_id.label("id"),
                    party.c.display_name,
                    party.c.party_kind,
                    party.c.archived_at,
                ).where(
                    party.c.party_id == subject.id,
                    exists(
                        select(1).where(
                            o.c.owner_kind == "client_owner", o.c.party_id == party.c.party_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )

    def property_scope(self, connection, subject, *, as_of):
        self._prepare(connection)
        p, o = PropertyModel.__table__, PropertyOwnershipModel.__table__
        if subject.kind == "property":
            return (
                select(p.c.id.label("property_id"))
                .where(p.c.id == subject.id)
                .subquery("subject_properties")
            )
        return (
            select(o.c.property_id)
            .join(p, p.c.id == o.c.property_id)
            .where(
                o.c.owner_kind == "client_owner",
                o.c.party_id == subject.id,
                _period(o, p, subject.relationship_scope, as_of),
            )
            .distinct()
            .subquery("subject_properties")
        )

    def coverage_preview_groups(self, connection, kind, ids, query, *, as_of):
        self._prepare(connection)
        p = PropertyModel.__table__
        if kind == "property":
            return (
                select(p.c.id.label("group_id"), p.c.id.label("property_id"))
                .where(p.c.id.in_(ids))
                .subquery("coverage_groups")
            )
        related = _related_properties(query, as_of)
        return (
            select(related.c.party_id.label("group_id"), related.c.property_id)
            .where(related.c.party_id.in_(ids))
            .subquery("coverage_groups")
        )

    def owners(self, connection, query, *, as_of, after):
        self._prepare(connection)
        o, p = PropertyOwnershipModel.__table__, PropertyModel.__table__
        party = self.parties.identities()
        related = _related_properties(query, as_of)
        membership = exists(select(1).where(related.c.party_id == party.c.party_id))
        predicates = [membership]
        if query.archive_state != "all":
            predicates.append(
                party.c.archived_at.is_(None)
                if query.archive_state == "active"
                else party.c.archived_at.is_not(None)
            )
        if query.text:
            address_match = exists(
                select(1)
                .select_from(o.join(p, o.c.property_id == p.c.id))
                .where(
                    o.c.party_id == party.c.party_id,
                    o.c.owner_kind == "client_owner",
                    _period(o, p, query.relationship_scope, as_of),
                    _property_state(p, query.property_state),
                    _property_text(p, query.text),
                )
            )
            predicates.append(
                or_(
                    func.instr(func.unicode_casefold(party.c.display_name), query.text) > 0,
                    address_match,
                )
            )
        selection = select(
            party.c.party_id.label("id"),
            party.c.display_name,
            party.c.party_kind,
            party.c.archived_at,
            func.unicode_casefold(party.c.display_name).label("sort_key"),
        ).where(*predicates)
        page = bounded_page(connection, selection, _DirectoryWindow(query.limit, after))
        ids = [row["id"] for row in page.items]
        previews = _property_previews(connection, related, ids)
        items = [
            {**row, "property_count": previews[row["id"]][0], "properties": previews[row["id"]][1]}
            for row in page.items
        ]
        return ReadPage(page.total, items, page.next_key)

    def properties(self, connection, subject, window):
        self._prepare(connection)
        p = PropertyModel.__table__
        scope = self.property_scope(connection, subject, as_of=window.as_of)
        selection = select(
            p.c.id,
            p.c.display_name,
            p.c.address_line_1,
            p.c.city,
            p.c.country_code,
            p.c.status,
            p.c.time_zone,
            func.unicode_casefold(p.c.display_name).label("sort_key"),
        ).where(p.c.id.in_(select(scope.c.property_id)))
        return bounded_page(connection, selection, window)

    def relationships(self, connection, subject, window):
        self._prepare(connection)
        o, p = PropertyOwnershipModel.__table__, PropertyModel.__table__
        party = self.parties.identities()
        predicates = [_period(o, p, subject.relationship_scope, window.as_of)]
        predicates.append(
            o.c.property_id == subject.id
            if subject.kind == "property"
            else and_(o.c.owner_kind == "client_owner", o.c.party_id == subject.id)
        )
        selection = (
            select(
                o.c.id,
                o.c.property_id,
                p.c.display_name.label("property_name"),
                o.c.owner_kind,
                o.c.party_id,
                party.c.display_name.label("owner_name"),
                o.c.starts_on,
                o.c.ends_on,
                _relationship_state(o, p, window.as_of).label("relationship_state"),
                o.c.starts_on.label("sort_key"),
            )
            .select_from(
                o.join(p, p.c.id == o.c.property_id).outerjoin(
                    party, party.c.party_id == o.c.party_id
                )
            )
            .where(*predicates)
        )
        return bounded_page(connection, selection, window, descending=True)

    def spaces(self, connection, subject, window):
        self._prepare(connection)
        scope = self.property_scope(connection, subject, as_of=window.as_of)
        facts = SQLitePortfolioDirectoryReader._space_facts(
            window.as_of.astimezone(UTC).isoformat()
        )
        selection = select(
            *facts.c, func.unicode_casefold(facts.c.display_name).label("sort_key")
        ).where(facts.c.property_id.in_(select(scope.c.property_id)))
        return bounded_page(connection, selection, window)


def _period(ownership, property, scope, instant):
    day = func.portfolio_local_day(property.c.time_zone, instant.astimezone(UTC).isoformat())
    if scope == "current":
        return and_(
            ownership.c.starts_on <= day,
            or_(ownership.c.ends_on.is_(None), ownership.c.ends_on > day),
        )
    if scope == "former":
        return ownership.c.ends_on <= day
    return literal(True)


def _relationship_state(o, p, instant):
    day = func.portfolio_local_day(p.c.time_zone, instant.astimezone(UTC).isoformat())
    return case((o.c.starts_on > day, "scheduled"), (o.c.ends_on <= day, "former"), else_="current")


def _property_state(p, state):
    return p.c.status == state if state != "all" else literal(True)


def _property_text(p, text):
    address = (
        p.c.address_line_1
        + literal(" ")
        + func.coalesce(p.c.address_line_2, "")
        + literal(" ")
        + p.c.city
        + literal(" ")
        + func.coalesce(p.c.region, "")
        + literal(" ")
        + func.coalesce(p.c.postal_code, "")
    )
    return or_(
        func.instr(func.unicode_casefold(p.c.display_name), text) > 0,
        func.instr(func.unicode_casefold(address), text) > 0,
    )


def _related_properties(query, instant):
    p, o = PropertyModel.__table__, PropertyOwnershipModel.__table__
    return (
        select(
            o.c.party_id,
            p.c.id.label("property_id"),
            p.c.display_name,
            p.c.status,
            p.c.address_line_1,
            p.c.city,
        )
        .join(p, p.c.id == o.c.property_id)
        .where(
            o.c.owner_kind == "client_owner",
            _period(o, p, query.relationship_scope, instant),
            _property_state(p, query.property_state),
        )
        .distinct()
        .subquery("related_owner_properties")
    )


def _property_previews(connection, facts, ids):
    if not ids:
        return {}
    ranked = (
        select(
            *facts.c,
            func.count().over(partition_by=facts.c.party_id).label("total"),
            func.row_number()
            .over(
                partition_by=facts.c.party_id,
                order_by=(func.unicode_casefold(facts.c.display_name), facts.c.property_id),
            )
            .label("position"),
        )
        .where(facts.c.party_id.in_(ids))
        .subquery()
    )
    result = {}
    for row in connection.execute(
        select(ranked)
        .where(ranked.c.position <= RECOGNITION_PREVIEW_LIMIT)
        .order_by(ranked.c.party_id, ranked.c.position)
    ).mappings():
        total, items = result.setdefault(row["party_id"], (row["total"], []))
        items.append(
            {
                key: row[key]
                for key in ("property_id", "display_name", "status", "address_line_1", "city")
            }
        )
    return result


@dataclass(frozen=True)
class _DirectoryWindow:
    limit: int
    after: tuple[str, str] | None
