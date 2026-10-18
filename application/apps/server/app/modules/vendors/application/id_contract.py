"""Bounded provider-owned identification contracts."""

from typing import Literal

from pydantic import Field, model_validator

from app.modules.parties.application.id_contract import MaskedIdInput
from app.modules.vendors.domain.official_ids import ProviderOfficialId


class ProviderOfficialIdInput(MaskedIdInput):
    documentType: Literal[
        "license", "passport", "drivers_license", "state_id", "national_id", "business_registration"
    ]
    documentNumber: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{0,79}$")

    @model_validator(mode="after")
    def validate_document_number(self):
        ProviderOfficialId(
            self.documentType,
            self.issuingCountry,
            self.lastFour,
            self.issuingRegion,
            self.expiresOn.isoformat() if self.expiresOn else None,
            self.documentNumber,
        )
        return self
