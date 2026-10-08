"""Bounded grouped metadata search, each source on the same read snapshot."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.modules.operator.application.cursors import ReadCursor, decode_cursor, read_revision
from app.modules.operator.application.ports import OperatorUnitOfWork
from app.modules.operator.domain.models import (
    OperatorError,
    OperatorSectionUnavailable,
    OperatorUnavailable,
    utc,
)
from app.platform.context_reads import MAX_CONTEXT_ITEMS, ReadWindow
from app.platform.metadata_search import SearchTerm


@dataclass(frozen=True)
class SearchQuery:
    term: SearchTerm
    limit: int = 10
    group: str | None = None

    def __post_init__(self):
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_CONTEXT_ITEMS:
            raise OperatorError("Search groups allow 1–50 results.")
        if self.group is not None and not isinstance(self.group, str):
            raise OperatorError("Search group must be a registered kind.")


@dataclass(frozen=True)
class _SearchContext:
    query: SearchQuery
    window: ReadWindow
    runtime: tuple[str, str]
    revision: str


class OperatorSearchService:
    def __init__(self, unit_of_work: OperatorUnitOfWork, *, runtime, now=lambda: datetime.now(UTC)):
        self.unit_of_work, self.runtime, self.now = unit_of_work, runtime, now

    def search(self, text, *, include_archived=False, limit=10, group=None, cursor=None):
        identity = self.runtime()
        if identity.state != "ready":
            raise OperatorUnavailable("Open and validate the workspace before this operation.")
        try:
            query = SearchQuery(SearchTerm(text, include_archived), limit, group)
        except ValueError as error:
            raise OperatorError(str(error)) from error
        if cursor and group is None:
            raise OperatorError("A search continuation requires its group.")
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise OperatorUnavailable("Operator clock is unavailable.")
        instant = instant.astimezone(UTC)
        runtime = (identity.workspace_id, identity.epoch)

        def read(tx):
            definitions = tx.search_sources()
            if group is not None and group not in {source.kind for source in definitions}:
                raise OperatorError("Search group is not registered.")
            revision = read_revision(
                runtime, tx.source_marker() + ":" + tx.property_calendar_signature(instant)
            )
            continuation = (
                decode_cursor(
                    cursor,
                    endpoint=f"search:{group}",
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
            window = ReadWindow(captured, limit, continuation.last if continuation else None)
            groups = {}
            for source in definitions:
                if group is None or group == source.kind:
                    groups[source.kind] = _group(
                        tx, source, _SearchContext(query, window, runtime, revision)
                    )
            return {
                "query": {
                    "q": text,
                    "normalizedQ": query.term.text,
                    "includeArchived": include_archived,
                    "group": group,
                    "limit": limit,
                },
                "asOf": captured.isoformat(),
                "sourceRevision": revision,
                "groups": groups,
            }

        return self.unit_of_work.read(read)


def _group(tx, source, context):
    query, window, runtime, revision = (
        context.query,
        context.window,
        context.runtime,
        context.revision,
    )
    base = {
        "kind": source.kind,
        "sourceKind": source.source_kind,
        "asOf": window.as_of.isoformat(),
        "viewAll": {
            "kind": "metadata_search",
            "group": source.kind,
            "q": query.term.text,
            "includeArchived": query.term.include_archived,
            "limit": query.limit,
        },
    }
    try:
        page = tx.search_group(source.kind, query.term, window)
    except OperatorSectionUnavailable:
        return {
            **base,
            "availability": "unavailable",
            "reasonCode": "source_read_unavailable",
            "sourceRevision": None,
            "matchingTotal": None,
            "items": None,
            "nextCursor": None,
        }
    filters = {**asdict(query), "group": source.kind}
    cursor = (
        ReadCursor(
            f"search:{source.kind}",
            filters,
            runtime,
            revision,
            window.as_of.isoformat(),
            page.next_key,
        ).encode()
        if page.next_key
        else None
    )
    items = []
    for row in page.items:
        if row["entity_type"] != source.entity_type:
            raise ValueError("Source returned an unregistered search target.")
        items.append(
            {
                "sourceType": source.entity_type,
                "sourceId": row["id"],
                "label": row["label"],
                "context": row["context"],
                "archived": bool(row["archived"]),
                "target": {"entityType": source.entity_type, "entityId": row["id"]},
            }
        )
    return {
        **base,
        "availability": "available",
        "reasonCode": None,
        "sourceRevision": revision,
        "matchingTotal": page.total,
        "items": items,
        "nextCursor": cursor,
    }
