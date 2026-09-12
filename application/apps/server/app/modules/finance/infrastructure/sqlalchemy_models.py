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


# FIN-008.  These records intentionally live beside the other finance facts;
# they are not rent receipts or operating expenses.
class SecurityDepositAccountModel(LocalBase):
    __tablename__ = "security_deposit_accounts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False, unique=True)
    lease_term_id: Mapped[str] = mapped_column(ForeignKey("lease_term_versions.id"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), nullable=False)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id"), nullable=False)
    agreed_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("typeof(agreed_amount_minor) = 'integer' AND agreed_amount_minor BETWEEN 0 AND 9999999999"),
        CheckConstraint("currency_code = 'USD'"),
        Index("security_deposit_accounts_property", "property_id", "space_id"),
    )


class SecurityDepositReceiptModel(LocalBase):
    __tablename__ = "security_deposit_receipts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_accounts.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    received_on: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String, nullable=False)
    received_from_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"))
    received_from_name: Mapped[str | None] = mapped_column(String)
    received_by_kind: Mapped[str] = mapped_column(String, nullable=False)
    received_by_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"))
    received_by_name: Mapped[str | None] = mapped_column(String)
    reference: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    replaces_receipt_id: Mapped[str | None] = mapped_column(ForeignKey("security_deposit_receipts.id"), unique=True)
    voided_at: Mapped[str | None] = mapped_column(String)
    void_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("length(request_fingerprint) = 64"),
        CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor BETWEEN 1 AND 9999999999"),
        CheckConstraint("currency_code = 'USD'"),
        CheckConstraint("received_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND received_on >= '1900-01-01' AND date(received_on, '+0 days') = received_on"),
        CheckConstraint("(received_from_party_id IS NULL AND received_from_name IS NULL) OR (received_from_party_id IS NOT NULL AND length(trim(received_from_name)) BETWEEN 1 AND 200)"),
        CheckConstraint("(received_by_kind = 'local_operator' AND received_by_party_id IS NULL AND received_by_name IS NULL) OR (received_by_kind = 'party' AND received_by_party_id IS NOT NULL AND length(trim(received_by_name)) BETWEEN 1 AND 200)"),
        CheckConstraint("received_by_kind IN ('local_operator', 'party')"),
        CheckConstraint("reference IS NULL OR length(trim(reference)) BETWEEN 1 AND 200"),
        CheckConstraint("notes IS NULL OR length(trim(notes)) BETWEEN 1 AND 4000"),
        CheckConstraint("replaces_receipt_id IS NULL OR replaces_receipt_id != id"),
        CheckConstraint("(voided_at IS NULL AND void_reason IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND length(trim(void_reason)) BETWEEN 1 AND 1000)"),
        Index("security_deposit_receipts_account_date", "account_id", "received_on", "id"),
        Index("security_deposit_receipts_duplicate", "account_id", "received_on", "amount_minor", "received_from_party_id", sqlite_where=text("voided_at IS NULL")),
    )


