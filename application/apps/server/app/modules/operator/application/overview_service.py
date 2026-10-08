"""One-snapshot contextual reads; expected section failures stay independent."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.modules.finance.application.money_models import MoneyQuery, MoneyError
from app.modules.operator.application.cursors import ReadCursor, decode_cursor, read_revision
from app.modules.operator.application.ports import OperatorUnitOfWork
from app.modules.operator.domain.models import (
    OperatorError,
    OperatorNotFound,
    OperatorSectionUnavailable,
    OperatorUnavailable,
    identifier,
    utc,
)
from app.modules.portfolio.application.owner_read_ports import PortfolioSubject, RELATIONSHIP_SCOPES
from app.platform.context_reads import MAX_CONTEXT_ITEMS, ReadWindow
from app.modules.operator.application.overview_projection import item_view

PROPERTY_SECTIONS = (
    "relationships",
    "spaces",
    "leases",
    "tasks",
    "maintenance",
    "communications",
    "concerns",
    "money",
    "coverage",
)
OWNER_SECTIONS = (
    "relationships",
    "properties",
    "leases",
    "tasks",
    "maintenance",
    "communications",
    "concerns",
    "money",
    "coverage",
)
SECTION_SOURCES = {
    "relationships": "portfolio",
    "spaces": "portfolio",
    "properties": "portfolio",
    "leases": "leases",
    "tasks": "tasks",
    "maintenance": "maintenance",
    "communications": "communications",
    "concerns": "owner_management",
    "money": "finance",
    "coverage": "operator",
}


@dataclass(frozen=True)
class OverviewQuery:
    relationship_scope: str = "current"
    from_on: str | None = None
    through_on: str | None = None
    limit: int = 10
    section: str | None = None

    def __post_init__(self):
        if (
            self.relationship_scope not in RELATIONSHIP_SCOPES
            or type(self.limit) is not int
            or not 1 <= self.limit <= MAX_CONTEXT_ITEMS
        ):
            raise OperatorError("Overview scope or section bounds are invalid.")
        if (self.from_on is None) != (self.through_on is None):
            raise OperatorError("Money sections require both fromOn and throughOn.")
        if self.from_on is not None:
            try:
                MoneyQuery(self.from_on, self.through_on)
            except MoneyError as error:
                raise OperatorError("Money period is invalid.") from error


@dataclass(frozen=True)
class _ReadContext:
    subject: PortfolioSubject
    query: OverviewQuery
    window: ReadWindow
    runtime: tuple[str, str]
    revision: str


class OperatorOverviewService:
    def __init__(self, unit_of_work: OperatorUnitOfWork, *, runtime, now=lambda: datetime.now(UTC)):
        self.unit_of_work, self.runtime, self.now = unit_of_work, runtime, now

    def overview(self, kind, subject_id, *, cursor=None, **filters):
        identity = self.runtime()
        if identity.state != "ready":
            raise OperatorUnavailable("Open and validate the workspace before this operation.")
        identifier(subject_id)
        query = OverviewQuery(**filters)
        names = PROPERTY_SECTIONS if kind == "property" else OWNER_SECTIONS
        if kind not in {"property", "owner"} or query.section not in (*names, None):
            raise OperatorError("Overview subject or section is invalid.")
        if cursor and (query.section is None or query.section == "money"):
            raise OperatorError("A collection continuation requires its section.")
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise OperatorUnavailable("Operator clock is unavailable.")
        instant = instant.astimezone(UTC)
        runtime = (identity.workspace_id, identity.epoch)
        subject = PortfolioSubject(kind, subject_id, query.relationship_scope)

        def read(tx):
            revision = read_revision(
                runtime, tx.source_marker() + ":" + tx.property_calendar_signature(instant)
            )
            endpoint = f"{kind}:{subject_id}:{query.section}"
            continuation = (
                decode_cursor(
                    cursor,
                    endpoint=endpoint,
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
            facts = tx.context_identity(subject)
            if facts is None:
                raise OperatorNotFound("Context subject was not found.")
            sections = {}
            for name in (query.section,) if query.section else names:
                window = ReadWindow(
                    captured,
                    query.limit,
                    continuation.last if continuation else None,
                    query.relationship_scope != "current",
                )
                sections[name] = _section(
                    tx, name, _ReadContext(subject, query, window, runtime, revision)
                )
            return {
                "subject": _identity(kind, facts),
                "relationshipScope": query.relationship_scope,
                "asOf": captured.isoformat(),
                "sourceRevision": revision,
                "sections": sections,
            }

        return self.unit_of_work.read(read)


def _section(tx, name, context):
    subject, query, window = context.subject, context.query, context.window
    base = {
        "kind": name,
        "sourceKind": SECTION_SOURCES[name],
        "asOf": window.as_of.isoformat(),
        "sourceRevision": context.revision,
        "viewAll": {
            "subjectKind": subject.kind,
            "subjectId": subject.id,
            "section": name,
            "relationshipScope": query.relationship_scope,
            "fromOn": query.from_on,
            "throughOn": query.through_on,
        },
    }
    if name == "money" and query.from_on is None:
        return _unavailable(base, "money_period_required")
    try:
        return _read_section(tx, base, context)
    except OperatorSectionUnavailable:
        return _unavailable(base, "source_read_unavailable")


def _read_section(tx, base, context):
    subject, query, window, runtime = (
        context.subject,
        context.query,
        context.window,
        context.runtime,
    )
    if base["kind"] == "money":
        summary = tx.context_money(
            subject,
            MoneyQuery(query.from_on, query.through_on),
            as_of=window.as_of,
            identity=runtime,
        )
        return {
            **base,
            "availability": "available",
            "reasonCode": None,
            "summary": asdict(summary),
            "scopeMeaning": "whole_property_activity_not_owner_entitlement",
        }
    page = (
        tx.coverage_page(subject, window)
        if base["kind"] == "coverage"
        else tx.context_collection(base["kind"], subject, window)
    )
    cursor_query = {**asdict(query), "section": base["kind"]}
    cursor = (
        ReadCursor(
            f"{subject.kind}:{subject.id}:{base['kind']}",
            cursor_query,
            runtime,
            base["sourceRevision"],
            window.as_of.isoformat(),
            page.next_key,
        ).encode()
        if page.next_key
        else None
    )
    return {
        **base,
        "availability": "available",
        "reasonCode": None,
        "matchingTotal": page.total,
        "items": list(page.items)
        if base["kind"] == "coverage"
        else [item_view(base["kind"], row) for row in page.items],
        "nextCursor": cursor,
    }


def _unavailable(base, reason):
    return {**base, "availability": "unavailable", "reasonCode": reason, "sourceRevision": None}


def _identity(kind, facts):
    common = {"kind": kind, "id": facts["id"], "displayName": facts["display_name"]}
    if kind == "owner":
        return {
            **common,
            "partyKind": facts["party_kind"],
            "archived": facts["archived_at"] is not None,
        }
    return {
        **common,
        "status": facts["status"],
        "timeZone": facts["time_zone"],
        "addressLine1": facts["address_line_1"],
        "city": facts["city"],
        "countryCode": facts["country_code"],
    }
