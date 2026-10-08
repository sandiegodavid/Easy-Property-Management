from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase

MUTATION_INSERT_GUARD = """CREATE TRIGGER task_mutation_operations_no_replace
BEFORE INSERT ON task_mutation_operations
WHEN EXISTS (SELECT 1 FROM task_mutation_operations
 WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key
 OR (task_id = NEW.task_id AND resulting_revision = NEW.resulting_revision
     AND resulting_revision > expected_revision
     AND NEW.resulting_revision > NEW.expected_revision))
BEGIN SELECT RAISE(ABORT, 'task mutation operations are append-only'); END"""

WAITING_CHECKS = (
    "typeof(revision) = 'integer' AND revision >= 1",
    "deleted_at_utc IS NULL OR (status = 'open' AND waiting_for_kind IS NULL)",
    "waiting_for_kind IS NULL OR waiting_for_kind IN ('person','organization','event','other')",
    "(waiting_for_kind IS NULL AND waiting_for_label IS NULL AND waiting_set_at_utc IS NULL) OR (waiting_for_kind IS NOT NULL AND waiting_for_label IS NOT NULL AND waiting_set_at_utc IS NOT NULL AND waiting_cleared_at_utc IS NULL)",
    "waiting_for_label IS NULL OR (length(waiting_for_label) BETWEEN 1 AND 255 AND waiting_for_label = trim(waiting_for_label))",
    "(follow_up_at_utc IS NULL AND follow_up_timezone IS NULL) OR (follow_up_at_utc IS NOT NULL AND follow_up_timezone IS NOT NULL AND waiting_for_kind IS NOT NULL)",
    "status IN ('open','in_progress') OR waiting_for_kind IS NULL",
)


class TaskModel(LocalBase):
    __tablename__ = "tasks"
    deleted_at_utc: Mapped[str | None] = mapped_column(String)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)
    due_at_utc: Mapped[str | None] = mapped_column(String)
    due_timezone: Mapped[str | None] = mapped_column(String)
    is_all_day: Mapped[int] = mapped_column(Integer)
    completed_at_utc: Mapped[str | None] = mapped_column(String)
    cancelled_at_utc: Mapped[str | None] = mapped_column(String)
    outcome_note: Mapped[str | None] = mapped_column(String)
    related_entity_type: Mapped[str | None] = mapped_column(String)
    related_entity_id: Mapped[str | None] = mapped_column(String)
    related_label: Mapped[str | None] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String)
    updated_at_utc: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    waiting_for_kind: Mapped[str | None] = mapped_column(String)
    waiting_for_label: Mapped[str | None] = mapped_column(String)
    follow_up_at_utc: Mapped[str | None] = mapped_column(String)
    follow_up_timezone: Mapped[str | None] = mapped_column(String)
    waiting_set_at_utc: Mapped[str | None] = mapped_column(String)
    waiting_cleared_at_utc: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("status IN ('open', 'in_progress', 'completed', 'cancelled')"),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')"),
        CheckConstraint("is_all_day IN (0, 1)"),
        Index("tasks_status_due", "status", "due_at_utc"),
        Index("tasks_related_record", "related_entity_type", "related_entity_id"),
        Index("tasks_waiting_follow_up", "status", "waiting_for_kind", "follow_up_at_utc"),
        *(CheckConstraint(check) for check in WAITING_CHECKS),
    )


class TaskReminderModel(LocalBase):
    __tablename__ = "task_reminders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    remind_at_utc: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    acknowledged_at_utc: Mapped[str | None] = mapped_column(String)
    dismissed_at_utc: Mapped[str | None] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'acknowledged', 'dismissed')"),
        Index("task_reminders_status_time", "status", "remind_at_utc"),
    )


class TaskWaitingOperationModel(LocalBase):
    __tablename__ = "task_waiting_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    action: Mapped[str] = mapped_column(String)
    request_fingerprint: Mapped[str] = mapped_column(String)
    expected_revision: Mapped[int] = mapped_column(Integer)
    resulting_revision: Mapped[int] = mapped_column(Integer)
    result_json: Mapped[str] = mapped_column(String)
    correlation_id: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String)
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint("action IN ('set','clear','reschedule')"),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 1"),
        CheckConstraint(
            "typeof(resulting_revision) = 'integer' AND resulting_revision IN (expected_revision, expected_revision + 1)"
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(result_json)"),
        CheckConstraint("json_valid(request_json)"),
        Index("task_waiting_operations_task", "task_id", "created_at_utc"),
    )
    request_json: Mapped[str] = mapped_column(String)


class TaskMutationOperationModel(LocalBase):
    __tablename__ = "task_mutation_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    action: Mapped[str] = mapped_column(String)
    expected_revision: Mapped[int] = mapped_column(Integer)
    resulting_revision: Mapped[int] = mapped_column(Integer)
    request_fingerprint: Mapped[str] = mapped_column(String)
    request_json: Mapped[str] = mapped_column(String)
    result_json: Mapped[str] = mapped_column(String)
    correlation_id: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String)
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index(
            "task_mutations_effective_revision",
            "task_id",
            "resulting_revision",
            unique=True,
            sqlite_where=text("resulting_revision > expected_revision"),
        ),
        CheckConstraint(
            "action IN ('start','reopen','complete','cancel','add_reminder','acknowledge','dismiss','edit','delete')"
        ),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 1"),
        CheckConstraint(
            "typeof(resulting_revision) = 'integer' AND resulting_revision IN (expected_revision, expected_revision + 1) AND (action = 'edit' OR resulting_revision = expected_revision + 1)"
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json)"),
        CheckConstraint("json_valid(result_json)"),
    )


class TaskCreationOperationModel(LocalBase):
    __tablename__ = "task_creation_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    request_fingerprint: Mapped[str] = mapped_column(String)
    request_json: Mapped[str] = mapped_column(String)
    result_json: Mapped[str] = mapped_column(String)
    correlation_id: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String)
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        UniqueConstraint("task_id"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json)"),
        CheckConstraint("json_valid(result_json)"),
    )
