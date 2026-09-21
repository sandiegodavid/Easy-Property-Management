from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import dumps, loads
from base64 import urlsafe_b64decode, urlsafe_b64encode
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
                context.get("occupancy_status") if command.concern_type == "vacancy" else None,
                context.get("availability_status") if command.concern_type == "vacancy" else None,
                context.get("available_on") if command.concern_type == "vacancy" else None, command.idempotency_key, fingerprint,
            )
            correlation = str(uuid4())
            tx.insert_concern(item)
            audit_after = item.to_dict() | {"historicalSelectionReason": command.historical_selection_reason, "duplicateReason": command.duplicate_reason}
            tx.record_change(entity_type="owner_concern", entity_id=item.id, action="created", before=None, after=audit_after, reason="owner_concern_created", correlation_id=correlation)
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
                try:
                    # A reopen creates active work, but must not re-adjudicate
                    # historical owner, space, lease, or tenant lifecycle facts.
                    tx.active_property(current.property_id)
                except KeyError as error:
                    raise OwnerConcernNotFoundError(str(error)) from error
                except ValueError as error:
                    raise OwnerConcernError(str(error)) from error
                narrative_value = text(narrative, "Reopen reason", 4000, required=True)
            elif target == "resolved": narrative_value = text(narrative, "Resolution summary", 4000, required=True)
            elif target == "dismissed": narrative_value = text(narrative, "Dismissal reason", 4000, required=True)
            else: narrative_value = None
            stamp = _stamp(self.now())
            updated = replace(current, status=target, updated_at_utc=stamp,
                resolved_at_utc=stamp if target == "resolved" else None, resolution_summary=narrative_value if target == "resolved" else None,
                dismissed_at_utc=stamp if target == "dismissed" else None, dismissal_reason=narrative_value if target == "dismissed" else None)
            correlation=str(uuid4()); tx.replace_concern(updated)
            audit_after = updated.to_dict() | ({"reopenReason": narrative_value} if target == "open" and current.status in TERMINAL_STATUSES else {})
            tx.record_change(entity_type="owner_concern", entity_id=current.id, action="status_changed", before=current.to_dict(), after=audit_after, reason="owner_concern_status_changed", correlation_id=correlation)
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
        for field, values in (("concern_type", {"general_rental","lease","tenant","vacancy"}), ("priority", PRIORITIES), ("status", ACTIVE_STATUSES|TERMINAL_STATUSES)):
            if filters.get(field) is not None and filters[field] not in values: raise OwnerConcernError(f"{field} is invalid.")
        for field in ("active_task","linked_communication"):
            if filters.get(field) is not None and type(filters[field]) is not bool: raise OwnerConcernError(f"{field} must be a boolean.")
        for field in ("raised_local_on_or_after","raised_local_on_or_before"):
            if filters.get(field) is not None:
                try: datetime.fromisoformat(f"{filters[field]}T00:00:00")
                except (TypeError, ValueError) as error: raise OwnerConcernError(f"{field} must be an ISO calendar date.") from error
        if filters.get("raised_local_on_or_after") and filters.get("raised_local_on_or_before") and filters["raised_local_on_or_after"] > filters["raised_local_on_or_before"]: raise OwnerConcernError("Raised local-date range is invalid.")
        cursor_values = _cursor(cursor) if cursor else None
        date_filters={key:filters.pop(key, None) for key in ("raised_local_on_or_after","raised_local_on_or_before")}
        scanned_cursor=None; scan_limited=False
        if any(date_filters.values()):
            rows=[]; scan_cursor=cursor_values; scanned=0
            while len(rows)<=page_size and scanned<2_000:
                batch=self.unit_of_work.read(lambda tx: tx.concern_page(limit=200,cursor=scan_cursor,**filters))
                if not batch: break
                scanned += len(batch); scan_cursor=_cursor(_encode_cursor(batch[-1]))
                scanned_cursor=scan_cursor
                rows.extend(item for item in batch if (not date_filters["raised_local_on_or_after"] or _local_date(item.raised_at_utc,item.property_timezone_snapshot)>=date_filters["raised_local_on_or_after"]) and (not date_filters["raised_local_on_or_before"] or _local_date(item.raised_at_utc,item.property_timezone_snapshot)<=date_filters["raised_local_on_or_before"]))
                if len(batch)<200: break
            scan_limited=scanned >= 2_000 and len(rows)<=page_size
        else:
            rows = self.unit_of_work.read(lambda tx: tx.concern_page(limit=page_size + 1, cursor=cursor_values, **filters))
        items = rows[:page_size]
        def summaries(tx):
            ids=[item.id for item in items]; task_counts=tx.active_task_counts(ids); communications=tx.communication_counts(ids)
            return [self._summary(item,task_counts.get(item.id,0),communications.get(item.id,0)) for item in items]
        views = self.unit_of_work.read(summaries)
        next_cursor=_encode_cursor(items[-1]) if len(rows) > page_size and items else None
        if next_cursor is None and scan_limited and scanned_cursor is not None:
            next_cursor=urlsafe_b64encode(dumps(list(scanned_cursor),separators=(",",":")).encode()).decode()
        return views, next_cursor

    def _context(self, tx, command):
        try:
            zone = tx.context(owner_party_id=command.owner_party_id, property_id=command.property_id, space_id=command.space_id, lease_id=command.lease_id, tenant_party_id=command.tenant_party_id, raised_on="", historical=command.historical_selection_confirmed, concern_type=command.concern_type)["time_zone"]
            raised_on = _local_date(command.raised_at_utc, zone)
            if command.historical_selection_confirmed and raised_on >= _local_date(_stamp(self.now()), zone):
                raise OwnerConcernError("Historical selection requires a genuinely backdated concern.")
            return tx.context(owner_party_id=command.owner_party_id, property_id=command.property_id, space_id=command.space_id, lease_id=command.lease_id, tenant_party_id=command.tenant_party_id, raised_on=raised_on, historical=command.historical_selection_confirmed, concern_type=command.concern_type)
        except KeyError as error:
            raise OwnerConcernNotFoundError(str(error)) from error
        except ValueError as error:
            raise OwnerConcernError(str(error)) from error

    def _create_follow_up(self, tx, concern, follow_up, key, fingerprint, correlation, stamp):
        task = tx.create_task({"title": follow_up.title, "notes": follow_up.notes, "priority": follow_up.priority, "due_at_utc": follow_up.due_at_utc, "due_timezone": follow_up.due_timezone, "is_all_day": False, "related_entity_type": "owner_concern", "related_entity_id": concern.id, "related_label": concern.summary}, correlation_id=correlation)
        tx.record_change(entity_type="owner_concern", entity_id=concern.id, action="follow_up_created", before=None, after={"taskId": task.id}, reason="owner_concern_follow_up_created", correlation_id=correlation)
        operation = {"id": str(uuid4()), "idempotency_key": key, "request_fingerprint": fingerprint, "concern_id": concern.id, "task_id": task.id, "correlation_id": correlation, "created_at_utc": stamp}
        tx.insert_follow_up_operation(operation)
        tx.record_change(entity_type="owner_concern_follow_up_operation", entity_id=operation["id"], action="created", before=None, after={"id": operation["id"], "concernId": concern.id, "taskId": task.id}, reason="owner_concern_follow_up_operation_created", correlation_id=correlation)

    def _view(self, tx, concern):
        data = concern.to_dict(); data["followUpTasks"] = tx.task_views([concern.id]).get(concern.id, []); data["linkedCommunicationCount"] = tx.communication_counts([concern.id]).get(concern.id, 0); data.update(tx.detail_projection(concern)); return data
    def _summary(self, concern, active_task_count, communication_count):
        return {"id":concern.id,"ownerPartyId":concern.owner_party_id,"ownerDisplayNameSnapshot":concern.owner_display_name_snapshot,"propertyId":concern.property_id,"propertyDisplayNameSnapshot":concern.property_display_name_snapshot,"spaceId":concern.space_id,"spaceDisplayNameSnapshot":concern.space_display_name_snapshot,"concernType":concern.concern_type,"summary":concern.summary,"priority":concern.priority,"status":concern.status,"raisedAtUtc":concern.raised_at_utc,"propertyTimezoneSnapshot":concern.property_timezone_snapshot,"activeFollowUpCount":active_task_count,"linkedCommunicationCount":communication_count}
    def _future_limit(self, raised_at):
        if datetime.fromisoformat(raised_at) > self.now().astimezone(UTC).replace(microsecond=0) + timedelta(minutes=5): raise OwnerConcernError("Raised time may not be more than five minutes in the future.")

def _required(value):
    if value is None: raise OwnerConcernNotFoundError("Owner concern was not found.")
    return value
def _stamp(value): return value.astimezone(UTC).isoformat()
def _local_date(value, zone): return datetime.fromisoformat(value).astimezone(ZoneInfo(zone)).date().isoformat()
def _fingerprint(value): return sha256(dumps(value, default=lambda item: getattr(item, "__dict__", str(item)), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def _cursor(value):
    try:
        rank, raised, item_id = loads(urlsafe_b64decode(value.encode()).decode())
        if type(rank) is not int or rank not in range(4): raise ValueError
        timestamp(raised, "Cursor raised time"); uuid(item_id, "Cursor ID")
        return rank, raised, item_id
    except Exception as error:
        raise OwnerConcernError("Cursor is invalid.") from error
def _encode_cursor(item):
    rank={"urgent":0,"high":1,"normal":2,"low":3}[item.priority]
    return urlsafe_b64encode(dumps([rank,item.raised_at_utc,item.id],separators=(",",":")).encode()).decode()
