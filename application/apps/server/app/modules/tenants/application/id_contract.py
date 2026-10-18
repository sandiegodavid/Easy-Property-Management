"""Shared typed masked-ID input for HTTP and recoverable forms."""

from typing import Literal

from app.modules.parties.application.id_contract import MaskedIdInput


class OfficialIdRequest(MaskedIdInput):
    documentType: Literal[
        "passport", "drivers_license", "state_id", "national_id", "business_registration"
    ]
