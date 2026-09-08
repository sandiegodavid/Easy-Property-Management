"""SQLAlchemy metadata owned by TEN-001."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class TenantProfileModel(LocalBase):
    __tablename__ = "tenant_profiles"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), primary_key=True)
    preferred_contact_method_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_contact_methods.id"))
    do_not_contact: Mapped[int] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        CheckConstraint("do_not_contact IN (0, 1)"),
        Index("tenant_profiles_active_name", "archived_at"),
    )


class TenantContactMethodModel(LocalBase):
    __tablename__ = "tenant_contact_methods"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("tenant_profiles.party_id"), nullable=False)
    method_kind: Mapped[str] = mapped_column(String, nullable=False)
    display_value: Mapped[str] = mapped_column(String, nullable=False)
    normalized_value: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        CheckConstraint("method_kind IN ('email', 'phone')"),
        CheckConstraint("status IN ('active', 'archived')"),
        CheckConstraint("length(trim(display_value)) > 0"),
        Index("tenant_contact_methods_party_status", "party_id", "status"),
        Index("tenant_contact_methods_one_active_value", "party_id", "method_kind", "normalized_value", unique=True, sqlite_where=text("status = 'active'")),
    )
