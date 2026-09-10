"""Portable tenant contact values."""

from dataclasses import dataclass

@dataclass(frozen=True)
class TenantProfile:
    party_id: str
    preferred_contact_method_id: str | None
    do_not_contact: bool
    notes: str | None
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {"partyId": self.party_id, "preferredContactMethodId": self.preferred_contact_method_id,
                "doNotContact": self.do_not_contact, "notes": self.notes, "createdAt": self.created_at,
                "updatedAt": self.updated_at, "archivedAt": self.archived_at}
