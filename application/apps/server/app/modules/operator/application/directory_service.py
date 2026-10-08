"""Snapshot-bound operator directory reads, without SQL or source policy."""

from dataclasses import asdict
from datetime import UTC, datetime

from app.modules.operator.application.cursors import ReadCursor, decode_cursor, read_revision
from app.modules.operator.application.ports import OperatorUnitOfWork
from app.modules.operator.domain.models import (
    OperatorError,
    OperatorUnavailable,
    OperatorSectionUnavailable,
    utc,
)
from app.modules.portfolio.application.directory_ports import PropertyDirectoryQuery
from app.modules.portfolio.application.service import PortfolioError
from app.modules.portfolio.application.owner_read_ports import OwnerDirectoryQuery


class OperatorDirectoryService:
    def __init__(self, unit_of_work: OperatorUnitOfWork, *, runtime, now=lambda: datetime.now(UTC)):
        self.unit_of_work, self.runtime, self.now = unit_of_work, runtime, now

    def properties(self, *, cursor=None, **filters):
        identity = self.runtime()
        if identity.state != "ready":
            raise OperatorUnavailable("Open and validate the workspace before this operation.")
        try:
            query = PropertyDirectoryQuery(**filters)
        except PortfolioError as error:
            raise OperatorError(str(error)) from error
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise OperatorUnavailable("Operator clock is unavailable.")
        instant = instant.astimezone(UTC)
        runtime = (identity.workspace_id, identity.epoch)

        def read(tx):
            revision = read_revision(
                runtime, tx.source_marker() + ":" + tx.property_calendar_signature(instant)
            )
            continuation = (
                decode_cursor(
                    cursor,
                    endpoint="properties",
                    filters=asdict(query),
                    identity=runtime,
                    source_revision=revision,
                    now=instant,
                    sort_kind="label",
                )
                if cursor
                else None
            )
            captured = utc(continuation.as_of) if continuation else instant
            total, rows = tx.property_directory(
                query, as_of=captured, after=continuation.last if continuation else None
            )
            selected = rows[: query.limit]
            coverage = _coverage_previews(
                tx, "property", [row["id"] for row in selected], query, captured, revision
            )
            return {
                "items": [{**_card(row), "coverage": coverage[row["id"]]} for row in selected],
                "matchingTotal": total,
                "nextCursor": ReadCursor(
                    "properties",
                    asdict(query),
                    runtime,
                    revision,
                    captured.isoformat(),
                    (selected[-1]["sort_key"], selected[-1]["id"]),
                ).encode()
                if len(rows) > query.limit
                else None,
                "asOf": captured.isoformat(),
                "sourceRevision": revision,
                "query": {
                    "q": query.text,
                    "status": query.status,
                    "ownershipContext": query.ownership_context,
                    "occupancy": query.occupancy,
                    "availability": query.availability,
                    "needsAttention": query.needs_attention,
                    "limit": query.limit,
                },
            }

        return self.unit_of_work.read(read)

    def owners(self, *, cursor=None, **filters):
        identity = self.runtime()
        if identity.state != "ready":
            raise OperatorUnavailable("Open and validate the workspace before this operation.")
        try:
            query = OwnerDirectoryQuery(**filters)
        except PortfolioError as error:
            raise OperatorError(str(error)) from error
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise OperatorUnavailable("Operator clock is unavailable.")
        instant = instant.astimezone(UTC)
        runtime = (identity.workspace_id, identity.epoch)

        def read(tx):
            revision = read_revision(
                runtime, tx.source_marker() + ":" + tx.property_calendar_signature(instant)
            )
            continuation = (
                decode_cursor(
                    cursor,
                    endpoint="owners",
                    filters=asdict(query),
                    identity=runtime,
                    source_revision=revision,
                    now=instant,
                    sort_kind="label",
                )
                if cursor
                else None
            )
            captured = utc(continuation.as_of) if continuation else instant
            page = tx.owner_directory(
                query, as_of=captured, after=continuation.last if continuation else None
            )
            coverage = _coverage_previews(
                tx, "owner", [row["id"] for row in page.items], query, captured, revision
            )
            return {
                "items": [
                    {**_owner_card(row), "coverage": coverage[row["id"]]} for row in page.items
                ],
                "matchingTotal": page.total,
                "nextCursor": ReadCursor(
                    "owners", asdict(query), runtime, revision, captured.isoformat(), page.next_key
                ).encode()
                if page.next_key
                else None,
                "asOf": captured.isoformat(),
                "sourceRevision": revision,
                "query": {
                    "q": query.text,
                    "archiveState": query.archive_state,
                    "relationshipScope": query.relationship_scope,
                    "propertyState": query.property_state,
                    "limit": query.limit,
                },
            }

        return self.unit_of_work.read(read)


def _card(row):
    return {
        "id": row["id"],
        "displayName": row["display_name"],
        "addressLine1": row["address_line_1"],
        "addressLine2": row["address_line_2"],
        "city": row["city"],
        "region": row["region"],
        "postalCode": row["postal_code"],
        "countryCode": row["country_code"],
        "timeZone": row["time_zone"],
        "status": row["status"],
        "propertyType": row["property_type"],
        "inventoryLayout": row["inventory_layout"],
        "ownershipContext": row["ownership_context"],
        "needsAttention": row["needs_attention"],
        "effectiveLocalDate": row["effective_local_date"],
        "ownerCount": row["owner_count"],
        "owners": [
            {"partyId": x["party_id"], "displayName": x["display_name"]} for x in row["owners"]
        ],
        "spaceCount": row["space_count"],
        "spaces": [
            {
                "id": x["id"],
                "displayName": x["display_name"],
                "revision": x["revision"],
                "occupancy": x["occupancy"],
                "availability": x["availability"],
                "needsAttention": x["needs_attention"],
            }
            for x in row["spaces"]
        ],
    }


def _coverage_previews(tx, kind, ids, query, as_of, revision):
    try:
        pages = tx.coverage_previews(kind, ids, query, as_of=as_of)
    except OperatorSectionUnavailable:
        pages = None
    available = pages is not None
    scope = (
        query.relationship_scope
        if kind == "owner"
        else ("all" if query.status != "active" else "current")
    )
    results = {}
    for subject_id in ids:
        page = pages.get(subject_id) if available else None
        total, items = (page.total, list(page.items)) if page else (0, [])
        results[subject_id] = {
            "availability": "available" if available else "unavailable",
            "reasonCode": None if available else "source_read_unavailable",
            "matchingTotal": total if available else None,
            "items": items if available else None,
            "hasMore": total > len(items) if available else None,
            "asOf": as_of.isoformat(),
            "sourceRevision": revision if available else None,
            "viewAll": {
                "subjectKind": kind,
                "subjectId": subject_id,
                "section": "coverage",
                "relationshipScope": scope,
            },
        }
    return results


def _owner_card(row):
    return {
        "partyId": row["id"],
        "displayName": row["display_name"],
        "partyKind": row["party_kind"],
        "archived": row["archived_at"] is not None,
        "propertyCount": row["property_count"],
        "properties": [
            {
                "id": p["property_id"],
                "displayName": p["display_name"],
                "status": p["status"],
                "addressLine1": p["address_line_1"],
                "city": p["city"],
            }
            for p in row["properties"]
        ],
    }
