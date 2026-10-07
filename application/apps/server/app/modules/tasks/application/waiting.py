"""Validated TASK-002 commands and immutable operation results."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class WaitingError(ValueError):
    status_code = 422
    code = "task_waiting_validation"


class WaitingConflict(WaitingError):
    status_code = 409
    code = "task_waiting_conflict"

    def __init__(self, message: str, current_revision: int | None = None):
        super().__init__(message)
        self.current_revision = current_revision


class WaitingNotFound(WaitingError):
    status_code = 404
    code = "task_not_found"


class WaitingUnavailable(WaitingError):
    status_code = 503
    code = "workspace_unavailable"


class WaitingBusy(WaitingError):
    status_code = 503
    code = "task_waiting_busy"

    def __init__(self):
        super().__init__("Task storage is busy. Retry the request shortly.")


class WaitingStorageFailure(WaitingError):
    status_code = 500
    code = "task_waiting_storage_failure"

    def __init__(self):
        super().__init__("Task storage could not complete the request.")


class WaitingPayloadTooLarge(WaitingError):
    status_code = 413
    code = "task_waiting_payload_too_large"


@dataclass(frozen=True)
class WaitingCommand:
    task_id: str
    action: str
    expected_revision: int
    idempotency_key: str
    kind: str | None = None
    label: str | None = None
    follow_up_at: str | None = None
    timezone: str | None = None
    confirmed: bool = False
    clear_follow_up: bool = False

    def __post_init__(self):
        try:
            for field in ("task_id", "idempotency_key"):
                value = getattr(self, field)
                if not isinstance(value, str):
                    raise ValueError
                object.__setattr__(self, field, str(UUID(value)))
        except (ValueError, TypeError, AttributeError) as error:
            raise WaitingError("Task ID and idempotency key must be UUIDs.") from error
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise WaitingError("expectedRevision must be a positive integer.")
        if type(self.confirmed) is not bool or type(self.clear_follow_up) is not bool:
            raise WaitingError("Confirmation fields must be booleans.")
        if self.action not in {"set", "clear", "reschedule"}:
            raise WaitingError("Unknown waiting action.")
        if self.action == "set":
            if self.kind not in {"person", "organization", "event", "other"}:
                raise WaitingError("Unknown waiting kind.")
            if isinstance(self.label, str) and len(self.label.strip()) > 255:
                raise WaitingPayloadTooLarge("Waiting label exceeds 255 characters.")
            if not isinstance(self.label, str) or not 1 <= len(self.label.strip()) <= 255:
                raise WaitingError("Waiting label must contain 1–255 characters.")
            object.__setattr__(self, "label", self.label.strip())
            if self.confirmed or self.clear_follow_up:
                raise WaitingError("Set cannot clear or confirm another action.")
        elif self.kind is not None or self.label is not None:
            raise WaitingError("This action cannot replace the waiting identity.")
        if self.action == "clear":
            if not self.confirmed or self.follow_up_at or self.timezone or self.clear_follow_up:
                raise WaitingError("Clear requires confirmed=true and no date fields.")
        elif self.action == "reschedule":
            if self.confirmed or (self.clear_follow_up == (self.follow_up_at is not None)):
                raise WaitingError("Supply a follow-up date or clearFollowUp=true, not both.")
        if (self.follow_up_at is None) != (self.timezone is None):
            raise WaitingError("Follow-up timestamp and zone must be supplied together.")
        if self.follow_up_at is not None:
            try:
                instant = datetime.fromisoformat(self.follow_up_at)
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise ValueError
                ZoneInfo(self.timezone)
            except (ValueError, TypeError, ZoneInfoNotFoundError) as error:
                raise WaitingError(
                    "Follow-up requires an aware timestamp and IANA zone."
                ) from error
            object.__setattr__(self, "follow_up_at", instant.astimezone(UTC).isoformat())

    def fingerprint(self) -> str:
        return sha256(
            dumps(self.__dict__, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class WaitingOperation:
    id: str
    idempotency_key: str
    task_id: str
    action: str
    request_fingerprint: str
    expected_revision: int
    resulting_revision: int
    result_json: str
    correlation_id: str
    created_at_utc: str
    request_json: str


@dataclass(frozen=True)
class FollowUpQuery:
    state: str | None = None
    actionable: bool | None = None
    priority: str | None = None
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self):
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise WaitingError("Follow-up limit must be between 1 and 100.")
        if self.state not in {None, "scheduled", "due", "overdue", "unscheduled"}:
            raise WaitingError("Unknown follow-up state.")
        if self.actionable is not None and type(self.actionable) is not bool:
            raise WaitingError("actionable must be a boolean.")
        if self.priority not in {None, "low", "normal", "high", "urgent"}:
            raise WaitingError("Unknown priority.")
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise WaitingError("Related type and ID must be supplied together.")
        if self.related_entity_type is not None:
            if (
                not isinstance(self.related_entity_type, str)
                or not 1 <= len(self.related_entity_type.strip()) <= 64
            ):
                raise WaitingError("Invalid related type.")
            try:
                UUID(self.related_entity_id)
            except (ValueError, TypeError, AttributeError) as error:
                raise WaitingError("Related ID must be a UUID.") from error

    def filters(self):
        return {
            key: value for key, value in self.__dict__.items() if key not in {"cursor", "limit"}
        }
