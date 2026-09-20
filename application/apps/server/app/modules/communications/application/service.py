"""COM-001 workflows.  All state changes go through one transaction port."""

from __future__ import annotations

import hashlib
import json
import base64
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.communications.application.ports import CommunicationTransaction, CommunicationUnitOfWork
from app.modules.communications.domain.models import Communication, CommunicationLink, CommunicationOperation, CommunicationParticipant

DIRECTIONS = frozenset({"inbound", "outbound", "internal"})
CHANNELS = frozenset({"phone", "email", "sms", "in_person", "letter", "other"})
PARTICIPANT_ROLES = frozenset({"sender", "recipient", "reporter", "other"})
LINK_TYPES = frozenset({"party", "property", "space", "lease", "rent_expectation", "rent_receipt", "renewal_option", "task", "maintenance_issue"})


class CommunicationError(ValueError):
    code = "communication_validation"


class CommunicationNotFoundError(CommunicationError):
    code = "communication_not_found"


class CommunicationConflictError(CommunicationError):
    def __init__(self, message: str, code: str = "communication_conflict") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParticipantInput:
    party_id: str
    role: str
    party_contact_method_id: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.party_id, "partyId")
        if self.party_contact_method_id is not None:
            _uuid(self.party_contact_method_id, "partyContactMethodId")
        if self.role not in PARTICIPANT_ROLES:
            raise CommunicationError("Participant role is invalid.")


@dataclass(frozen=True)
class LinkInput:
    entity_type: str
    entity_id: str

    def __post_init__(self) -> None:
        if self.entity_type not in LINK_TYPES:
            raise CommunicationError("Communication link type is unsupported.")
        _uuid(self.entity_id, "entityId")


@dataclass(frozen=True)
class FollowUpInput:
    title: str
    notes: str | None = None
    due_at_utc: str | None = None
    due_timezone: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not (title := self.title.strip()) or len(title) > 240:
            raise CommunicationError("Follow-up title must contain 1 to 240 characters.")
        object.__setattr__(self, "title", title)
        if self.notes is not None and (not isinstance(self.notes, str) or len(self.notes) > 10_000):
            raise CommunicationError("Follow-up notes are invalid.")
        if self.due_at_utc is not None:
            _instant(self.due_at_utc, "dueAtUtc")
            if not isinstance(self.due_timezone, str):
                raise CommunicationError("A follow-up due time requires dueTimezone.")
            _zone(self.due_timezone)


@dataclass(frozen=True)
class CommunicationCommand:
    direction: str
    channel: str
    subject: str
    body: str
    occurred_at_utc: str
    occurred_timezone: str
    participants: tuple[ParticipantInput, ...]
    links: tuple[LinkInput, ...] = ()
    follow_up: FollowUpInput | None = None
    record: bool = False

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS or self.channel not in CHANNELS:
            raise CommunicationError("Direction or channel is invalid.")
        object.__setattr__(self, "subject", _text(self.subject, "subject", 240))
        object.__setattr__(self, "body", _text(self.body, "body", 10_000))
        _instant(self.occurred_at_utc, "occurredAtUtc"); _zone(self.occurred_timezone)
        if not isinstance(self.participants, tuple) or not self.participants:
            raise CommunicationError("At least one participant is required.")
        if any(not isinstance(item, ParticipantInput) for item in self.participants):
            raise CommunicationError("Participants are invalid.")
        if any(not isinstance(item, LinkInput) for item in self.links):
            raise CommunicationError("Links are invalid.")
        if self.follow_up is not None and not isinstance(self.follow_up, FollowUpInput):
            raise CommunicationError("Follow-up is invalid.")
        if not isinstance(self.record, bool):
            raise CommunicationError("record must be a boolean.")


