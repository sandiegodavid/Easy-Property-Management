"""Existing Finance conflict envelope, shared by its HTTP adapters."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class FinanceConflictDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    scopeKind: Literal["rent_ledger", "expense", "deposit_account"] | None = None
    scopeId: UUID | None = None
    currentRevision: StrictInt | None = Field(default=None, ge=0)


class FinanceConflictResponse(BaseModel):
    detail: FinanceConflictDetail
