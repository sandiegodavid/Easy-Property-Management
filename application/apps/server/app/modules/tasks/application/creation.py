"""Durable TASK creation identity and source-owned recovery receipts."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from json import dumps
from typing import Any, Mapping, Protocol
from uuid import UUID

from app.modules.tasks.application.service import TaskCreateCommand, TaskError


def canonical(value):
    return dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def creation_request(command: TaskCreateCommand, expected_revision: int):
    if type(expected_revision) is not int or expected_revision != 0:
        raise TaskError("Task creation requires expected revision zero.")
    return {"action": "create", "expectedRevision": 0, "command": asdict(command)}


def creation_fingerprint(command: TaskCreateCommand, expected_revision: int = 0):
    return sha256(canonical(creation_request(command, expected_revision)).encode()).hexdigest()


def creation_key(value: str):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise TaskError("Task creation requires a canonical UUID idempotency key.") from error


@dataclass(frozen=True)
class TaskCreationOperation:
    id: str
    idempotency_key: str
    task_id: str
    request_fingerprint: str
    request_json: str
    result_json: str
    correlation_id: str
    created_at_utc: str

    def audit_snapshot(self):
        return {
            "id": self.id,
            "taskId": self.task_id,
            "action": "create",
            "expectedRevision": 0,
            "resultingRevision": 1,
            "createdAtUtc": self.created_at_utc,
        }


class TaskCreationReceiptReader(Protocol):
    def receipt(self, connection: Any, key: str) -> Mapping[str, object] | None: ...
