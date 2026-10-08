"""Enumerated, bounded property directory query contract."""

from typing import Annotated

from fastapi import Query
from pydantic import Field

from app.modules.operator.api.directory_contracts import (
    Availability,
    Occupancy,
    OwnershipContext,
    PropertyDirectoryPage,
    PropertyState,
    OwnerDirectoryPage,
)
from app.modules.operator.domain.models import Contract
from app.modules.operator.api.overview_contracts import RelationshipScope


class OwnerDirectoryInput(Contract):
    q: str = Field("", max_length=240)
    archiveState: PropertyState = "active"
    relationshipScope: RelationshipScope = "current"
    propertyState: PropertyState = "active"
    limit: int = Field(50, ge=1, le=100)
    cursor: str | None = Field(None, max_length=4096)


class PropertyDirectoryInput(Contract):
    q: str = Field("", max_length=240)
    status: PropertyState = "active"
    ownershipContext: OwnershipContext | None = None
    occupancy: Occupancy | None = None
    availability: Availability | None = None
    needsAttention: bool | None = None
    limit: int = Field(50, ge=1, le=100)
    cursor: str | None = Field(None, max_length=4096)


def register_directory(router, service, invoke):
    @router.get("/owners", response_model=OwnerDirectoryPage, operation_id="getOperatorOwners")
    def owners(query: Annotated[OwnerDirectoryInput, Query()]):
        return invoke(
            lambda: service.owners(
                text=query.q,
                archive_state=query.archiveState,
                relationship_scope=query.relationshipScope,
                property_state=query.propertyState,
                limit=query.limit,
                cursor=query.cursor,
            )
        )

    @router.get(
        "/properties", response_model=PropertyDirectoryPage, operation_id="getOperatorProperties"
    )
    def properties(query: Annotated[PropertyDirectoryInput, Query()]):
        return invoke(
            lambda: service.properties(
                text=query.q,
                status=query.status,
                ownership_context=query.ownershipContext,
                occupancy=query.occupancy,
                availability=query.availability,
                needs_attention=query.needsAttention,
                limit=query.limit,
                cursor=query.cursor,
            )
        )
