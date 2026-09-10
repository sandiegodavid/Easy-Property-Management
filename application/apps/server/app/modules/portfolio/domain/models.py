"""Portable PORT-001 values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.parties.domain.models import Party


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
    time_zone: str
    notes: str | None
    status: str
    created_at: str
    updated_at: str
    archived_at: str | None
    property_type: str
    inventory_layout: str

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
            "timeZone": self.time_zone,
            "notes": self.notes,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
            "propertyType": self.property_type,
            "inventoryLayout": self.inventory_layout,
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


@dataclass(frozen=True)
class Space:
    id: str
    property_id: str
    space_kind: str
    display_name: str
    normalized_name: str
    suite_or_floor: str | None
    notes: str | None
    status: str
    created_at: str
    updated_at: str
    archived_at: str | None
    archived_by_property_operation_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "propertyId": self.property_id,
            "spaceKind": self.space_kind,
            "displayName": self.display_name,
            "suiteOrFloor": self.suite_or_floor,
            "notes": self.notes,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
        }


@dataclass(frozen=True)
class SpaceOccupancyPeriod:
    id: str
    space_id: str
    occupancy_status: str
    starts_on: str
    ends_on: str | None
    record_state: str
    superseded_by_id: str | None
    source_kind: str
    source_id: str | None
    note: str | None
    created_at: str
    ended_at: str | None
    cancelled_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "spaceId": self.space_id,
            "occupancyStatus": self.occupancy_status,
            "startsOn": self.starts_on,
            "endsOn": self.ends_on,
            "recordState": self.record_state,
            "supersededById": self.superseded_by_id,
            "sourceKind": self.source_kind,
            "sourceId": self.source_id,
            "note": self.note,
            "createdAt": self.created_at,
            "endedAt": self.ended_at,
            "cancelledAt": self.cancelled_at,
        }


@dataclass(frozen=True)
class SpaceAvailability:
    space_id: str
    availability_status: str
    available_on: str | None
    source_kind: str
    source_id: str | None
    note: str | None
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "spaceId": self.space_id,
            "availabilityStatus": self.availability_status,
            "availableOn": self.available_on,
            "sourceKind": self.source_kind,
            "sourceId": self.source_id,
            "note": self.note,
            "updatedAt": self.updated_at,
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
