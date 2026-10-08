"""Typed local LEASE-001 API."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from app.platform.api_errors import domain_problem, workspace_unavailable

from app.modules.leases.application.commands import LeaseCommandAction
from app.modules.portfolio.application.status_contracts import SpaceStatusResponse
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


class LeaseCommandRequest(Contract):
    expectedLeaseRevision: StrictInt = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)


class TermRequest(Contract):
    baseRentMinor: StrictInt = Field(gt=0)
    currencyCode: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    paymentFrequency: Literal["monthly", "weekly"]
    paymentDueDay: StrictInt | None = Field(None, ge=1, le=31)
    agreedSecurityDepositMinor: StrictInt = Field(ge=0)


class ParticipantRequest(Contract):
    tenantPartyId: UUID
    participantRole: Literal["primary_tenant", "co_tenant", "guarantor", "business_signatory"]
    startsOn: date | None = None
    endsOn: date | None = None
    notes: str | None = Field(None, max_length=2000)


class TermMutationRequest(TermRequest, LeaseCommandRequest):
    pass


class ParticipantMutationRequest(ParticipantRequest, LeaseCommandRequest):
    pass


class LeaseCreateRequest(LeaseCommandRequest):
    expectedLeaseRevision: StrictInt = Field(ge=0, le=0)
    spaceId: UUID
    leaseKind: Literal["residential", "commercial"]
    contractStartsOn: date
    contractEndsOn: date | None = None
    occupancyStartsOn: date
    initialTerm: TermRequest
    participants: list[ParticipantRequest] = Field(min_length=1)
    notes: str | None = Field(None, max_length=4000)


class LeasePatchRequest(LeaseCommandRequest):
    contractStartsOn: date | None = None
    contractEndsOn: date | None = None
    occupancyStartsOn: date | None = None
    notes: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set - {"expectedLeaseRevision", "idempotencyKey"}:
            raise ValueError("At least one lease field is required")
        return self


class ConfirmationRequest(Contract):
    confirmed: StrictBool


class TimelineConfirmationRequest(ConfirmationRequest, LeaseCommandRequest):
    expectedRevision: StrictInt = Field(ge=0)


class ExecuteRequest(TimelineConfirmationRequest):
    executedOn: date


class EndRequest(TimelineConfirmationRequest):
    actualMoveOutOn: date


class TerminateRequest(EndRequest):
    endReason: Literal["early_termination", "mutual_termination", "other"]


class TerminationCaseRequest(LeaseCommandRequest):
    reason: Literal["job_relocation", "military", "habitability", "mutual", "other"]
    noticeReceivedOn: date
    requestedTerminationOn: date
    expectedMoveOutOn: date
    tenantExplanation: str | None = Field(None, max_length=4000)
    contractClauseReference: str | None = Field(None, max_length=500)
    operatorNotes: str | None = Field(None, max_length=4000)


class TerminationProposalRequest(LeaseCommandRequest):
    proposedTerminationOn: date
    expectedMoveOutOn: date
    rentResponsibilityEndsOn: date | None = None
    terminationFeeMinor: StrictInt | None = Field(None, ge=0)
    currencyCode: str | None = Field(None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    feeWaived: StrictBool = False
    replacementTenantCondition: str | None = Field(None, max_length=2000)
    accessArrangement: str | None = Field(None, max_length=2000)
    otherTerms: str | None = Field(None, max_length=2000)
    responseDueOn: date | None = None


class TerminationAcceptRequest(ConfirmationRequest, LeaseCommandRequest):
    proposalId: UUID
    acceptedOn: date


class TerminationCasePatchRequest(LeaseCommandRequest):
    status: Literal["under_review", "withdrawn", "declined"]
    operatorNotes: str | None = Field(None, max_length=4000)


class TerminationCompleteRequest(TimelineConfirmationRequest):
    actualMoveOutOn: date


class TerminationProposalResponse(Contract):
    id: UUID
    terminationCaseId: UUID
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
    createdAt: AwareDatetime


class TerminationCaseResponse(Contract):
    id: UUID
    leaseId: UUID
    leaseRevision: StrictInt = Field(ge=0)
    status: Literal[
        "requested", "under_review", "proposed", "accepted", "withdrawn", "declined", "completed"
    ]
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
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    proposals: list[TerminationProposalResponse]
    files: list[LeaseFileResponse]


class RenewalRequest(LeaseCommandRequest):
    proposedStartsOn: date
    proposedEndsOn: date | None = None
    noticeDueOn: date | None = None
    responseDueOn: date | None = None
    notes: str | None = Field(None, max_length=2000)


class RenewalDecisionRequest(LeaseCommandRequest):
    status: Literal["exercised", "declined", "expired", "withdrawn"] | None = None
    decidedOn: date | None = None
    proposedStartsOn: date | None = None
    proposedEndsOn: date | None = None
    noticeDueOn: date | None = None
    responseDueOn: date | None = None
    notes: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def validate_operation(self):
        if not self.model_fields_set - {"expectedLeaseRevision", "idempotencyKey"}:
            raise ValueError("At least one renewal field is required")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Renewal status cannot be null")
        if (self.status is None) != (self.decidedOn is None):
            raise ValueError("A renewal decision requires both status and decidedOn")
        if self.status is not None and self.model_fields_set - {
            "status",
            "decidedOn",
            "notes",
            "expectedLeaseRevision",
            "idempotencyKey",
        }:
            raise ValueError("A renewal decision cannot also edit proposal fields")
        return self


class LeaseTermResponse(Contract):
    id: UUID
    leaseId: UUID
    effectiveOn: date
    endsOn: date | None
    baseRentMinor: int
    currencyCode: str
    paymentFrequency: Literal["monthly", "weekly"]
    paymentDueDay: int | None
    agreedSecurityDepositMinor: int
    createdAt: AwareDatetime


class LeaseParticipantResponse(Contract):
    id: UUID
    leaseId: UUID
    tenantPartyId: UUID
    participantRole: Literal["primary_tenant", "co_tenant", "guarantor", "business_signatory"]
    startsOn: date
    endsOn: date | None
    notes: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class LeaseRenewalResponse(Contract):
    id: UUID
    leaseId: UUID
    status: Literal["open", "exercised", "declined", "expired", "withdrawn"]
    proposedStartsOn: date
    proposedEndsOn: date | None
    noticeDueOn: date | None
    responseDueOn: date | None
    decidedOn: date | None
    notes: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class LeaseFileResponse(Contract):
    id: UUID
    originalName: str
    mediaType: str
    sizeBytes: int
    contentSha256: str
    linkId: UUID
    purpose: str
    storageState: Literal["available", "missing", "quarantined"]
    available: bool
    verifiedAt: AwareDatetime | None


class InspectionAttentionResponse(Contract):
    preMoveIn: str
    postMoveOut: str


class LeaseResponse(Contract):
    id: UUID
    spaceId: UUID
    leaseKind: Literal["residential", "commercial"]
    status: Literal["draft", "executed", "ended", "terminated", "void"]
    contractStartsOn: date
    contractEndsOn: date | None
    occupancyStartsOn: date
    executedOn: date | None
    actualMoveOutOn: date | None
    endReason: (
        Literal["contract_completed", "early_termination", "mutual_termination", "other"] | None
    )
    notes: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    occupancyState: Literal["none", "scheduled", "current", "ended"]
    terms: list[LeaseTermResponse]
    participants: list[LeaseParticipantResponse]
    renewalOptions: list[LeaseRenewalResponse]
    files: list[LeaseFileResponse]
    inspectionAttention: InspectionAttentionResponse
    leaseRevision: StrictInt = Field(ge=0)
    revision: StrictInt | None = None
    operationId: UUID | None = None


class LeaseMutationResponse(LeaseResponse):
    operationId: UUID


class TerminationCaseMutationResponse(TerminationCaseResponse):
    leaseRevision: StrictInt = Field(ge=0)
    operationId: UUID


class TimelineLeaseResponse(LeaseMutationResponse):
    """The replayable source-timeline mutation contract."""

    revision: StrictInt = Field(ge=0)
    operationId: UUID


class LeaseOperationReceipt(Contract):
    operationId: UUID
    idempotencyKey: str
    leaseId: UUID
    action: LeaseCommandAction
    expectedLeaseRevision: StrictInt = Field(ge=0)
    leaseRevision: StrictInt = Field(ge=0)
    effective: bool
    requestFingerprint: str
    correlationId: UUID
    committedAt: AwareDatetime
    response: TimelineLeaseResponse | LeaseMutationResponse | TerminationCaseMutationResponse


class LeaseConflictDetail(Contract):
    code: Literal["lease_conflict"]
    message: str
    currentStatus: LeaseResponse | SpaceStatusResponse | None = None


class LeaseConflictResponse(Contract):
    detail: LeaseConflictDetail


def build_router(service: LeaseService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["leases"], responses={409: {"model": LeaseConflictResponse}})
    leases = APIRouter(prefix="/api/leases", responses={409: {"model": LeaseConflictResponse}})

    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except LeaseNotFoundError as error:
            raise domain_problem(error, status_code=404, code="lease_not_found") from error
        except LeaseConflictError as error:
            detail: str | dict[str, object] = str(error)
            if error.current_status is not None:
                detail = {"message": str(error), "currentStatus": error.current_status}
            if isinstance(detail, dict):
                raise domain_problem(
                    error,
                    status_code=409,
                    code="lease_conflict",
                    **{key: value for key, value in detail.items() if key != "message"},
                ) from error
            raise domain_problem(error, status_code=409, code="lease_conflict") from error
        except LeaseError as error:
            raise domain_problem(error, status_code=400, code="lease_validation") from error

    @leases.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=LeaseMutationResponse,
        operation_id="leaseCreate",
    )
    def create(data: LeaseCreateRequest):
        ready(True)
        return invoke(
            lambda: service.create(
                _create_command(data),
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.get("", response_model=list[LeaseResponse], operation_id="listLeases")
    def list_leases(
        lease_status: Literal["draft", "executed", "ended", "terminated", "void"] | None = Query(
            None, alias="status"
        ),
        property_id: str | None = Query(None, alias="propertyId"),
        space_id: str | None = Query(None, alias="spaceId"),
        tenant_party_id: str | None = Query(None, alias="tenantPartyId"),
        contract_start_from: date | None = Query(None, alias="contractStartFrom"),
        contract_start_to: date | None = Query(None, alias="contractStartTo"),
        renewal_due_on_or_before: date | None = Query(None, alias="renewalDueOnOrBefore"),
    ):
        ready()
        return invoke(
            lambda: service.list(
                status=lease_status,
                property_id=property_id,
                space_id=space_id,
                tenant_party_id=tenant_party_id,
                contract_start_from=contract_start_from,
                contract_start_to=contract_start_to,
                renewal_due_on_or_before=renewal_due_on_or_before,
            )
        )

    @leases.get(
        "/operations/{operation_id}",
        response_model=LeaseOperationReceipt,
        operation_id="getLeaseCommandOperation",
    )
    def get_operation(operation_id: UUID):
        ready()
        return invoke(lambda: service.get_command_operation(operation_id=str(operation_id)))

    @leases.get(
        "/{lease_id}/operations/by-key",
        response_model=LeaseOperationReceipt,
        operation_id="getLeaseCommandOperationByKey",
    )
    def get_operation_by_key(
        lease_id: UUID,
        idempotency_key: str = Query(alias="idempotencyKey", min_length=1, max_length=200),
    ):
        ready()
        return invoke(
            lambda: service.get_command_operation(
                lease_id=str(lease_id),
                idempotency_key=idempotency_key,
            )
        )

    @leases.get("/{lease_id}", response_model=LeaseResponse, operation_id="getLease")
    def get(lease_id: UUID):
        ready()
        return invoke(lambda: service.get(str(lease_id)))

    @leases.patch("/{lease_id}", response_model=LeaseMutationResponse, operation_id="leasePatch")
    def patch(lease_id: UUID, data: LeasePatchRequest):
        ready(True)
        mapping = {
            "contractStartsOn": "contract_starts_on",
            "contractEndsOn": "contract_ends_on",
            "occupancyStartsOn": "occupancy_starts_on",
            "notes": "notes",
        }
        supplied = frozenset(mapping[field] for field in data.model_fields_set if field in mapping)
        command = LeasePatchCommand(
            contract_starts_on=data.contractStartsOn,
            contract_ends_on=data.contractEndsOn,
            occupancy_starts_on=data.occupancyStartsOn,
            notes=data.notes,
            supplied_fields=supplied,
        )
        return invoke(
            lambda: service.patch(
                str(lease_id),
                command,
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.put(
        "/{lease_id}/initial-term",
        response_model=LeaseMutationResponse,
        operation_id="leaseReplaceTerm",
    )
    def replace_term(lease_id: UUID, data: TermMutationRequest):
        ready(True)
        return invoke(
            lambda: service.replace_initial_term(
                str(lease_id),
                _term_command(data),
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.post(
        "/{lease_id}/participants",
        status_code=201,
        response_model=LeaseMutationResponse,
        operation_id="leaseAddParticipant",
    )
    def add_participant(lease_id: UUID, data: ParticipantMutationRequest):
        ready(True)
        return invoke(
            lambda: service.add_participant(
                str(lease_id),
                _participant_command(data),
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.patch(
        "/{lease_id}/participants/{participant_id}",
        response_model=LeaseMutationResponse,
        operation_id="leaseUpdateParticipant",
    )
    def update_participant(lease_id: UUID, participant_id: UUID, data: ParticipantMutationRequest):
        ready(True)
        return invoke(
            lambda: service.update_participant(
                str(lease_id),
                str(participant_id),
                _participant_command(data),
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.delete(
        "/{lease_id}/participants/{participant_id}",
        response_model=LeaseMutationResponse,
        operation_id="leaseRemoveParticipant",
    )
    def remove_participant(lease_id: UUID, participant_id: UUID, data: LeaseCommandRequest):
        ready(True)
        return invoke(
            lambda: service.remove_participant(
                str(lease_id),
                str(participant_id),
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.post(
        "/{lease_id}/execute", response_model=TimelineLeaseResponse, operation_id="leaseExecute"
    )
    def execute(lease_id: UUID, data: ExecuteRequest):
        ready(True)
        return invoke(
            lambda: service.execute(
                str(lease_id),
                executed_on=data.executedOn,
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                expected_lease_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.post("/{lease_id}/end", response_model=TimelineLeaseResponse, operation_id="leaseEnd")
    def end(lease_id: UUID, data: EndRequest):
        ready(True)
        return invoke(
            lambda: service.end(
                str(lease_id),
                actual_move_out_on=data.actualMoveOutOn,
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                expected_lease_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.post(
        "/{lease_id}/terminate", response_model=TimelineLeaseResponse, operation_id="leaseTerminate"
    )
    def terminate(lease_id: UUID, data: TerminateRequest):
        ready(True)
        return invoke(
            lambda: service.terminate(
                str(lease_id),
                actual_move_out_on=data.actualMoveOutOn,
                end_reason=data.endReason,
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                expected_lease_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.post("/{lease_id}/void", response_model=TimelineLeaseResponse, operation_id="leaseVoid")
    def void(lease_id: UUID, data: TimelineConfirmationRequest):
        ready(True)
        return invoke(
            lambda: service.void(
                str(lease_id),
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                expected_lease_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.post(
        "/{lease_id}/renewal-options",
        status_code=201,
        response_model=LeaseMutationResponse,
        operation_id="leaseAddRenewal",
    )
    def add_renewal(lease_id: UUID, data: RenewalRequest):
        ready(True)
        command = RenewalCommand(
            data.proposedStartsOn,
            data.proposedEndsOn,
            data.noticeDueOn,
            data.responseDueOn,
            data.notes,
        )
        return invoke(
            lambda: service.add_renewal_option(
                str(lease_id),
                command,
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.patch(
        "/{lease_id}/renewal-options/{option_id}",
        response_model=LeaseMutationResponse,
        operation_id="leaseDecideRenewal",
    )
    def decide_renewal(lease_id: UUID, option_id: UUID, data: RenewalDecisionRequest):
        ready(True)
        if data.status is not None:
            return invoke(
                lambda: service.decide_renewal_option(
                    str(lease_id),
                    str(option_id),
                    status=data.status,
                    decided_on=data.decidedOn,
                    notes=data.notes,
                    expected_revision=data.expectedLeaseRevision,
                    idempotency_key=data.idempotencyKey,
                )
            )
        mapping = {
            "proposedStartsOn": "proposed_starts_on",
            "proposedEndsOn": "proposed_ends_on",
            "noticeDueOn": "notice_due_on",
            "responseDueOn": "response_due_on",
            "notes": "notes",
        }
        command = RenewalPatchCommand(
            proposed_starts_on=data.proposedStartsOn,
            proposed_ends_on=data.proposedEndsOn,
            notice_due_on=data.noticeDueOn,
            response_due_on=data.responseDueOn,
            notes=data.notes,
            supplied_fields=frozenset(
                mapping[field] for field in data.model_fields_set if field in mapping
            ),
        )
        return invoke(
            lambda: service.update_renewal_option(
                str(lease_id),
                str(option_id),
                command,
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.post(
        "/{lease_id}/termination-cases",
        status_code=201,
        response_model=TerminationCaseMutationResponse,
        operation_id="leaseCreateTerminationCase",
    )
    def create_termination_case(lease_id: UUID, data: TerminationCaseRequest):
        ready(True)
        return invoke(
            lambda: service.create_termination_case(
                str(lease_id),
                TerminationCaseCommand(
                    data.reason,
                    data.noticeReceivedOn,
                    data.requestedTerminationOn,
                    data.expectedMoveOutOn,
                    data.tenantExplanation,
                    data.contractClauseReference,
                    data.operatorNotes,
                ),
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @leases.get(
        "/{lease_id}/termination-cases",
        response_model=list[TerminationCaseResponse],
        operation_id="listLeaseTerminationCases",
    )
    def list_termination_cases(lease_id: UUID):
        ready()
        return invoke(lambda: service.list_termination_cases(str(lease_id)))

    @router.post(
        "/api/termination-cases/{case_id}/proposals",
        status_code=201,
        response_model=TerminationCaseMutationResponse,
        operation_id="leaseCreateTerminationProposal",
    )
    def create_termination_proposal(case_id: UUID, data: TerminationProposalRequest):
        ready(True)
        return invoke(
            lambda: service.add_termination_proposal(
                str(case_id),
                TerminationProposalCommand(
                    data.proposedTerminationOn,
                    data.expectedMoveOutOn,
                    data.rentResponsibilityEndsOn,
                    data.terminationFeeMinor,
                    data.currencyCode,
                    data.feeWaived,
                    data.replacementTenantCondition,
                    data.accessArrangement,
                    data.otherTerms,
                    data.responseDueOn,
                ),
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/termination-cases/{case_id}/accept",
        response_model=TerminationCaseMutationResponse,
        operation_id="leaseAcceptTerminationProposal",
    )
    def accept_termination_proposal(case_id: UUID, data: TerminationAcceptRequest):
        ready(True)
        return invoke(
            lambda: service.accept_termination_proposal(
                str(case_id),
                str(data.proposalId),
                accepted_on=data.acceptedOn,
                confirmed=data.confirmed,
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.patch(
        "/api/termination-cases/{case_id}",
        response_model=TerminationCaseMutationResponse,
        operation_id="leaseTransitionTerminationCase",
    )
    def transition_termination_case(case_id: UUID, data: TerminationCasePatchRequest):
        ready(True)
        return invoke(
            lambda: service.transition_termination_case(
                str(case_id),
                status=data.status,
                operator_notes=data.operatorNotes,
                expected_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/termination-cases/{case_id}/complete",
        response_model=TimelineLeaseResponse,
        operation_id="leaseCompleteTerminationCase",
    )
    def complete_termination_case(case_id: UUID, data: TerminationCompleteRequest):
        ready(True)
        return invoke(
            lambda: service.complete_termination_case(
                str(case_id),
                actual_move_out_on=data.actualMoveOutOn,
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                expected_lease_revision=data.expectedLeaseRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    router.include_router(leases)
    return router


def _term_command(data: TermRequest) -> TermCommand:
    return TermCommand(
        data.baseRentMinor,
        data.currencyCode,
        data.paymentFrequency,
        data.paymentDueDay,
        data.agreedSecurityDepositMinor,
    )


def _participant_command(data: ParticipantRequest) -> ParticipantCommand:
    return ParticipantCommand(
        str(data.tenantPartyId), data.participantRole, data.startsOn, data.endsOn, data.notes
    )


def _create_command(data: LeaseCreateRequest) -> LeaseCreateCommand:
    return LeaseCreateCommand(
        str(data.spaceId),
        data.leaseKind,
        data.contractStartsOn,
        data.contractEndsOn,
        data.occupancyStartsOn,
        _term_command(data.initialTerm),
        tuple(_participant_command(item) for item in data.participants),
        data.notes,
    )
