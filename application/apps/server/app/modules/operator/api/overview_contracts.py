"""Bounded metadata sections with explicit unavailable state and provenance."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator

from app.modules.finance.application.money_models import MoneySummary
from app.modules.operator.api.directory_contracts import Availability, Occupancy
from app.modules.operator.domain.models import Contract
from app.modules.operator.application.coverage_models import CoverageResult

RelationshipScope = Literal["current", "former", "all"]
SectionKind = Literal[
    "properties",
    "relationships",
    "spaces",
    "leases",
    "tasks",
    "maintenance",
    "communications",
    "concerns",
    "money",
    "coverage",
]
Priority = Literal["low", "normal", "high", "urgent"]


class EntityTarget(Contract):
    entityType: Literal[
        "property", "space", "lease", "task", "maintenance_issue", "communication", "owner_concern"
    ]
    entityId: UUID


class ContextTarget(Contract):
    subjectKind: Literal["property", "owner"]
    subjectId: UUID
    section: SectionKind
    relationshipScope: RelationshipScope
    fromOn: date | None
    throughOn: date | None


class PropertyIdentity(Contract):
    kind: Literal["property"]
    id: UUID
    displayName: str
    status: Literal["active", "archived"]
    timeZone: str
    addressLine1: str
    city: str
    countryCode: str


class OwnerIdentity(Contract):
    kind: Literal["owner"]
    id: UUID
    displayName: str
    partyKind: Literal["individual", "organization"]
    archived: StrictBool


class PropertyItem(Contract):
    id: UUID
    displayName: str
    status: Literal["active", "archived"]
    addressLine1: str
    city: str
    countryCode: str
    timeZone: str
    target: EntityTarget


class SpaceItem(Contract):
    id: UUID
    propertyId: UUID
    displayName: str
    revision: StrictInt
    occupancy: Occupancy
    availability: Availability
    needsAttention: StrictBool
    target: EntityTarget


class RelationshipItem(Contract):
    id: UUID
    propertyId: UUID
    propertyName: str
    ownerKind: Literal["client_owner", "local_operator"]
    partyId: UUID | None
    ownerName: str | None
    startsOn: date
    endsOn: date | None
    relationshipState: Literal["current", "former", "scheduled"]
    target: EntityTarget


class LeaseItem(Contract):
    id: UUID
    propertyId: UUID
    spaceId: UUID
    leaseKind: Literal["residential", "commercial"]
    status: Literal["draft", "executed", "ended", "terminated", "void"]
    contractStartsOn: date
    contractEndsOn: date | None
    occupancyStartsOn: date
    actualMoveOutOn: date | None
    isCurrent: StrictBool
    target: EntityTarget


class TaskItem(Contract):
    id: UUID
    title: str
    status: Literal["open", "in_progress", "completed", "cancelled"]
    priority: Priority
    revision: StrictInt
    dueAtUtc: AwareDatetime | None
    dueTimezone: str | None
    isAllDay: StrictBool
    waitingForKind: Literal["person", "organization", "event", "other"] | None
    waitingForLabel: str | None
    followUpAtUtc: AwareDatetime | None
    followUpTimezone: str | None
    followUpState: Literal["unscheduled", "overdue", "due", "scheduled"] | None
    followUpDueToday: StrictBool
    followUpActionable: StrictBool
    taskDeadlineState: Literal["none", "inactive", "overdue", "today", "upcoming"]
    asOf: AwareDatetime
    target: EntityTarget


class IssueItem(Contract):
    id: UUID
    propertyId: UUID
    spaceId: UUID | None
    summary: str
    status: Literal["open", "in_progress", "resolved", "cancelled"]
    priority: Priority
    category: str
    target: EntityTarget


class CommunicationItem(Contract):
    id: UUID
    subject: str
    channel: Literal["phone", "email", "sms", "in_person", "letter", "other"]
    direction: Literal["inbound", "outbound", "internal"]
    status: Literal["recorded", "superseded"]
    occurredAtUtc: AwareDatetime
    occurredTimezone: str
    target: EntityTarget


class ConcernItem(Contract):
    id: UUID
    ownerPartyId: UUID
    propertyId: UUID
    summary: str
    status: Literal["open", "in_progress", "resolved", "dismissed"]
    priority: Priority
    concernType: Literal["general_rental", "lease", "tenant", "vacancy"]
    target: EntityTarget


class SectionState(Contract):
    availability: Literal["available", "unavailable"]
    reasonCode: (
        Literal[
            "coverage_source_not_configured", "money_period_required", "source_read_unavailable"
        ]
        | None
    )
    sourceKind: Literal[
        "portfolio",
        "leases",
        "tasks",
        "maintenance",
        "communications",
        "owner_management",
        "finance",
        "operator",
    ]
    asOf: AwareDatetime
    sourceRevision: str | None
    viewAll: ContextTarget

    @model_validator(mode="after")
    def availability_state(self):
        if self.availability == "available":
            if self.reasonCode is not None or self.sourceRevision is None:
                raise ValueError("Available sections require provenance, not failure reasons.")
        elif self.reasonCode is None or self.sourceRevision is not None:
            raise ValueError("Unavailable sections require a reason, not fabricated provenance.")
        return self


class CollectionSection(SectionState):
    matchingTotal: StrictInt | None = Field(None, ge=0)
    nextCursor: str | None = None

    @model_validator(mode="after")
    def collection_state(self):
        if self.availability == "available":
            if (
                self.matchingTotal is None
                or self.items is None
                or self.matchingTotal < len(self.items)
            ):
                raise ValueError(
                    "Available collection requires a complete count and bounded slice."
                )
        elif (
            self.matchingTotal is not None or self.items is not None or self.nextCursor is not None
        ):
            raise ValueError("Unavailable collection cannot claim empty results.")
        return self


class PropertySection(CollectionSection):
    kind: Literal["properties"]
    items: list[PropertyItem] | None = Field(None, max_length=50)


class RelationshipSection(CollectionSection):
    kind: Literal["relationships"]
    items: list[RelationshipItem] | None = Field(None, max_length=50)


class SpaceSection(CollectionSection):
    kind: Literal["spaces"]
    items: list[SpaceItem] | None = Field(None, max_length=50)


class LeaseSection(CollectionSection):
    kind: Literal["leases"]
    items: list[LeaseItem] | None = Field(None, max_length=50)


class TaskSection(CollectionSection):
    kind: Literal["tasks"]
    items: list[TaskItem] | None = Field(None, max_length=50)


class IssueSection(CollectionSection):
    kind: Literal["maintenance"]
    items: list[IssueItem] | None = Field(None, max_length=50)


class CommunicationSection(CollectionSection):
    kind: Literal["communications"]
    items: list[CommunicationItem] | None = Field(None, max_length=50)


class ConcernSection(CollectionSection):
    kind: Literal["concerns"]
    items: list[ConcernItem] | None = Field(None, max_length=50)


class MoneySection(SectionState):
    kind: Literal["money"]
    summary: MoneySummary | None = None
    scopeMeaning: Literal["whole_property_activity_not_owner_entitlement"] | None = None

    @model_validator(mode="after")
    def money_state(self):
        if (self.availability == "available") != (
            self.summary is not None and self.scopeMeaning is not None
        ):
            raise ValueError("Money availability must reflect the retained source result.")
        if self.availability == "unavailable" and (
            self.summary is not None or self.scopeMeaning is not None
        ):
            raise ValueError("Unavailable money cannot retain a partial result.")
        return self


class CoverageSection(CollectionSection):
    kind: Literal["coverage"]
    items: list[CoverageResult] | None = Field(None, max_length=50)


Section = Annotated[
    PropertySection
    | RelationshipSection
    | SpaceSection
    | LeaseSection
    | TaskSection
    | IssueSection
    | CommunicationSection
    | ConcernSection
    | MoneySection
    | CoverageSection,
    Field(discriminator="kind"),
]


class OverviewResponse(Contract):
    subject: Annotated[PropertyIdentity | OwnerIdentity, Field(discriminator="kind")]
    relationshipScope: RelationshipScope
    asOf: AwareDatetime
    sourceRevision: str
    sections: dict[SectionKind, Section]
