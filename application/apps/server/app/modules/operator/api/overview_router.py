"""Typed subject overviews and independent section continuations."""

from datetime import date
from typing import Annotated
from uuid import UUID
from fastapi import Query
from pydantic import Field

from app.modules.operator.api.overview_contracts import (
    OverviewResponse,
    RelationshipScope,
    SectionKind,
)
from app.modules.operator.domain.models import Contract


class OverviewInput(Contract):
    relationshipScope: RelationshipScope = "current"
    fromOn: date | None = None
    throughOn: date | None = None
    sectionLimit: int = Field(10, ge=1, le=50)
    section: SectionKind | None = None
    cursor: str | None = Field(None, max_length=4096)


def register_overviews(router, service, invoke):
    def read(kind, subject_id, query):
        return invoke(
            lambda: service.overview(
                kind,
                str(subject_id),
                relationship_scope=query.relationshipScope,
                from_on=query.fromOn.isoformat() if query.fromOn else None,
                through_on=query.throughOn.isoformat() if query.throughOn else None,
                limit=query.sectionLimit,
                section=query.section,
                cursor=query.cursor,
            )
        )

    @router.get(
        "/properties/{subject_id}/overview",
        response_model=OverviewResponse,
        operation_id="getOperatorPropertyOverview",
    )
    def property_overview(subject_id: UUID, query: Annotated[OverviewInput, Query()]):
        return read("property", subject_id, query)

    @router.get(
        "/owners/{subject_id}/overview",
        response_model=OverviewResponse,
        operation_id="getOperatorOwnerOverview",
    )
    def owner_overview(subject_id: UUID, query: Annotated[OverviewInput, Query()]):
        return read("owner", subject_id, query)
