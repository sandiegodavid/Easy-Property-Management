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
    revision: Mapped[int] = mapped_column(nullable=False, server_default="1")
    __table_args__ = (
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 1"),
        CheckConstraint("selection_status IN ('neutral', 'preferred', 'avoid')"),
        CheckConstraint(
            "selection_status != 'avoid' OR (selection_reason IS NOT NULL AND length(trim(selection_reason)) > 0)"
        ),
        Index("provider_profiles_selection", "archived_at", "selection_status"),
    )


class ProviderCommandOperationModel(LocalBase):
    __tablename__ = "provider_command_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("provider_profiles.party_id"), nullable=False)
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
            "action IN ('create','designate','patch','archive','restore','assignment_create','assignment_archive','assignment_restore',"
            + ",".join(
                f"'{kind}_{verb}'"
                for kind in ("service", "area", "work", "reference", "reputation")
                for verb in ("create", "update", "archive", "restore")
            )
            + ")"
        ),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 0"),
        CheckConstraint(
            "typeof(resulting_revision) = 'integer' AND resulting_revision >= 1 AND resulting_revision IN (expected_revision, expected_revision + 1)"
        ),
        CheckConstraint(
            "(action IN ('create','designate') AND expected_revision = 0) OR (action NOT IN ('create','designate') AND expected_revision >= 1)"
        ),
        CheckConstraint(
            "action IN ('patch','service_update','area_update','work_update','reference_update','reputation_update','assignment_archive','assignment_restore') OR resulting_revision = expected_revision + 1"
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json) AND json_valid(result_json)"),
        Index("provider_command_operations_party", "party_id", "created_at"),
    )


PROVIDER_COMMAND_TRIGGERS = {
    f"provider_command_operations_no_{action}": f"CREATE TRIGGER provider_command_operations_no_{action} BEFORE {action.upper()} ON provider_command_operations BEGIN SELECT RAISE(ABORT, 'provider operations are immutable'); END"
    for action in ("update", "delete")
}
PROVIDER_COMMAND_TRIGGERS[
    "provider_command_operations_no_replace"
] = """CREATE TRIGGER provider_command_operations_no_replace BEFORE INSERT ON provider_command_operations
WHEN EXISTS (SELECT 1 FROM provider_command_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'provider operations are immutable'); END"""


class ProviderCategoryCommandOperationModel(LocalBase):
    __tablename__ = "provider_category_command_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("provider_categories.id"), nullable=False)
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
        CheckConstraint("action IN ('create','patch','archive','restore')"),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 0"),
        CheckConstraint(
            "typeof(resulting_revision) = 'integer' AND resulting_revision >= 1 AND resulting_revision IN (expected_revision, expected_revision + 1)"
        ),
        CheckConstraint(
            "(action IN ('create') AND expected_revision = 0) OR (action NOT IN ('create') AND expected_revision >= 1)"
        ),
        CheckConstraint("action != 'create' OR resulting_revision = expected_revision + 1"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json) AND json_valid(result_json)"),
        Index("provider_category_command_operations_category", "category_id", "created_at"),
    )


CATEGORY_COMMAND_TRIGGERS = {
    f"provider_category_command_operations_no_{action}": f"CREATE TRIGGER provider_category_command_operations_no_{action} BEFORE {action.upper()} ON provider_category_command_operations BEGIN SELECT RAISE(ABORT, 'category operations are immutable'); END"
    for action in ("update", "delete")
}
CATEGORY_COMMAND_TRIGGERS[
    "provider_category_command_operations_no_replace"
] = """CREATE TRIGGER provider_category_command_operations_no_replace BEFORE INSERT ON provider_category_command_operations
WHEN EXISTS (SELECT 1 FROM provider_category_command_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'category operations are immutable'); END"""


class ProviderCategoryModel(LocalBase):
    __tablename__ = "provider_categories"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    archive_reason: Mapped[str | None] = mapped_column(String)
    create_idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    create_request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False, server_default="1")
    __table_args__ = (
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 1"),
        CheckConstraint("length(trim(display_name)) BETWEEN 1 AND 160"),
        CheckConstraint("display_order >= 0"),
        CheckConstraint(
            "(archived_at IS NULL AND archive_reason IS NULL) OR (archived_at IS NOT NULL AND archive_reason IS NOT NULL AND length(trim(archive_reason)) BETWEEN 1 AND 1000)"
        ),
        Index(
            "provider_categories_active_order",
            "archived_at",
            "display_order",
            "normalized_name",
            "id",
        ),
        Index(
            "provider_categories_one_active_name",
            "normalized_name",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
    )


class ProviderCategoryAssignmentModel(LocalBase):
    __tablename__ = "provider_category_assignments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider_party_id: Mapped[str] = mapped_column(
        ForeignKey("provider_profiles.party_id"), nullable=False
    )
    category_id: Mapped[str] = mapped_column(ForeignKey("provider_categories.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    archive_reason: Mapped[str | None] = mapped_column(String)
    create_idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    create_request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "(archived_at IS NULL AND archive_reason IS NULL) OR (archived_at IS NOT NULL AND archive_reason IS NOT NULL AND length(trim(archive_reason)) BETWEEN 1 AND 1000)"
        ),
        Index(
            "provider_category_assignments_provider_status",
            "provider_party_id",
            "archived_at",
            "category_id",
        ),
        Index(
            "provider_category_assignments_category_status",
            "category_id",
            "archived_at",
            "provider_party_id",
        ),
        Index(
            "provider_category_assignments_one_active_pair",
            "provider_party_id",
            "category_id",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
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
        Index(
            "provider_services_one_active_name",
            "party_id",
            "normalized_name",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
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
        CheckConstraint(
            "country_code = '' OR (length(country_code) = 2 AND country_code = upper(country_code) AND country_code GLOB '[A-Z][A-Z]')"
        ),
        Index("provider_service_areas_party_status", "party_id", "archived_at"),
        Index(
            "provider_service_areas_one_active_name",
            "party_id",
            "normalized_name",
            "country_code",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
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
        CheckConstraint(
            "length(trim(coalesce(reference_name, ''))) > 0 OR length(trim(coalesce(organization_name, ''))) > 0 OR length(trim(coalesce(relationship, ''))) > 0"
        ),
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
            "party_id",
            "normalized_source_key",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
        Index(
            "provider_reputation_links_one_active_url",
            "party_id",
            "normalized_url",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
    )
