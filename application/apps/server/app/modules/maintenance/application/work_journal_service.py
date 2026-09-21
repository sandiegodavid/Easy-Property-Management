"""MAINT-003 append-only work-journal orchestration."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.maintenance.domain.models import MaintenanceConflictError, MaintenanceError, MaintenanceNotFoundError, fingerprint, uuid
from app.modules.maintenance.domain.work_journal import WorkJournalCreate
from .ports import MaintenanceUnitOfWork


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(item.title() for item in tail)


def _view(row, *, corrected_ids: set[str] | None = None, files=None, assignment_start_seconds=None):
    hidden = {"idempotency_key", "request_fingerprint"}
    result = {"id": row["id"], **{_camel(key): value for key, value in row.items() if key not in hidden | {"id"}}}
    result["effectiveKind"] = row["corrected_entry_kind"] or row["entry_kind"]
    result["isEffective"] = row["id"] not in (corrected_ids or set())
    if row.get("assignment_id") is not None:
        result["recordedAssignmentToWorkStartSeconds"] = (assignment_start_seconds or {}).get(row["assignment_id"])
    if files is not None:
        result["files"] = [_file_view(item) for item in files]
    return result


def _file_view(item):
    return {
        "id": item.id, "entityType": item.entity_type, "entityId": item.entity_id,
        "purpose": item.purpose, "fileId": item.file_id, "createdAt": item.created_at,
        "archivedAt": item.archived_at, "archiveReason": item.archive_reason,
        "originalName": item.original_name, "mediaType": item.media_type,
        "sizeBytes": item.size_bytes, "contentSha256": item.content_sha256,
    }


class WorkJournalService:
    def __init__(self, unit_of_work: MaintenanceUnitOfWork, *, now=None):
        self.unit_of_work = unit_of_work
        self.now = now or (lambda: datetime.now(UTC))

    def record(self, issue_id: str, command: WorkJournalCreate, idempotency_key: str):
        uuid(issue_id, "issueId"); uuid(idempotency_key, "idempotencyKey")
        payload = {"issueId": issue_id, "command": command.fingerprint_payload()}
        request_fingerprint = fingerprint("work_journal", payload)
        def operation(tx):
            existing = tx.work_journal_by_key(idempotency_key)
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise MaintenanceConflictError("Idempotency key payload changed.", "idempotency_conflict")
                return self._entry_view(tx, existing["id"])
            issue = tx.issue(issue_id)
            if issue is None:
                raise MaintenanceNotFoundError("Issue was not found.")
            if issue["status"] in {"resolved", "cancelled"} and command.historical_entry_confirmed is not True:
                raise MaintenanceConflictError("Terminal issue history requires confirmation.", "historical_entry_confirmation")
            now = self.now().astimezone(UTC)
            occurred = datetime.fromisoformat(command.occurred_at_utc)
            if occurred > now + timedelta(minutes=5):
                raise MaintenanceError("occurredAtUtc cannot be more than five minutes in the future.")
            context = tx.issue_context(issue["property_id"], issue["space_id"])
            if context is None:
                raise MaintenanceConflictError("Issue property context is unavailable.", "issue_context")
            if command.assignment_id is not None:
                assignment = tx.assignment(command.assignment_id)
                if assignment is None:
                    raise MaintenanceNotFoundError("Assignment was not found.")
                if assignment["issue_id"] != issue_id:
                    raise MaintenanceConflictError("Assignment must belong to the issue.", "assignment_mismatch")
            if command.entry_kind == "correction":
                target = tx.work_journal(command.corrects_entry_id)
                if target is None:
                    raise MaintenanceNotFoundError("Correction target was not found.")
                if target["issue_id"] != issue_id:
                    raise MaintenanceConflictError("Correction target must belong to the issue.", "correction_mismatch")
                if tx.work_journal_correction(command.corrects_entry_id) is not None:
                    raise MaintenanceConflictError("Journal entry already has a correction.", "correction_exists")
            item = {
                "id": str(uuid4()), "issue_id": issue_id, "assignment_id": command.assignment_id,
                "entry_kind": command.entry_kind, "corrected_entry_kind": command.corrected_entry_kind,
                "source_kind": command.source_kind, "occurred_at_utc": command.occurred_at_utc,
                "occurred_timezone": context["property"]["time_zone"], "summary": command.summary,
                "detail": command.detail, "outcome_status": command.outcome_status,
                "outcome_summary": command.outcome_summary,
                "follow_up_required": command.follow_up_required,
                "operator_verified": command.operator_verified,
                "corrects_entry_id": command.corrects_entry_id, "correction_reason": command.correction_reason,
                "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
                "recorded_at_utc": now.isoformat(),
            }
            tx.insert_work_journal(item)
            reason = "work_journal_historical_created" if issue["status"] in {"resolved", "cancelled"} else "work_journal_created"
            tx.record_change(entity_type="maintenance_work_journal_entry", entity_id=item["id"], action="created", before=None, after=_view(item), reason=reason, correlation_id=str(uuid4()))
            return _view(item)
        return self.unit_of_work.write(operation)

    def issue_journal(self, issue_id: str, *, cursor=None, page_size: int = 50, descending: bool = True):
        uuid(issue_id, "issueId")
        if not isinstance(page_size, int) or not 1 <= page_size <= 100:
            raise MaintenanceError("pageSize must be between 1 and 100.")
        def operation(tx):
            if tx.issue(issue_id) is None:
                raise MaintenanceNotFoundError("Issue was not found.")
            rows = tx.work_journal_page(issue_id=issue_id, provider_party_id=None, cursor=cursor, limit=page_size + 1, descending=descending)
            page = rows[:page_size]
            corrected = tx.work_journal_corrected_ids([item["id"] for item in page])
            files = tx.work_journal_files([item["id"] for item in page])
            timings = tx.work_journal_assignment_start_seconds([item.get("assignment_id") for item in page])
            next_cursor = None
            if len(rows) > page_size:
                tail = page[-1]
                next_cursor = f"{tail['occurred_at_utc']}|{tail['recorded_at_utc']}|{tail['id']}"
            return {"items": [_view(item, corrected_ids=corrected, files=files.get(item["id"], []), assignment_start_seconds=timings) for item in page], "nextCursor": next_cursor}
        return self.unit_of_work.read(operation)

    def provider_history(self, provider_party_id: str, *, cursor=None, page_size: int = 50, descending: bool = True):
        uuid(provider_party_id, "providerPartyId")
        if not isinstance(page_size, int) or not 1 <= page_size <= 100:
            raise MaintenanceError("pageSize must be between 1 and 100.")
        def operation(tx):
            rows = tx.work_journal_page(issue_id=None, provider_party_id=provider_party_id, cursor=cursor, limit=page_size + 1, descending=descending)
            page = rows[:page_size]
            corrected = tx.work_journal_corrected_ids([item["id"] for item in page])
            files = tx.work_journal_files([item["id"] for item in page])
            timings = tx.work_journal_assignment_start_seconds([item.get("assignment_id") for item in page])
            next_cursor = None
            if len(rows) > page_size:
                tail = page[-1]
                next_cursor = f"{tail['occurred_at_utc']}|{tail['recorded_at_utc']}|{tail['id']}"
            return {"items": [_view(item, corrected_ids=corrected, files=files.get(item["id"], []), assignment_start_seconds=timings) for item in page], "nextCursor": next_cursor}
        return self.unit_of_work.read(operation)

    def _entry_view(self, tx, entry_id: str):
        row = tx.work_journal(entry_id)
        return _view(row, corrected_ids=tx.work_journal_corrected_ids([entry_id]))
