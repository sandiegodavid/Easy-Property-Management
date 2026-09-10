"""Shared identities used by portfolio, tenant, vendor, and lease roles."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Party:
    id: str
    party_kind: str
    display_name: str
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "partyKind": self.party_kind,
            "displayName": self.display_name,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
        }


@dataclass(frozen=True)
class PartyContactMethod:
    id: str
    party_id: str
    method_kind: str
    display_value: str
    normalized_value: str
    extension: str | None
    label: str | None
    status: str
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "partyId": self.party_id, "methodKind": self.method_kind,
                "displayValue": self.display_value, "extension": self.extension,
                "label": self.label, "status": self.status, "createdAt": self.created_at,
                "updatedAt": self.updated_at, "archivedAt": self.archived_at}

    def to_audit_dict(self) -> dict[str, object]:
        return {**self.to_dict(), "normalizedValue": self.normalized_value}
