"""Strict grouped metadata-search contract and stable generated-client operation."""

from typing import Annotated, Literal
from uuid import UUID
from fastapi import Query
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator

from app.modules.operator.domain.models import Contract
from app.platform.metadata_search import SearchTerm

SearchKind = Literal[
    "properties", "spaces", "owners", "tenants", "leases", "communications", "maintenance", "tasks"
]
EntityKind = Literal[
    "property", "space", "owner", "tenant", "lease", "communication", "maintenance_issue", "task"
]


class SearchInput(Contract):
    q: str = Field(min_length=2, max_length=240)
    includeArchived: bool = False
    limit: int = Field(10, ge=1, le=50)
    group: SearchKind | None = None
    cursor: str | None = Field(None, max_length=4096)

    @model_validator(mode="after")
    def search_shape(self):
        SearchTerm(self.q, self.includeArchived)
        if self.cursor is not None and self.group is None:
            raise ValueError("A continuation requires its search group.")
        return self


class SearchTarget(Contract):
    entityType: EntityKind
    entityId: UUID


class SearchHit(Contract):
    sourceType: EntityKind
    sourceId: UUID
    label: str = Field(max_length=1000)
    context: str = Field(max_length=2000)
    archived: StrictBool
    target: SearchTarget

    @model_validator(mode="after")
    def target_identity(self):
        if self.target.entityType != self.sourceType or self.target.entityId != self.sourceId:
            raise ValueError("Search identity and target must match.")
        return self


class SearchViewAll(Contract):
    kind: Literal["metadata_search"]
    group: SearchKind
    q: str
    includeArchived: StrictBool
    limit: StrictInt = Field(ge=1, le=50)


class SearchGroup(Contract):
    kind: SearchKind
    sourceKind: Literal["portfolio", "tenants", "leases", "communications", "maintenance", "tasks"]
    availability: Literal["available", "unavailable"]
    reasonCode: Literal["source_read_unavailable"] | None
    asOf: AwareDatetime
    sourceRevision: str | None
    matchingTotal: StrictInt | None = Field(ge=0)
    items: list[SearchHit] | None = Field(max_length=50)
    nextCursor: str | None
    viewAll: SearchViewAll

    @model_validator(mode="after")
    def group_state(self):
        if self.kind != self.viewAll.group:
            raise ValueError("Search continuation target must match its group.")
        if self.availability == "available":
            if (
                self.reasonCode is not None
                or self.sourceRevision is None
                or self.matchingTotal is None
                or self.items is None
                or self.matchingTotal < len(self.items)
            ):
                raise ValueError("Available search requires count, slice and provenance.")
        elif self.reasonCode is None or any(
            value is not None
            for value in (self.sourceRevision, self.matchingTotal, self.items, self.nextCursor)
        ):
            raise ValueError("Unavailable search must not fabricate results.")
        return self


class SearchEcho(Contract):
    q: str
    normalizedQ: str
    includeArchived: StrictBool
    group: SearchKind | None
    limit: StrictInt


class SearchResponse(Contract):
    query: SearchEcho
    asOf: AwareDatetime
    sourceRevision: str
    groups: dict[SearchKind, SearchGroup]

    @model_validator(mode="after")
    def group_identity(self):
        if any(key != group.kind or group.asOf != self.asOf for key, group in self.groups.items()):
            raise ValueError("Search groups must share the captured response identity and instant.")
        if any(
            group.availability == "available" and group.sourceRevision != self.sourceRevision
            for group in self.groups.values()
        ):
            raise ValueError("Available search groups must share the source revision.")
        return self


def register_search(router, service, invoke):
    @router.get("/search", response_model=SearchResponse, operation_id="searchOperatorMetadata")
    def search(query: Annotated[SearchInput, Query()]):
        return invoke(
            lambda: service.search(
                query.q,
                include_archived=query.includeArchived,
                limit=query.limit,
                group=query.group,
                cursor=query.cursor,
            )
        )
