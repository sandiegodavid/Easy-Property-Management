"""Domain values for the manual communication ledger."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Communication:
    id: str
    direction: str
    channel: str
    subject: str
    body: str
    occurred_at_utc: str
    occurred_timezone: str
    status: str
    recorded_at: str | None
    supersedes_communication_id: str | None
    superseded_by_communication_id: str | None
    correction_reason: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "direction": self.direction, "channel": self.channel,
            "subject": self.subject, "body": self.body,
            "occurredAtUtc": self.occurred_at_utc,
            "occurredTimezone": self.occurred_timezone, "status": self.status,
            "recordedAt": self.recorded_at,
            "supersedesCommunicationId": self.supersedes_communication_id,
            "supersededByCommunicationId": self.superseded_by_communication_id,
            "correctionReason": self.correction_reason,
            "createdAt": self.created_at, "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class CommunicationParticipant:
    id: str
    communication_id: str
    party_id: str
    party_contact_method_id: str | None
    role: str
    party_display_name_snapshot: str
    contact_display_snapshot: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "communicationId": self.communication_id,
            "partyId": self.party_id, "partyContactMethodId": self.party_contact_method_id,
            "role": self.role, "partyDisplayName": self.party_display_name_snapshot,
            "contactDisplayValue": self.contact_display_snapshot,
        }


@dataclass(frozen=True)
class CommunicationLink:
    id: str
    communication_id: str
    entity_type: str
    entity_id: str
    property_timezone_snapshot: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "communicationId": self.communication_id,
            "entityType": self.entity_type, "entityId": self.entity_id,
            "propertyTimezoneSnapshot": self.property_timezone_snapshot,
        }


@dataclass(frozen=True)
class CommunicationOperation:
    id: str
    target_communication_id: str | None
    result_communication_id: str | None
    action: str
    idempotency_key: str
    request_fingerprint: str
    correlation_id: str
    created_at: str
    follow_up_task_id: str | None
