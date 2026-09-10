"""LEASE-001 use cases and business rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import uuid4

from app.modules.leases.application.ports import LeaseConflictError, LeaseTransaction, LeaseUnitOfWork
from app.modules.leases.domain.models import Lease, LeaseParticipant, LeaseRenewalOption, LeaseTerm, LeaseTerminationCase, LeaseTerminationProposal
from app.modules.portfolio.domain.models import SpaceOccupancyPeriod

LEASE_KINDS = {"residential", "commercial"}
LEASE_STATUSES = {"draft", "executed", "ended", "terminated", "void"}
PARTICIPANT_ROLES = {"primary_tenant", "co_tenant", "guarantor", "business_signatory"}
RENEWAL_STATUSES = {"open", "exercised", "declined", "expired", "withdrawn"}
END_REASONS = {"contract_completed", "early_termination", "mutual_termination", "other"}
TERMINATION_REASONS = {"job_relocation", "military", "habitability", "mutual", "other"}


class LeaseError(ValueError):
    """Invalid lease input or lifecycle operation."""


class LeaseNotFoundError(LeaseError):
    """Requested lease record does not exist."""


@dataclass(frozen=True)
class TermCommand:
    base_rent_minor: int
    currency_code: str
    payment_frequency: str
    payment_due_day: int | None
    agreed_security_deposit_minor: int

    def __post_init__(self) -> None:
        if type(self.base_rent_minor) is not int or self.base_rent_minor <= 0:
            raise LeaseError("Base rent must be a positive integer minor-unit amount.")
        if type(self.agreed_security_deposit_minor) is not int or self.agreed_security_deposit_minor < 0:
            raise LeaseError("Security deposit must be a non-negative integer minor-unit amount.")
        currency = _currency_code(self.currency_code)
        if self.payment_frequency not in {"monthly", "weekly"}:
            raise LeaseError("Payment frequency must be monthly or weekly.")
        if self.payment_frequency == "monthly":
            if type(self.payment_due_day) is not int or not 1 <= self.payment_due_day <= 31:
                raise LeaseError("Monthly rent requires a due day from 1 to 31.")
        elif self.payment_due_day is not None:
            raise LeaseError("Weekly rent does not use a monthly due day.")
        object.__setattr__(self, "currency_code", currency)


@dataclass(frozen=True)
class ParticipantCommand:
    tenant_party_id: str
    participant_role: str
    starts_on: str | None = None
    ends_on: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_party_id", _text(self.tenant_party_id, "Tenant party ID", 80))
        if self.participant_role not in PARTICIPANT_ROLES:
            raise LeaseError("Unsupported lease participant role.")
        if self.starts_on is not None:
            object.__setattr__(self, "starts_on", _date(self.starts_on, "Participant start date"))
        if self.ends_on is not None:
            object.__setattr__(self, "ends_on", _date(self.ends_on, "Participant end date"))
        object.__setattr__(self, "notes", _optional(self.notes, "Participant notes", 2000))


@dataclass(frozen=True)
class LeaseCreateCommand:
    space_id: str
    lease_kind: str
    contract_starts_on: str
    contract_ends_on: str | None
    occupancy_starts_on: str
    initial_term: TermCommand
    participants: tuple[ParticipantCommand, ...]
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "space_id", _text(self.space_id, "Space ID", 80))
        if self.lease_kind not in LEASE_KINDS:
            raise LeaseError("Lease kind must be residential or commercial.")
        start = _date(self.contract_starts_on, "Contract start date")
        end = None if self.contract_ends_on is None else _date(self.contract_ends_on, "Contract end date")
        occupancy = _date(self.occupancy_starts_on, "Occupancy start date")
        if end is not None and end <= start:
            raise LeaseError("Contract end date must follow its start date.")
        if occupancy < start or (end is not None and occupancy >= end):
            raise LeaseError("Occupancy start must fall within the contract range.")
        if not isinstance(self.initial_term, TermCommand):
            raise LeaseError("A valid initial term is required.")
        if not isinstance(self.participants, tuple) or not self.participants:
            raise LeaseError("At least one lease participant is required.")
        if any(not isinstance(item, ParticipantCommand) for item in self.participants):
            raise LeaseError("Every participant must be a valid participant command.")
        object.__setattr__(self, "contract_starts_on", start)
        object.__setattr__(self, "contract_ends_on", end)
        object.__setattr__(self, "occupancy_starts_on", occupancy)
        object.__setattr__(self, "notes", _optional(self.notes, "Lease notes", 4000))


@dataclass(frozen=True)
class LeasePatchCommand:
    contract_starts_on: str | None = None
    contract_ends_on: str | None = None
    occupancy_starts_on: str | None = None
    notes: str | None = None
    supplied_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        allowed = {"contract_starts_on", "contract_ends_on", "occupancy_starts_on", "notes"}
        if not self.supplied_fields or not self.supplied_fields <= allowed:
            raise LeaseError("A lease patch requires supported fields.")


@dataclass(frozen=True)
class RenewalCommand:
    proposed_starts_on: str
    proposed_ends_on: str | None = None
    notice_due_on: str | None = None
    response_due_on: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        start = _date(self.proposed_starts_on, "Proposed start date")
        end = None if self.proposed_ends_on is None else _date(self.proposed_ends_on, "Proposed end date")
        if end is not None and end <= start:
            raise LeaseError("Proposed end date must follow its start date.")
        object.__setattr__(self, "proposed_starts_on", start)
        object.__setattr__(self, "proposed_ends_on", end)
        for field in ("notice_due_on", "response_due_on"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _date(value, field.replace("_", " ").title()))
        object.__setattr__(self, "notes", _optional(self.notes, "Renewal notes", 2000))


@dataclass(frozen=True)
class RenewalPatchCommand:
    proposed_starts_on: str | None = None
    proposed_ends_on: str | None = None
    notice_due_on: str | None = None
    response_due_on: str | None = None
    notes: str | None = None
    supplied_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        allowed = {"proposed_starts_on", "proposed_ends_on", "notice_due_on", "response_due_on", "notes"}
        if not self.supplied_fields or not self.supplied_fields <= allowed:
            raise LeaseError("A renewal patch requires supported fields.")


@dataclass(frozen=True)
class TerminationCaseCommand:
    reason: str
    notice_received_on: str
    requested_termination_on: str
    expected_move_out_on: str
    tenant_explanation: str | None = None
    contract_clause_reference: str | None = None
    operator_notes: str | None = None

    def __post_init__(self) -> None:
        if self.reason not in TERMINATION_REASONS:
            raise LeaseError("Unsupported early-termination reason.")
        for field in ("notice_received_on", "requested_termination_on", "expected_move_out_on"):
            object.__setattr__(self, field, _date(getattr(self, field), field.replace("_", " ").title()))
        if self.expected_move_out_on < self.notice_received_on:
            raise LeaseError("Expected move-out cannot precede notice receipt.")
        object.__setattr__(self, "tenant_explanation", _optional(self.tenant_explanation, "Tenant explanation", 4000))
        object.__setattr__(self, "contract_clause_reference", _optional(self.contract_clause_reference, "Contract clause reference", 500))
        object.__setattr__(self, "operator_notes", _optional(self.operator_notes, "Operator notes", 4000))


@dataclass(frozen=True)
class TerminationProposalCommand:
    proposed_termination_on: str
    expected_move_out_on: str
    rent_responsibility_ends_on: str | None = None
    termination_fee_minor: int | None = None
    currency_code: str | None = None
    fee_waived: bool = False
    replacement_tenant_condition: str | None = None
    access_arrangement: str | None = None
    other_terms: str | None = None
    response_due_on: str | None = None

    def __post_init__(self) -> None:
        for field in ("proposed_termination_on", "expected_move_out_on"):
            object.__setattr__(self, field, _date(getattr(self, field), field.replace("_", " ").title()))
        for field in ("rent_responsibility_ends_on", "response_due_on"):
            if getattr(self, field) is not None:
                object.__setattr__(self, field, _date(getattr(self, field), field.replace("_", " ").title()))
        if self.expected_move_out_on > self.proposed_termination_on:
            raise LeaseError("Expected move-out cannot follow the proposed termination date.")
        if self.termination_fee_minor is not None and (type(self.termination_fee_minor) is not int or self.termination_fee_minor < 0):
            raise LeaseError("Termination fee must be a non-negative integer minor-unit amount.")
        if self.termination_fee_minor is None:
            if self.currency_code is not None:
                raise LeaseError("Currency requires a termination fee.")
        else:
            object.__setattr__(self, "currency_code", _currency_code(self.currency_code))
        if type(self.fee_waived) is not bool:
            raise LeaseError("Fee-waived must be a boolean.")
        for field, label in (("replacement_tenant_condition", "Replacement tenant condition"), ("access_arrangement", "Access arrangement"), ("other_terms", "Other terms")):
            object.__setattr__(self, field, _optional(getattr(self, field), label, 2000))


class LeaseService:
    def __init__(self, unit_of_work: LeaseUnitOfWork, inspection_attention_reader=None) -> None:
        self.unit_of_work = unit_of_work
        self.inspection_attention_reader = inspection_attention_reader

    def create(self, command: LeaseCreateCommand) -> dict[str, object]:
        if not isinstance(command, LeaseCreateCommand):
            raise LeaseError("A valid lease command is required.")
        now, correlation = _now(), str(uuid4())

        def write(tx: LeaseTransaction) -> str:
            space = tx.space(command.space_id)
            if space is None:
                raise KeyError
            property = tx.property(space.property_id)
            if space.status != "active" or property is None or property.status != "active":
                raise LeaseConflictError("A lease requires an active property and rentable space.")
            lease = Lease(
                id=str(uuid4()), space_id=space.id, lease_kind=command.lease_kind, status="draft",
                contract_starts_on=command.contract_starts_on, contract_ends_on=command.contract_ends_on,
                occupancy_starts_on=command.occupancy_starts_on, executed_on=None,
                actual_move_out_on=None, end_reason=None, notes=command.notes,
                created_at=now, updated_at=now,
            )
            tx.insert_lease(lease)
            term = _term(lease, command.initial_term, now)
            tx.insert_term(term)
            tx.record_change(entity_type="lease", entity_id=lease.id, action="created", before=None,
                             after=lease.to_dict(), reason="lease_draft_created", correlation_id=correlation)
            tx.record_change(entity_type="lease_term", entity_id=term.id, action="created", before=None,
                             after=term.to_dict(), reason="lease_initial_term_created", correlation_id=correlation)
            seen: set[str] = set()
            for participant_command in command.participants:
                if participant_command.tenant_party_id in seen:
                    raise LeaseConflictError("A tenant party may participate only once in a lease draft.")
                seen.add(participant_command.tenant_party_id)
                participant = self._participant(tx, lease, participant_command, now)
                tx.insert_participant(participant)
                tx.record_change(entity_type="lease_participant", entity_id=participant.id, action="created",
                                 before=None, after=participant.to_dict(), reason="lease_participant_added",
                                 correlation_id=correlation)
            return lease.id

        return self.get(self._write(write, "Space"))

    def get(self, lease_id: str) -> dict[str, object]:
        record = self.unit_of_work.lease_view(lease_id)
        if record is None:
            raise LeaseNotFoundError("Lease was not found.")
        return _view(*record, inspection_attention=self.inspection_attention_reader(lease_id) if self.inspection_attention_reader else None)

    def list(
        self,
        *,
        status: str | None = None,
        property_id: str | None = None,
        space_id: str | None = None,
        tenant_party_id: str | None = None,
        contract_start_from: str | None = None,
        contract_start_to: str | None = None,
        renewal_due_on_or_before: str | None = None,
    ) -> list[dict[str, object]]:
        if status is not None and status not in LEASE_STATUSES:
            raise LeaseError("Unsupported lease status filter.")
        contract_start_from = None if contract_start_from is None else _date(contract_start_from, "Contract start from")
        contract_start_to = None if contract_start_to is None else _date(contract_start_to, "Contract start to")
        renewal_due_on_or_before = None if renewal_due_on_or_before is None else _date(renewal_due_on_or_before, "Renewal due date")
        return [
            _view(*record, inspection_attention=self.inspection_attention_reader(record[0].id) if self.inspection_attention_reader else None)
            for record in self.unit_of_work.lease_views(
                status=status,
                property_id=property_id,
                space_id=space_id,
                tenant_party_id=tenant_party_id,
                contract_start_from=contract_start_from,
                contract_start_to=contract_start_to,
                renewal_due_on_or_before=renewal_due_on_or_before,
            )
        ]

    def patch(self, lease_id: str, command: LeasePatchCommand) -> dict[str, object]:
        if not isinstance(command, LeasePatchCommand):
            raise LeaseError("A valid lease patch is required.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            _require_draft(lease)
            start = lease.contract_starts_on
            end = lease.contract_ends_on
            occupancy = lease.occupancy_starts_on
            notes = lease.notes
            if "contract_starts_on" in command.supplied_fields:
                start = _date(command.contract_starts_on, "Contract start date")
            if "contract_ends_on" in command.supplied_fields:
                end = None if command.contract_ends_on is None else _date(command.contract_ends_on, "Contract end date")
            if "occupancy_starts_on" in command.supplied_fields:
                occupancy = _date(command.occupancy_starts_on, "Occupancy start date")
            if "notes" in command.supplied_fields:
                notes = _optional(command.notes, "Lease notes", 4000)
            if end is not None and end <= start:
                raise LeaseError("Contract end date must follow its start date.")
            if occupancy < start or (end is not None and occupancy >= end):
                raise LeaseError("Occupancy start must fall within the contract range.")
            updated = replace(lease, contract_starts_on=start, contract_ends_on=end,
                              occupancy_starts_on=occupancy, notes=notes, updated_at=now)
            for participant in tx.participants(lease_id):
                _participant_range(updated, participant.starts_on, participant.ends_on)
            tx.replace_lease(updated)
            terms = tx.terms(lease_id)
            if len(terms) != 1:
                raise LeaseConflictError("A draft lease must have exactly one initial term.")
            prior_term = terms[0]
            updated_term = replace(prior_term, effective_on=start, ends_on=end)
            tx.delete_terms(lease_id)
            tx.insert_term(updated_term)
            tx.record_change(entity_type="lease", entity_id=lease.id, action="updated",
                             before=lease.to_dict(), after=updated.to_dict(), reason="lease_draft_updated",
                             correlation_id=correlation)
            if updated_term != prior_term:
                tx.record_change(entity_type="lease_term", entity_id=prior_term.id, action="updated", before=prior_term.to_dict(), after=updated_term.to_dict(), reason="lease_contract_dates_updated", correlation_id=correlation)
            return lease.id

        return self.get(self._write(write))

    def replace_initial_term(self, lease_id: str, command: TermCommand) -> dict[str, object]:
        if not isinstance(command, TermCommand):
            raise LeaseError("A valid lease term is required.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            _require_draft(lease)
            prior = tx.terms(lease_id)
            tx.delete_terms(lease_id)
            term = _term(lease, command, now)
            tx.insert_term(term)
            tx.record_change(entity_type="lease_term", entity_id=term.id, action="replaced",
                             before=None if not prior else prior[0].to_dict(), after=term.to_dict(),
                             reason="lease_initial_term_replaced", correlation_id=correlation)
            return lease.id

        return self.get(self._write(write))

    def add_participant(self, lease_id: str, command: ParticipantCommand) -> dict[str, object]:
        if not isinstance(command, ParticipantCommand):
            raise LeaseError("A valid participant is required.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            _require_draft(lease)
            if any(item.tenant_party_id == command.tenant_party_id for item in tx.participants(lease_id)):
                raise LeaseConflictError("A tenant party may participate only once in a lease draft.")
            participant = self._participant(tx, lease, command, now)
            tx.insert_participant(participant)
            tx.record_change(entity_type="lease_participant", entity_id=participant.id, action="created",
                             before=None, after=participant.to_dict(), reason="lease_participant_added",
                             correlation_id=correlation)
            return lease.id

        return self.get(self._write(write))

    def update_participant(self, lease_id: str, participant_id: str, command: ParticipantCommand) -> dict[str, object]:
        if not isinstance(command, ParticipantCommand):
            raise LeaseError("A valid participant is required.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            _require_draft(lease)
            participants = tx.participants(lease_id)
            current = next((item for item in participants if item.id == participant_id), None)
            if current is None:
                raise KeyError
            if any(item.id != participant_id and item.tenant_party_id == command.tenant_party_id for item in participants):
                raise LeaseConflictError("A tenant party may participate only once in a lease draft.")
            replacement = self._participant(tx, lease, command, now, participant_id)
            tx.replace_participant(replacement)
            tx.record_change(entity_type="lease_participant", entity_id=participant_id, action="updated",
                             before=current.to_dict(), after=replacement.to_dict(),
                             reason="lease_participant_updated", correlation_id=correlation)
            return lease.id

        return self.get(self._write(write, "Lease participant"))

    def remove_participant(self, lease_id: str, participant_id: str) -> dict[str, object]:
        correlation = str(uuid4())

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            _require_draft(lease)
            current = next((item for item in tx.participants(lease_id) if item.id == participant_id), None)
            if current is None:
                raise KeyError
            tx.delete_participant(participant_id)
            tx.record_change(entity_type="lease_participant", entity_id=participant_id, action="deleted",
                             before=current.to_dict(), after=None, reason="lease_participant_removed",
                             correlation_id=correlation)
            return lease.id

        return self.get(self._write(write, "Lease participant"))

    def execute(self, lease_id: str, *, executed_on: str, confirmed: bool) -> dict[str, object]:
        if confirmed is not True:
            raise LeaseError("Executing a lease requires explicit confirmation.")
        execution_date = _date(executed_on, "Execution date")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            _require_draft(lease)
            if lease.occupancy_starts_on < date.today().isoformat():
                raise LeaseError("Lease execution cannot create historical occupancy.")
            participants = tx.participants(lease_id)
            if any(not tx.tenant_profile_active(item.tenant_party_id) for item in participants):
                raise LeaseConflictError("Every participant must have an active tenant profile at execution.")
            required_role = "primary_tenant" if lease.lease_kind == "residential" else "business_signatory"
            if sum(item.participant_role == required_role and _active_on(item.starts_on, item.ends_on, lease.occupancy_starts_on) for item in participants) != 1:
                raise LeaseError(f"Execution requires exactly one active {required_role.replace('_', ' ')}.")
            terms = tx.terms(lease_id)
            if len(terms) != 1 or terms[0].effective_on != lease.contract_starts_on or terms[0].ends_on != lease.contract_ends_on:
                raise LeaseConflictError("Initial terms must cover the lease contract range.")
            space = tx.space(lease.space_id)
            property = None if space is None else tx.property(space.property_id)
            if space is None or space.status != "active" or property is None or property.status != "active":
                raise LeaseConflictError("The lease space or property is archived.")
            period = self._begin_lease_occupancy(tx, lease, now, correlation)
            updated = replace(lease, status="executed", executed_on=execution_date, updated_at=now)
            tx.replace_lease(updated)
            tx.record_change(entity_type="lease", entity_id=lease.id, action="executed",
                             before=lease.to_dict(), after=updated.to_dict(), reason="lease_executed",
                             correlation_id=correlation)
            tx.record_change(entity_type="space_occupancy", entity_id=period.id, action="created",
                             before=None, after=period.to_dict(), reason="lease_executed",
                             correlation_id=correlation)
            return lease.id

        return self.get(self._write(write))

    def end(self, lease_id: str, *, actual_move_out_on: str, confirmed: bool) -> dict[str, object]:
        return self._close(lease_id, "ended", "contract_completed", actual_move_out_on, confirmed)

    def terminate(self, lease_id: str, *, actual_move_out_on: str, end_reason: str, confirmed: bool) -> dict[str, object]:
        if end_reason not in END_REASONS - {"contract_completed"}:
            raise LeaseError("A supported early termination reason is required.")
        return self._close(lease_id, "terminated", end_reason, actual_move_out_on, confirmed)

    def create_termination_case(self, lease_id: str, command: TerminationCaseCommand) -> dict[str, object]:
        if not isinstance(command, TerminationCaseCommand):
            raise LeaseError("A valid termination request is required.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            if lease.status != "executed":
                raise LeaseConflictError("Only an executed lease can receive an early-termination request.")
            if any(item.status not in {"withdrawn", "declined", "completed"} for item in tx.termination_cases(lease_id)):
                raise LeaseConflictError("The lease already has an open termination case.")
            item = LeaseTerminationCase(
                id=str(uuid4()), lease_id=lease_id, status="requested", reason=command.reason,
                notice_received_on=command.notice_received_on,
                requested_termination_on=command.requested_termination_on,
                expected_move_out_on=command.expected_move_out_on,
                agreed_termination_on=None, accepted_on=None, completed_on=None,
                tenant_explanation=command.tenant_explanation,
                contract_clause_reference=command.contract_clause_reference,
                operator_notes=command.operator_notes, created_at=now, updated_at=now,
            )
            tx.insert_termination_case(item)
            tx.record_change(entity_type="lease_termination_case", entity_id=item.id, action="created", before=None, after=item.to_dict(), reason="early_termination_requested", correlation_id=correlation)
            return item.id

        return self.get_termination_case(self._write(write))

    def list_termination_cases(self, lease_id: str) -> list[dict[str, object]]:
        if self.unit_of_work.lease_view(lease_id) is None:
            raise LeaseNotFoundError("Lease was not found.")
        return [_termination_view(item, proposals, files) for item, proposals, files in self.unit_of_work.termination_case_views(lease_id)]

    def get_termination_case(self, case_id: str) -> dict[str, object]:
        record = self.unit_of_work.termination_case_view(case_id)
        if record is None:
            raise LeaseNotFoundError("Termination case was not found.")
        return _termination_view(*record)

    def add_termination_proposal(self, case_id: str, command: TerminationProposalCommand) -> dict[str, object]:
        if not isinstance(command, TerminationProposalCommand):
            raise LeaseError("A valid termination proposal is required.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            case = tx.termination_case(case_id)
            if case is None:
                raise KeyError
            if case.status in {"accepted", "withdrawn", "declined", "completed"}:
                raise LeaseConflictError("This termination case no longer accepts proposals.")
            proposals = tx.termination_proposals(case_id)
            for current in proposals:
                if current.status == "open":
                    countered = replace(current, status="countered", decided_on=date.today().isoformat())
                    tx.replace_termination_proposal(countered)
                    tx.record_change(entity_type="lease_termination_proposal", entity_id=current.id, action="countered", before=current.to_dict(), after=countered.to_dict(), reason="termination_counterproposal_recorded", correlation_id=correlation)
            proposal = LeaseTerminationProposal(
                id=str(uuid4()), termination_case_id=case_id, proposal_version=len(proposals) + 1,
                proposed_termination_on=command.proposed_termination_on,
                expected_move_out_on=command.expected_move_out_on,
                rent_responsibility_ends_on=command.rent_responsibility_ends_on,
                termination_fee_minor=command.termination_fee_minor, currency_code=command.currency_code,
                fee_waived=command.fee_waived,
                replacement_tenant_condition=command.replacement_tenant_condition,
                access_arrangement=command.access_arrangement, other_terms=command.other_terms,
                response_due_on=command.response_due_on, status="open", decided_on=None, created_at=now,
            )
            tx.insert_termination_proposal(proposal)
            updated_case = replace(case, status="proposed", updated_at=now)
            tx.replace_termination_case(updated_case)
            tx.record_change(entity_type="lease_termination_proposal", entity_id=proposal.id, action="created", before=None, after=proposal.to_dict(), reason="termination_proposal_recorded", correlation_id=correlation)
            tx.record_change(entity_type="lease_termination_case", entity_id=case.id, action="status_changed", before=case.to_dict(), after=updated_case.to_dict(), reason="termination_proposal_recorded", correlation_id=correlation)
            return case.id

        return self.get_termination_case(self._write(write, "Termination case"))

    def accept_termination_proposal(self, case_id: str, proposal_id: str, *, accepted_on: str, confirmed: bool) -> dict[str, object]:
        if confirmed is not True:
            raise LeaseError("Accepting a termination agreement requires explicit confirmation.")
        accepted = _date(accepted_on, "Acceptance date")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            case = tx.termination_case(case_id)
            if case is None:
                raise KeyError
            if case.status != "proposed":
                raise LeaseConflictError("Only a proposed termination case can be accepted.")
            proposal = next((item for item in tx.termination_proposals(case_id) if item.id == proposal_id), None)
            if proposal is None:
                raise KeyError
            if proposal.status != "open":
                raise LeaseConflictError("Only an open proposal can be accepted.")
            accepted_proposal = replace(proposal, status="accepted", decided_on=accepted)
            updated_case = replace(case, status="accepted", agreed_termination_on=proposal.proposed_termination_on, accepted_on=accepted, expected_move_out_on=proposal.expected_move_out_on, updated_at=now)
            tx.replace_termination_proposal(accepted_proposal)
            tx.replace_termination_case(updated_case)
            tx.record_change(entity_type="lease_termination_proposal", entity_id=proposal.id, action="accepted", before=proposal.to_dict(), after=accepted_proposal.to_dict(), reason="termination_agreement_accepted", correlation_id=correlation)
            tx.record_change(entity_type="lease_termination_case", entity_id=case.id, action="accepted", before=case.to_dict(), after=updated_case.to_dict(), reason="termination_agreement_accepted", correlation_id=correlation)
            return case.id

        return self.get_termination_case(self._write(write, "Termination case"))

    def transition_termination_case(self, case_id: str, *, status: str, operator_notes: str | None = None) -> dict[str, object]:
        if status not in {"under_review", "withdrawn", "declined"}:
            raise LeaseError("Unsupported termination-case transition.")
        notes = _optional(operator_notes, "Operator notes", 4000)
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            current = tx.termination_case(case_id)
            if current is None:
                raise KeyError
            allowed = {"requested": {"under_review", "withdrawn", "declined"}, "under_review": {"withdrawn", "declined"}, "proposed": {"withdrawn", "declined"}}
            if status not in allowed.get(current.status, set()):
                raise LeaseConflictError("The termination case cannot make that transition.")
            updated = replace(current, status=status, operator_notes=notes if operator_notes is not None else current.operator_notes, updated_at=now)
            tx.replace_termination_case(updated)
            if status in {"withdrawn", "declined"}:
                proposal_status = "withdrawn" if status == "withdrawn" else "rejected"
                for proposal in tx.termination_proposals(case_id):
                    if proposal.status != "open":
                        continue
                    decided = replace(
                        proposal,
                        status=proposal_status,
                        decided_on=date.today().isoformat(),
                    )
                    tx.replace_termination_proposal(decided)
                    tx.record_change(
                        entity_type="lease_termination_proposal",
                        entity_id=proposal.id,
                        action=proposal_status,
                        before=proposal.to_dict(),
                        after=decided.to_dict(),
                        reason=f"termination_case_{status}",
                        correlation_id=correlation,
                    )
            tx.record_change(entity_type="lease_termination_case", entity_id=case_id, action="status_changed", before=current.to_dict(), after=updated.to_dict(), reason=f"termination_case_{status}", correlation_id=correlation)
            return case_id

        return self.get_termination_case(self._write(write, "Termination case"))

    def complete_termination_case(self, case_id: str, *, actual_move_out_on: str, confirmed: bool) -> dict[str, object]:
        record = self.unit_of_work.termination_case_view(case_id)
        if record is None:
            raise LeaseNotFoundError("Termination case was not found.")
        case = record[0]
        if case.status != "accepted":
            raise LeaseConflictError("Only an accepted termination case can be completed.")
        return self._close(
            case.lease_id,
            "terminated",
            _termination_end_reason(case),
            actual_move_out_on,
            confirmed,
            termination_case_id=case_id,
        )

    def void(self, lease_id: str, *, confirmed: bool) -> dict[str, object]:
        if confirmed is not True:
            raise LeaseError("Voiding a lease requires explicit confirmation.")
        correlation, now, today = str(uuid4()), _now(), date.today().isoformat()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            if lease.status != "executed":
                raise LeaseError("Only an executed lease can be voided.")
            if lease.occupancy_starts_on <= today:
                raise LeaseConflictError("A lease cannot be voided after occupancy begins.")
            periods = tx.occupancy_periods(lease.space_id)
            owned = next((item for item in periods if item.source_kind == "lease" and item.source_id == lease.id and item.record_state == "valid" and item.occupancy_status == "occupied"), None)
            if owned is None:
                raise LeaseConflictError("The lease-owned occupancy period is missing.")
            cancelled = replace(owned, record_state="cancelled", cancelled_at=now)
            tx.replace_occupancy_period(cancelled)
            predecessor = next((item for item in periods if item.record_state == "valid" and item.ends_on == owned.starts_on), None)
            if predecessor is not None:
                reopened = replace(predecessor, ends_on=None, ended_at=None)
                tx.replace_occupancy_period(reopened)
                tx.record_change(entity_type="space_occupancy", entity_id=predecessor.id, action="reopened",
                                 before=predecessor.to_dict(), after=reopened.to_dict(), reason="lease_voided",
                                 correlation_id=correlation)
            updated = replace(lease, status="void", updated_at=now)
            tx.replace_lease(updated)
            tx.record_change(entity_type="space_occupancy", entity_id=owned.id, action="cancelled",
                             before=owned.to_dict(), after=cancelled.to_dict(), reason="lease_voided",
                             correlation_id=correlation)
            tx.record_change(entity_type="lease", entity_id=lease.id, action="voided", before=lease.to_dict(),
                             after=updated.to_dict(), reason="lease_voided", correlation_id=correlation)
            return lease.id

        return self.get(self._write(write))

    def add_renewal_option(self, lease_id: str, command: RenewalCommand) -> dict[str, object]:
        if not isinstance(command, RenewalCommand):
            raise LeaseError("A valid renewal option is required.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            if lease.status not in {"executed", "ended"}:
                raise LeaseError("Renewal options require an executed or ended lease.")
            item = LeaseRenewalOption(
                str(uuid4()), lease.id, "open", command.proposed_starts_on, command.proposed_ends_on,
                command.notice_due_on, command.response_due_on, None, command.notes, now, now,
            )
            tx.insert_renewal_option(item)
            tx.record_change(entity_type="lease_renewal_option", entity_id=item.id, action="created",
                             before=None, after=item.to_dict(), reason="lease_renewal_recorded",
                             correlation_id=correlation)
            return lease.id

        return self.get(self._write(write))

    def decide_renewal_option(self, lease_id: str, option_id: str, *, status: str, decided_on: str, notes: str | None = None) -> dict[str, object]:
        if status not in RENEWAL_STATUSES - {"open"}:
            raise LeaseError("A supported renewal decision is required.")
        decision_date = _date(decided_on, "Renewal decision date")
        normalized_notes = _optional(notes, "Renewal notes", 2000)
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            _required_lease(tx, lease_id)
            current = next((item for item in tx.renewal_options(lease_id) if item.id == option_id), None)
            if current is None:
                raise KeyError
            if current.status != "open":
                raise LeaseConflictError("The renewal option has already been decided.")
            updated = replace(current, status=status, decided_on=decision_date,
                              notes=normalized_notes if notes is not None else current.notes, updated_at=now)
            tx.replace_renewal_option(updated)
            tx.record_change(entity_type="lease_renewal_option", entity_id=option_id, action="status_changed",
                             before=current.to_dict(), after=updated.to_dict(), reason="lease_renewal_decided",
                             correlation_id=correlation)
            return lease_id

        return self.get(self._write(write, "Renewal option"))

    def update_renewal_option(self, lease_id: str, option_id: str, command: RenewalPatchCommand) -> dict[str, object]:
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            _required_lease(tx, lease_id)
            current = next((item for item in tx.renewal_options(lease_id) if item.id == option_id), None)
            if current is None:
                raise KeyError
            if current.status != "open":
                raise LeaseConflictError("Only an open renewal option can be edited.")
            values = {field: getattr(current, field) for field in command.supplied_fields}
            for field in command.supplied_fields:
                value = getattr(command, field)
                values[field] = _optional(value, "Renewal notes", 2000) if field == "notes" else (None if value is None else _date(value, field.replace("_", " ").title()))
            updated = replace(current, **values, updated_at=now)
            if updated.proposed_starts_on is None:
                raise LeaseError("Proposed start date is required.")
            if updated.proposed_ends_on is not None and updated.proposed_ends_on <= updated.proposed_starts_on:
                raise LeaseError("Proposed end date must follow its start date.")
            tx.replace_renewal_option(updated)
            tx.record_change(entity_type="lease_renewal_option", entity_id=option_id, action="updated", before=current.to_dict(), after=updated.to_dict(), reason="lease_renewal_updated", correlation_id=correlation)
            return lease_id

        return self.get(self._write(write, "Renewal option"))

    def _close(self, lease_id: str, status: str, reason: str, move_out_on: str,
               confirmed: bool, termination_case_id: str | None = None) -> dict[str, object]:
        if confirmed is not True:
            raise LeaseError("Ending a lease requires explicit move-out confirmation.")
        move_out = _date(move_out_on, "Actual move-out date")
        if move_out > date.today().isoformat():
            raise LeaseError("Actual move-out cannot be in the future.")
        correlation, now = str(uuid4()), _now()

        def write(tx: LeaseTransaction) -> str:
            lease = _required_lease(tx, lease_id)
            if lease.status != "executed":
                raise LeaseError("Only an executed lease can be ended or terminated.")
            if status == "ended":
                if lease.contract_ends_on is not None and move_out < lease.contract_ends_on:
                    raise LeaseConflictError("Early move-out requires termination completion.")
                if any(item.status == "accepted" for item in tx.termination_cases(lease_id)):
                    raise LeaseConflictError("Complete the accepted termination case instead.")
            accepted_case = None
            if status == "terminated":
                accepted_case = next((item for item in tx.termination_cases(lease_id)
                                      if item.status == "accepted" and
                                      (termination_case_id is None or item.id == termination_case_id)), None)
                if accepted_case is None:
                    raise LeaseConflictError("The accepted termination case is missing.")
                expected_reason = _termination_end_reason(accepted_case)
                if reason != expected_reason:
                    raise LeaseConflictError(
                        "Lease termination reason must match the accepted termination case."
                    )
            if move_out <= lease.occupancy_starts_on:
                raise LeaseError("Actual move-out must follow occupancy start.")
            periods = tx.occupancy_periods(lease.space_id)
            owned = next((item for item in periods if item.source_kind == "lease" and item.source_id == lease.id and item.record_state == "valid" and item.occupancy_status == "occupied"), None)
            if owned is None or owned.starts_on >= move_out or (owned.ends_on is not None and owned.ends_on != move_out):
                raise LeaseConflictError("The lease-owned occupancy period cannot be closed safely.")
            ended = replace(owned, ends_on=move_out, ended_at=now)
            vacant = SpaceOccupancyPeriod(
                str(uuid4()), lease.space_id, "vacant", move_out, None, "valid", None,
                "lease", lease.id, f"Vacant after {status} lease", now, None, None,
            )
            tx.replace_occupancy_period(ended)
            tx.insert_occupancy_period(vacant)
            updated = replace(lease, status=status, actual_move_out_on=move_out,
                              end_reason=reason, updated_at=now)
            tx.replace_lease(updated)
            if status == "terminated":
                case = accepted_case
                completed = replace(case, status="completed", completed_on=move_out, updated_at=now)
                tx.replace_termination_case(completed)
                tx.record_change(entity_type="lease_termination_case", entity_id=case.id, action="completed", before=case.to_dict(), after=completed.to_dict(), reason="lease_terminated", correlation_id=correlation)
            tx.record_change(entity_type="space_occupancy", entity_id=ended.id, action="ended",
                             before=owned.to_dict(), after=ended.to_dict(), reason=f"lease_{status}",
                             correlation_id=correlation)
            tx.record_change(entity_type="space_occupancy", entity_id=vacant.id, action="created",
                             before=None, after=vacant.to_dict(), reason=f"lease_{status}",
                             correlation_id=correlation)
            tx.record_change(entity_type="lease", entity_id=lease.id, action=status,
                             before=lease.to_dict(), after=updated.to_dict(), reason=f"lease_{status}",
                             correlation_id=correlation)
            return lease.id

        return self.get(self._write(write))

    def _participant(self, tx: LeaseTransaction, lease: Lease, command: ParticipantCommand, now: str, participant_id: str | None = None) -> LeaseParticipant:
        if not tx.tenant_profile_active(command.tenant_party_id):
            raise LeaseConflictError("Lease participants require active tenant profiles.")
        starts_on = command.starts_on or lease.contract_starts_on
        ends_on = command.ends_on or lease.contract_ends_on
        _participant_range(lease, starts_on, ends_on)
        return LeaseParticipant(participant_id or str(uuid4()), lease.id, command.tenant_party_id,
                                command.participant_role, starts_on, ends_on, command.notes, now, now)

    def _begin_lease_occupancy(self, tx: LeaseTransaction, lease: Lease, now: str, correlation: str) -> SpaceOccupancyPeriod:
        periods = tx.occupancy_periods(lease.space_id)
        start = lease.occupancy_starts_on
        if any(item.record_state == "valid" and item.starts_on > start for item in periods):
            raise LeaseConflictError("A current or scheduled occupancy transition conflicts with this lease.")
        active = next((item for item in periods if item.record_state == "valid" and item.starts_on <= start and (item.ends_on is None or item.ends_on > start)), None)
        if active is None:
            raise LeaseConflictError("The space occupancy timeline is incomplete.")
        if active.source_kind != "manual":
            prior_lease = tx.lease(active.source_id) if active.source_kind == "lease" and active.source_id else None
            reusable_vacancy = active.occupancy_status == "vacant" and prior_lease is not None and prior_lease.status in {"ended", "terminated"}
            if not reusable_vacancy:
                raise LeaseConflictError("Another source owns the space occupancy timeline.")
        period = SpaceOccupancyPeriod(
            str(uuid4()), lease.space_id, "occupied", start, None, "valid", None,
            "lease", lease.id, "Occupied under executed lease", now, None, None,
        )
        if active.starts_on == start:
            prior = replace(active, record_state="superseded", superseded_by_id=period.id, ended_at=now)
            action = "superseded"
            # Release the open-period constraint before inserting the referenced successor;
            # SQLite foreign keys are immediate, so connect the reference afterward.
            tx.replace_occupancy_period(replace(prior, superseded_by_id=None))
            tx.insert_occupancy_period(period)
            tx.replace_occupancy_period(prior)
        else:
            prior = replace(active, ends_on=start, ended_at=now)
            action = "ended"
            tx.replace_occupancy_period(prior)
            tx.insert_occupancy_period(period)
        tx.record_change(entity_type="space_occupancy", entity_id=active.id, action=action,
                         before=active.to_dict(), after=prior.to_dict(), reason="lease_executed",
                         correlation_id=correlation)
        return period

    def _write(self, operation, label: str = "Lease"):
        try:
            return self.unit_of_work.write(operation)
        except KeyError as error:
            raise LeaseNotFoundError(f"{label} was not found.") from error


def _required_lease(tx: LeaseTransaction, lease_id: str) -> Lease:
    lease = tx.lease(lease_id)
    if lease is None:
        raise KeyError
    return lease


def _require_draft(lease: Lease) -> None:
    if lease.status != "draft":
        raise LeaseConflictError("Only a draft lease can be edited.")


def _term(lease: Lease, command: TermCommand, now: str) -> LeaseTerm:
    return LeaseTerm(str(uuid4()), lease.id, lease.contract_starts_on, lease.contract_ends_on,
                     command.base_rent_minor, command.currency_code, command.payment_frequency,
                     command.payment_due_day, command.agreed_security_deposit_minor, now)


def _participant_range(lease: Lease, starts_on: str, ends_on: str | None) -> None:
    start = _date(starts_on, "Participant start date")
    end = None if ends_on is None else _date(ends_on, "Participant end date")
    if start < lease.contract_starts_on or (lease.contract_ends_on is not None and start >= lease.contract_ends_on):
        raise LeaseError("Participant dates must fall within the lease contract.")
    if end is not None and (end <= start or (lease.contract_ends_on is not None and end > lease.contract_ends_on)):
        raise LeaseError("Participant end date must follow its start and remain within the contract.")


def _active_on(starts_on: str, ends_on: str | None, when: str) -> bool:
    return starts_on <= when and (ends_on is None or ends_on > when)


def _termination_end_reason(case: LeaseTerminationCase) -> str:
    if case.reason == "mutual":
        return "mutual_termination"
    if case.reason == "other":
        return "other"
    return "early_termination"


def _view(lease: Lease, terms: list[LeaseTerm], participants: list[LeaseParticipant], renewals: list[LeaseRenewalOption], files: list[dict[str, object]], inspection_attention=None) -> dict[str, object]:
    today = date.today().isoformat()
    if lease.status in {"ended", "terminated", "void"}:
        occupancy_state = "ended"
    elif lease.status == "executed":
        occupancy_state = "scheduled" if lease.occupancy_starts_on > today else "current"
    else:
        occupancy_state = "none"
    return {
        **lease.to_dict(),
        "occupancyState": occupancy_state,
        "terms": [item.to_dict() for item in terms],
        "participants": [item.to_dict() for item in participants],
        "renewalOptions": [item.to_dict() for item in renewals],
        "files": files,
        "inspectionAttention": inspection_attention or {"preMoveIn": "not_available", "postMoveOut": "not_available"},
    }


def _termination_view(item: LeaseTerminationCase, proposals: list[LeaseTerminationProposal], files: list[dict[str, object]]) -> dict[str, object]:
    return {**item.to_dict(), "proposals": [proposal.to_dict() for proposal in proposals], "files": files}


def _date(value: object, label: str) -> str:
    if type(value) is date:
        return value.isoformat()
    if not isinstance(value, str):
        raise LeaseError(f"{label} must be a calendar date.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise LeaseError(f"{label} must be a valid ISO date.") from error


def _text(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not (text := value.strip()) or len(text) > limit:
        raise LeaseError(f"{label} must contain 1 to {limit} characters.")
    return text


def _currency_code(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or any(character < "A" or character > "Z" for character in value)
    ):
        raise LeaseError("Currency must be exactly three ASCII uppercase letters.")
    return value


def _optional(value: object, label: str, limit: int) -> str | None:
    if value is None:
        return None
    return _text(value, label, limit)


def _now() -> str:
    return datetime.now(UTC).isoformat()
