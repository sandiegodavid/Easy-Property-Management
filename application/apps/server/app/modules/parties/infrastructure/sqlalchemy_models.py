"""SQLAlchemy metadata for the shared party identity."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
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

    __table_args__ = (
        CheckConstraint("party_kind IN ('individual', 'organization')"),
        CheckConstraint("length(trim(display_name)) > 0"),
        Index("parties_active_name", "archived_at", "display_name"),
    )


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
        CheckConstraint("(status = 'active' AND archived_at IS NULL) OR (status = 'archived' AND archived_at IS NOT NULL)"),
        CheckConstraint("method_kind = 'phone' OR extension IS NULL"),
        Index("party_contact_methods_party_status", "party_id", "status"),
        Index("party_contact_methods_one_active_value", "party_id", "method_kind", "normalized_value", text("coalesce(extension, '')"), unique=True, sqlite_where=text("status = 'active'")),
    )
