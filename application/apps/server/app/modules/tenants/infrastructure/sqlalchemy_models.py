"""SQLAlchemy metadata owned by TEN-001."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import (
    CommandOperationColumns,
    LocalBase,
    immutable_command_triggers,
)


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
    official_ids_json: Mapped[str] = mapped_column(String, nullable=False, server_default="[]")

    __table_args__ = (
        CheckConstraint("do_not_contact IN (0, 1)"),
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 1"),
        CheckConstraint(
            "json_valid(official_ids_json) AND json_type(official_ids_json) = 'array' AND json_array_length(official_ids_json) <= 10"
        ),
        Index("tenant_profiles_active_name", "archived_at"),
    )


class TenantCommandOperationModel(CommandOperationColumns, LocalBase):
    __tablename__ = "tenant_command_operations"

    party_id: Mapped[str] = mapped_column(ForeignKey("tenant_profiles.party_id"), nullable=False)

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


TENANT_COMMAND_TRIGGERS = immutable_command_triggers(
    "tenant_command_operations", "tenant operations are immutable"
)
