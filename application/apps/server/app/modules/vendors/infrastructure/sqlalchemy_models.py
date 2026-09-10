"""SQLAlchemy metadata owned by the provider module."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class ProviderProfileModel(LocalBase):
    __tablename__ = "provider_profiles"
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), primary_key=True)
    selection_status: Mapped[str] = mapped_column(String, nullable=False)
    selection_reason: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("selection_status IN ('neutral', 'preferred', 'avoid')"),
        CheckConstraint("selection_status != 'avoid' OR (selection_reason IS NOT NULL AND length(trim(selection_reason)) > 0)"),
        Index("provider_profiles_selection", "archived_at", "selection_status"),
    )


class ProviderServiceModel(LocalBase):
    __tablename__ = "provider_services"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("provider_profiles.party_id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("length(trim(display_name)) > 0"),
        Index("provider_services_party_status", "party_id", "archived_at"),
        Index("provider_services_one_active_name", "party_id", "normalized_name", unique=True,
              sqlite_where=text("archived_at IS NULL")),
    )


class ProviderServiceAreaModel(LocalBase):
    __tablename__ = "provider_service_areas"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("provider_profiles.party_id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    country_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("length(trim(display_name)) > 0"),
        CheckConstraint("country_code = '' OR (length(country_code) = 2 AND country_code = upper(country_code) AND country_code GLOB '[A-Z][A-Z]')"),
        Index("provider_service_areas_party_status", "party_id", "archived_at"),
        Index("provider_service_areas_one_active_name", "party_id", "normalized_name", "country_code", unique=True,
              sqlite_where=text("archived_at IS NULL")),
    )


class ProviderWorkHistoryModel(LocalBase):
    __tablename__ = "provider_work_history"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("provider_profiles.party_id"), nullable=False)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id"))
    performed_on: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    outcome_notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("length(trim(summary)) > 0"),
        Index("provider_work_history_party_status", "party_id", "archived_at", "performed_on"),
        Index("provider_work_history_property", "property_id", "archived_at"),
    )


class ProviderReferenceModel(LocalBase):
    __tablename__ = "provider_references"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("provider_profiles.party_id"), nullable=False)
    reference_name: Mapped[str | None] = mapped_column(String)
    organization_name: Mapped[str | None] = mapped_column(String)
    relationship: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("length(trim(coalesce(reference_name, ''))) > 0 OR length(trim(coalesce(organization_name, ''))) > 0 OR length(trim(coalesce(relationship, ''))) > 0"),
        Index("provider_references_party_status", "party_id", "archived_at"),
    )


class ProviderReputationLinkModel(LocalBase):
    __tablename__ = "provider_reputation_links"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("provider_profiles.party_id"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String)
    normalized_source_key: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    normalized_url: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String)
    last_checked_on: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("source_kind IN ('google', 'yelp', 'angi', 'other')"),
        CheckConstraint(
            "(source_kind IN ('google', 'yelp', 'angi') AND source_name IS NULL) "
            "OR (source_kind = 'other' AND source_name IS NOT NULL AND length(trim(source_name)) > 0)"
        ),
        CheckConstraint("length(trim(normalized_source_key)) > 0"),
        CheckConstraint("length(trim(url)) > 0"),
        CheckConstraint("length(trim(normalized_url)) > 0"),
        Index("provider_reputation_links_party_status", "party_id", "archived_at"),
        Index(
            "provider_reputation_links_one_active_source",
            "party_id", "normalized_source_key",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
        Index(
            "provider_reputation_links_one_active_url",
            "party_id", "normalized_url",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
    )
