from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase


class TaskModel(LocalBase):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True); title: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String); status: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String); due_at_utc: Mapped[str | None] = mapped_column(String)
    due_timezone: Mapped[str | None] = mapped_column(String); is_all_day: Mapped[int] = mapped_column(Integer)
    completed_at_utc: Mapped[str | None] = mapped_column(String); cancelled_at_utc: Mapped[str | None] = mapped_column(String)
    outcome_note: Mapped[str | None] = mapped_column(String); related_entity_type: Mapped[str | None] = mapped_column(String)
    related_entity_id: Mapped[str | None] = mapped_column(String); related_label: Mapped[str | None] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String); updated_at_utc: Mapped[str] = mapped_column(String)
    __table_args__ = (CheckConstraint("status IN ('open', 'in_progress', 'completed', 'cancelled')"), CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')"), CheckConstraint("is_all_day IN (0, 1)"), Index("tasks_status_due", "status", "due_at_utc"), Index("tasks_related_record", "related_entity_type", "related_entity_id"))


class TaskReminderModel(LocalBase):
    __tablename__ = "task_reminders"
    id: Mapped[str] = mapped_column(String, primary_key=True); task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    remind_at_utc: Mapped[str] = mapped_column(String); status: Mapped[str] = mapped_column(String)
    acknowledged_at_utc: Mapped[str | None] = mapped_column(String); dismissed_at_utc: Mapped[str | None] = mapped_column(String)
    created_at_utc: Mapped[str] = mapped_column(String)
    __table_args__ = (CheckConstraint("status IN ('pending', 'acknowledged', 'dismissed')"), Index("task_reminders_status_time", "status", "remind_at_utc"))
