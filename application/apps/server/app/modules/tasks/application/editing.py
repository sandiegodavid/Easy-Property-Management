"""Task-owned partial-edit normalization and resulting-record validation."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.tasks.application.waiting import WaitingConflict, WaitingError
from app.modules.tasks.domain.models import ACTIVE_TASK_STATUSES, Task

TEXT_FIELDS = {
    "title": (255, False),
    "notes": (10_000, True),
    "related_entity_type": (64, True),
    "related_label": (255, True),
}
EDITABLE_FIELDS = {
    *TEXT_FIELDS,
    "priority",
    "due_at_utc",
    "due_timezone",
    "is_all_day",
    "related_entity_id",
}


def normalize_changes(changes) -> tuple[tuple[str, object], ...]:
    try:
        values = dict(changes)
        if len(values) != len(changes) or not values or set(values) - EDITABLE_FIELDS:
            raise ValueError
    except (ValueError, TypeError) as error:
        raise WaitingError("Task edits require distinct supported fields.") from error
    for field, value in values.items():
        if field in TEXT_FIELDS:
            maximum, nullable = TEXT_FIELDS[field]
            if nullable and value is None:
                continue
            if field == "notes" and isinstance(value, str) and not value.strip():
                values[field] = None
                continue
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                raise WaitingError(f"Invalid {field}.")
            values[field] = value.strip()
        elif field == "priority" and (
            not isinstance(value, str) or value not in {"low", "normal", "high", "urgent"}
        ):
            raise WaitingError("Invalid Task priority.")
        elif field == "is_all_day" and type(value) is not bool:
            raise WaitingError("isAllDay must be a boolean.")
        elif field == "related_entity_id" and value is not None:
            try:
                if not isinstance(value, str) or str(UUID(value)) != value:
                    raise ValueError
            except (ValueError, TypeError, AttributeError) as error:
                raise WaitingError("Related entity ID must be a canonical UUID.") from error
        elif field == "due_at_utc" and value is not None:
            try:
                instant = datetime.fromisoformat(value)
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise WaitingError("Due time requires an offset-bearing timestamp.") from error
            values[field] = instant.astimezone(UTC).isoformat()
        elif field == "due_timezone" and value is not None:
            try:
                if not isinstance(value, str):
                    raise ValueError
                ZoneInfo(value)
            except (ValueError, TypeError, ZoneInfoNotFoundError) as error:
                raise WaitingError("Due timezone must be an IANA zone.") from error
    return tuple(sorted(values.items()))


def edit_task(task: Task, changes: tuple[tuple[str, object], ...], stamp: str) -> Task:
    if task.status not in ACTIVE_TASK_STATUSES or task.deleted_at_utc:
        raise WaitingConflict("Only active Tasks can be edited.", task.revision)
    updated = replace(task, **dict(changes))
    if (updated.related_entity_type is None) != (updated.related_entity_id is None) or (
        updated.related_label is not None and updated.related_entity_type is None
    ):
        raise WaitingError("Related type and ID must be paired; labels require a relation.")
    if (updated.due_at_utc is None) != (updated.due_timezone is None) or (
        updated.is_all_day and updated.due_at_utc is None
    ):
        raise WaitingError("Due time/zone must be paired; all-day requires a due time.")
    if updated.is_all_day and any(
        field in {"due_at_utc", "due_timezone", "is_all_day"} for field, _ in changes
    ):
        local = datetime.fromisoformat(updated.due_at_utc).astimezone(
            ZoneInfo(updated.due_timezone)
        )
        updated = replace(
            updated,
            due_at_utc=local.replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .isoformat(),
        )
    if updated == task:
        return task
    return replace(updated, revision=task.revision + 1, updated_at_utc=stamp)
