"""Inspection-owned concurrency and immutable command results."""

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from uuid import UUID
from typing import Protocol
from collections.abc import Mapping

from app.platform.command_recovery import CommandRecoveryReader


class InspectionRecoveryReader(CommandRecoveryReader, Protocol):
    def correction_payload(self, connection, source_id: str, payload: dict) -> Mapping: ...


class InspectionError(ValueError):
    pass


class InspectionNotFoundError(InspectionError):
    pass


class InspectionConflictError(InspectionError):
    pass


class InspectionRevisionConflict(InspectionConflictError):
    def __init__(self, current):
        super().__init__("Inspection changed. Review the current revision.")
        self.current = current


def validate_command(expected_revision, idempotency_key):
    if type(expected_revision) is not int or expected_revision < 0:
        raise InspectionError("Expected revision must be an exact non-negative integer.")
    try:
        if not isinstance(idempotency_key, str) or str(UUID(idempotency_key)) != idempotency_key:
            raise ValueError
    except ValueError as error:
        raise InspectionError("Idempotency key must be a canonical UUID.") from error


def canonical_json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda item: asdict(item) if is_dataclass(item) else _unsupported(item),
    )


def _unsupported(item):
    raise InspectionError(f"Unsupported command value: {type(item).__name__}.")


def fingerprint(action, request):
    return hashlib.sha256(
        canonical_json({"action": action, "request": request}).encode()
    ).hexdigest()


@dataclass(frozen=True)
class InspectionCommandReceipt:
    id: str
    idempotency_key: str
    action: str
    request_json: str
    request_fingerprint: str
    lease_id: str | None
    template_id: str | None
    revision: int
    result_json: str
    correlation_id: str
    created_at: str

    def result(self):
        return json.loads(self.result_json)

    def replay(self, action, request):
        if self.action != action or self.request_fingerprint != fingerprint(action, request):
            raise InspectionConflictError("Idempotency key was used for a different command.")
        return self.result()
