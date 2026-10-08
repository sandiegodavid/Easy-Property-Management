"""Append-only, lease- or template-scoped inspection command receipts."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class InspectionCommandOperationModel(LocalBase):
    __tablename__ = "inspection_command_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    lease_id: Mapped[str | None] = mapped_column(String, ForeignKey("leases.id"))
    template_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("condition_checklist_templates.id")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("(lease_id IS NULL) != (template_id IS NULL)"),
        CheckConstraint("typeof(revision) = 'integer' AND revision > 0"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json) AND json_valid(result_json)"),
        CheckConstraint(
            "action IN ('report.create','report.patch','report.areas','report.acknowledge','report.finalize','comparison.review','evidence.attach','template.create','template.patch')"
        ),
        Index("inspection_commands_key", "idempotency_key", unique=True),
        Index("inspection_commands_lease_revision", "lease_id", "revision", unique=True),
        Index("inspection_commands_template_revision", "template_id", "revision", unique=True),
    )


INSPECTION_COMMAND_TRIGGERS = {
    f"inspection_commands_no_{action}": (
        f"CREATE TRIGGER inspection_commands_no_{action} BEFORE {action.upper()} "
        "ON inspection_command_operations BEGIN SELECT RAISE(ABORT, 'Inspection receipts are immutable'); END"
    )
    for action in ("update", "delete")
}
INSPECTION_COMMAND_TRIGGERS["inspection_commands_no_replace"] = (
    "CREATE TRIGGER inspection_commands_no_replace BEFORE INSERT ON inspection_command_operations "
    "WHEN EXISTS (SELECT 1 FROM inspection_command_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key "
    "OR (lease_id = NEW.lease_id AND revision = NEW.revision) OR (template_id = NEW.template_id AND revision = NEW.revision)) "
    "BEGIN SELECT RAISE(ABORT, 'Inspection receipts are immutable'); END"
)
