"""Portable provider-directory records."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    party_id: str
    selection_status: str
    selection_reason: str | None
    notes: str | None
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "partyId": self.party_id,
            "selectionStatus": self.selection_status,
            "selectionReason": self.selection_reason,
            "notes": self.notes,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
        }


@dataclass(frozen=True)
class ProviderService:
    id: str
    party_id: str
    display_name: str
    normalized_name: str
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "partyId": self.party_id, "displayName": self.display_name,
            "normalizedName": self.normalized_name, "createdAt": self.created_at,
            "updatedAt": self.updated_at, "archivedAt": self.archived_at,
        }


@dataclass(frozen=True)
class ProviderServiceArea:
    id: str
    party_id: str
    display_name: str
    normalized_name: str
    country_code: str
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "partyId": self.party_id, "displayName": self.display_name,
            "normalizedName": self.normalized_name,
            "countryCode": self.country_code or None, "createdAt": self.created_at,
            "updatedAt": self.updated_at, "archivedAt": self.archived_at,
        }


@dataclass(frozen=True)
class ProviderWorkHistory:
    id: str
    party_id: str
    property_id: str | None
    performed_on: str
    summary: str
    outcome_notes: str | None
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "partyId": self.party_id, "propertyId": self.property_id,
            "performedOn": self.performed_on, "summary": self.summary,
            "outcomeNotes": self.outcome_notes, "createdAt": self.created_at,
            "updatedAt": self.updated_at, "archivedAt": self.archived_at,
        }


@dataclass(frozen=True)
class ProviderReference:
    id: str
    party_id: str
    reference_name: str | None
    organization_name: str | None
    relationship: str | None
    email: str | None
    phone: str | None
    notes: str | None
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "partyId": self.party_id,
            "referenceName": self.reference_name, "organizationName": self.organization_name,
            "relationship": self.relationship, "email": self.email, "phone": self.phone,
            "notes": self.notes, "createdAt": self.created_at,
            "updatedAt": self.updated_at, "archivedAt": self.archived_at,
        }
