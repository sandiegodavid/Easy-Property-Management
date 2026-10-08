"""SQLAlchemy metadata owned by TEN-001."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class TenantProfileModel(LocalBase):
    __tablename__ = "tenant_profiles"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), primary_key=True)
    preferred_contact_method_id: Mapped[str | None] = mapped_column(
        ForeignKey("party_contact_methods.id")
    )
    do_not_contact: Mapped[int] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    revision: Mapped[int] = mapped_column(nullable=False, server_default="1")

    __table_args__ = (
        CheckConstraint("do_not_contact IN (0, 1)"),
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 1"),
        Index("tenant_profiles_active_name", "archived_at"),
    )


class TenantCommandOperationModel(LocalBase):
    __tablename__ = "tenant_command_operations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("tenant_profiles.party_id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_json: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    expected_revision: Mapped[int] = mapped_column(nullable=False)
    resulting_revision: Mapped[int] = mapped_column(nullable=False)
    result_json: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "action IN ('create','designate','patch','archive','restore','resolve_contact')"
        ),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 0"),
        CheckConstraint(
            "typeof(resulting_revision) = 'integer' AND resulting_revision >= 1 AND resulting_revision IN (expected_revision, expected_revision + 1)"
        ),
        CheckConstraint(
            "(action IN ('create','designate') AND expected_revision = 0) OR (action NOT IN ('create','designate') AND expected_revision >= 1)"
        ),
        CheckConstraint("action = 'patch' OR resulting_revision = expected_revision + 1"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json) AND json_valid(result_json)"),
        Index("tenant_command_operations_party", "party_id", "created_at"),
    )


TENANT_COMMAND_TRIGGERS = {
    f"tenant_command_operations_no_{action}": f"CREATE TRIGGER tenant_command_operations_no_{action} BEFORE {action.upper()} ON tenant_command_operations BEGIN SELECT RAISE(ABORT, 'tenant operations are immutable'); END"
    for action in ("update", "delete")
}
TENANT_COMMAND_TRIGGERS[
    "tenant_command_operations_no_replace"
] = """CREATE TRIGGER tenant_command_operations_no_replace BEFORE INSERT ON tenant_command_operations
WHEN EXISTS (SELECT 1 FROM tenant_command_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'tenant operations are immutable'); END"""
