"""Portable, immutable FILE-001 command identities and outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID
import re
from collections.abc import Mapping
from typing import Protocol

from app.platform.command_recovery import CommandRecoveryReader

from app.modules.files.application.errors import FileError, normalize_filename, normalize_media_type


class FileCommandRecoveryReader(CommandRecoveryReader, Protocol):
    """Read-only command gates on the composition owner's existing transaction."""

    def creation_state(self, connection, payload: Mapping) -> str: ...
    def archival_state(self, connection, source_id: str) -> str: ...


def link_fields(entity_type: str, entity_id: str, purpose: str) -> tuple[str, str, str]:
    if not isinstance(entity_type, str) or not (entity_type := entity_type.strip()):
        raise FileError("A file link requires a nonblank entity type.")
    if not isinstance(entity_id, str) or not (entity_id := entity_id.strip()):
        raise FileError("A file link requires a nonblank entity ID.")
    if not isinstance(purpose, str) or not (purpose := purpose.strip()):
        raise FileError("File link purpose must be nonblank text.")
    return entity_type, entity_id, purpose


def upload_request(original_name, media_type, digest, entity_type, entity_id, purpose):
    name, mime = normalize_filename(original_name), normalize_media_type(media_type)
    entity_type, entity_id, purpose = link_fields(entity_type, entity_id, purpose)
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise FileError("Content hash must be lowercase SHA-256.")
    return {
        "originalName": name,
        "mediaType": mime,
        "contentSha256": digest,
        "entityType": entity_type,
        "entityId": entity_id,
        "purpose": purpose,
    }


def archive_request(link_id, confirmed, reason, expected_revision):
    if type(expected_revision) is not int or expected_revision < 1:
        raise FileError("Expected revision must be a positive integer.")
    if (
        confirmed is not True
        or not isinstance(reason, str)
        or not (reason := reason.strip())
        or len(reason) > 1000
    ):
        raise FileError("Archive requires confirmation and a bounded reason.")
    return {
        "linkId": link_id,
        "confirmed": True,
        "reason": reason,
        "expectedRevision": expected_revision,
    }


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
