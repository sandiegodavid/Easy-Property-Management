"""SQLAlchemy metadata for the shared party identity."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class PartyModel(LocalBase):
    __tablename__ = "parties"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_kind: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        CheckConstraint("party_kind IN ('individual', 'organization')"),
        CheckConstraint("length(trim(display_name)) > 0"),
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 1"),
        Index("parties_active_name", "archived_at", "display_name"),
    )


class PartyCommandOperationModel(LocalBase):
    __tablename__ = "party_command_operations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), nullable=False)
    contact_method_id: Mapped[str | None] = mapped_column(ForeignKey("party_contact_methods.id"))
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint(
            "action IN ('create','patch','archive','restore','contact_add','contact_update','contact_archive','contact_restore')"
        ),
        CheckConstraint(
            "(action IN ('contact_add','contact_update','contact_archive','contact_restore') AND contact_method_id IS NOT NULL) OR (action IN ('create','patch','archive','restore') AND contact_method_id IS NULL)"
        ),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 0"),
        CheckConstraint(
            "typeof(resulting_revision) = 'integer' AND resulting_revision IN (expected_revision, expected_revision + 1) AND resulting_revision >= 1"
        ),
        CheckConstraint(
            "action IN ('patch','contact_update') OR resulting_revision = expected_revision + 1"
        ),
        CheckConstraint(
            "(action = 'create' AND expected_revision = 0) OR (action != 'create' AND expected_revision >= 1)"
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json) AND json_valid(result_json)"),
        Index("party_command_operations_party", "party_id", "created_at"),
    )


PARTY_COMMAND_TRIGGERS = {
    f"party_command_operations_no_{action}": f"CREATE TRIGGER party_command_operations_no_{action} BEFORE {action.upper()} ON party_command_operations BEGIN SELECT RAISE(ABORT, 'party operations are immutable'); END"
    for action in ("update", "delete")
}
PARTY_COMMAND_TRIGGERS[
    "party_command_operations_no_replace"
] = """CREATE TRIGGER party_command_operations_no_replace BEFORE INSERT ON party_command_operations
WHEN EXISTS (SELECT 1 FROM party_command_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'party operations are immutable'); END"""


class PartyContactMethodModel(LocalBase):
    __tablename__ = "party_contact_methods"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), nullable=False)
    method_kind: Mapped[str] = mapped_column(String, nullable=False)
    display_value: Mapped[str] = mapped_column(String, nullable=False)
    normalized_value: Mapped[str] = mapped_column(String, nullable=False)
    extension: Mapped[str | None] = mapped_column(String)
    label: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        CheckConstraint("method_kind IN ('email', 'phone')"),
        CheckConstraint("status IN ('active', 'archived')"),
        CheckConstraint("length(trim(display_value)) > 0"),
        CheckConstraint(
            "(status = 'active' AND archived_at IS NULL) OR (status = 'archived' AND archived_at IS NOT NULL)"
        ),
        CheckConstraint("method_kind = 'phone' OR extension IS NULL"),
        Index("party_contact_methods_party_status", "party_id", "status"),
        Index(
            "party_contact_methods_one_active_value",
            "party_id",
            "method_kind",
            "normalized_value",
            text("coalesce(extension, '')"),
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )
