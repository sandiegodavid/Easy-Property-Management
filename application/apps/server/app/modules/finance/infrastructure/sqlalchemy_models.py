"""SQLAlchemy metadata owned by FIN-001."""
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase

class RentExpectationModel(LocalBase):
    __tablename__ = "rent_expectations"
    id: Mapped[str] = mapped_column(String, primary_key=True); lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False); lease_term_id: Mapped[str] = mapped_column(ForeignKey("lease_term_versions.id"), nullable=False); period_starts_on: Mapped[str] = mapped_column(String, nullable=False); period_ends_on: Mapped[str] = mapped_column(String, nullable=False); due_on: Mapped[str] = mapped_column(String, nullable=False); expected_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False); currency_code: Mapped[str] = mapped_column(String, nullable=False); payment_frequency: Mapped[str] = mapped_column(String, nullable=False); schedule_anchor_on: Mapped[str] = mapped_column(String, nullable=False); is_prorated: Mapped[bool] = mapped_column(Integer, nullable=False); proration_numerator_days: Mapped[int | None] = mapped_column(Integer); proration_denominator_days: Mapped[int | None] = mapped_column(Integer); responsibility_boundary_on: Mapped[str | None] = mapped_column(String); responsibility_override_reason: Mapped[str | None] = mapped_column(String); voided_at: Mapped[str | None] = mapped_column(String); void_reason: Mapped[str | None] = mapped_column(String); created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("typeof(expected_amount_minor) = 'integer' AND expected_amount_minor > 0"), CheckConstraint("currency_code = 'USD'"), CheckConstraint("payment_frequency IN ('monthly', 'weekly')"), CheckConstraint("period_ends_on > period_starts_on AND due_on >= period_starts_on AND due_on <= period_ends_on"), CheckConstraint("is_prorated IN (0, 1)"), CheckConstraint("(is_prorated = 0 AND proration_numerator_days IS NULL AND proration_denominator_days IS NULL) OR (is_prorated = 1 AND proration_numerator_days IS NOT NULL AND proration_denominator_days IS NOT NULL AND typeof(proration_numerator_days) = 'integer' AND typeof(proration_denominator_days) = 'integer' AND proration_numerator_days > 0 AND proration_denominator_days > proration_numerator_days)"), CheckConstraint("(voided_at IS NULL AND void_reason IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND length(trim(void_reason)) > 0)"), Index("rent_expectations_term_due", "lease_term_id", "due_on", unique=True), Index("rent_expectations_lease_due", "lease_id", "due_on"))

class RentExpectationTimelinessReviewModel(LocalBase):
    __tablename__ = "rent_expectation_timeliness_reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True); expectation_id: Mapped[str] = mapped_column(ForeignKey("rent_expectations.id"), nullable=False); decision: Mapped[str] = mapped_column(String, nullable=False); reason: Mapped[str] = mapped_column(String, nullable=False); created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("decision IN ('mark_missed', 'clear_missed')"), CheckConstraint("length(trim(reason)) > 0"), Index("rent_expectation_reviews_order", "expectation_id", "created_at", "id"))

class RentReceiptModel(LocalBase):
    __tablename__ = "rent_receipts"
    id: Mapped[str] = mapped_column(String, primary_key=True); lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False); idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True); received_on: Mapped[str] = mapped_column(String, nullable=False); amount_minor: Mapped[int] = mapped_column(Integer, nullable=False); currency_code: Mapped[str] = mapped_column(String, nullable=False); received_by_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id")); replaces_receipt_id: Mapped[str | None] = mapped_column(ForeignKey("rent_receipts.id"), unique=True); notes: Mapped[str | None] = mapped_column(String); voided_at: Mapped[str | None] = mapped_column(String); void_reason: Mapped[str | None] = mapped_column(String); created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor > 0"), CheckConstraint("currency_code = 'USD'"), CheckConstraint("(voided_at IS NULL AND void_reason IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND length(trim(void_reason)) > 0)"), Index("rent_receipts_lease_received", "lease_id", "received_on"))

class RentReceiptAllocationModel(LocalBase):
    __tablename__ = "rent_receipt_allocations"
    id: Mapped[str] = mapped_column(String, primary_key=True); receipt_id: Mapped[str] = mapped_column(ForeignKey("rent_receipts.id"), nullable=False); expectation_id: Mapped[str] = mapped_column(ForeignKey("rent_expectations.id"), nullable=False); amount_minor: Mapped[int] = mapped_column(Integer, nullable=False); created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor > 0"), Index("rent_receipt_allocations_one_receipt_expectation", "receipt_id", "expectation_id", unique=True), Index("rent_receipt_allocations_expectation", "expectation_id"))


