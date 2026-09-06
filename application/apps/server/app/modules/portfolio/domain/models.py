"""Portable PORT-001 values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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


@dataclass(frozen=True)
class Property:
    id: str
    display_name: str
    address_line_1: str
    address_line_2: str | None
    city: str
    region: str | None
    postal_code: str | None
    country_code: str
    notes: str | None
    status: str
    created_at: str
    updated_at: str
    archived_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "addressLine1": self.address_line_1,
            "addressLine2": self.address_line_2,
            "city": self.city,
            "region": self.region,
            "postalCode": self.postal_code,
            "countryCode": self.country_code,
            "notes": self.notes,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
        }


@dataclass(frozen=True)
class PropertyOwnership:
    id: str
    property_id: str
    owner_kind: str
    party_id: str | None
    starts_on: str
    ends_on: str | None
    created_at: str
    ended_at: str | None

    def to_dict(self, party: Party | None = None) -> dict[str, object]:
        return {
            "id": self.id,
            "propertyId": self.property_id,
            "ownerKind": self.owner_kind,
            "partyId": self.party_id,
            "party": None if party is None else party.to_dict(),
            "startsOn": self.starts_on,
            "endsOn": self.ends_on,
            "createdAt": self.created_at,
            "endedAt": self.ended_at,
        }


def ownership_context(ownerships: list[PropertyOwnership]) -> str:
    local = any(item.owner_kind == "local_operator" for item in ownerships)
    client = any(item.owner_kind == "client_owner" for item in ownerships)
    if local and client:
        return "mixed"
    if local:
        return "self_owned"
    if client:
        return "managed_for_owner"
    raise ValueError("An active property requires an active ownership relationship.")


def active_on(ownership: PropertyOwnership, when: date) -> bool:
    day = when.isoformat()
    return ownership.starts_on <= day and (
        ownership.ends_on is None or ownership.ends_on > day
    )