class SecurityDepositSettlementModel(LocalBase):
    __tablename__ = "security_deposit_settlements"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_accounts.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    settlement_due_on: Mapped[str] = mapped_column(String, nullable=False)
    legal_rule_reference: Mapped[str | None] = mapped_column(String)
    review_notes: Mapped[str | None] = mapped_column(String)
    eligibility_override_reason: Mapped[str | None] = mapped_column(String)
    deadline_override_reason: Mapped[str | None] = mapped_column(String)
    receipt_total_minor: Mapped[int | None] = mapped_column(Integer)
    credit_total_minor: Mapped[int | None] = mapped_column(Integer)
    deduction_total_minor: Mapped[int | None] = mapped_column(Integer)
    refund_due_minor: Mapped[int | None] = mapped_column(Integer)
    replaces_settlement_id: Mapped[str | None] = mapped_column(ForeignKey("security_deposit_settlements.id"), unique=True)
    approved_at: Mapped[str | None] = mapped_column(String)
    completed_at: Mapped[str | None] = mapped_column(String)
    voided_at: Mapped[str | None] = mapped_column(String)
    void_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'approved', 'completed', 'voided')"),
        CheckConstraint("settlement_due_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND settlement_due_on >= '1900-01-01' AND date(settlement_due_on, '+0 days') = settlement_due_on"),
        CheckConstraint("legal_rule_reference IS NULL OR length(trim(legal_rule_reference)) BETWEEN 1 AND 500"),
        CheckConstraint("review_notes IS NULL OR length(trim(review_notes)) BETWEEN 1 AND 4000"),
        CheckConstraint("(status = 'draft' AND receipt_total_minor IS NULL AND credit_total_minor IS NULL AND deduction_total_minor IS NULL AND refund_due_minor IS NULL AND approved_at IS NULL AND completed_at IS NULL AND voided_at IS NULL AND void_reason IS NULL) OR (status = 'approved' AND receipt_total_minor IS NOT NULL AND credit_total_minor IS NOT NULL AND deduction_total_minor IS NOT NULL AND refund_due_minor IS NOT NULL AND approved_at IS NOT NULL AND completed_at IS NULL AND voided_at IS NULL AND void_reason IS NULL) OR (status = 'completed' AND receipt_total_minor IS NOT NULL AND credit_total_minor IS NOT NULL AND deduction_total_minor IS NOT NULL AND refund_due_minor IS NOT NULL AND approved_at IS NOT NULL AND completed_at IS NOT NULL AND voided_at IS NULL AND void_reason IS NULL) OR (status = 'voided' AND voided_at IS NOT NULL AND void_reason IS NOT NULL AND length(trim(void_reason)) BETWEEN 1 AND 1000 AND ((approved_at IS NULL AND completed_at IS NULL AND receipt_total_minor IS NULL AND credit_total_minor IS NULL AND deduction_total_minor IS NULL AND refund_due_minor IS NULL) OR (approved_at IS NOT NULL AND receipt_total_minor IS NOT NULL AND credit_total_minor IS NOT NULL AND deduction_total_minor IS NOT NULL AND refund_due_minor IS NOT NULL)))"),
        CheckConstraint("receipt_total_minor IS NULL OR (typeof(receipt_total_minor) = 'integer' AND typeof(credit_total_minor) = 'integer' AND typeof(deduction_total_minor) = 'integer' AND typeof(refund_due_minor) = 'integer' AND receipt_total_minor BETWEEN 0 AND 9999999999 AND credit_total_minor BETWEEN 0 AND 9999999999 AND deduction_total_minor BETWEEN 0 AND 9999999999 AND refund_due_minor = receipt_total_minor + credit_total_minor - deduction_total_minor AND refund_due_minor BETWEEN 0 AND 9999999999)"),
        Index("security_deposit_settlements_one_current", "account_id", unique=True, sqlite_where=text("status != 'voided'")),
    )


class SecurityDepositSettlementReceiptModel(LocalBase):
    __tablename__ = "security_deposit_settlement_receipts"
    settlement_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_settlements.id"), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_receipts.id"), primary_key=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class SecurityDepositDeductionModel(LocalBase):
    __tablename__ = "security_deposit_deductions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    settlement_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_settlements.id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("category IN ('unpaid_rent', 'damage', 'cleaning', 'missing_property', 'contractual_fee', 'other')"),
        CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor BETWEEN 1 AND 9999999999"),
        CheckConstraint("length(trim(description)) BETWEEN 1 AND 500"),
        CheckConstraint("length(trim(rationale)) BETWEEN 1 AND 2000"),
        Index("security_deposit_deductions_settlement", "settlement_id"),
    )


