"""Portable, immutable FILE-001 command identities and outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from app.modules.files.application.errors import FileError


def command_key(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except ValueError as error:
        raise FileError("Idempotency key must be a canonical UUID.") from error
    return value


def command_json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def command_fingerprint(action: str, request: dict[str, object]) -> str:
    return hashlib.sha256(command_json({"action": action, "request": request}).encode()).hexdigest()


@dataclass(frozen=True)
class FileCommandReceipt:
    id: str
    idempotency_key: str
    action: str
    request_fingerprint: str
    request_json: str
    file_id: str
    link_id: str
    result_json: str
    correlation_id: str
    created_at: str

    def result(self) -> dict[str, object]:
        return json.loads(self.result_json)

    def replay(self, action: str, request: dict[str, object]) -> dict[str, object]:
        if self.action != action or self.request_fingerprint != command_fingerprint(
            action, request
        ):
            raise FileError(
                "Idempotency key was used for a different command.", "file_command_conflict"
            )
        return self.result()


class FileRevisionConflict(FileError):
    def __init__(self, current: dict[str, object]) -> None:
        super().__init__("File link changed. Review its current state.", "file_revision_conflict")
        self.current = current
