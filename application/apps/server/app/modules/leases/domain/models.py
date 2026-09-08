"""Immutable lease domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass


def _camel(values: dict[str, object]) -> dict[str, object]:
    return {
        "".join([parts[0], *(part.title() for part in parts[1:])]): value
        for key, value in values.items()
        for parts in [key.split("_")]
    }


@dataclass(frozen=True)
class Lease:
    id: str
    space_id: str
    lease_kind: str
    status: str
    contract_starts_on: str
    contract_ends_on: str | None
    occupancy_starts_on: str
    executed_on: str | None
    actual_move_out_on: str | None
    end_reason: str | None
    notes: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class LeaseTerm:
    id: str
    lease_id: str
    effective_on: str
    ends_on: str | None
    base_rent_minor: int
    currency_code: str
    payment_frequency: str
    payment_due_day: int | None
    agreed_security_deposit_minor: int
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class LeaseParticipant:
    id: str
    lease_id: str
    tenant_party_id: str
    participant_role: str
    starts_on: str
    ends_on: str | None
    notes: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class LeaseRenewalOption:
    id: str
    lease_id: str
    status: str
    proposed_starts_on: str
    proposed_ends_on: str | None
    notice_due_on: str | None
    response_due_on: str | None
    decided_on: str | None
    notes: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class LeaseTerminationCase:
    id: str
    lease_id: str
    status: str
    reason: str
    notice_received_on: str
    requested_termination_on: str
    expected_move_out_on: str
    agreed_termination_on: str | None
    accepted_on: str | None
    completed_on: str | None
    tenant_explanation: str | None
    contract_clause_reference: str | None
    operator_notes: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class LeaseTerminationProposal:
    id: str
    termination_case_id: str
    proposal_version: int
    proposed_termination_on: str
    expected_move_out_on: str
    rent_responsibility_ends_on: str | None
    termination_fee_minor: int | None
    currency_code: str | None
    fee_waived: bool
    replacement_tenant_condition: str | None
    access_arrangement: str | None
    other_terms: str | None
    response_due_on: str | None
    status: str
    decided_on: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))
