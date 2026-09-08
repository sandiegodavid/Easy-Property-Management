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
    property_type: Mapped[str] = mapped_column(String, nullable=False)
    inventory_layout: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("status IN ('active', 'archived')"), CheckConstraint("property_type IN ('single_family_home', 'condo', 'townhome', 'office')"), CheckConstraint("inventory_layout IN ('single_space', 'whole_office', 'office_suites')"), CheckConstraint("length(trim(display_name)) > 0"), CheckConstraint("length(trim(address_line_1)) > 0"), CheckConstraint("length(trim(city)) > 0"), CheckConstraint("length(trim(country_code)) = 2"), Index("properties_status_name", "status", "display_name"))


class PropertyOwnershipModel(LocalBase):
    __tablename__ = "property_ownerships"
    id: Mapped[str] = mapped_column(String, primary_key=True); property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), nullable=False)
    owner_kind: Mapped[str] = mapped_column(String, nullable=False); party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"))
    starts_on: Mapped[str] = mapped_column(String, nullable=False); ends_on: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False); ended_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (CheckConstraint("owner_kind IN ('local_operator', 'client_owner')"), CheckConstraint("(owner_kind = 'local_operator' AND party_id IS NULL) OR (owner_kind = 'client_owner' AND party_id IS NOT NULL)"), CheckConstraint("ends_on IS NULL OR ends_on >= starts_on"), Index("property_ownerships_property_active", "property_id", "ends_on"), Index("property_ownerships_party_active", "party_id", "ends_on"), Index("property_ownerships_one_active_operator", "property_id", unique=True, sqlite_where=text("owner_kind = 'local_operator' AND ends_on IS NULL")), Index("property_ownerships_one_active_client", "property_id", "party_id", unique=True, sqlite_where=text("owner_kind = 'client_owner' AND ends_on IS NULL")))


class SpaceModel(LocalBase):
    __tablename__ = "spaces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), nullable=False)
    space_kind: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    suite_or_floor: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    archived_by_property_operation_id: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("space_kind IN ('whole_home', 'whole_office', 'office_suite')"),
        CheckConstraint("status IN ('active', 'archived')"),
        CheckConstraint("length(trim(display_name)) > 0"),
        Index("spaces_property_status_name", "property_id", "status", "display_name"),
        Index(
            "spaces_one_active_name",
            "property_id",
            "normalized_name",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )


class SpaceOccupancyPeriodModel(LocalBase):
    __tablename__ = "space_occupancy_periods"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id"), nullable=False)
    occupancy_status: Mapped[str] = mapped_column(String, nullable=False)
    starts_on: Mapped[str] = mapped_column(String, nullable=False)
    ends_on: Mapped[str | None] = mapped_column(String)
    record_state: Mapped[str] = mapped_column(String, nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(ForeignKey("space_occupancy_periods.id"))
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String)
    cancelled_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("occupancy_status IN ('occupied', 'vacant', 'unknown')"),
        CheckConstraint("record_state IN ('valid', 'cancelled', 'superseded')"),
        CheckConstraint("ends_on IS NULL OR ends_on > starts_on"),
        CheckConstraint("(source_kind = 'manual' AND source_id IS NULL) OR (source_kind = 'lease' AND source_id IS NOT NULL)"),
        Index("space_occupancy_periods_space_dates", "space_id", "starts_on", "ends_on"),
        Index("space_occupancy_periods_one_open", "space_id", unique=True, sqlite_where=text("record_state = 'valid' AND ends_on IS NULL")),
    )


class SpaceAvailabilityModel(LocalBase):
    __tablename__ = "space_availability"
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id"), primary_key=True)
    availability_status: Mapped[str] = mapped_column(String, nullable=False)
    available_on: Mapped[str | None] = mapped_column(String)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("availability_status IN ('available_now', 'available_on', 'not_available', 'unknown')"),
        CheckConstraint("(availability_status = 'available_on' AND available_on IS NOT NULL) OR (availability_status != 'available_on' AND available_on IS NULL)"),
        CheckConstraint("(source_kind = 'manual' AND source_id IS NULL) OR (source_kind IN ('listing', 'lease') AND source_id IS NOT NULL)"),
        Index("space_availability_status_date", "availability_status", "available_on"),
    )
