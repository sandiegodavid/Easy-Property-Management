"""Bounded masked-ID primitives shared by profile owners."""

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import ClassVar


@dataclass(frozen=True)
class OfficialId:
    document_types: ClassVar[frozenset[str]] = frozenset(
        {"passport", "drivers_license", "state_id", "national_id", "business_registration"}
    )
    api_fields: ClassVar[dict[str, str]] = {
        "documentType": "document_type",
        "issuingCountry": "issuing_country",
        "lastFour": "last_four",
        "issuingRegion": "issuing_region",
        "expiresOn": "expires_on",
    }
    document_type: str
    issuing_country: str
    last_four: str
    issuing_region: str | None = None
    expires_on: str | None = None

    def __post_init__(self):
        if self.document_type not in self.document_types:
            raise ValueError("Choose a supported official ID type.")
        if not isinstance(self.issuing_country, str) or not re.fullmatch(
            r"[A-Z]{2}", self.issuing_country
        ):
            raise ValueError("Issuing country must be a two-letter uppercase country code.")
        if not isinstance(self.last_four, str) or not re.fullmatch(
            r"[A-Za-z0-9]{4}", self.last_four
        ):
            raise ValueError(
                "Enter only the last four letters or digits, never the full ID number."
            )
        if self.issuing_region is not None and (
            not isinstance(self.issuing_region, str)
            or not re.fullmatch(r"[A-Z0-9-]{1,10}", self.issuing_region)
        ):
            raise ValueError(
                "Issuing state or region must contain 1–10 uppercase letters or digits."
            )
        if self.expires_on is not None and (
            not isinstance(self.expires_on, str)
            or date.fromisoformat(self.expires_on).isoformat() != self.expires_on
        ):
            raise ValueError("ID expiration must be an ISO date.")

    def to_dict(self):
        return {
            "documentType": self.document_type,
            "issuingCountry": self.issuing_country,
            "lastFour": self.last_four,
            "issuingRegion": self.issuing_region,
            "expiresOn": self.expires_on,
        }


def official_ids(values: object, definition=OfficialId) -> tuple[OfficialId, ...]:
    if not isinstance(values, (list, tuple)) or len(values) > 10:
        raise ValueError("Record at most ten official IDs.")
    result = tuple(item if isinstance(item, definition) else definition(**item) for item in values)
    identities = [
        (item.document_type, item.issuing_country, item.issuing_region, item.last_four)
        for item in result
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("The same masked official ID cannot be recorded twice.")
    return result


def official_ids_from_api(values: object, definition=OfficialId) -> tuple[OfficialId, ...]:
    if not isinstance(values, list):
        raise ValueError("Official IDs must be a list.")
    names = definition.api_fields
    return official_ids(
        [{names[key]: value for key, value in item.items()} for item in values], definition
    )


def stored_ids(values: tuple[OfficialId, ...]):
    return [asdict(item) for item in values]
