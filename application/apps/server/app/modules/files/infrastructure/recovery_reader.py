"""Transaction-aware Files command state and immutable metadata-only outcomes."""

from sqlalchemy import select, func, case

from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileLink, FileLinkPolicyRegistry
from app.modules.files.infrastructure.sqlalchemy_models import (
    FileLinkModel,
    FileCommandOperationModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteFileRecoveryReader:
    def __init__(self, policies: FileLinkPolicyRegistry):
        self.policies = policies

    def state(self, connection, source_id):
        return (
            connection.execute(
                select(
                    case((FileLinkModel.archived_at.is_(None), 1), else_=2).label("revision"),
                    case((FileLinkModel.archived_at.is_(None), "active"), else_="archived").label(
                        "status"
                    ),
                ).where(FileLinkModel.id == source_id)
            )
            .mappings()
            .first()
        )

    def creation_state(self, connection, payload):
        if any(payload.get(field) is None for field in ("entityType", "entityId", "purpose")):
            return "available"  # incomplete autosave, not an executable upload
        policy = self.policies.get(payload["entityType"].strip())
        if policy is None or not policy.allows_generic_upload:
            return "source_unavailable"
        link = FileLink(
            "00000000-0000-0000-0000-000000000000",
            payload["entityType"].strip(),
            payload["entityId"],
            payload["purpose"].strip(),
            "",
        )
        try:
            policy.validate_create(connection, link)
        except FileError, ValueError:
            return "source_unavailable"
        return "available"

    def archival_state(self, connection, source_id):
        row = (
            connection.execute(select(FileLinkModel.__table__).where(FileLinkModel.id == source_id))
            .mappings()
            .first()
        )
        if row is None or row["archived_at"] is not None:
            return "source_unavailable"
        policy = self.policies.get(row["entity_type"])
        if policy is None:
            return "source_unavailable"
        try:
            policy.validate_archive(connection, FileLink(**row))
        except FileError, ValueError:
            return "source_unavailable"
        return "available"

    def outcome(self, connection, key, *, family):
        if family != "file":
            raise ValueError("Unsupported Files recovery family.")
        model = FileCommandOperationModel
        row = (
            connection.execute(
                select(
                    model.id,
                    model.action,
                    model.file_id,
                    model.link_id,
                    model.request_fingerprint,
                    case(
                        (
                            model.action == "upload",
                            func.json_extract(model.result_json, "$.links[0].revision"),
                        ),
                        else_=func.json_extract(model.result_json, "$.revision"),
                    ).label("revision"),
                    case(
                        (
                            model.action == "upload",
                            func.json_extract(model.result_json, "$.storageState"),
                        ),
                        else_="archived",
                    ).label("status"),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        target = row["file_id"] if row["action"] == "upload" else row["link_id"]
        return CommandOutcome(
            row["id"],
            row["action"],
            target,
            row["request_fingerprint"],
            CommandResult(
                target,
                row["revision"],
                row["status"],
                file_id=row["file_id"],
                link_id=row["link_id"],
            ),
        )
