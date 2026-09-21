from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase


class OwnerRentReportModel(LocalBase):
    __tablename__ = "owner_rent_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id"), nullable=False)
    property_timezone_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    owner_party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), nullable=False)
    owner_display_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    received_on: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String, nullable=False)
    payment_method_kind: Mapped[str] = mapped_column(String, nullable=False)
    payment_method_label: Mapped[str | None] = mapped_column(String)
    masked_reference: Mapped[str | None] = mapped_column(String)
    other_payment_method_note: Mapped[str | None] = mapped_column(String)
    reported_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    source_note: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    verified_receipt_id: Mapped[str | None] = mapped_column(ForeignKey("rent_receipts.id"), unique=True)
    reviewed_at: Mapped[str | None] = mapped_column(String)
    review_note: Mapped[str | None] = mapped_column(String)
    replaces_report_id: Mapped[str | None] = mapped_column(ForeignKey("owner_rent_reports.id"), unique=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("currency_code = 'USD'"), CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor BETWEEN 1 AND 9999999999"),
        CheckConstraint("length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND replace(lower(id),'-','') NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint("length(lease_id)=36 AND length(property_id)=36 AND length(space_id)=36 AND length(owner_party_id)=36 AND substr(lease_id,9,1)='-' AND substr(property_id,9,1)='-' AND substr(space_id,9,1)='-' AND substr(owner_party_id,9,1)='-' AND replace(lower(lease_id),'-','') NOT GLOB '*[^0-9a-f]*' AND replace(lower(property_id),'-','') NOT GLOB '*[^0-9a-f]*' AND replace(lower(space_id),'-','') NOT GLOB '*[^0-9a-f]*' AND replace(lower(owner_party_id),'-','') NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint("received_on = date(received_on) AND length(received_on)=10"),
        CheckConstraint("length(property_timezone_snapshot) BETWEEN 1 AND 128"),
        CheckConstraint("length(reported_at_utc) BETWEEN 20 AND 40 AND substr(reported_at_utc,5,1)='-' AND substr(reported_at_utc,8,1)='-' AND substr(reported_at_utc,11,1)='T' AND substr(reported_at_utc,14,1)=':' AND substr(reported_at_utc,17,1)=':' AND (substr(reported_at_utc,-1)='Z' OR substr(reported_at_utc,-6,1) IN ('+','-'))"),
        CheckConstraint("length(created_at) BETWEEN 20 AND 40 AND length(updated_at) BETWEEN 20 AND 40 AND substr(created_at,5,1)='-' AND substr(created_at,8,1)='-' AND substr(created_at,11,1)='T' AND substr(created_at,14,1)=':' AND substr(created_at,17,1)=':' AND (substr(created_at,-1)='Z' OR substr(created_at,-6,1) IN ('+','-')) AND substr(updated_at,5,1)='-' AND substr(updated_at,8,1)='-' AND substr(updated_at,11,1)='T' AND substr(updated_at,14,1)=':' AND substr(updated_at,17,1)=':' AND (substr(updated_at,-1)='Z' OR substr(updated_at,-6,1) IN ('+','-'))"),
        CheckConstraint("payment_method_kind IN ('automatic_bank_payment','bank_transfer','check','cash','online_payment','other')"),
        CheckConstraint("(payment_method_kind='other' AND other_payment_method_note IS NOT NULL AND length(trim(other_payment_method_note)) BETWEEN 1 AND 200) OR (payment_method_kind!='other' AND other_payment_method_note IS NULL)"),
        CheckConstraint("status IN ('pending','verified','rejected')"),
        CheckConstraint("(status='pending' AND verified_receipt_id IS NULL AND reviewed_at IS NULL AND review_note IS NULL) OR (status='verified' AND verified_receipt_id IS NOT NULL AND reviewed_at IS NOT NULL AND review_note IS NOT NULL) OR (status='rejected' AND verified_receipt_id IS NULL AND reviewed_at IS NOT NULL AND review_note IS NOT NULL)"),
        CheckConstraint("replaces_report_id IS NULL OR (replaces_report_id != id AND length(replaces_report_id)=36 AND substr(replaces_report_id,9,1)='-' AND substr(replaces_report_id,14,1)='-' AND substr(replaces_report_id,19,1)='-' AND substr(replaces_report_id,24,1)='-' AND replace(lower(replaces_report_id),'-','') NOT GLOB '*[^0-9a-f]*')"),
        CheckConstraint("length(trim(owner_display_name_snapshot)) BETWEEN 1 AND 240"),
        CheckConstraint("payment_method_label IS NULL OR length(trim(payment_method_label)) BETWEEN 1 AND 100"),
        CheckConstraint("masked_reference IS NULL OR length(trim(masked_reference)) BETWEEN 1 AND 100"),
        CheckConstraint("source_note IS NULL OR length(trim(source_note)) BETWEEN 1 AND 4000"),
        CheckConstraint("review_note IS NULL OR length(trim(review_note)) BETWEEN 1 AND 1000"),
        CheckConstraint("reviewed_at IS NULL OR (length(reviewed_at) BETWEEN 20 AND 40 AND substr(reviewed_at,5,1)='-' AND substr(reviewed_at,8,1)='-' AND substr(reviewed_at,11,1)='T' AND substr(reviewed_at,14,1)=':' AND substr(reviewed_at,17,1)=':' AND (substr(reviewed_at,-1)='Z' OR substr(reviewed_at,-6,1) IN ('+','-')) )"),
        Index("owner_rent_reports_lease_received", "lease_id", "received_on", "id"),
        Index("owner_rent_reports_owner_received", "owner_party_id", "received_on", "id"),
        Index("owner_rent_reports_status_received", "status", "received_on", "id"),
    )


class OwnerRentReportOperationModel(LocalBase):
    __tablename__ = "owner_rent_report_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    report_id: Mapped[str] = mapped_column(ForeignKey("owner_rent_reports.id"), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    result_receipt_id: Mapped[str | None] = mapped_column(ForeignKey("rent_receipts.id"))
    receipt_created: Mapped[bool | None] = mapped_column(Integer)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("action IN ('create','patch','verify','reject')"),
        CheckConstraint("length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND replace(lower(id),'-','') NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint("length(idempotency_key)=36 AND length(report_id)=36 AND length(correlation_id)=36 AND substr(idempotency_key,9,1)='-' AND substr(report_id,9,1)='-' AND substr(correlation_id,9,1)='-' AND replace(lower(idempotency_key),'-','') NOT GLOB '*[^0-9a-f]*' AND replace(lower(report_id),'-','') NOT GLOB '*[^0-9a-f]*' AND replace(lower(correlation_id),'-','') NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint("length(request_fingerprint)=64 AND lower(request_fingerprint) NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint("length(created_at) BETWEEN 20 AND 40 AND substr(created_at,5,1)='-' AND substr(created_at,8,1)='-' AND substr(created_at,11,1)='T' AND substr(created_at,14,1)=':' AND substr(created_at,17,1)=':' AND (substr(created_at,-1)='Z' OR substr(created_at,-6,1) IN ('+','-'))"),
        CheckConstraint("(action='verify' AND result_receipt_id IS NOT NULL AND receipt_created IN (0,1) AND length(result_receipt_id)=36 AND substr(result_receipt_id,9,1)='-' AND substr(result_receipt_id,14,1)='-' AND substr(result_receipt_id,19,1)='-' AND substr(result_receipt_id,24,1)='-' AND replace(lower(result_receipt_id),'-','') NOT GLOB '*[^0-9a-f]*') OR (action!='verify' AND result_receipt_id IS NULL AND receipt_created IS NULL)"),
        Index("owner_rent_report_operations_report", "report_id", "created_at"),
    )
