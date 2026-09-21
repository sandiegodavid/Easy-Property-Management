from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import dumps
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.owner_management.application.ports import OwnerConcernUnitOfWork
from app.modules.owner_management.domain.models import ACTIVE_STATUSES, Concern, ConcernCreateCommand, FollowUpInput, OwnerConcernConflictError, OwnerConcernError, OwnerConcernNotFoundError, PRIORITIES, TERMINAL_STATUSES, text, timestamp, uuid


class OwnerConcernService:
    def __init__(self, unit_of_work: OwnerConcernUnitOfWork, *, now=lambda: datetime.now(UTC)):
        self.unit_of_work = unit_of_work
        self.now = now

    def create(self, command: ConcernCreateCommand) -> dict[str, object]:
        fingerprint = _fingerprint(command)
        def operation(tx):
            retry = tx.operation(command.idempotency_key)
            if retry:
                if retry["request_fingerprint"] != fingerprint:
                    raise OwnerConcernConflictError("Idempotency key was already used for a different request.", "idempotency_conflict")
                return self._view(tx, _required(tx.concern(str(retry["id"]))))
            context = self._context(tx, command)
            self._future_limit(command.raised_at_utc)
            if command.originating_communication_id and not tx.originating_communication(command.originating_communication_id, command.owner_party_id, command.property_id):
                raise OwnerConcernError("Originating communication is not compatible with the selected owner and property.")
            candidates = tx.duplicate_candidates(owner_party_id=command.owner_party_id, property_id=command.property_id, concern_type=command.concern_type, space_id=command.space_id, lease_id=command.lease_id, tenant_party_id=command.tenant_party_id)
            if candidates and not command.duplicate_confirmed:
                raise OwnerConcernConflictError("Likely duplicate owner concerns require independent-concern confirmation.", "duplicate_review_required", {"candidateConcernIds": candidates[:20]})
            if command.replaces_concern_id:
                source = _required(tx.concern(command.replaces_concern_id))
                if source.status != "dismissed" or tx.duplicate_candidates(replaces_concern_id=source.id):
                    raise OwnerConcernConflictError("A replacement requires one dismissed concern without an existing replacement.", "replacement_conflict")
            stamp = _stamp(self.now())
            item = Concern(
                str(uuid4()), command.owner_party_id, str(context["owner_display_name"]), command.property_id, str(context["property_display_name"]),
                command.space_id, context.get("space_display_name"), command.lease_id, context.get("lease_display"), command.tenant_party_id, context.get("tenant_display_name"),
                command.originating_communication_id, command.concern_type, command.summary, command.description, command.priority, "open", command.raised_at_utc,
                str(context["time_zone"]), stamp, stamp, None, None, None, None, command.replaces_concern_id,
                context.get("occupancy_status"), context.get("availability_status"), context.get("available_on"), command.idempotency_key, fingerprint,
            )
            correlation = str(uuid4())
            tx.insert_concern(item)
            tx.record_change(entity_type="owner_concern", entity_id=item.id, action="created", before=None, after=item.to_dict(), reason="owner_concern_created", correlation_id=correlation)
            if command.follow_up:
                self._create_follow_up(tx, item, command.follow_up, command.idempotency_key, fingerprint, correlation, stamp)
            return self._view(tx, item)
        return self.unit_of_work.write(operation)

    def patch(self, concern_id: str, values: dict[str, object]) -> dict[str, object]:
        uuid(concern_id, "Concern ID")
        allowed = {"summary", "description", "priority"}
        if not set(values).issubset(allowed):
            raise OwnerConcernError("Patch contains unsupported fields.")
        def operation(tx):
            current = _required(tx.concern(concern_id))
            if current.status not in ACTIVE_STATUSES:
                raise OwnerConcernConflictError("Only active concerns can be edited.", "active_required")
            summary = text(values["summary"], "Summary", 240, required=True) if "summary" in values else current.summary
            description = text(values["description"], "Description", 10_000, required=True) if "description" in values else current.description
            priority = values.get("priority", current.priority)
            if priority not in PRIORITIES: raise OwnerConcernError("Concern priority is invalid.")
            if (summary, description, priority) == (current.summary, current.description, current.priority): return self._view(tx, current)
            updated = replace(current, summary=summary, description=description, priority=priority, updated_at_utc=_stamp(self.now()))
            correlation = str(uuid4()); tx.replace_concern(updated)
            tx.record_change(entity_type="owner_concern", entity_id=current.id, action="updated", before=current.to_dict(), after=updated.to_dict(), reason="owner_concern_updated", correlation_id=correlation)
            return self._view(tx, updated)
        return self.unit_of_work.write(operation)

    def transition(self, concern_id: str, target: str, *, confirmed: bool, narrative: str | None = None) -> dict[str, object]:
        uuid(concern_id, "Concern ID")
        if confirmed is not True: raise OwnerConcernError("Explicit confirmation is required.")
        if target not in {"in_progress", "open", "resolved", "dismissed"}: raise OwnerConcernError("Concern status is invalid.")
        def operation(tx):
            current = _required(tx.concern(concern_id)); allowed = {"open": {"in_progress", "resolved", "dismissed"}, "in_progress": {"open", "resolved", "dismissed"}, "resolved": {"open"}, "dismissed": {"open"}}
            if target not in allowed[current.status]: raise OwnerConcernConflictError("Requested concern transition is not allowed.", "lifecycle_conflict")
            if target == "open" and current.status in TERMINAL_STATUSES:
                # Reopening belongs to an active property, checked by neutral context.
                tx.context(owner_party_id=current.owner_party_id, property_id=current.property_id, space_id=current.space_id, lease_id=current.lease_id, tenant_party_id=current.tenant_party_id, raised_on=_local_date(current.raised_at_utc, current.property_timezone_snapshot), historical=False)
                narrative_value = text(narrative, "Reopen reason", 4000, required=True)
            elif target == "resolved": narrative_value = text(narrative, "Resolution summary", 4000, required=True)
            elif target == "dismissed": narrative_value = text(narrative, "Dismissal reason", 4000, required=True)
            else: narrative_value = None
            stamp = _stamp(self.now())
            updated = replace(current, status=target, updated_at_utc=stamp,
                resolved_at_utc=stamp if target == "resolved" else None, resolution_summary=narrative_value if target == "resolved" else None,
                dismissed_at_utc=stamp if target == "dismissed" else None, dismissal_reason=narrative_value if target == "dismissed" else None)
            correlation=str(uuid4()); tx.replace_concern(updated)
            tx.record_change(entity_type="owner_concern", entity_id=current.id, action="status_changed", before=current.to_dict(), after=updated.to_dict(), reason="owner_concern_status_changed", correlation_id=correlation)
            return self._view(tx, updated)
        return self.unit_of_work.write(operation)

    def follow_up(self, concern_id: str, follow_up: FollowUpInput, idempotency_key: str) -> dict[str, object]:
        uuid(concern_id, "Concern ID"); uuid(idempotency_key, "Idempotency key")
        fingerprint = _fingerprint((concern_id, follow_up))
        def operation(tx):
            prior = tx.follow_up_operation(idempotency_key)
            if prior:
                if prior["request_fingerprint"] != fingerprint: raise OwnerConcernConflictError("Idempotency key was already used for a different follow-up.", "idempotency_conflict")
                return self._view(tx, _required(tx.concern(concern_id)))
            concern = _required(tx.concern(concern_id)); correlation=str(uuid4()); stamp=_stamp(self.now())
            self._create_follow_up(tx, concern, follow_up, idempotency_key, fingerprint, correlation, stamp)
            return self._view(tx, concern)
        return self.unit_of_work.write(operation)

    def get(self, concern_id: str) -> dict[str, object]:
        uuid(concern_id, "Concern ID")
        return self.unit_of_work.read(lambda tx: self._view(tx, _required(tx.concern(concern_id))))

    def list(self, *, page_size: int = 100, cursor: str | None = None, **filters) -> tuple[list[dict[str, object]], str | None]:
        if type(page_size) is not int or not 1 <= page_size <= 500: raise OwnerConcernError("Page size must be between 1 and 500.")
        rows = self.unit_of_work.read(lambda tx: tx.concern_page(limit=page_size + 1, cursor=cursor, **filters))
        items = rows[:page_size]
        views = self.unit_of_work.read(lambda tx: [self._view(tx, item) for item in items])
        return views, (items[-1].id if len(rows) > page_size and items else None)

    def _context(self, tx, command):
        raised_on = _local_date(command.raised_at_utc, tx.context(owner_party_id=command.owner_party_id, property_id=command.property_id, space_id=command.space_id, lease_id=command.lease_id, tenant_party_id=command.tenant_party_id, raised_on="", historical=command.historical_selection_confirmed)["time_zone"])
        return tx.context(owner_party_id=command.owner_party_id, property_id=command.property_id, space_id=command.space_id, lease_id=command.lease_id, tenant_party_id=command.tenant_party_id, raised_on=raised_on, historical=command.historical_selection_confirmed)

    def _create_follow_up(self, tx, concern, follow_up, key, fingerprint, correlation, stamp):
        task = tx.create_task({"title": follow_up.title, "notes": follow_up.notes, "priority": follow_up.priority, "due_at_utc": follow_up.due_at_utc, "due_timezone": follow_up.due_timezone, "is_all_day": False, "related_entity_type": "owner_concern", "related_entity_id": concern.id, "related_label": concern.summary}, correlation_id=correlation)
        tx.record_change(entity_type="owner_concern", entity_id=concern.id, action="follow_up_created", before=None, after={"taskId": task.id}, reason="owner_concern_follow_up_created", correlation_id=correlation)
        operation = {"id": str(uuid4()), "idempotency_key": key, "request_fingerprint": fingerprint, "concern_id": concern.id, "task_id": task.id, "correlation_id": correlation, "created_at_utc": stamp}
        tx.insert_follow_up_operation(operation)
        tx.record_change(entity_type="owner_concern_follow_up_operation", entity_id=operation["id"], action="created", before=None, after={"id": operation["id"], "concernId": concern.id, "taskId": task.id}, reason="owner_concern_follow_up_operation_created", correlation_id=correlation)

    def _view(self, tx, concern):
        data = concern.to_dict(); data["followUpTasks"] = tx.task_views([concern.id]).get(concern.id, []); data["linkedCommunicationCount"] = tx.communication_counts([concern.id]).get(concern.id, 0); return data
    def _future_limit(self, raised_at):
        if datetime.fromisoformat(raised_at) > self.now().astimezone(UTC).replace(microsecond=0) + timedelta(minutes=5): raise OwnerConcernError("Raised time may not be more than five minutes in the future.")

def _required(value):
    if value is None: raise OwnerConcernNotFoundError("Owner concern was not found.")
    return value
def _stamp(value): return value.astimezone(UTC).isoformat()
def _local_date(value, zone): return datetime.fromisoformat(value).astimezone(ZoneInfo(zone)).date().isoformat()
def _fingerprint(value): return sha256(dumps(value, default=lambda item: getattr(item, "__dict__", str(item)), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
