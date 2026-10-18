"""Shared masked document fields; owning profiles declare their document types."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class MaskedIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuingCountry: str = Field(pattern=r"^[A-Z]{2}$")
    lastFour: str = Field(pattern=r"^[A-Za-z0-9]{4}$")
    issuingRegion: str | None = Field(None, pattern=r"^[A-Z0-9-]{1,10}$")
    expiresOn: date | None = None
