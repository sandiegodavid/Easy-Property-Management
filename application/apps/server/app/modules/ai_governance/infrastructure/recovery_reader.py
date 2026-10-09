"""Connection-bound AI state and immutable receipt metadata for composition."""

from sqlalchemy import func, select
from app.modules.ai_governance.domain.models import AiValidationError

from app.modules.ai_governance.infrastructure.sqlalchemy_models import (
    AiSettingsModel,
    AiModelConnectionModel,
    AiActionLimitModel,
    AiDraftModel,
    AiCommandOperationModel,
    AiExternalOperationModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteAiRecoveryReader:
    def __init__(self, kind, actions):
        self.kind, self.actions = kind, actions

    def state(self, connection, source_id):
        if self.kind == "ai_draft":
            model = AiDraftModel
            return (
                connection.execute(
                    select(model.version.label("revision"), model.status).where(
                        model.id == source_id
                    )
                )
                .mappings()
                .first()
            )
        models = {
            "ai_settings": (AiSettingsModel, AiSettingsModel.singleton),
            "ai_connection": (AiModelConnectionModel, AiModelConnectionModel.id),
            "ai_action_limit": (AiActionLimitModel, AiActionLimitModel.action_type),
        }
        model, identity = models[self.kind]
        if self.kind == "ai_action_limit":
            try:
                self.actions.require(source_id)
            except AiValidationError:
                return None
        columns = (model.revision,)
        if self.kind == "ai_connection":
            columns += (model.execution_location,)
            columns += (
                select(AiExternalOperationModel.id)
                .where(
                    AiExternalOperationModel.connection_id == model.id,
                    AiExternalOperationModel.result_json.is_(None),
                )
                .exists()
                .label("external_pending"),
            )
        row = connection.execute(select(*columns).where(identity == source_id)).mappings().first()
        if row is None:
            return (
                {"revision": 0, "status": "available"} if self.kind == "ai_action_limit" else None
            )
        return {**row, "status": "available"}

    def outcome(self, connection, key, *, family):
        if family == "ai_external":
            model = AiExternalOperationModel
            row = (
                connection.execute(
                    select(
                        model.id,
                        model.action,
                        model.connection_id,
                        model.request_fingerprint,
                        model.revision,
                        func.json_extract(model.result_json, "$.status").label("status"),
                    ).where(model.idempotency_key == key)
                )
                .mappings()
                .first()
            )
            if row is None or row["status"] is None:
                return None
            return CommandOutcome(
                row["id"],
                row["action"],
                row["connection_id"],
                row["request_fingerprint"],
                CommandResult(row["connection_id"], row["revision"], row["status"]),
            )
        if family != "ai":
            raise ValueError("Unsupported AI command family.")
        model = AiCommandOperationModel
        row = (
            connection.execute(
                select(
                    model.id,
                    model.action,
                    model.target_id,
                    model.request_fingerprint,
                    func.json_extract(model.result_json, "$.id").label("connection_id"),
                    func.json_extract(model.result_json, "$.revision").label("revision"),
                    func.json_extract(model.result_json, "$.version").label("version"),
                    func.json_extract(model.result_json, "$.status").label("status"),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        target = row["connection_id"] if row["action"] == "connection_create" else row["target_id"]
        return CommandOutcome(
            row["id"],
            row["action"],
            target,
            row["request_fingerprint"],
            CommandResult(
                target,
                row["revision"] if row["revision"] is not None else row["version"],
                row["status"],
            ),
        )
