"""Immutable command identity and transaction-bound original-result recovery."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping
from uuid import uuid4

from app.modules.ai_governance.domain.models import (
    AiConflictError,
    AiValidationError,
    validate_uuid,
)


def command_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


@dataclass(frozen=True)
class AiCommand:
    action: str
    target_id: str
    expected_revision: int
    idempotency_key: str
    payload: Mapping[str, Any]
    operation_id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    request_json: str = field(init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise AiValidationError("expectedRevision must be an exact non-negative integer.")
        object.__setattr__(
            self, "idempotency_key", validate_uuid(self.idempotency_key, "idempotencyKey")
        )
        if self.action not in {
            "settings",
            "connection_create",
            "connection_update",
            "disclosure",
            "limit",
            "edited",
            "dismissed",
            "approved",
        }:
            raise AiValidationError("Unsupported AI command.")
        if self.action == "connection_create" and self.expected_revision != 0:
            raise AiValidationError("New connections require revision zero.")
        if self.action not in {"connection_create", "limit"} and self.expected_revision < 1:
            raise AiValidationError("expectedRevision must be positive for an existing record.")
        request = command_json(
            {
                "action": self.action,
                "targetId": self.target_id,
                "expectedRevision": self.expected_revision,
                "payload": dict(self.payload),
            }
        )
        object.__setattr__(self, "request_json", request)
        object.__setattr__(self, "fingerprint", sha256(request.encode()).hexdigest())


def replay_command(tx, command: AiCommand):
    prior = tx.command_by_key(command.idempotency_key)
    return _replay_result(prior, command)


def read_command_replay(unit_of_work, command: AiCommand):
    return _replay_result(unit_of_work.command_row(key=command.idempotency_key), command)


def _replay_result(prior, command):
    if prior is None:
        return None
    if prior["request_fingerprint"] != command.fingerprint:
        raise AiConflictError("ai_idempotency_conflict")
    return json.loads(prior["result_json"])


def require_revision(command: AiCommand, revision: int, current: Mapping[str, Any]) -> None:
    if command.expected_revision != revision:
        error = AiConflictError("ai_revision_conflict")
        error.current = dict(current)
        error.revision = revision
        raise error


def record_command(tx, command: AiCommand, result, stamp: str):
    result = {**result, "operationId": command.operation_id}
    row = {
        "id": command.operation_id,
        "idempotency_key": command.idempotency_key,
        "action": command.action,
        "target_id": command.target_id,
        "request_json": command.request_json,
        "request_fingerprint": command.fingerprint,
        "result_json": command_json(result),
        "correlation_id": command.correlation_id,
        "created_at": stamp,
    }
    tx.insert_command(row)
    tx.record_audit(
        entity_type="ai_command_operation",
        entity_id=row["id"],
        action="recorded",
        before=None,
        after={k: v for k, v in row.items() if k not in {"request_json", "result_json"}},
        correlation_id=command.correlation_id,
        actor="local_operator",
        reason="ai_command_recorded",
    )
    return result


def execute_command(tx, command: AiCommand, operation, stamp: str):
    prior = replay_command(tx, command)
    if prior is not None:
        return prior
    return record_command(tx, command, operation(), stamp)