@dataclass(frozen=True)
class PatchCommand:
    subject: str | None = None
    body: str | None = None
    occurred_at_utc: str | None = None
    occurred_timezone: str | None = None
    participants: tuple[ParticipantInput, ...] | None = None
    links: tuple[LinkInput, ...] | None = None

    def __post_init__(self) -> None:
        if self.subject is not None: object.__setattr__(self, "subject", _text(self.subject, "subject", 240))
        if self.body is not None: object.__setattr__(self, "body", _text(self.body, "body", 10_000))
        if self.occurred_at_utc is not None: _instant(self.occurred_at_utc, "occurredAtUtc")
        if self.occurred_timezone is not None: _zone(self.occurred_timezone)
        if self.participants is not None and (not self.participants or any(not isinstance(x, ParticipantInput) for x in self.participants)):
            raise CommunicationError("At least one valid participant is required.")
        if self.links is not None and any(not isinstance(x, LinkInput) for x in self.links):
            raise CommunicationError("Links are invalid.")


class CommunicationService:
    def __init__(self, unit_of_work: CommunicationUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def create(self, command: CommunicationCommand, idempotency_key: str) -> dict[str, object]:
        _uuid(idempotency_key, "idempotencyKey")
        fingerprint = _fingerprint("created", None, command)
        now = _now(); correlation_id = str(uuid4())
        communication = Communication(str(uuid4()), command.direction, command.channel, command.subject, command.body,
            _utc(command.occurred_at_utc), command.occurred_timezone, "recorded" if command.record else "draft",
            now if command.record else None, None, None, None, now, now)

        def operation(tx: CommunicationTransaction) -> dict[str, object]:
            prior = self._idempotent(tx, idempotency_key, fingerprint)
            if prior: return self._view(tx, prior.result_communication_id or prior.target_communication_id or "")
            participants, links, zones = self._validated_children(tx, communication.id, command.participants, command.links)
            self._validate_timezone(communication.occurred_timezone, zones)
            tx.insert_communication(communication)
            for item in participants: tx.insert_participant(item)
            for item in links: tx.insert_link(item)
            self._audit_created(tx, communication, participants, links, correlation_id)
            if command.record:
                tx.record_change(entity_type="communication", entity_id=communication.id, action="recorded",
                    before={**communication.to_dict(), "status": "draft", "recordedAt": None}, after=communication.to_dict(),
                    reason="communication_recorded", correlation_id=correlation_id)
            follow_up_task_id = None
            if command.follow_up:
                task = tx.create_follow_up(communication=communication, title=command.follow_up.title, notes=command.follow_up.notes,
                    due_at_utc=command.follow_up.due_at_utc, due_timezone=command.follow_up.due_timezone, correlation_id=correlation_id)
                task_id = str(task["id"])
                follow_up_task_id = task_id
                tx.record_change(entity_type="task", entity_id=task_id, action="created", before=None, after=task,
                    reason="communication_follow_up", correlation_id=correlation_id)
                tx.record_change(entity_type="communication", entity_id=communication.id, action="follow_up_created",
                    before=None, after={"taskId": task_id}, reason="communication_follow_up", correlation_id=correlation_id)
            tx.insert_operation(CommunicationOperation(str(uuid4()), None, communication.id, "created", idempotency_key, fingerprint, correlation_id, now, follow_up_task_id))
            return self._view(tx, communication.id)
        return self.unit_of_work.write(operation)

    def record(self, communication_id: str, follow_up: FollowUpInput | None, idempotency_key: str) -> dict[str, object]:
        _uuid(communication_id, "communicationId"); _uuid(idempotency_key, "idempotencyKey")
        fingerprint = _fingerprint("recorded", communication_id, follow_up)
        def operation(tx: CommunicationTransaction) -> dict[str, object]:
            prior = self._idempotent(tx, idempotency_key, fingerprint)
            if prior: return self._view(tx, prior.result_communication_id or communication_id)
            current = self._require(tx, communication_id)
            if current.status != "draft": raise CommunicationConflictError("Only drafts can be recorded.", "draft_required")
            # A draft is only a proposal: participant/contact eligibility is checked again
            # immediately before immutable history is created.
            for participant in tx.participants(current.id):
                tx.validate_participant(participant.party_id, participant.party_contact_method_id)
            now = _now(); correlation_id = str(uuid4()); updated = replace(current, status="recorded", recorded_at=now, updated_at=now)
            links, zones = self._refresh_link_snapshots(tx, tx.links(current.id), correlation_id)
            self._validate_timezone(updated.occurred_timezone, zones)
            tx.replace_communication(updated)
            tx.record_change(entity_type="communication", entity_id=current.id, action="recorded", before=current.to_dict(), after=updated.to_dict(), reason="communication_recorded", correlation_id=correlation_id)
            follow_up_task_id = None
            if follow_up:
                task = tx.create_follow_up(communication=updated, title=follow_up.title, notes=follow_up.notes, due_at_utc=follow_up.due_at_utc, due_timezone=follow_up.due_timezone, correlation_id=correlation_id)
                task_id = str(task["id"])
                follow_up_task_id = task_id
                tx.record_change(entity_type="task", entity_id=task_id, action="created", before=None, after=task,
                    reason="communication_follow_up", correlation_id=correlation_id)
                tx.record_change(entity_type="communication", entity_id=current.id, action="follow_up_created", before=None, after={"taskId": task_id}, reason="communication_follow_up", correlation_id=correlation_id)
            tx.insert_operation(CommunicationOperation(str(uuid4()), current.id, current.id, "recorded", idempotency_key, fingerprint, correlation_id, now, follow_up_task_id))
            return self._view(tx, current.id)
        return self.unit_of_work.write(operation)

    def patch(self, communication_id: str, command: PatchCommand, idempotency_key: str) -> dict[str, object]:
        _uuid(communication_id, "communicationId"); _uuid(idempotency_key, "idempotencyKey")
        fingerprint = _fingerprint("patched", communication_id, command)
        def operation(tx: CommunicationTransaction) -> dict[str, object]:
            prior = self._idempotent(tx, idempotency_key, fingerprint)
            if prior: return self._view(tx, communication_id)
            current = self._require(tx, communication_id)
            if current.status != "draft": raise CommunicationConflictError("Only drafts can be edited.", "draft_required")
            if command == PatchCommand(): return self._view(tx, current.id)
            updated = replace(current, subject=command.subject if command.subject is not None else current.subject,
                body=command.body if command.body is not None else current.body,
                occurred_at_utc=_utc(command.occurred_at_utc) if command.occurred_at_utc else current.occurred_at_utc,
                occurred_timezone=command.occurred_timezone or current.occurred_timezone, updated_at=_now())
            old_participants = tx.participants(current.id); old_links = tx.links(current.id)
            participants = old_participants if command.participants is None else self._validated_children(tx, current.id, command.participants, ())[0]
            links = old_links if command.links is None else self._validated_children(tx, current.id, (), command.links)[1]
            correlation_id = str(uuid4())
            if command.links is None:
                links, zones = self._refresh_link_snapshots(tx, links, correlation_id)
            else:
                zones = [item.property_timezone_snapshot for item in links]
            self._validate_timezone(updated.occurred_timezone, zones)
            tx.replace_communication(updated)
            tx.record_change(entity_type="communication", entity_id=current.id, action="updated", before=current.to_dict(), after=updated.to_dict(), reason="communication_updated", correlation_id=correlation_id)
            if command.participants is not None:
                tx.delete_participants(current.id)
                for item in old_participants: tx.record_change(entity_type="communication_participant", entity_id=item.id, action="deleted", before=item.to_dict(), after=None, reason="communication_participant_replaced", correlation_id=correlation_id)
                for item in participants:
                    tx.insert_participant(item); tx.record_change(entity_type="communication_participant", entity_id=item.id, action="created", before=None, after=item.to_dict(), reason="communication_participant_replaced", correlation_id=correlation_id)
            if command.links is not None:
                tx.delete_links(current.id)
                for item in old_links: tx.record_change(entity_type="communication_link", entity_id=item.id, action="deleted", before=item.to_dict(), after=None, reason="communication_link_replaced", correlation_id=correlation_id)
                for item in links:
                    tx.insert_link(item); tx.record_change(entity_type="communication_link", entity_id=item.id, action="created", before=None, after=item.to_dict(), reason="communication_link_replaced", correlation_id=correlation_id)
            tx.insert_operation(CommunicationOperation(str(uuid4()), current.id, current.id, "patched", idempotency_key, fingerprint, correlation_id, _now(), None))
            return self._view(tx, current.id)
        return self.unit_of_work.write(operation)

    def correct(self, source_id: str, command: CommunicationCommand, correction_reason: str, idempotency_key: str) -> dict[str, object]:
        _uuid(source_id, "communicationId"); _uuid(idempotency_key, "idempotencyKey")
        reason = _text(correction_reason, "correctionReason", 1000)
        fingerprint = _fingerprint("corrected", source_id, (command, reason)); now = _now(); correlation_id = str(uuid4())
        def operation(tx: CommunicationTransaction) -> dict[str, object]:
            prior = self._idempotent(tx, idempotency_key, fingerprint)
            if prior: return self._view(tx, prior.result_communication_id or "")
            source = self._require(tx, source_id)
            if source.status != "recorded" or source.superseded_by_communication_id:
                raise CommunicationConflictError("Only a current recorded communication can be corrected.", "correction_conflict")
            replacement = Communication(str(uuid4()), command.direction, command.channel, command.subject, command.body,
                _utc(command.occurred_at_utc), command.occurred_timezone, "recorded", now, source.id, None, reason, now, now)
            participants, links, zones = self._validated_children(tx, replacement.id, command.participants, command.links)
            self._validate_timezone(replacement.occurred_timezone, zones)
            superseded = replace(source, status="superseded", superseded_by_communication_id=replacement.id, updated_at=now)
            # Insert the child first so the source's forward foreign key is never dangling.
            tx.insert_communication(replacement); tx.replace_communication(superseded)
            for item in participants: tx.insert_participant(item)
            for item in links: tx.insert_link(item)
            tx.record_change(entity_type="communication", entity_id=source.id, action="superseded", before=source.to_dict(), after=superseded.to_dict(), reason="communication_corrected", correlation_id=correlation_id)
            self._audit_created(tx, replacement, participants, links, correlation_id)
            follow_up_task_id = None
            if command.follow_up:
                task = tx.create_follow_up(communication=replacement, title=command.follow_up.title, notes=command.follow_up.notes,
                    due_at_utc=command.follow_up.due_at_utc, due_timezone=command.follow_up.due_timezone, correlation_id=correlation_id)
                task_id = str(task["id"])
                follow_up_task_id = task_id
                tx.record_change(entity_type="task", entity_id=task_id, action="created", before=None, after=task,
                    reason="communication_follow_up", correlation_id=correlation_id)
                tx.record_change(entity_type="communication", entity_id=replacement.id, action="follow_up_created", before=None,
                    after={"taskId": task_id}, reason="communication_follow_up", correlation_id=correlation_id)
            tx.insert_operation(CommunicationOperation(str(uuid4()), source.id, replacement.id, "corrected", idempotency_key, fingerprint, correlation_id, now, follow_up_task_id))
            return self._view(tx, replacement.id)
        return self.unit_of_work.write(operation)

    def get(self, communication_id: str) -> dict[str, object]:
        _uuid(communication_id, "communicationId")
        return self.unit_of_work.read(lambda tx: self._view(tx, communication_id))

    def list(self, *, status: str | None = None, direction: str | None = None, channel: str | None = None,
             party_id: str | None = None, entity_type: str | None = None, entity_id: str | None = None,
             limit: int = 100, cursor: str | None = None, occurred_on_or_after: str | None = None,
             occurred_on_or_before: str | None = None, linked_task_status: str | None = None) -> tuple[list[dict[str, object]], str | None]:
        # The adapter owns bounded filtered queries; validation remains an app rule.
        if status is not None and status not in {"draft", "recorded", "superseded"}: raise CommunicationError("Status is invalid.")
        if direction is not None and direction not in DIRECTIONS: raise CommunicationError("Direction is invalid.")
        if channel is not None and channel not in CHANNELS: raise CommunicationError("Channel is invalid.")
        if party_id is not None: _uuid(party_id, "partyId")
        if entity_type is not None and entity_type not in LINK_TYPES: raise CommunicationError("Link type is invalid.")
        if entity_id is not None: _uuid(entity_id, "entityId")
        if (entity_type is None) != (entity_id is None):
            raise CommunicationError("entityType and entityId must be provided together.")
        if not isinstance(limit, int) or not 1 <= limit <= 100: raise CommunicationError("limit must be between 1 and 100.")
        start = _date(occurred_on_or_after, "occurredOnOrAfter") if occurred_on_or_after else None
        end = _date(occurred_on_or_before, "occurredOnOrBefore") if occurred_on_or_before else None
        if start and end and start > end: raise CommunicationError("Occurrence date range is invalid.")
        if linked_task_status is not None and linked_task_status not in {"open", "in_progress", "completed", "cancelled"}:
            raise CommunicationError("linkedTaskStatus is invalid.")
        cursor_values = _cursor(cursor) if cursor else None
        items, scanned_cursor = self.unit_of_work.read(lambda tx: tx.list_views(status, direction, channel, party_id, entity_type, entity_id, limit + 1, cursor_values, start.isoformat() if start else None, end.isoformat() if end else None, linked_task_status))
        page = items[:limit]
        next_cursor = _encode_cursor(page[-1]) if len(items) > limit and page else (
            _encode_cursor_values(scanned_cursor) if scanned_cursor else None
        )
        return page, next_cursor

    def _idempotent(self, tx: CommunicationTransaction, key: str, fingerprint: str) -> CommunicationOperation | None:
        existing = tx.operation(key)
        if existing is None: return None
        if existing.request_fingerprint != fingerprint:
            raise CommunicationConflictError("Idempotency key was reused with different input.", "idempotency_conflict")
        return existing

    def _require(self, tx: CommunicationTransaction, item_id: str) -> Communication:
        item = tx.communication(item_id)
        if item is None: raise CommunicationNotFoundError("Communication was not found.")
        return item

    def _validated_children(self, tx: CommunicationTransaction, communication_id: str, participants: tuple[ParticipantInput, ...], links: tuple[LinkInput, ...]) -> tuple[list[CommunicationParticipant], list[CommunicationLink], list[str | None]]:
        seen = set(); output: list[CommunicationParticipant] = []
        for item in participants:
            key = (item.party_id, item.party_contact_method_id, item.role)
            if key in seen: raise CommunicationError("Duplicate participant.")
            seen.add(key); party_name, contact = tx.validate_participant(item.party_id, item.party_contact_method_id)
            output.append(CommunicationParticipant(str(uuid4()), communication_id, item.party_id, item.party_contact_method_id, item.role, party_name, contact))
        link_seen = set(); output_links: list[CommunicationLink] = []; zones: list[str | None] = []
        for item in links:
            key = (item.entity_type, item.entity_id)
            if key in link_seen: raise CommunicationError("Duplicate communication link.")
            link_seen.add(key)
            zone = tx.validate_link(item.entity_type, item.entity_id)
            zones.append(zone)
            output_links.append(CommunicationLink(
                str(uuid4()), communication_id, item.entity_type, item.entity_id, zone,
            ))
        return output, output_links, zones

    def _validate_timezone(self, timezone: str, resolved_zones: list[str | None]) -> None:
        zones = {zone for zone in resolved_zones if zone}
        if len(zones) > 1 or (zones and timezone not in zones):
            raise CommunicationConflictError("Linked property contexts require one matching time zone.", "timezone_conflict")

    def _refresh_link_snapshots(
        self,
        tx: CommunicationTransaction,
        links: list[CommunicationLink],
        correlation_id: str,
    ) -> tuple[list[CommunicationLink], list[str | None]]:
        refreshed: list[CommunicationLink] = []
        zones: list[str | None] = []
        for link in links:
            zone = tx.validate_link(link.entity_type, link.entity_id)
            zones.append(zone)
            updated = replace(link, property_timezone_snapshot=zone)
            if updated != link:
                tx.replace_link(updated)
                tx.record_change(
                    entity_type="communication_link",
                    entity_id=link.id,
                    action="updated",
                    before=link.to_dict(),
                    after=updated.to_dict(),
                    reason="communication_link_timezone_refreshed",
                    correlation_id=correlation_id,
                )
            refreshed.append(updated)
        return refreshed, zones

    def _audit_created(self, tx: CommunicationTransaction, communication: Communication, participants: list[CommunicationParticipant], links: list[CommunicationLink], correlation_id: str) -> None:
        tx.record_change(entity_type="communication", entity_id=communication.id, action="created", before=None, after=communication.to_dict(), reason="communication_created", correlation_id=correlation_id)
        for item in participants:
            tx.record_change(entity_type="communication_participant", entity_id=item.id, action="created", before=None, after=item.to_dict(), reason="communication_participant_created", correlation_id=correlation_id)
        for item in links:
            tx.record_change(entity_type="communication_link", entity_id=item.id, action="created", before=None, after=item.to_dict(), reason="communication_link_created", correlation_id=correlation_id)

    def _view(self, tx: CommunicationTransaction, communication_id: str) -> dict[str, object]:
        item = self._require(tx, communication_id)
        return {**item.to_dict(), "participants": [x.to_dict() for x in tx.participants(item.id)], "links": [x.to_dict() for x in tx.links(item.id)], "followUpTasks": tx.task_views(item.id)}


def _text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not (text := value.strip()) or len(text) > maximum: raise CommunicationError(f"{name} must contain 1 to {maximum} characters.")
    return text
def _uuid(value: object, name: str) -> str:
    if not isinstance(value, str): raise CommunicationError(f"{name} must be a UUID.")
    try: return str(UUID(value))
    except ValueError as error: raise CommunicationError(f"{name} must be a UUID.") from error
def _zone(value: object) -> None:
    if not isinstance(value, str): raise CommunicationError("occurredTimezone must be an IANA time zone.")
    try: ZoneInfo(value)
    except ZoneInfoNotFoundError as error: raise CommunicationError("occurredTimezone must be an IANA time zone.") from error
def _instant(value: object, name: str) -> None:
    if not isinstance(value, str): raise CommunicationError(f"{name} must be an aware timestamp.")
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error: raise CommunicationError(f"{name} must be an aware timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise CommunicationError(f"{name} must be an aware timestamp.")
def _date(value: object, name: str) -> date:
    if not isinstance(value, str): raise CommunicationError(f"{name} must be an ISO date.")
    try: return date.fromisoformat(value)
    except ValueError as error: raise CommunicationError(f"{name} must be an ISO date.") from error
def _utc(value: str) -> str: return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()
def _now() -> str: return datetime.now(UTC).isoformat()
def _fingerprint(action: str, target: str | None, value: object) -> str:
    def encode(item: object) -> object:
        if hasattr(item, "__dict__"): return {key: encode(child) for key, child in item.__dict__.items()}
        if isinstance(item, tuple): return [encode(child) for child in item]
        return item
    return hashlib.sha256(json.dumps({"action": action, "target": target, "value": encode(value)}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def _cursor(value: str) -> tuple[str, str]:
    try:
        parsed = json.loads(base64.urlsafe_b64decode(value.encode()).decode())
        if not isinstance(parsed, dict) or not isinstance(parsed.get("occurredAtUtc"), str): raise ValueError
        return parsed["occurredAtUtc"], _uuid(parsed.get("id"), "cursor")
    except (ValueError, TypeError, json.JSONDecodeError) as error: raise CommunicationError("cursor is invalid.") from error
def _encode_cursor(item: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps({"occurredAtUtc": item["occurredAtUtc"], "id": item["id"]}, separators=(",", ":")).encode()).decode()
def _encode_cursor_values(value: tuple[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps({"occurredAtUtc": value[0], "id": value[1]}, separators=(",", ":")).encode()).decode()
