"""Neutral, bounded source attention facts on a caller-owned read transaction."""

from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date
from typing import Protocol, Literal
from uuid import UUID
from zoneinfo import ZoneInfo
from app.platform.coverage import CoverageResolution, CoverageArea, CoverageCause

MAX_ATTENTION_ITEMS = 100
MAX_CHILD_PREVIEW = 3
MAX_REASON_FACTS = 32
MAX_ATTENTION_TITLE = 500


@dataclass(frozen=True, order=True)
class AttentionKey:
    priority: int
    at: datetime
    source_kind: str
    source_id: str

    def __post_init__(self):
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("Attention ordering needs a nonnegative priority.")
        if self.at.tzinfo is None or self.at.utcoffset() != UTC.utcoffset(self.at):
            raise ValueError("Attention ordering needs a UTC boundary.")
        if not self.source_kind or not self.source_id:
            raise ValueError("Attention ordering needs a stable source identity.")


@dataclass(frozen=True)
class AttentionDate:
    time_zone: str
    at: datetime | None = None
    on: date | None = None

    def __post_init__(self):
        if (self.at is None) == (self.on is None):
            raise ValueError("Source date requires exactly one instant or local date.")
        ZoneInfo(self.time_zone)
        if self.at is not None and (
            self.at.tzinfo is None or self.at.utcoffset() != UTC.utcoffset(self.at)
        ):
            raise ValueError("Source instants require UTC.")


@dataclass(frozen=True)
class AttentionReasonFact:
    code: str
    priority: Literal["urgent", "overdue", "today", "review", "waiting", "future", "information"]
    source_kind: str
    source_id: UUID
    date: AttentionDate | None = None


@dataclass(frozen=True)
class AttentionRelation:
    kind: Literal["issue_follow_up", "concern_follow_up", "task_reminder"]
    parent_kind: str
    parent_id: UUID
    child_kind: Literal["task", "reminder"]
    child_id: UUID


@dataclass(frozen=True)
class AttentionSourceContext:
    kind: Literal["maintenance_issue", "owner_concern"]
    id: UUID
    active: bool


@dataclass(frozen=True)
class AttentionChild:
    relation: AttentionRelation
    reasons: tuple[AttentionReasonFact, ...]
    revision: str
    status: str
    children: tuple["AttentionChild", ...] = ()
    child_count: int = 0

    def __post_init__(self):
        if (
            len(self.children) > MAX_CHILD_PREVIEW
            or type(self.child_count) is not int
            or self.child_count < len(self.children)
        ):
            raise ValueError("Nested child previews require bounded rows and exact counts.")
        if self.relation.child_kind == "reminder" and self.children:
            raise ValueError("Reminder previews cannot contain nested children.")
        if any(
            child.relation.kind != "task_reminder"
            or child.relation.parent_kind != "task"
            or child.relation.parent_id != self.relation.child_id
            for child in self.children
        ):
            raise ValueError("Nested reminders must retain their exact Task parent.")


@dataclass(frozen=True)
class AttentionWindow:
    as_of: datetime
    collection: str
    property_id: UUID | None = None
    horizon_days: int = 7
    limit: int = 5
    after: AttentionKey | None = None
    source_kind: (
        Literal[
            "task",
            "rent_expectation",
            "maintenance_issue",
            "owner_rent_report",
            "owner_concern",
            "lease",
            "maintenance_appointment",
            "coverage",
        ]
        | None
    ) = None

    def __post_init__(self):
        if self.as_of.tzinfo is None or self.as_of.utcoffset() != UTC.utcoffset(self.as_of):
            raise ValueError("Attention reads require UTC.")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_ATTENTION_ITEMS:
            raise ValueError("Attention page bound is 1–100.")
        if type(self.horizon_days) is not int or self.horizon_days not in (7, 30, 90):
            raise ValueError("Attention horizon is 7, 30 or 90 days.")
        if self.collection not in (
            "needs_action",
            "waiting",
            "upcoming",
            "appointments",
            "information_review",
        ):
            raise ValueError("Unknown attention collection.")
        if self.source_kind is not None and self.source_kind not in (
            "task",
            "rent_expectation",
            "maintenance_issue",
            "owner_rent_report",
            "owner_concern",
            "lease",
            "maintenance_appointment",
            "coverage",
        ):
            raise ValueError("Unknown attention source discriminator.")


