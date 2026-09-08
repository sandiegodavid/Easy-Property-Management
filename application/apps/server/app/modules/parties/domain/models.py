"""Shared identities used by portfolio, tenant, vendor, and lease roles."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Party:
    id: str
    party_kind: str
    display_name: str
    email: str | None
    phone: str | None
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "partyKind": self.party_kind,
            "displayName": self.display_name,
            "email": self.email,
            "phone": self.phone,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
        }
