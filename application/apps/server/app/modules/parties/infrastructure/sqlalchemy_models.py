"""SQLAlchemy metadata for the shared party identity."""

from sqlalchemy import CheckConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class PartyModel(LocalBase):
    __tablename__ = "parties"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_kind: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        CheckConstraint("party_kind IN ('individual', 'organization')"),
        CheckConstraint("length(trim(display_name)) > 0"),
        Index("parties_active_name", "archived_at", "display_name"),
    )