class SecurityDepositDeductionSourceModel(LocalBase):
    __tablename__ = "security_deposit_deduction_sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    deduction_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_deductions.id"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    source_summary: Mapped[str] = mapped_column(String, nullable=False)
    outstanding_amount_minor: Mapped[int | None] = mapped_column(Integer)
    historical_confirmed: Mapped[bool] = mapped_column(Integer, nullable=False)
    historical_reason: Mapped[str | None] = mapped_column(String)
    duplicate_use_confirmed: Mapped[bool] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("source_kind IN ('inspection_comparison', 'inspection_observation', 'rent_expectation', 'expense')"),
        CheckConstraint("length(trim(source_summary)) BETWEEN 1 AND 4000"),
        CheckConstraint("outstanding_amount_minor IS NULL OR (typeof(outstanding_amount_minor) = 'integer' AND outstanding_amount_minor >= 0)"),
        CheckConstraint("historical_confirmed IN (0, 1) AND duplicate_use_confirmed IN (0, 1)"),
        CheckConstraint("(historical_confirmed = 0 AND historical_reason IS NULL) OR (historical_confirmed = 1 AND historical_reason IS NOT NULL AND length(trim(historical_reason)) BETWEEN 1 AND 1000)"),
        Index("security_deposit_deduction_sources_unique", "deduction_id", "source_kind", "source_id", unique=True),
    )


class SecurityDepositCreditModel(LocalBase):
    __tablename__ = "security_deposit_credits"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    settlement_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_settlements.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    calculator_principal_minor: Mapped[int | None] = mapped_column(Integer)
    annual_rate_basis_points: Mapped[int | None] = mapped_column(Integer)
    starts_on: Mapped[str | None] = mapped_column(String)
    ends_on: Mapped[str | None] = mapped_column(String)
    day_count: Mapped[int | None] = mapped_column(Integer)
    calculated_amount_minor: Mapped[int | None] = mapped_column(Integer)
    override_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('interest', 'other')"),
        CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor BETWEEN 1 AND 9999999999"),
        CheckConstraint("length(trim(description)) BETWEEN 1 AND 500"),
        CheckConstraint("(calculator_principal_minor IS NULL AND annual_rate_basis_points IS NULL AND starts_on IS NULL AND ends_on IS NULL AND day_count IS NULL AND calculated_amount_minor IS NULL) OR (calculator_principal_minor IS NOT NULL AND annual_rate_basis_points BETWEEN 1 AND 100000 AND starts_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND starts_on >= '1900-01-01' AND date(starts_on, '+0 days') = starts_on AND ends_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND ends_on >= '1900-01-01' AND date(ends_on, '+0 days') = ends_on AND ends_on > starts_on AND day_count BETWEEN 1 AND 36600 AND calculated_amount_minor >= 0)"),
        CheckConstraint("override_reason IS NULL OR length(trim(override_reason)) BETWEEN 1 AND 1000"),
        Index("security_deposit_credits_settlement", "settlement_id"),
    )


class SecurityDepositRefundModel(LocalBase):
    __tablename__ = "security_deposit_refunds"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_accounts.id"), nullable=False)
    authorized_by_settlement_id: Mapped[str] = mapped_column(ForeignKey("security_deposit_settlements.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    recipient_party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String, nullable=False)
    paid_on: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String, nullable=False)
    reference: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    recipient_override_reason: Mapped[str | None] = mapped_column(String)
    replaces_refund_id: Mapped[str | None] = mapped_column(ForeignKey("security_deposit_refunds.id"), unique=True)
    voided_at: Mapped[str | None] = mapped_column(String)
    void_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("length(request_fingerprint) = 64"),
        CheckConstraint("typeof(amount_minor) = 'integer' AND amount_minor BETWEEN 1 AND 9999999999"),
        CheckConstraint("currency_code = 'USD'"),
        CheckConstraint("paid_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND paid_on >= '1900-01-01' AND date(paid_on, '+0 days') = paid_on"),
        CheckConstraint("length(trim(recipient_name)) BETWEEN 1 AND 200"),
        CheckConstraint("reference IS NULL OR length(trim(reference)) BETWEEN 1 AND 200"),
        CheckConstraint("notes IS NULL OR length(trim(notes)) BETWEEN 1 AND 4000"),
        CheckConstraint("recipient_override_reason IS NULL OR length(trim(recipient_override_reason)) BETWEEN 1 AND 1000"),
        CheckConstraint("replaces_refund_id IS NULL OR replaces_refund_id != id"),
        CheckConstraint("(voided_at IS NULL AND void_reason IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND length(trim(void_reason)) BETWEEN 1 AND 1000)"),
        Index("security_deposit_refunds_account_paid", "account_id", "paid_on", "id"),
    )