@dataclass(frozen=True)
class AttentionFact:
    """Source classification and relation facts; metadata only, never evidence."""

    key: AttentionKey
    source_revision: str
    status: str
    title: str
    reasons: tuple[AttentionReasonFact, ...]
    property_id: UUID | None = None
    space_id: UUID | None = None
    time_zone: str | None = None
    property_archived: bool = False
    relation: AttentionRelation | None = None
    children: tuple[AttentionChild, ...] = ()
    child_count: int = 0
    task_deadline: AttentionDate | None = None
    follow_up: AttentionDate | None = None
    source_deadline: AttentionDate | None = None
    appointment_end: datetime | None = None
    subject_kind: Literal["property", "space"] | None = None
    coverage_area: CoverageArea | None = None
    coverage_causes: tuple[CoverageCause, ...] = ()
    coverage_resolution: CoverageResolution | None = None
    recorded_at: datetime | None = None
    outstanding_minor: int | None = None
    currency: Literal["USD"] | None = None
    lease_id: UUID | None = None
    expected_minor: int | None = None
    received_minor: int | None = None
    period_starts_on: date | None = None
    period_ends_on: date | None = None
    owner_party_id: UUID | None = None
    owner_display_name_snapshot: str | None = None
    property_name: str | None = None
    space_name: str | None = None
    related_source: AttentionSourceContext | None = None

    def __post_init__(self):
        if (
            not self.source_revision
            or not self.status
            or not self.title
            or len(self.title) > MAX_ATTENTION_TITLE
        ):
            raise ValueError("Source metadata needs bounded title, revision and status.")
        if self.key.source_kind == "coverage":
            target = self.coverage_resolution
            if target is None or (target.subject_kind, target.area, target.subject_id) != (
                self.subject_kind,
                self.coverage_area,
                self.property_id if self.subject_kind == "property" else self.space_id,
            ):
                raise ValueError("Coverage facts require an exact typed resolution target.")
        if self.key.source_kind == "rent_expectation":
            amounts = (self.expected_minor, self.received_minor, self.outstanding_minor)
            if any(type(amount) is not int for amount in amounts) or self.currency != "USD":
                raise ValueError("Rent attention requires exact USD integer amounts.")
            if (
                self.expected_minor - self.received_minor != self.outstanding_minor
                or self.received_minor < 0
                or self.outstanding_minor <= 0
            ):
                raise ValueError("Rent attention requires a positive corrected outstanding amount.")
            if (
                self.lease_id is None
                or self.period_starts_on is None
                or self.period_ends_on is None
                or self.period_starts_on >= self.period_ends_on
            ):
                raise ValueError("Rent attention must retain its exact lease and period identity.")
        if not 1 <= len(self.reasons) <= MAX_REASON_FACTS or len(self.children) > MAX_CHILD_PREVIEW:
            raise ValueError("Source reasons and child previews must be bounded.")
        if type(self.child_count) is not int or self.child_count < len(self.children):
            raise ValueError("Source child count must be exact.")


@dataclass(frozen=True)
class AttentionPage:
    """Counts reflect grouping before LIMIT; candidates contain at most limit+1."""

    matching_total: int
    candidates: tuple[AttentionFact, ...]
    next_transition_at: datetime | None = None
    priority_counts: tuple[tuple[str, int], ...] = ()
    reason_counts: tuple[tuple[str, int], ...] = ()
    applicable_count: int | None = None
    not_applicable_count: int | None = None

    def validate_window(self, window: AttentionWindow) -> None:
        if type(self.matching_total) is not int or self.matching_total < 0:
            raise ValueError("Source counts must be exact non-negative integers.")
        if len(self.candidates) > window.limit + 1 or self.matching_total < len(self.candidates):
            raise ValueError("Source candidates exceed their bounded grouped count.")
        if window.source_kind is not None and any(
            item.key.source_kind != window.source_kind for item in self.candidates
        ):
            raise ValueError("Source candidates must match the requested discriminator.")
        keys = tuple(item.key for item in self.candidates)
        if keys != tuple(sorted(set(keys))) or any(
            window.after is not None and key <= window.after for key in keys
        ):
            raise ValueError("Source candidates must be unique, ordered and after the cursor.")
        if self.next_transition_at is not None and self.next_transition_at <= window.as_of:
            raise ValueError("Source transition must follow capture.")
        if any(
            len(item.children) > MAX_CHILD_PREVIEW
            or item.child_count < len(item.children)
            or not item.reasons
            for item in self.candidates
        ):
            raise ValueError("Source reasons and child previews must be complete and bounded.")
        for counts in (self.priority_counts, self.reason_counts):
            if len({name for name, _ in counts}) != len(counts) or any(
                type(count) is not int or count < 0 for _, count in counts
            ):
                raise ValueError("Breakdowns require unique names and exact counts.")


@dataclass(frozen=True)
class InventoryFacts:
    vacant_count: int
    unknown_count: int
    active_property_count: int
    active_space_count: int
    next_transition_at: datetime | None


@dataclass(frozen=True)
class PropertyCalendar:
    property_id: UUID
    time_zone: str
    local_date: date
    today_start: datetime
    tomorrow_start: datetime
    horizon_end: datetime
    archived: bool
    property_name: str


class AttentionReader(Protocol):
    def attention(self, connection: object, window: AttentionWindow) -> AttentionPage: ...
