"""Explicit Slice 33 Files recovery composition; never publishes content."""

from app.bootstrap.file_link_policies import build_file_link_policy_registry
from app.modules.files.application.commands import (
    FileCommandRecoveryReader,
    upload_request,
    archive_request,
    command_fingerprint,
)
from app.modules.files.application.errors import FileError
from app.modules.files.infrastructure.recovery_reader import SQLiteFileRecoveryReader
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError


def file_fingerprint(action, source_id, payload, key):
    del key  # FILE-001 keys identify operations but are not semantic payload fields.
    try:
        if action == "upload":
            if payload.get("expectedRevision") != 0:
                raise OperatorError("File upload preparation requires revision zero.")
            request = upload_request(
                payload.get("originalName"),
                payload.get("mediaType"),
                payload.get("contentSha256"),
                payload.get("entityType"),
                payload.get("entityId"),
                payload.get("purpose"),
            )
        else:
            request = archive_request(
                source_id,
                payload.get("confirmed"),
                payload.get("reason"),
                payload.get("expectedRevision"),
            )
        return command_fingerprint(action, request)
    except FileError as error:
        raise OperatorError("Complete a valid owning Files command.") from error


def compose_file_forms():
    reader: FileCommandRecoveryReader = SQLiteFileRecoveryReader(build_file_link_policy_registry())
    return {
        "file.upload": RecoveryBinding(
            None,
            "upload",
            "file",
            reader,
            lambda source, payload, key: file_fingerprint("upload", source, payload, key),
            "file",
        ),
        "file.link.archive": RecoveryBinding(
            "file_link",
            "archive_link",
            "file",
            reader,
            lambda source, payload, key: file_fingerprint("archive_link", source, payload, key),
            "file_link",
        ),
    }
