"""Portable tenant contact values."""

from dataclasses import dataclass
from app.modules.parties.domain.official_ids import OfficialId


@dataclass(frozen=True)
class TenantProfile:
    party_id: str
    preferred_contact_method_id: str | None
    do_not_contact: bool
    notes: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    revision: int = 1
    official_ids: tuple[OfficialId, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "partyId": self.party_id,
            "preferredContactMethodId": self.preferred_contact_method_id,
            "doNotContact": self.do_not_contact,
            "notes": self.notes,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
            "revision": self.revision,
            "officialIds": [item.to_dict() for item in self.official_ids],
        }
