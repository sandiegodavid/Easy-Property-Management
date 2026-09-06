"""SQLAlchemy metadata for PORT-001."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class PartyModel(LocalBase):
    __tablename__ = "parties"
    id: Mapped[str] = mapped_column(String, primary_key=True); party_kind: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False); email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String); created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False); archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (CheckConstraint("party_kind IN ('individual', 'organization')"), CheckConstraint("length(trim(display_name)) > 0"), Index("parties_active_name", "archived_at", "display_name"))


class PropertyModel(LocalBase):
    __tablename__ = "properties"
    id: Mapped[str] = mapped_column(String, primary_key=True); display_name: Mapped[str] = mapped_column(String, nullable=False)
    address_line_1: Mapped[str] = mapped_column(String, nullable=False); address_line_2: Mapped[str | None] = mapped_column(String)
    city: Mapped[str] = mapped_column(String, nullable=False); region: Mapped[str | None] = mapped_column(String)
    postal_code: Mapped[str | None] = mapped_column(String); country_code: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String); status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False); updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (CheckConstraint("status IN ('active', 'archived')"), CheckConstraint("length(trim(display_name)) > 0"), CheckConstraint("length(trim(address_line_1)) > 0"), CheckConstraint("length(trim(city)) > 0"), CheckConstraint("length(trim(country_code)) = 2"), Index("properties_status_name", "status", "display_name"))


class PropertyOwnershipModel(LocalBase):
    __tablename__ = "property_ownerships"
    id: Mapped[str] = mapped_column(String, primary_key=True); property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), nullable=False)
    owner_kind: Mapped[str] = mapped_column(String, nullable=False); party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"))
    starts_on: Mapped[str] = mapped_column(String, nullable=False); ends_on: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False); ended_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (CheckConstraint("owner_kind IN ('local_operator', 'client_owner')"), CheckConstraint("(owner_kind = 'local_operator' AND party_id IS NULL) OR (owner_kind = 'client_owner' AND party_id IS NOT NULL)"), CheckConstraint("ends_on IS NULL OR ends_on >= starts_on"), Index("property_ownerships_property_active", "property_id", "ends_on"), Index("property_ownerships_party_active", "party_id", "ends_on"), Index("property_ownerships_one_active_operator", "property_id", unique=True, sqlite_where=text("owner_kind = 'local_operator' AND ends_on IS NULL")), Index("property_ownerships_one_active_client", "property_id", "party_id", unique=True, sqlite_where=text("owner_kind = 'client_owner' AND ends_on IS NULL")))
