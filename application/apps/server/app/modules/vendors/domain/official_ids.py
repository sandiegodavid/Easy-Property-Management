"""Provider identification includes occupational licenses as well as personal IDs."""

from dataclasses import dataclass
import re

from app.modules.parties.domain.official_ids import OfficialId


@dataclass(frozen=True)
class ProviderOfficialId(OfficialId):
    document_types = OfficialId.document_types | {"license"}
    api_fields = OfficialId.api_fields | {"documentNumber": "document_number"}
    document_number: str | None = None

    def __post_init__(self):
        super().__post_init__()
        number = self.document_number
        if number is not None and (
            not isinstance(number, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ./_-]{0,79}", number)
            or number != number.strip()
            or re.sub(r"[^A-Za-z0-9]", "", number)[-4:].upper() != self.last_four.upper()
        ):
            raise ValueError(
                "An ID number must be bounded to 80 letters, digits or separators; its last four characters must match the masked ID."
            )

    def to_dict(self):
        return {**super().to_dict(), "documentNumber": self.document_number}
