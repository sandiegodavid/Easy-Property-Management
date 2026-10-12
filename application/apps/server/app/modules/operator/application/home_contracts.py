"""DASH-001 bounded metadata contracts; no source evidence or write authority."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictBool,
    field_validator,
    model_validator,
)

from app.modules.operator.application.home_vocabulary import Collection, SourceKind
from app.modules.operator.application.home_registry import validate_item, COLLECTION_DEPENDENCIES
from app.platform.coverage import CoverageArea


class HomeContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        alias_generator=lambda value: (
            value.split("_")[0] + "".join(word.title() for word in value.split("_")[1:])
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def integer_discriminators(cls, value):
        if isinstance(value, dict):
            for name in ("horizon_days", "horizonDays", "contract_version", "contractVersion"):
                if name in value and type(value[name]) is not int:
                    raise ValueError("Version and horizon must be exact integers.")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def utc_instants(cls, value):
        if isinstance(value, datetime) and (
            value.utcoffset() is None or value.utcoffset().total_seconds() != 0
        ):
            raise ValueError("Home instants require aware UTC values.")
        return value


class HomeScope(HomeContract):
    kind: Literal["portfolio", "property"] = "portfolio"
    property_id: UUID | None = None

    @model_validator(mode="after")
    def property_scope(self):
        if (self.kind == "property") != (self.property_id is not None):
            raise ValueError("Only property scope requires propertyId.")
        return self


class HomeQuery(HomeContract):
    scope: HomeScope = HomeScope()
    horizon_days: Literal[7, 30, 90] = 7
    from_on: date
    through_on: date
    limit_per_section: StrictInt = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def money_period(self):
        if self.from_on > self.through_on:
            raise ValueError("Money dates must be ordered.")
        return self


class AttentionQuery(HomeContract):
    scope: HomeScope = HomeScope()
    limit: StrictInt = Field(default=5, ge=1, le=10)


class CollectionQuery(HomeContract):
    scope: HomeScope = HomeScope()
    collection: Collection
    horizon_days: Literal[7, 30, 90] = 7
    limit: StrictInt = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)


class SourceIdentity(HomeContract):
    id: UUID


class TaskSource(SourceIdentity):
    kind: Literal["task"]


class RentSource(SourceIdentity):
    kind: Literal["rent_expectation"]


class IssueSource(SourceIdentity):
    kind: Literal["maintenance_issue"]


class ReportSource(SourceIdentity):
    kind: Literal["owner_rent_report"]


class ConcernSource(SourceIdentity):
    kind: Literal["owner_concern"]


class LeaseSource(SourceIdentity):
    kind: Literal["lease"]


class AppointmentSource(SourceIdentity):
    kind: Literal["maintenance_appointment"]


class CoverageSource(SourceIdentity):
    kind: Literal["coverage"]
    subject_kind: Literal["property", "space"]
    area: CoverageArea


SourceReference = Annotated[
    TaskSource
    | RentSource
    | IssueSource
    | ReportSource
    | ConcernSource
    | LeaseSource
    | AppointmentSource
    | CoverageSource,
    Field(discriminator="kind"),
]

ReasonCode = Literal[
    "emergency",
    "urgent",
    "overdue",
    "due_today",
    "follow_up_due",
    "reminder_due",
    "undated",
    "unresolved",
    "pending_verification",
    "lease_review",
    "continued_occupancy",
    "outcome_review",
    "waiting",
    "follow_up_unscheduled",
    "scheduled",
    "missing_required",
    "needs_review",
]


class SourceTarget(HomeContract):
    kind: Literal["source"] = "source"
    source: SourceReference


class CollectionTarget(HomeContract):
    kind: Literal["home_collection"] = "home_collection"
    collection: Collection
    scope: HomeScope
    horizon_days: Literal[7, 30, 90] = 7


class AttentionReason(HomeContract):
    code: ReasonCode
    priority: Literal["urgent", "overdue", "today", "review", "waiting", "future", "information"]
    source: SourceReference
    at: datetime | None = None
    on: date | None = None
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def local_date(self):
        if (self.on is not None or self.at is not None) and self.time_zone is None:
            raise ValueError("Date-only facts require their source time zone.")
        if self.on is not None and self.at is not None:
            raise ValueError("Temporal facts must distinguish date-only from timed values.")
        if self.time_zone is not None:
            try:
                ZoneInfo(self.time_zone)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("Source time zone must be an IANA zone.") from error
        return self


class TemporalFact(HomeContract):
    """Dates are source facts, independent of the attention reason vocabulary."""

    at: datetime | None = None
    on: date | None = None
    time_zone: str

    @model_validator(mode="after")
    def temporal_kind(self):
        if (self.at is None) == (self.on is None):
            raise ValueError("Specify exactly one instant or local date.")
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Source time zone must be an IANA zone.") from error
        return self


class HomeAction(HomeContract):
    kind: Literal[
        "review_task",
        "record_payment",
        "review_issue",
        "review_report",
        "review_concern",
        "review_lease",
        "review_appointment",
        "review_coverage",
    ]
    target: SourceTarget


class GroupLink(HomeContract):
    relation: Literal["issue_follow_up", "concern_follow_up", "task_reminder"]
    child_id: UUID
    parent: SourceReference


class RelatedSourceContext(HomeContract):
    source: IssueSource | ConcernSource
    active: StrictBool


class ChildPreview(HomeContract):
    id: UUID
    kind: Literal["task", "reminder"]
    target: SourceTarget
    source_revision: str | None = Field(default=None, min_length=1, max_length=128)
    source_status: str | None = Field(default=None, min_length=1, max_length=64)
    reasons: tuple[AttentionReason, ...] = Field(default=(), max_length=32)
    children: tuple["ChildPreview", ...] = Field(default=(), max_length=3)
    child_count: StrictInt = Field(default=0, ge=0)

    @model_validator(mode="after")
    def bounded_reminders(self):
        if self.child_count < len(self.children) or (self.kind == "reminder" and self.children):
            raise ValueError("Child previews require bounded reminders and exact counts.")
        if any(child.kind != "reminder" or child.target != self.target for child in self.children):
            raise ValueError("Nested reminders retain their Task action target.")
        return self


class Provenance(HomeContract):
    owner: Literal[
        "tasks",
        "finance",
        "maintenance",
        "owner_accounting",
        "owner_management",
        "leases",
        "operator",
    ]
    source_revision: str = Field(min_length=1, max_length=128)
    recorded_at: datetime | None = None


class HomeItem(HomeContract):
    key: str = Field(min_length=1, max_length=200)
    source: SourceReference
    source_revision: str = Field(min_length=1, max_length=128)
    source_status: str = Field(min_length=1, max_length=64)
    property_id: UUID | None = None
    space_id: UUID | None = None
    property_name: str | None = Field(default=None, min_length=1, max_length=500)
    space_name: str | None = Field(default=None, min_length=1, max_length=500)
    related_source: RelatedSourceContext | None = None
    property_archived: StrictBool = False
    title: str = Field(min_length=1, max_length=500)
    collection: Collection
    reasons: tuple[AttentionReason, ...] = Field(min_length=1, max_length=32)
    task_deadline: TemporalFact | None = None
    follow_up: TemporalFact | None = None
    source_deadline: TemporalFact | None = None
    group_links: tuple[GroupLink, ...] = Field(default=(), max_length=3)
    children: tuple[ChildPreview, ...] = Field(default=(), max_length=3)
    child_count: StrictInt = Field(default=0, ge=0)
    child_detail_target: SourceTarget | None = None
    next_action: HomeAction
    provenance: Provenance
    outstanding_minor: StrictInt | None = Field(default=None, gt=0)
    currency: Literal["USD"] | None = None

    @model_validator(mode="after")
    def registered_pairing(self):
        validate_item(self)
        return self


class Capture(HomeContract):
    as_of: datetime
    source_revision: str = Field(min_length=1, max_length=128)
    read_mode: Literal["live", "snapshot"]
    generation_id: UUID | None = None
    freshness: Literal["checked", "checking", "stale", "unavailable"]
    checked_at: datetime | None = None
    next_transition_at: datetime | None = None

    @model_validator(mode="after")
    def capture_mode(self):
        if (self.read_mode == "snapshot") != (self.generation_id is not None):
            raise ValueError("Only snapshot captures require generationId.")
        if self.freshness == "checked" and (
            self.checked_at is None or (self.read_mode == "live" and self.checked_at != self.as_of)
        ):
            raise ValueError("Checked live captures require checkedAt equal to asOf.")
        if self.next_transition_at is not None and self.next_transition_at <= self.as_of:
            raise ValueError("The next transition must follow capture.")
        if self.checked_at is not None and self.checked_at < self.as_of:
            raise ValueError("A check cannot precede capture.")
        return self


class AvailableCollection(HomeContract):
    status: Literal["available"] = "available"
    collection: Collection
    capture: Capture
    matching_total: StrictInt = Field(ge=0)
    items: tuple[HomeItem, ...] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4096)
    view_all_target: CollectionTarget

    @model_validator(mode="after")
    def coherent_items(self):
        if (
            self.matching_total < len(self.items)
            or any(item.collection != self.collection for item in self.items)
            or len({item.key for item in self.items}) != len(self.items)
            or self.view_all_target.collection != self.collection
        ):
            raise ValueError("Collection rows, count and target must agree.")
        if self.capture.freshness == "unavailable":
            raise ValueError("An available collection cannot have unavailable capture.")
        if self.view_all_target.scope.kind == "property" and any(
            item.property_id != self.view_all_target.scope.property_id for item in self.items
        ):
            raise ValueError("Property scope excludes unrelated and unlinked items.")
        return self


class UnavailableCollection(HomeContract):
    status: Literal["unavailable"] = "unavailable"
    collection: Collection
    capture: Capture
    reason_code: Literal["source_unavailable", "adapter_missing", "source_contract_invalid"]
    retry_target: CollectionTarget

    @model_validator(mode="after")
    def unavailable_capture(self):
        if (
            self.capture.freshness != "unavailable"
            or self.retry_target.collection != self.collection
        ):
            raise ValueError("Unavailable capture and retry collection must match.")
        return self


CollectionResult = Annotated[
    AvailableCollection | UnavailableCollection, Field(discriminator="status")
]


class AttentionResponse(HomeContract):
    contract_version: Literal[1] = 1
    workspace_id: UUID
    runtime_epoch: UUID
    scope: HomeScope
    as_of: datetime
    source_revision: str = Field(min_length=1, max_length=128)
    next_transition_at: datetime | None = None
    supported_sources: tuple[SourceKind, ...]
    needs_action: CollectionResult
    priority_totals: dict[Literal["urgent", "overdue", "today", "review"], StrictInt] | None = None
    reason_totals: dict[ReasonCode, StrictInt] | None = None

    @model_validator(mode="after")
    def complete_live_contract(self):
        section = self.needs_action
        if section.collection != Collection.NEEDS_ACTION or section.capture.read_mode != "live":
            raise ValueError("Attention is exclusively a live Needs action read.")
        if len(self.supported_sources) != len(set(self.supported_sources)):
            raise ValueError("Supported sources must be unique.")
        if (self.as_of, self.source_revision, self.next_transition_at) != (
            section.capture.as_of,
            section.capture.source_revision,
            section.capture.next_transition_at,
        ):
            raise ValueError("Live attention envelope must match its capture.")
        target = section.view_all_target if section.status == "available" else section.retry_target
        if target.scope != self.scope:
            raise ValueError("Attention target scope must match its request.")
        if section.status == "available" and len(section.items) > 10:
            raise ValueError("Live attention preview permits at most ten rows.")
        if section.status == "available" and section.capture.freshness != "checked":
            raise ValueError("Successful live attention must be checked at its capture.")
        if section.status == "available" and set(self.supported_sources) != set(SourceKind) - {
            SourceKind.COVERAGE
        }:
            raise ValueError("A successful live check requires every action source.")
        if section.status == "unavailable" and (
            self.priority_totals is not None or self.reason_totals is not None
        ):
            raise ValueError("Unavailable attention cannot provide totals.")
        if section.status == "available" and (
            self.priority_totals is None
            or self.reason_totals is None
            or sum(self.priority_totals.values()) != section.matching_total
            or any(
                value < 0
                for value in (*self.priority_totals.values(), *self.reason_totals.values())
            )
            or any(value > section.matching_total for value in self.reason_totals.values())
        ):
            raise ValueError("Available attention requires exact priority and reason totals.")
        return self


class InventoryTarget(HomeContract):
    kind: Literal["inventory"] = "inventory"
    scope: HomeScope
    occupancy: Literal["vacant", "unknown"]
    property_state: Literal["active"] = "active"


class InventoryCount(HomeContract):
    count: StrictInt = Field(ge=0)
    target: InventoryTarget


class AvailableInventory(HomeContract):
    status: Literal["available"] = "available"
    capture: Capture
    vacant: InventoryCount
    unknown: InventoryCount

    @model_validator(mode="after")
    def occupancy_targets(self):
        if self.capture.freshness == "unavailable":
            raise ValueError("Available inventory requires available capture.")
        if self.vacant.target.occupancy != "vacant" or self.unknown.target.occupancy != "unknown":
            raise ValueError("Inventory targets must identify the counted occupancy.")
        return self


class UnavailableSummary(HomeContract):
    status: Literal["unavailable"] = "unavailable"
    capture: Capture
    reason_code: Literal["source_unavailable", "adapter_missing", "source_contract_invalid"]

    @model_validator(mode="after")
    def summary_unavailable(self):
        if self.capture.freshness != "unavailable":
            raise ValueError("Unavailable summary requires unavailable freshness.")
        return self


class MoneyTarget(HomeContract):
    kind: Literal["money_metric"] = "money_metric"
    scope: HomeScope
    metric: Literal[
        "rentReceived",
        "expensesPaid",
        "expenseRefundsReceived",
        "netRecordedExpenses",
        "operatingRemainder",
    ]
    from_on: date
    through_on: date
    property_state: Literal["all"] = "all"


class MoneyMetric(HomeContract):
    amount_minor: StrictInt
    amount: str = Field(pattern=r"^-?[0-9]+\.[0-9]{2}$")
    currency: Literal["USD"] = "USD"
    target: MoneyTarget


class AvailableMoney(HomeContract):
    status: Literal["available"] = "available"
    capture: Capture
    from_on: date
    through_on: date
    metrics: tuple[MoneyMetric, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def metric_values(self):
        if self.capture.freshness == "unavailable":
            raise ValueError("Available money requires available capture.")
        if (
            self.from_on > self.through_on
            or len({item.target.metric for item in self.metrics}) != 5
        ):
            raise ValueError("Money requires an ordered period and all five unique metrics.")
        for item in self.metrics:
            cents = item.amount_minor
            amount = f"{'-' if cents < 0 else ''}{abs(cents) // 100}.{abs(cents) % 100:02d}"
            if item.amount != amount or (item.target.from_on, item.target.through_on) != (
                self.from_on,
                self.through_on,
            ):
                raise ValueError("Money formatting and drill-down dates must match the metric.")
        return self


class HomeResponse(HomeContract):
    contract_version: Literal[1] = 1
    workspace_id: UUID
    runtime_epoch: UUID
    as_of: datetime
    source_revision: str = Field(min_length=1, max_length=128)
    scope: HomeScope
    next_transition_at: datetime | None = None
    supported_sources: tuple[SourceKind, ...]
    needs_action: CollectionResult
    waiting: CollectionResult
    upcoming: CollectionResult
    appointments: CollectionResult
    information_review: CollectionResult
    inventory: Annotated[AvailableInventory | UnavailableSummary, Field(discriminator="status")]
    money: Annotated[AvailableMoney | UnavailableSummary, Field(discriminator="status")]

    @model_validator(mode="after")
    def named_collections(self):
        if len(self.supported_sources) != len(set(self.supported_sources)):
            raise ValueError("Supported sources must be unique.")
        for name in Collection:
            section = getattr(self, name.value)
            if section.collection != name:
                raise ValueError("Named section must match its collection.")
            target = (
                section.view_all_target if section.status == "available" else section.retry_target
            )
            if target.scope != self.scope:
                raise ValueError("Section targets must retain Home scope.")
            if section.status == "available" and len(section.items) > 10:
                raise ValueError("Home previews permit at most ten rows.")
            if section.status == "available" and not COLLECTION_DEPENDENCIES[name].issubset(
                self.supported_sources
            ):
                raise ValueError("Available collections require every registered dependency.")
        if self.inventory.status == "available" and any(
            count.target.scope != self.scope
            for count in (self.inventory.vacant, self.inventory.unknown)
        ):
            raise ValueError("Inventory targets must retain Home scope.")
        if self.money.status == "available" and any(
            metric.target.scope != self.scope for metric in self.money.metrics
        ):
            raise ValueError("Money targets must retain Home scope.")
        return self


class CollectionResponse(HomeContract):
    contract_version: Literal[1] = 1
    workspace_id: UUID
    runtime_epoch: UUID
    scope: HomeScope
    supported_sources: tuple[SourceKind, ...]
    as_of: datetime
    source_revision: str = Field(min_length=1, max_length=128)
    next_transition_at: datetime | None = None
    result: CollectionResult

    @model_validator(mode="after")
    def collection_scope(self):
        if (self.as_of, self.source_revision, self.next_transition_at) != (
            self.result.capture.as_of,
            self.result.capture.source_revision,
            self.result.capture.next_transition_at,
        ):
            raise ValueError("Collection envelope must match its captured section.")
        target = (
            self.result.view_all_target
            if self.result.status == "available"
            else self.result.retry_target
        )
        if target.scope != self.scope or len(self.supported_sources) != len(
            set(self.supported_sources)
        ):
            raise ValueError("Collection scope and supported sources must be coherent.")
        if self.result.status == "available" and not COLLECTION_DEPENDENCIES[
            self.result.collection
        ].issubset(self.supported_sources):
            raise ValueError("Available collection requires every registered dependency.")
        return self
