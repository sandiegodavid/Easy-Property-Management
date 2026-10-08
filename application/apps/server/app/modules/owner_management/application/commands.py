"""Concern revision checks and immutable command results."""

from dataclasses import dataclass
from hashlib import sha256
from json import dumps, loads
from uuid import uuid4

from app.modules.owner_management.domain.models import (
    OwnerConcernConflictError,
    OwnerConcernError,
    OwnerConcernNotFoundError,
    uuid,
)


def canonical(value):
    return dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class ConcernCommand:
    action: str
    concern_id: str | None
    expected_revision: int
    idempotency_key: str
    payload: dict

    def __post_init__(self):
        if self.action not in {
            "create",
            "patch",
            "in_progress",
            "open",
            "resolved",
            "dismissed",
            "follow_up",
        }:
            raise OwnerConcernError("Unsupported concern command.")
        if type(self.expected_revision) is not int or (
            self.expected_revision != 0 if self.action == "create" else self.expected_revision < 1
        ):
            raise OwnerConcernError("Revision must be zero for creation or a positive integer.")
        for value, label in (
            (self.idempotency_key, "Idempotency key"),
            (self.concern_id, "Concern ID"),
        ):
            if value is None and label == "Concern ID" and self.action == "create":
                continue
            if not isinstance(value, str) or uuid(value, label) != value:
                raise OwnerConcernError(f"{label} must be a canonical UUID.")

    def request(self):
        return {
            "action": self.action,
            "concernId": self.concern_id,
            "expectedRevision": self.expected_revision,
            "payload": self.payload,
        }


def start(tx, command, view):
    prior = tx.command_operation_by_key(command.idempotency_key)
    if prior:
        if prior["request_fingerprint"] != fingerprint(command.request()):
            raise OwnerConcernConflictError(
                "Key was used for a different concern command.", "idempotency_conflict"
            )
        return loads(prior["result_json"])
    if command.concern_id is not None:
        current = tx.concern(command.concern_id)
        if current is None:
            raise OwnerConcernNotFoundError("Owner concern was not found.")
        if current.revision != command.expected_revision:
            raise OwnerConcernConflictError(
                "Concern revision has changed.",
                "owner_concern_revision_conflict",
                {"current": view(tx, current), "currentRevision": current.revision},
            )
    return None


def receipt_audit(row):
    return {
        "id": row["id"],
        "concernId": row["concern_id"],
        "action": row["action"],
        "expectedRevision": row["expected_revision"],
        "revision": row["resulting_revision"],
    }


def finish(tx, command, concern, result, stamp, correlation, task=None):
    operation_id = str(uuid4())
    result = {**result, "revision": concern.revision, "operationId": operation_id}
    if task is not None:
        result["followUpTask"] = task.to_dict()
    row = {
        "id": operation_id,
        "concern_id": concern.id,
        "action": command.action,
        "idempotency_key": command.idempotency_key,
        "request_json": canonical(command.request()),
        "request_fingerprint": fingerprint(command.request()),
        "expected_revision": command.expected_revision,
        "resulting_revision": concern.revision,
        "result_json": canonical(result),
        "correlation_id": correlation,
        "created_at_utc": stamp,
    }
    tx.insert_command_operation(row)
    tx.record_change(
        entity_type="owner_concern_command_operation",
        entity_id=operation_id,
        action="recorded",
        before=None,
        after=receipt_audit(row),
        reason="owner_concern_command_recorded",
        correlation_id=correlation,
    )
    return result
