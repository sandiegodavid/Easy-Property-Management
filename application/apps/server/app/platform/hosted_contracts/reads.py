"""Bounded continuation and freshness context, independent of cursor encoding."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictStr, field_validator, model_validator

from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    EpochMillis,
    Reference,
    RequestHash,
    Revision,
    SafeCode,
    Scope,
)


class FreshnessState(StrEnum):
    KNOWN = "known"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class Freshness(Contract):
    state: FreshnessState
    as_of: EpochMillis | None = None
    source_revision: Reference | None = None
    error_code: SafeCode | None = None

    @model_validator(mode="after")
    def valid_freshness(self):
        if self.state in {FreshnessState.KNOWN, FreshnessState.STALE}:
            if self.as_of is None or self.source_revision is None:
                raise ValueError("Known/stale observations require capture and source revision.")
        elif self.as_of is not None or self.source_revision is not None or self.error_code is None:
            raise ValueError(
                "Unknown/unavailable observations require a reason, not invented facts."
            )
        if self.state == FreshnessState.KNOWN and self.error_code is not None:
            raise ValueError("A known observation cannot claim a source error.")
        return self


class CursorContext(Contract):
    deployment_id: CanonicalId
    scope: Scope
    endpoint: SafeCode
    filter_hash: RequestHash
    as_of: EpochMillis
    source_revision: Reference
    ordering_version: Revision


class ContinuationCursor(Contract):
    version: Literal[1] = 1
    context: CursorContext
    position: Annotated[
        tuple[Annotated[StrictStr, Field(min_length=1, max_length=1024)], ...],
        Field(min_length=1, max_length=8),
    ]
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 50

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("Cursor version must be an integer.")
        return value

    def require_context(self, expected: CursorContext) -> None:
        if self.context != expected:
            raise ValueError("The collection context changed; restart with the current filters.")
