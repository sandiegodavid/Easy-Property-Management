"""SQLAlchemy metadata owned by TEN-001."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class TenantProfileModel(LocalBase):
    __tablename__ = "tenant_profiles"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), primary_key=True)
    preferred_contact_method_id: Mapped[str | None] = mapped_column(ForeignKey("party_contact_methods.id"))
    do_not_contact: Mapped[int] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        CheckConstraint("do_not_contact IN (0, 1)"),
        Index("tenant_profiles_active_name", "archived_at"),
    )
