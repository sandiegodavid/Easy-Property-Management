"""Typed local LEASE-001 API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.leases.application.ports import LeaseConflictError
from app.modules.leases.application.service import (
    LeaseCreateCommand,
    LeaseError,
    LeaseNotFoundError,
    LeasePatchCommand,
    LeaseService,
    ParticipantCommand,
    RenewalCommand,
    RenewalPatchCommand,
    TermCommand,
    TerminationCaseCommand,
    TerminationProposalCommand,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TermRequest(Contract):
    baseRentMinor: int = Field(ge=0)
    currencyCode: str = Field(min_length=3, max_length=3)
    paymentFrequency: Literal["monthly", "weekly"]
    paymentDueDay: int | None = Field(None, ge=1, le=31)
    agreedSecurityDepositMinor: int = Field(ge=0)


class ParticipantRequest(Contract):
    tenantPartyId: str = Field(min_length=1, max_length=80)
    participantRole: Literal["primary_tenant", "co_tenant", "guarantor", "business_signatory"]
    startsOn: date | None = None
    endsOn: date | None = None
    notes: str | None = Field(None, max_length=2000)


class LeaseCreateRequest(Contract):
    spaceId: str = Field(min_length=1, max_length=80)
    leaseKind: Literal["residential", "commercial"]
    contractStartsOn: date
    contractEndsOn: date | None = None
    occupancyStartsOn: date
    initialTerm: TermRequest
    participants: list[ParticipantRequest] = Field(min_length=1)
    notes: str | None = Field(None, max_length=4000)


class LeasePatchRequest(Contract):
    contractStartsOn: date | None = None
    contractEndsOn: date | None = None
    occupancyStartsOn: date | None = None
    notes: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one lease field is required")
        return self


class ConfirmationRequest(Contract):
    confirmed: StrictBool


class ExecuteRequest(ConfirmationRequest):
    executedOn: date


class EndRequest(ConfirmationRequest):
    actualMoveOutOn: date


class TerminateRequest(EndRequest):
    endReason: Literal["early_termination", "mutual_termination", "other"]


class TerminationCaseRequest(Contract):
    reason: Literal["job_relocation", "military", "habitability", "mutual", "other"]
    noticeReceivedOn: date
    requestedTerminationOn: date
    expectedMoveOutOn: date
    tenantExplanation: str | None = Field(None, max_length=4000)
    contractClauseReference: str | None = Field(None, max_length=500)
    operatorNotes: str | None = Field(None, max_length=4000)


class TerminationProposalRequest(Contract):
    proposedTerminationOn: date
    expectedMoveOutOn: date
    rentResponsibilityEndsOn: date | None = None
    terminationFeeMinor: int | None = Field(None, ge=0)
    currencyCode: str | None = Field(None, min_length=3, max_length=3)
    feeWaived: StrictBool = False
    replacementTenantCondition: str | None = Field(None, max_length=2000)
    accessArrangement: str | None = Field(None, max_length=2000)
    otherTerms: str | None = Field(None, max_length=2000)
    responseDueOn: date | None = None


class TerminationAcceptRequest(ConfirmationRequest):
    proposalId: str = Field(min_length=1, max_length=80)
    acceptedOn: date


class TerminationCasePatchRequest(Contract):
    status: Literal["under_review", "withdrawn", "declined"]
    operatorNotes: str | None = Field(None, max_length=4000)


class TerminationCompleteRequest(ConfirmationRequest):
    actualMoveOutOn: date


class TerminationProposalResponse(Contract):
    id: str
    terminationCaseId: str
    proposalVersion: int
    proposedTerminationOn: date
    expectedMoveOutOn: date
    rentResponsibilityEndsOn: date | None
    terminationFeeMinor: int | None
    currencyCode: str | None
    feeWaived: bool
    replacementTenantCondition: str | None
    accessArrangement: str | None
    otherTerms: str | None
    responseDueOn: date | None
    status: Literal["open", "accepted", "rejected", "countered", "withdrawn", "expired"]
    decidedOn: date | None
    createdAt: datetime


class TerminationCaseResponse(Contract):
    id: str
    leaseId: str
    status: Literal["requested", "under_review", "proposed", "accepted", "withdrawn", "declined", "completed"]
    reason: Literal["job_relocation", "military", "habitability", "mutual", "other"]
    noticeReceivedOn: date
    requestedTerminationOn: date
    expectedMoveOutOn: date
    agreedTerminationOn: date | None
    acceptedOn: date | None
    completedOn: date | None
    tenantExplanation: str | None
    contractClauseReference: str | None
    operatorNotes: str | None
    createdAt: datetime
    updatedAt: datetime
    proposals: list[TerminationProposalResponse]
    files: list[LeaseFileResponse]


class RenewalRequest(Contract):
    proposedStartsOn: date
    proposedEndsOn: date | None = None
    noticeDueOn: date | None = None
    responseDueOn: date | None = None
    notes: str | None = Field(None, max_length=2000)


class RenewalDecisionRequest(Contract):
    status: Literal["exercised", "declined", "expired", "withdrawn"] | None = None
    decidedOn: date | None = None
    proposedStartsOn: date | None = None
    proposedEndsOn: date | None = None
    noticeDueOn: date | None = None
    responseDueOn: date | None = None
    notes: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def validate_operation(self):
        if not self.model_fields_set:
            raise ValueError("At least one renewal field is required")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Renewal status cannot be null")
        if (self.status is None) != (self.decidedOn is None):
            raise ValueError("A renewal decision requires both status and decidedOn")
        if self.status is not None and self.model_fields_set - {"status", "decidedOn", "notes"}:
            raise ValueError("A renewal decision cannot also edit proposal fields")
        return self


class LeaseTermResponse(Contract):
    id: str
    leaseId: str
    effectiveOn: date
    endsOn: date | None
    baseRentMinor: int
    currencyCode: str
    paymentFrequency: Literal["monthly", "weekly"]
    paymentDueDay: int | None
    agreedSecurityDepositMinor: int
    createdAt: datetime


class LeaseParticipantResponse(Contract):
    id: str
    leaseId: str
    tenantPartyId: str
    participantRole: Literal["primary_tenant", "co_tenant", "guarantor", "business_signatory"]
    startsOn: date
    endsOn: date | None
    notes: str | None
    createdAt: datetime
    updatedAt: datetime


class LeaseRenewalResponse(Contract):
    id: str
    leaseId: str
    status: Literal["open", "exercised", "declined", "expired", "withdrawn"]
    proposedStartsOn: date
    proposedEndsOn: date | None
    noticeDueOn: date | None
    responseDueOn: date | None
    decidedOn: date | None
    notes: str | None
    createdAt: datetime
    updatedAt: datetime


class LeaseFileResponse(Contract):
    id: str
    originalName: str
    mediaType: str
    sizeBytes: int
    contentSha256: str
    linkId: str
    purpose: str


class InspectionAttentionResponse(Contract):
    preMoveIn: str
    postMoveOut: str


class LeaseResponse(Contract):
    id: str
    spaceId: str
    leaseKind: Literal["residential", "commercial"]
    status: Literal["draft", "executed", "ended", "terminated", "void"]
    contractStartsOn: date
    contractEndsOn: date | None
    occupancyStartsOn: date
    executedOn: date | None
    actualMoveOutOn: date | None
    endReason: Literal["contract_completed", "early_termination", "mutual_termination", "other"] | None
    notes: str | None
    createdAt: datetime
    updatedAt: datetime
    occupancyState: Literal["none", "scheduled", "current", "ended"]
    terms: list[LeaseTermResponse]
    participants: list[LeaseParticipantResponse]
    renewalOptions: list[LeaseRenewalResponse]
    files: list[LeaseFileResponse]
    inspectionAttention: InspectionAttentionResponse


def build_router(service: LeaseService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["leases"])
    leases = APIRouter(prefix="/api/leases")

    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise HTTPException(503, "Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except LeaseNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except LeaseConflictError as error:
            raise HTTPException(409, str(error)) from error
        except LeaseError as error:
            raise HTTPException(400, str(error)) from error

    @leases.post("", status_code=status.HTTP_201_CREATED, response_model=LeaseResponse)
    def create(data: LeaseCreateRequest):
        ready(True)
        return invoke(lambda: service.create(_create_command(data)))

    @leases.get("", response_model=list[LeaseResponse])
    def list_leases(
        lease_status: Literal["draft", "executed", "ended", "terminated", "void"] | None = Query(None, alias="status"),
        property_id: str | None = Query(None, alias="propertyId"),
        space_id: str | None = Query(None, alias="spaceId"),
        tenant_party_id: str | None = Query(None, alias="tenantPartyId"),
        contract_start_from: date | None = Query(None, alias="contractStartFrom"),
        contract_start_to: date | None = Query(None, alias="contractStartTo"),
        renewal_due_on_or_before: date | None = Query(None, alias="renewalDueOnOrBefore"),
    ):
        ready()
        return invoke(lambda: service.list(
            status=lease_status, property_id=property_id, space_id=space_id,
            tenant_party_id=tenant_party_id, contract_start_from=contract_start_from,
            contract_start_to=contract_start_to,
            renewal_due_on_or_before=renewal_due_on_or_before,
        ))

    @leases.get("/{lease_id}", response_model=LeaseResponse)
    def get(lease_id: str):
        ready()
        return invoke(lambda: service.get(lease_id))

    @leases.patch("/{lease_id}", response_model=LeaseResponse)
    def patch(lease_id: str, data: LeasePatchRequest):
        ready(True)
        mapping = {
            "contractStartsOn": "contract_starts_on",
            "contractEndsOn": "contract_ends_on",
            "occupancyStartsOn": "occupancy_starts_on",
            "notes": "notes",
        }
        supplied = frozenset(mapping[field] for field in data.model_fields_set)
        command = LeasePatchCommand(
            contract_starts_on=data.contractStartsOn,
            contract_ends_on=data.contractEndsOn,
            occupancy_starts_on=data.occupancyStartsOn,
            notes=data.notes,
            supplied_fields=supplied,
        )
        return invoke(lambda: service.patch(lease_id, command))

    @leases.put("/{lease_id}/initial-term", response_model=LeaseResponse)
    def replace_term(lease_id: str, data: TermRequest):
        ready(True)
        return invoke(lambda: service.replace_initial_term(lease_id, _term_command(data)))

    @leases.post("/{lease_id}/participants", status_code=201, response_model=LeaseResponse)
    def add_participant(lease_id: str, data: ParticipantRequest):
        ready(True)
        return invoke(lambda: service.add_participant(lease_id, _participant_command(data)))

    @leases.patch("/{lease_id}/participants/{participant_id}", response_model=LeaseResponse)
    def update_participant(lease_id: str, participant_id: str, data: ParticipantRequest):
        ready(True)
        return invoke(lambda: service.update_participant(lease_id, participant_id, _participant_command(data)))

    @leases.delete("/{lease_id}/participants/{participant_id}", response_model=LeaseResponse)
    def remove_participant(lease_id: str, participant_id: str):
        ready(True)
        return invoke(lambda: service.remove_participant(lease_id, participant_id))

    @leases.post("/{lease_id}/execute", response_model=LeaseResponse)
    def execute(lease_id: str, data: ExecuteRequest):
        ready(True)
        return invoke(lambda: service.execute(lease_id, executed_on=data.executedOn, confirmed=data.confirmed))

    @leases.post("/{lease_id}/end", response_model=LeaseResponse)
    def end(lease_id: str, data: EndRequest):
        ready(True)
        return invoke(lambda: service.end(lease_id, actual_move_out_on=data.actualMoveOutOn,
                                          confirmed=data.confirmed))

    @leases.post("/{lease_id}/terminate", response_model=LeaseResponse)
    def terminate(lease_id: str, data: TerminateRequest):
        ready(True)
        return invoke(lambda: service.terminate(lease_id, actual_move_out_on=data.actualMoveOutOn,
                                                end_reason=data.endReason, confirmed=data.confirmed))

    @leases.post("/{lease_id}/void", response_model=LeaseResponse)
    def void(lease_id: str, data: ConfirmationRequest):
        ready(True)
        return invoke(lambda: service.void(lease_id, confirmed=data.confirmed))

    @leases.post("/{lease_id}/renewal-options", status_code=201, response_model=LeaseResponse)
    def add_renewal(lease_id: str, data: RenewalRequest):
        ready(True)
        command = RenewalCommand(data.proposedStartsOn, data.proposedEndsOn, data.noticeDueOn,
                                 data.responseDueOn, data.notes)
        return invoke(lambda: service.add_renewal_option(lease_id, command))

    @leases.patch("/{lease_id}/renewal-options/{option_id}", response_model=LeaseResponse)
    def decide_renewal(lease_id: str, option_id: str, data: RenewalDecisionRequest):
        ready(True)
        if data.status is not None:
            return invoke(lambda: service.decide_renewal_option(
                lease_id, option_id, status=data.status, decided_on=data.decidedOn, notes=data.notes
            ))
        mapping = {"proposedStartsOn": "proposed_starts_on", "proposedEndsOn": "proposed_ends_on", "noticeDueOn": "notice_due_on", "responseDueOn": "response_due_on", "notes": "notes"}
        command = RenewalPatchCommand(
            proposed_starts_on=data.proposedStartsOn, proposed_ends_on=data.proposedEndsOn,
            notice_due_on=data.noticeDueOn, response_due_on=data.responseDueOn, notes=data.notes,
            supplied_fields=frozenset(mapping[field] for field in data.model_fields_set),
        )
        return invoke(lambda: service.update_renewal_option(lease_id, option_id, command))

    @leases.post("/{lease_id}/termination-cases", status_code=201, response_model=TerminationCaseResponse)
    def create_termination_case(lease_id: str, data: TerminationCaseRequest):
        ready(True)
        return invoke(lambda: service.create_termination_case(lease_id, TerminationCaseCommand(
            data.reason, data.noticeReceivedOn, data.requestedTerminationOn, data.expectedMoveOutOn,
            data.tenantExplanation, data.contractClauseReference, data.operatorNotes,
        )))

    @leases.get("/{lease_id}/termination-cases", response_model=list[TerminationCaseResponse])
    def list_termination_cases(lease_id: str):
        ready()
        return invoke(lambda: service.list_termination_cases(lease_id))

    @router.post("/api/termination-cases/{case_id}/proposals", status_code=201, response_model=TerminationCaseResponse)
    def create_termination_proposal(case_id: str, data: TerminationProposalRequest):
        ready(True)
        return invoke(lambda: service.add_termination_proposal(case_id, TerminationProposalCommand(
            data.proposedTerminationOn, data.expectedMoveOutOn, data.rentResponsibilityEndsOn,
            data.terminationFeeMinor, data.currencyCode, data.feeWaived,
            data.replacementTenantCondition, data.accessArrangement, data.otherTerms, data.responseDueOn,
        )))

    @router.post("/api/termination-cases/{case_id}/accept", response_model=TerminationCaseResponse)
    def accept_termination_proposal(case_id: str, data: TerminationAcceptRequest):
        ready(True)
        return invoke(lambda: service.accept_termination_proposal(case_id, data.proposalId, accepted_on=data.acceptedOn, confirmed=data.confirmed))

    @router.patch("/api/termination-cases/{case_id}", response_model=TerminationCaseResponse)
    def transition_termination_case(case_id: str, data: TerminationCasePatchRequest):
        ready(True)
        return invoke(lambda: service.transition_termination_case(case_id, status=data.status, operator_notes=data.operatorNotes))

    @router.post("/api/termination-cases/{case_id}/complete", response_model=LeaseResponse)
    def complete_termination_case(case_id: str, data: TerminationCompleteRequest):
        ready(True)
        return invoke(lambda: service.complete_termination_case(case_id, actual_move_out_on=data.actualMoveOutOn, confirmed=data.confirmed))

    router.include_router(leases)
    return router


def _term_command(data: TermRequest) -> TermCommand:
    return TermCommand(data.baseRentMinor, data.currencyCode, data.paymentFrequency,
                       data.paymentDueDay, data.agreedSecurityDepositMinor)


def _participant_command(data: ParticipantRequest) -> ParticipantCommand:
    return ParticipantCommand(data.tenantPartyId, data.participantRole, data.startsOn,
                              data.endsOn, data.notes)


def _create_command(data: LeaseCreateRequest) -> LeaseCreateCommand:
    return LeaseCreateCommand(
        data.spaceId,
        data.leaseKind,
        data.contractStartsOn,
        data.contractEndsOn,
        data.occupancyStartsOn,
        _term_command(data.initialTerm),
        tuple(_participant_command(item) for item in data.participants),
        data.notes,
    )