class ExpenseCategoryModel(LocalBase):
    __tablename__ = "expense_categories"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("length(trim(display_name)) BETWEEN 1 AND 100"),
        CheckConstraint("length(trim(normalized_name)) BETWEEN 1 AND 100"),
        CheckConstraint("description IS NULL OR length(trim(description)) BETWEEN 1 AND 1000"),
        CheckConstraint("typeof(display_order) = 'integer' AND display_order BETWEEN 0 AND 10000"),
        Index("expense_categories_active_order", "archived_at", "display_order", "display_name"),
        Index("expense_categories_one_active_name", "normalized_name", unique=True,
              sqlite_where=text("archived_at IS NULL")),
    )


class ExpenseModel(LocalBase):
    __tablename__ = "expenses"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), nullable=False)
    space_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id"))
    category_id: Mapped[str] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)
    provider_party_id: Mapped[str | None] = mapped_column(ForeignKey("provider_profiles.party_id"))
    payee_name: Mapped[str] = mapped_column(String, nullable=False)
    paid_by_kind: Mapped[str] = mapped_column(String, nullable=False)
    paid_by_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"))
    paid_on: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    reference: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    replaces_expense_id: Mapped[str | None] = mapped_column(ForeignKey("expenses.id"), unique=True)
    voided_at: Mapped[str | None] = mapped_column(String)
    void_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor BETWEEN 1 AND 9999999999"),
        CheckConstraint("length(request_fingerprint) = 64"),
        CheckConstraint("currency_code = 'USD'"),
        CheckConstraint("paid_by_kind IN ('local_operator', 'party')"),
        CheckConstraint("(paid_by_kind = 'local_operator' AND paid_by_party_id IS NULL) OR (paid_by_kind = 'party' AND paid_by_party_id IS NOT NULL)"),
        CheckConstraint("length(trim(payee_name)) BETWEEN 1 AND 200"),
        CheckConstraint("length(trim(description)) BETWEEN 1 AND 500"),
        CheckConstraint("reference IS NULL OR length(trim(reference)) BETWEEN 1 AND 200"),
        CheckConstraint("notes IS NULL OR length(trim(notes)) BETWEEN 1 AND 4000"),
        CheckConstraint("replaces_expense_id IS NULL OR replaces_expense_id != id"),
        CheckConstraint("(voided_at IS NULL AND void_reason IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND length(trim(void_reason)) BETWEEN 1 AND 1000)"),
        Index("expenses_property_paid", "property_id", "paid_on", "id"),
        Index("expenses_space_paid", "space_id", "paid_on", "id"),
        Index("expenses_category_paid", "category_id", "paid_on", "id"),
        Index("expenses_provider_paid", "provider_party_id", "paid_on", "id"),
        Index("expenses_payer_paid", "paid_by_party_id", "paid_on", "id"),
        Index("expenses_lifecycle_paid", "voided_at", "paid_on", "id"),
        Index("expenses_duplicate_lookup", "property_id", "paid_on", "amount_minor", "currency_code", "payee_name"),
    )


class ExpenseRefundModel(LocalBase):
    __tablename__ = "expense_refunds"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    expense_id: Mapped[str] = mapped_column(ForeignKey("expenses.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    received_on: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String)
    replaces_refund_id: Mapped[str | None] = mapped_column(ForeignKey("expense_refunds.id"), unique=True)
    voided_at: Mapped[str | None] = mapped_column(String)
    void_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor BETWEEN 1 AND 9999999999"),
        CheckConstraint("currency_code = 'USD'"),
        CheckConstraint("notes IS NULL OR length(trim(notes)) BETWEEN 1 AND 4000"),
        CheckConstraint("replaces_refund_id IS NULL OR replaces_refund_id != id"),
        CheckConstraint("(voided_at IS NULL AND void_reason IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND length(trim(void_reason)) BETWEEN 1 AND 1000)"),
        Index("expense_refunds_expense_received", "expense_id", "received_on", "id"),
        Index("expense_refunds_lifecycle", "voided_at", "received_on", "id"),
    )
