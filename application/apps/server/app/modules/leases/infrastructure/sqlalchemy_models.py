"""SQLAlchemy metadata owned by LEASE-001."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class LeaseModel(LocalBase):
    __tablename__ = "leases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id"), nullable=False)
    lease_kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    contract_starts_on: Mapped[str] = mapped_column(String, nullable=False)
    contract_ends_on: Mapped[str | None] = mapped_column(String)
    occupancy_starts_on: Mapped[str] = mapped_column(String, nullable=False)
    executed_on: Mapped[str | None] = mapped_column(String)
    actual_move_out_on: Mapped[str | None] = mapped_column(String)
    end_reason: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("lease_kind IN ('residential', 'commercial')"),
        CheckConstraint("status IN ('draft', 'executed', 'ended', 'terminated', 'void')"),
        CheckConstraint("end_reason IS NULL OR end_reason IN ('contract_completed', 'early_termination', 'mutual_termination', 'other')"),
        CheckConstraint("contract_ends_on IS NULL OR contract_ends_on > contract_starts_on"),
        CheckConstraint("occupancy_starts_on >= contract_starts_on"),
        CheckConstraint("(status = 'draft' AND executed_on IS NULL AND actual_move_out_on IS NULL AND end_reason IS NULL) OR (status = 'executed' AND executed_on IS NOT NULL AND actual_move_out_on IS NULL AND end_reason IS NULL) OR (status = 'ended' AND executed_on IS NOT NULL AND actual_move_out_on IS NOT NULL AND end_reason IS NOT NULL AND end_reason = 'contract_completed') OR (status = 'terminated' AND executed_on IS NOT NULL AND actual_move_out_on IS NOT NULL AND end_reason IS NOT NULL AND end_reason IN ('early_termination', 'mutual_termination', 'other')) OR (status = 'void' AND executed_on IS NOT NULL AND actual_move_out_on IS NULL AND end_reason IS NULL)"),
        Index("leases_space_status_dates", "space_id", "status", "contract_starts_on", "contract_ends_on"),
    )


class LeaseTermModel(LocalBase):
    __tablename__ = "lease_term_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False)
    effective_on: Mapped[str] = mapped_column(String, nullable=False)
    ends_on: Mapped[str | None] = mapped_column(String)
    base_rent_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String, nullable=False)
    payment_frequency: Mapped[str] = mapped_column(String, nullable=False)
    payment_due_day: Mapped[int | None] = mapped_column(Integer)
    agreed_security_deposit_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("ends_on IS NULL OR ends_on > effective_on"),
        CheckConstraint("typeof(base_rent_minor) = 'integer' AND base_rent_minor > 0"),
        CheckConstraint("length(currency_code) = 3 AND currency_code GLOB '[A-Z][A-Z][A-Z]'"),
        CheckConstraint("payment_frequency IN ('monthly', 'weekly')"),
        CheckConstraint("(payment_frequency = 'monthly' AND payment_due_day BETWEEN 1 AND 31) OR (payment_frequency = 'weekly' AND payment_due_day IS NULL)"),
        CheckConstraint("agreed_security_deposit_minor >= 0"),
        Index("lease_terms_lease_dates", "lease_id", "effective_on", "ends_on"),
    )


class LeaseParticipantModel(LocalBase):
    __tablename__ = "lease_participants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False)
    tenant_party_id: Mapped[str] = mapped_column(ForeignKey("tenant_profiles.party_id"), nullable=False)
    participant_role: Mapped[str] = mapped_column(String, nullable=False)
    starts_on: Mapped[str] = mapped_column(String, nullable=False)
    ends_on: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("participant_role IN ('primary_tenant', 'co_tenant', 'guarantor', 'business_signatory')"),
        CheckConstraint("ends_on IS NULL OR ends_on > starts_on"),
        Index("lease_participants_lease_dates", "lease_id", "starts_on", "ends_on"),
        Index("lease_participants_tenant_dates", "tenant_party_id", "starts_on", "ends_on"),
    )


class LeaseRenewalOptionModel(LocalBase):
    __tablename__ = "lease_renewal_options"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    proposed_starts_on: Mapped[str] = mapped_column(String, nullable=False)
    proposed_ends_on: Mapped[str | None] = mapped_column(String)
    notice_due_on: Mapped[str | None] = mapped_column(String)
    response_due_on: Mapped[str | None] = mapped_column(String)
    decided_on: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('open', 'exercised', 'declined', 'expired', 'withdrawn')"),
        CheckConstraint("proposed_ends_on IS NULL OR proposed_ends_on > proposed_starts_on"),
        CheckConstraint("(status = 'open' AND decided_on IS NULL) OR (status != 'open' AND decided_on IS NOT NULL)"),
        Index("lease_renewals_lease_status_dates", "lease_id", "status", "notice_due_on", "response_due_on"),
    )


class LeaseTerminationCaseModel(LocalBase):
    __tablename__ = "lease_termination_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    notice_received_on: Mapped[str] = mapped_column(String, nullable=False)
    requested_termination_on: Mapped[str] = mapped_column(String, nullable=False)
    expected_move_out_on: Mapped[str] = mapped_column(String, nullable=False)
    agreed_termination_on: Mapped[str | None] = mapped_column(String)
    accepted_on: Mapped[str | None] = mapped_column(String)
    completed_on: Mapped[str | None] = mapped_column(String)
    tenant_explanation: Mapped[str | None] = mapped_column(String)
    contract_clause_reference: Mapped[str | None] = mapped_column(String)
    operator_notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('requested', 'under_review', 'proposed', 'accepted', 'withdrawn', 'declined', 'completed')"),
        CheckConstraint("reason IN ('job_relocation', 'military', 'habitability', 'mutual', 'other')"),
        CheckConstraint("(status IN ('accepted', 'completed') AND agreed_termination_on IS NOT NULL AND accepted_on IS NOT NULL) OR (status NOT IN ('accepted', 'completed') AND completed_on IS NULL)"),
        CheckConstraint("(status = 'completed' AND completed_on IS NOT NULL) OR status != 'completed'"),
        Index("lease_termination_cases_lease_status", "lease_id", "status", "requested_termination_on"),
    )


class LeaseTerminationProposalModel(LocalBase):
    __tablename__ = "lease_termination_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    termination_case_id: Mapped[str] = mapped_column(ForeignKey("lease_termination_cases.id"), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_termination_on: Mapped[str] = mapped_column(String, nullable=False)
    expected_move_out_on: Mapped[str] = mapped_column(String, nullable=False)
    rent_responsibility_ends_on: Mapped[str | None] = mapped_column(String)
    termination_fee_minor: Mapped[int | None] = mapped_column(Integer)
    currency_code: Mapped[str | None] = mapped_column(String)
    fee_waived: Mapped[bool] = mapped_column(Integer, nullable=False)
    replacement_tenant_condition: Mapped[str | None] = mapped_column(String)
    access_arrangement: Mapped[str | None] = mapped_column(String)
    other_terms: Mapped[str | None] = mapped_column(String)
    response_due_on: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    decided_on: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("proposal_version > 0"),
        CheckConstraint("termination_fee_minor IS NULL OR termination_fee_minor >= 0"),
        CheckConstraint("fee_waived IN (0, 1)"),
        CheckConstraint("(termination_fee_minor IS NULL AND currency_code IS NULL) OR (termination_fee_minor IS NOT NULL AND length(currency_code) = 3 AND currency_code GLOB '[A-Z][A-Z][A-Z]')"),
        CheckConstraint("status IN ('open', 'accepted', 'rejected', 'countered', 'withdrawn', 'expired')"),
        CheckConstraint("(status = 'open' AND decided_on IS NULL) OR (status != 'open' AND decided_on IS NOT NULL)"),
        Index("lease_termination_proposals_case_version", "termination_case_id", "proposal_version", unique=True),
    )
