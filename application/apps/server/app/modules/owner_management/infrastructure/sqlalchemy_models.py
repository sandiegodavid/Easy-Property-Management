from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase

_UUID = "length({})=36 AND substr({},9,1)='-' AND substr({},14,1)='-' AND substr({},19,1)='-' AND substr({},24,1)='-' AND replace(lower({}),'-','') NOT GLOB '*[^0-9a-f]*'"

class OwnerConcernModel(LocalBase):
    __tablename__ = "owner_concerns"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), nullable=False)
    owner_display_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), nullable=False)
    property_display_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    space_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id"))
    space_display_name_snapshot: Mapped[str | None] = mapped_column(String)
    lease_id: Mapped[str | None] = mapped_column(ForeignKey("leases.id"))
    lease_display_snapshot: Mapped[str | None] = mapped_column(String)
    tenant_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"))
    tenant_display_name_snapshot: Mapped[str | None] = mapped_column(String)
    originating_communication_id: Mapped[str | None] = mapped_column(ForeignKey("communications.id"))
    concern_type: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    raised_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    property_timezone_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    resolved_at_utc: Mapped[str | None] = mapped_column(String)
    resolution_summary: Mapped[str | None] = mapped_column(String)
    dismissed_at_utc: Mapped[str | None] = mapped_column(String)
    dismissal_reason: Mapped[str | None] = mapped_column(String)
    replaces_concern_id: Mapped[str | None] = mapped_column(ForeignKey("owner_concerns.id"), unique=True)
    observed_occupancy_status: Mapped[str | None] = mapped_column(String)
    observed_availability_status: Mapped[str | None] = mapped_column(String)
    observed_available_on: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("concern_type IN ('general_rental','lease','tenant','vacancy')"),
        CheckConstraint("priority IN ('low','normal','high','urgent')"),
        CheckConstraint("status IN ('open','in_progress','resolved','dismissed')"),
        CheckConstraint("length(trim(owner_display_name_snapshot)) BETWEEN 1 AND 240 AND length(trim(property_display_name_snapshot)) BETWEEN 1 AND 240"),
        CheckConstraint("length(trim(summary)) BETWEEN 1 AND 240 AND length(trim(description)) BETWEEN 1 AND 10000"),
        CheckConstraint("(space_id IS NULL AND space_display_name_snapshot IS NULL) OR (space_id IS NOT NULL AND space_display_name_snapshot IS NOT NULL AND length(trim(space_display_name_snapshot)) BETWEEN 1 AND 240)"),
        CheckConstraint("(lease_id IS NULL AND lease_display_snapshot IS NULL) OR (lease_id IS NOT NULL AND lease_display_snapshot IS NOT NULL AND length(trim(lease_display_snapshot)) BETWEEN 1 AND 240)"),
        CheckConstraint("(tenant_party_id IS NULL AND tenant_display_name_snapshot IS NULL) OR (tenant_party_id IS NOT NULL AND tenant_display_name_snapshot IS NOT NULL AND length(trim(tenant_display_name_snapshot)) BETWEEN 1 AND 240)"),
        CheckConstraint("(concern_type IN ('lease','tenant','vacancy') AND space_id IS NOT NULL) OR (concern_type='general_rental')"),
        CheckConstraint("(concern_type IN ('lease','tenant') AND lease_id IS NOT NULL) OR (concern_type NOT IN ('lease','tenant'))"),
        CheckConstraint("(concern_type='tenant' AND tenant_party_id IS NOT NULL) OR (concern_type!='tenant')"),
        CheckConstraint("(status='resolved' AND resolved_at_utc IS NOT NULL AND resolution_summary IS NOT NULL AND length(trim(resolution_summary)) BETWEEN 1 AND 4000 AND dismissed_at_utc IS NULL AND dismissal_reason IS NULL) OR (status='dismissed' AND dismissed_at_utc IS NOT NULL AND dismissal_reason IS NOT NULL AND length(trim(dismissal_reason)) BETWEEN 1 AND 4000 AND resolved_at_utc IS NULL AND resolution_summary IS NULL) OR (status IN ('open','in_progress') AND resolved_at_utc IS NULL AND resolution_summary IS NULL AND dismissed_at_utc IS NULL AND dismissal_reason IS NULL)"),
        CheckConstraint("replaces_concern_id IS NULL OR replaces_concern_id != id"),
        CheckConstraint("length(request_fingerprint)=64 AND lower(request_fingerprint) NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint("(concern_type='vacancy' AND observed_occupancy_status IN ('occupied','vacant','unknown') AND observed_availability_status IN ('available_now','available_on','not_available','unknown') AND ((observed_availability_status='available_on' AND observed_available_on IS NOT NULL AND length(observed_available_on)=10) OR (observed_availability_status!='available_on' AND observed_available_on IS NULL))) OR (concern_type!='vacancy' AND observed_occupancy_status IS NULL AND observed_availability_status IS NULL AND observed_available_on IS NULL)"),
        Index("owner_concerns_status_priority_raised", "status", "priority", "raised_at_utc", "id"),
        Index("owner_concerns_owner_status_raised", "owner_party_id", "status", "raised_at_utc"),
        Index("owner_concerns_property_status_raised", "property_id", "status", "raised_at_utc"),
        Index("owner_concerns_space_status", "space_id", "status"), Index("owner_concerns_lease_status", "lease_id", "status"), Index("owner_concerns_tenant_status", "tenant_party_id", "status"),
        Index("owner_concerns_type_status", "concern_type", "status"),
    )

class OwnerConcernFollowUpOperationModel(LocalBase):
    __tablename__ = "owner_concern_follow_up_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    concern_id: Mapped[str] = mapped_column(ForeignKey("owner_concerns.id"), nullable=False)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("length(request_fingerprint)=64 AND lower(request_fingerprint) NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint("length(trim(created_at_utc)) BETWEEN 20 AND 40"),
        Index("owner_concern_follow_up_operations_concern", "concern_id", "created_at_utc"),
    )
