"""Task-owned keyed lookup; no replay dispatch or independent session."""

from sqlalchemy import select, func

from app.platform.command_recovery import CommandOutcome, CommandResult
from app.modules.tasks.infrastructure.sqlalchemy_models import (
    TaskModel,
    TaskMutationOperationModel,
    TaskWaitingOperationModel,
    TaskReminderModel,
)


class SQLiteTaskRecoveryReader:
    def related_state(self, connection, kind, target_id):
        return (
            connection.execute(
                select(
                    TaskReminderModel.task_id.label("source_id"), TaskReminderModel.status
                ).where(TaskReminderModel.id == target_id)
            )
            .mappings()
            .first()
        )

    def state(self, connection, source_id):
        return (
            connection.execute(
                select(TaskModel.revision, TaskModel.status, TaskModel.deleted_at_utc).where(
                    TaskModel.id == source_id
                )
            )
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        model = TaskWaitingOperationModel if family == "waiting" else TaskMutationOperationModel
        target_path = "$.id" if family == "waiting" else "$.task.id"
        status_path = "$.status" if family == "waiting" else "$.task.status"
        row = (
            connection.execute(
                select(
                    model.id,
                    model.action,
                    model.task_id,
                    model.request_fingerprint,
                    func.json_extract(model.result_json, target_path).label("target_id"),
                    func.json_extract(model.result_json, "$.revision").label("revision"),
                    func.json_extract(model.result_json, status_path).label("status"),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return CommandOutcome(
            row["id"],
            row["action"],
            row["task_id"],
            row["request_fingerprint"],
            CommandResult(row["target_id"], row["revision"], row["status"]),
        )
