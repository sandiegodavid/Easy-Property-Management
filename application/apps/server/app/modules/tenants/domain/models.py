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


@dataclass(frozen=True)
class TenantContactMethod:
    id: str
    party_id: str
    method_kind: str
    display_value: str
    normalized_value: str
    label: str | None
    status: str
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "partyId": self.party_id, "methodKind": self.method_kind,
                "displayValue": self.display_value, "label": self.label, "status": self.status,
                "createdAt": self.created_at, "updatedAt": self.updated_at, "archivedAt": self.archived_at}

    def to_audit_dict(self) -> dict[str, object]:
        """Retain normalized lookup state in the protected append-only ledger."""
        return {**self.to_dict(), "normalizedValue": self.normalized_value}
