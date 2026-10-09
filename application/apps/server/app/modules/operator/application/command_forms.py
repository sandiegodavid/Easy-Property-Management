"""Explicit bounded incomplete inputs, never official drafts or dispatch commands."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract
from app.modules.operator.application.financial_forms import FINANCIAL_SCHEMAS
from app.modules.operator.application.intake_forms import INTAKE_SCHEMAS
from app.modules.operator.application.file_forms import FILE_SCHEMAS
from app.modules.operator.application.identity_forms import IDENTITY_SCHEMAS, identity_source_kind
from app.modules.operator.application.provider_forms import PROVIDER_SCHEMAS, provider_source_kind
from app.modules.operator.application.concern_forms import CONCERN_SCHEMAS
from app.modules.operator.application.ai_forms import AI_SCHEMAS, ai_source_kind
from app.modules.operator.application.inventory_forms import INVENTORY_SCHEMAS
from app.modules.operator.application.inspection_forms import (
    INSPECTION_SCHEMAS,
    inspection_source_kind,
)
from app.modules.operator.application.recovery_schemas import (
    CommunicationForm,
    ReporterForm,
    TaskForm,
    ParticipantForm,
    LinkForm,
)

MAX_FINANCE_RECEIPT_ALLOCATIONS = 100


class RevisionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0)


class TaskChanges(TaskForm):
    title: str | None = Field(None, max_length=255)
    relatedLabel: str | None = Field(None, max_length=255)


class TaskEditForm(RevisionForm):
    changes: TaskChanges | None = None


class ConfirmationForm(RevisionForm):
    confirmed: StrictBool | None = None


class TaskOutcomeForm(ConfirmationForm):
    outcomeNote: str | None = Field(None, max_length=4000)


class ReminderAddForm(RevisionForm):
    remindAtUtc: AwareDatetime | None = None


class ReminderTransitionForm(ConfirmationForm):
    reminderId: UUID | None = None


class WaitingSetForm(RevisionForm):
    kind: Literal["person", "organization", "event", "other"] | None = None
    label: str | None = Field(None, max_length=255)
    followUpAtUtc: AwareDatetime | None = None
    followUpTimezone: str | None = Field(None, max_length=100)


class WaitingRescheduleForm(RevisionForm):
    followUpAtUtc: AwareDatetime | None = None
    followUpTimezone: str | None = Field(None, max_length=100)
    clearFollowUp: StrictBool | None = None


class FollowUpForm(Contract):
    title: str | None = Field(None, max_length=240)
    notes: str | None = Field(None, max_length=10000)
    dueAtUtc: AwareDatetime | None = None
    dueTimezone: str | None = Field(None, max_length=100)


class CommunicationCreateForm(CommunicationForm, RevisionForm):
    record: StrictBool | None = None
    followUp: FollowUpForm | None = None


class CommunicationPatchForm(RevisionForm):
    subject: str | None = Field(None, max_length=240)
    body: str | None = Field(None, max_length=10000)
    occurredAtUtc: AwareDatetime | None = None
    occurredTimezone: str | None = Field(None, max_length=100)
    participants: list[ParticipantForm] = Field(default_factory=list, max_length=100)
    links: list[LinkForm] = Field(default_factory=list, max_length=100)


class CommunicationRecordForm(RevisionForm):
    followUp: FollowUpForm | None = None


class CommunicationCorrectionForm(CommunicationCreateForm):
    correctionReason: str | None = Field(None, max_length=1000)


class IssueChanges(Contract):
    summary: str | None = Field(None, max_length=240)
    description: str | None = Field(None, max_length=10000)
    category: (
        Literal[
            "plumbing",
            "electrical",
            "heating_cooling",
            "appliance",
            "structural",
            "safety_security",
            "pest",
            "exterior_grounds",
            "cleaning",
            "other",
        ]
        | None
    ) = None
    categoryDetail: str | None = Field(None, max_length=200)
    priority: Literal["low", "normal", "high", "urgent"] | None = None


class IssuePatchForm(RevisionForm):
    changes: IssueChanges | None = None


class ReporterCorrectionForm(ConfirmationForm):
    reporter: ReporterForm | None = None
    reason: str | None = Field(None, max_length=1000)


class ReasonForm(ConfirmationForm):
    reason: str | None = Field(None, max_length=1000)


class AppointmentForm(RevisionForm):
    startsAtUtc: AwareDatetime | None = None
    endsAtUtc: AwareDatetime | None = None
    purpose: str | None = Field(None, max_length=500)
    instructions: str | None = Field(None, max_length=4000)


class AppointmentEditForm(AppointmentForm):
    targetId: UUID | None = None
    rescheduleReason: str | None = Field(None, max_length=1000)


class ChildReasonForm(ReasonForm):
    targetId: UUID | None = None


class AppointmentFinishForm(ConfirmationForm):
    targetId: UUID | None = None
    cancelled: StrictBool | None = None
    reason: str | None = Field(None, max_length=4000)


class CostForm(RevisionForm):
    contextKind: Literal["operator_estimate", "work_reported"] | None = None
    label: str | None = Field(None, max_length=200)
    amount: str | None = Field(None, max_length=100)
    observedOn: date | None = None
    sourceNote: str | None = Field(None, max_length=4000)
    replacesCostContextId: UUID | None = None


class ExpenseLinkForm(RevisionForm):
    expenseId: UUID | None = None


class QuoteForm(RevisionForm):
    providerPartyId: UUID | None = None
    label: str | None = Field(None, max_length=200)
    scopeSummary: str | None = Field(None, max_length=4000)
    amount: str | None = Field(None, max_length=100)
    receivedOn: date | None = None
    validThrough: date | None = None
    earliestWorkStartOn: date | None = None
    estimatedWorkFinishOn: date | None = None
    termsNotes: str | None = Field(None, max_length=4000)
    replacesQuoteId: UUID | None = None


class AssignmentForm(RevisionForm):
    providerPartyId: UUID | None = None
    quoteId: UUID | None = None
    selectionReason: str | None = Field(None, max_length=1000)
    instructions: str | None = Field(None, max_length=4000)
    directAssignmentConfirmed: StrictBool | None = None
    avoidOverrideConfirmed: StrictBool | None = None
    avoidOverrideReason: str | None = Field(None, max_length=1000)
    replacesAssignmentId: UUID | None = None
    replacementConfirmed: StrictBool | None = None
    endReason: str | None = Field(None, max_length=1000)


class IssueFollowUpForm(FollowUpForm, RevisionForm):
    priority: Literal["low", "normal", "high", "urgent"] | None = None


class WorkJournalForm(RevisionForm):
    assignmentId: UUID | None = None
    entryKind: (
        Literal[
            "work_started",
            "progress_update",
            "work_blocked",
            "work_completed",
            "general_note",
            "correction",
        ]
        | None
    ) = None
    correctedEntryKind: (
        Literal["work_started", "progress_update", "work_blocked", "work_completed", "general_note"]
        | None
    ) = None
    sourceKind: Literal["operator_observation", "provider_report", "other_report"] | None = None
    occurredAtUtc: AwareDatetime | None = None
    summary: str | None = Field(None, max_length=240)
    detail: str | None = Field(None, max_length=4000)
    outcomeStatus: Literal["completed", "partially_completed", "unsuccessful"] | None = None
    outcomeSummary: str | None = Field(None, max_length=4000)
    followUpRequired: StrictBool | None = None
    operatorVerified: StrictBool | None = None
    correctsEntryId: UUID | None = None
    correctionReason: str | None = Field(None, max_length=1000)
    historicalEntryConfirmed: StrictBool | None = None


class OccupancyForm(Contract):
    occupancyStatus: Literal["occupied", "vacant", "unknown"] | None = None
    effectiveOn: date | None = None
    note: str | None = Field(None, max_length=1000)


class AvailabilityForm(Contract):
    availabilityStatus: (
        Literal["available_now", "available_on", "not_available", "unknown"] | None
    ) = None
    availableOn: date | None = None
    note: str | None = Field(None, max_length=1000)


class OccupancyChangeForm(OccupancyForm, RevisionForm):
    pass


class OccupancyPeriodForm(OccupancyChangeForm):
    periodId: UUID | None = None


class OccupancyCorrectionForm(OccupancyPeriodForm):
    reason: str | None = Field(None, max_length=1000)


class OccupancyCancelForm(RevisionForm):
    periodId: UUID | None = None


class AvailabilityChangeForm(AvailabilityForm, RevisionForm):
    pass


class ClassificationForm(RevisionForm):
    occupancy: OccupancyForm | None = None
    availability: AvailabilityForm | None = None


class LeaseRevisionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0)


class LeaseTermForm(Contract):
    baseRentMinor: StrictInt | None = Field(None, gt=0)
    currencyCode: str | None = Field(None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    paymentFrequency: Literal["monthly", "weekly"] | None = None
    paymentDueDay: StrictInt | None = Field(None, ge=1, le=31)
    agreedSecurityDepositMinor: StrictInt | None = Field(None, ge=0)


class LeaseParticipantForm(Contract):
    tenantPartyId: UUID | None = None
    participantRole: (
        Literal["primary_tenant", "co_tenant", "guarantor", "business_signatory"] | None
    ) = None
    startsOn: date | None = None
    endsOn: date | None = None
    notes: str | None = Field(None, max_length=2000)


class LeaseCreateForm(LeaseRevisionForm):
    spaceId: UUID | None = None
    leaseKind: Literal["residential", "commercial"] | None = None
    contractStartsOn: date | None = None
    contractEndsOn: date | None = None
    occupancyStartsOn: date | None = None
    initialTerm: LeaseTermForm | None = None
    participants: list[LeaseParticipantForm] | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=4000)


class LeasePatchForm(LeaseRevisionForm):
    contractStartsOn: date | None = None
    contractEndsOn: date | None = None
    occupancyStartsOn: date | None = None
    notes: str | None = Field(None, max_length=4000)


class LeaseTermMutationForm(LeaseTermForm, LeaseRevisionForm):
    pass


class LeaseParticipantMutationForm(LeaseParticipantForm, LeaseRevisionForm):
    pass


class LeaseParticipantEditForm(LeaseParticipantMutationForm):
    participantId: UUID | None = None


class LeaseParticipantRemoveForm(LeaseRevisionForm):
    participantId: UUID | None = None


class LeaseTimelineForm(LeaseRevisionForm):
    expectedSpaceRevision: StrictInt | None = Field(None, ge=0)
    confirmed: StrictBool | None = None


class LeaseExecuteForm(LeaseTimelineForm):
    executedOn: date | None = None


class LeaseEndForm(LeaseTimelineForm):
    actualMoveOutOn: date | None = None


class LeaseTerminateForm(LeaseEndForm):
    endReason: Literal["early_termination", "mutual_termination", "other"] | None = None


class LeaseRenewalForm(LeaseRevisionForm):
    proposedStartsOn: date | None = None
    proposedEndsOn: date | None = None
    noticeDueOn: date | None = None
    responseDueOn: date | None = None
    notes: str | None = Field(None, max_length=2000)


class LeaseRenewalEditForm(LeaseRenewalForm):
    optionId: UUID | None = None


class LeaseRenewalDecisionForm(LeaseRevisionForm):
    optionId: UUID | None = None
    status: Literal["exercised", "declined", "expired", "withdrawn"] | None = None
    decidedOn: date | None = None
    notes: str | None = Field(None, max_length=2000)


class LeaseTerminationCaseForm(LeaseRevisionForm):
    reason: Literal["job_relocation", "military", "habitability", "mutual", "other"] | None = None
    noticeReceivedOn: date | None = None
    requestedTerminationOn: date | None = None
    expectedMoveOutOn: date | None = None
    tenantExplanation: str | None = Field(None, max_length=4000)
    contractClauseReference: str | None = Field(None, max_length=500)
    operatorNotes: str | None = Field(None, max_length=4000)


class LeaseTerminationProposalForm(LeaseRevisionForm):
    caseId: UUID | None = None
    proposedTerminationOn: date | None = None
    expectedMoveOutOn: date | None = None
    rentResponsibilityEndsOn: date | None = None
    terminationFeeMinor: StrictInt | None = Field(None, ge=0)
    currencyCode: str | None = Field(None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    feeWaived: StrictBool | None = None
    replacementTenantCondition: str | None = Field(None, max_length=2000)
    accessArrangement: str | None = Field(None, max_length=2000)
    otherTerms: str | None = Field(None, max_length=2000)
    responseDueOn: date | None = None


class LeaseTerminationAcceptForm(LeaseRevisionForm):
    caseId: UUID | None = None
    proposalId: UUID | None = None
    acceptedOn: date | None = None
    confirmed: StrictBool | None = None


class LeaseTerminationTransitionForm(LeaseRevisionForm):
    caseId: UUID | None = None
    status: Literal["under_review", "withdrawn", "declined"] | None = None
    operatorNotes: str | None = Field(None, max_length=4000)


class LeaseTerminationCompleteForm(LeaseTimelineForm):
    caseId: UUID | None = None
    actualMoveOutOn: date | None = None


class FinanceRevisionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0)


class ExpectationSynchronizeForm(FinanceRevisionForm):
    leaseTermId: UUID | None = None
    throughOn: date | None = None
    scheduleAnchorOn: date | None = None
    responsibilityEndsOnOverride: date | None = None
    overrideReason: str | None = Field(None, max_length=1000)
    overrideConfirmed: StrictBool | None = None


class ExpectationVoidForm(FinanceRevisionForm):
    expectationId: UUID | None = None
    confirmed: StrictBool | None = None
    voidReason: str | None = Field(None, max_length=1000)


class TimelinessReviewForm(FinanceRevisionForm):
    expectationId: UUID | None = None
    decision: Literal["mark_missed", "clear_missed"] | None = None
    reason: str | None = Field(None, max_length=1000)
    confirmed: StrictBool | None = None


class ReceiptAllocationForm(Contract):
    expectationId: UUID | None = None
    amountMinor: StrictInt | None = Field(None, gt=0)


class RentReceiptCreateForm(FinanceRevisionForm):
    receivedOn: date | None = None
    amountMinor: StrictInt | None = Field(None, gt=0)
    currencyCode: Literal["USD"] | None = None
    allocations: list[ReceiptAllocationForm] = Field(
        default_factory=list, max_length=MAX_FINANCE_RECEIPT_ALLOCATIONS
    )
    paymentMethodKind: (
        Literal[
            "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
        ]
        | None
    ) = None
    paymentMethodLabel: str | None = Field(None, max_length=100)
    maskedReference: str | None = Field(None, max_length=80)
    otherPaymentMethodNote: str | None = Field(None, max_length=200)
    receivedByPartyId: UUID | None = None
    replacesReceiptId: UUID | None = None
    notes: str | None = Field(None, max_length=4000)
    duplicateConfirmed: StrictBool | None = None
    duplicateReason: str | None = Field(None, max_length=1000)


class ReceiptVoidForm(FinanceRevisionForm):
    receiptId: UUID | None = None
    confirmed: StrictBool | None = None
    voidReason: str | None = Field(None, max_length=1000)


class PrepaidCheckCreateForm(FinanceRevisionForm):
    expectationId: UUID | None = None
    payerPartyId: UUID | None = None
    receivedOn: date | None = None
    checkDatedOn: date | None = None
    maskedReference: str | None = Field(None, max_length=80)


class PrepaidCheckDepositForm(FinanceRevisionForm):
    prepaidCheckId: UUID | None = None
    confirmed: StrictBool | None = None
    occurredOn: date | None = None
    existingReceiptId: UUID | None = None


class PrepaidCheckReturnForm(FinanceRevisionForm):
    prepaidCheckId: UUID | None = None
    confirmed: StrictBool | None = None
    reason: str | None = Field(None, max_length=1000)
    returnedOn: date | None = None


class PrepaidCheckVoidForm(FinanceRevisionForm):
    prepaidCheckId: UUID | None = None
    confirmed: StrictBool | None = None
    reason: str | None = Field(None, max_length=1000)


class PrepaidCheckReplaceForm(PrepaidCheckCreateForm):
    prepaidCheckId: UUID | None = None
    confirmed: StrictBool | None = None
    reason: str | None = Field(None, max_length=1000)


# Each entry is an explicit reviewed workflow, not a command discovery/dispatcher.
COMMAND_SCHEMAS = {
    **INVENTORY_SCHEMAS,
    **FILE_SCHEMAS,
    **IDENTITY_SCHEMAS,
    **PROVIDER_SCHEMAS,
    **CONCERN_SCHEMAS,
    **AI_SCHEMAS,
    **INSPECTION_SCHEMAS,
    **INTAKE_SCHEMAS,
    **FINANCIAL_SCHEMAS,
    "task.edit": TaskEditForm,
    "task.delete": ConfirmationForm,
    "task.start": RevisionForm,
    "task.complete": TaskOutcomeForm,
    "task.cancel": TaskOutcomeForm,
    "task.reopen": ConfirmationForm,
    "task.reminder.add": ReminderAddForm,
    "task.reminder.acknowledge": ReminderTransitionForm,
    "task.reminder.dismiss": ReminderTransitionForm,
    "task.waiting.set": WaitingSetForm,
    "task.waiting.clear": ConfirmationForm,
    "task.waiting.reschedule": WaitingRescheduleForm,
    "communication.create": CommunicationCreateForm,
    "communication.patch": CommunicationPatchForm,
    "communication.draft.record": CommunicationRecordForm,
    "communication.correct": CommunicationCorrectionForm,
    "maintenance.issue.patch": IssuePatchForm,
    "maintenance.reporter.correct": ReporterCorrectionForm,
    "maintenance.issue.start": ReasonForm,
    "maintenance.issue.return_to_open": ReasonForm,
    "maintenance.issue.resolve": ReasonForm,
    "maintenance.issue.cancel": ReasonForm,
    "maintenance.issue.reopen": ReasonForm,
    "maintenance.appointment.create": AppointmentForm,
    "maintenance.appointment.update": AppointmentEditForm,
    "maintenance.appointment.finish": AppointmentFinishForm,
    "maintenance.cost.create": CostForm,
    "maintenance.cost.void": ChildReasonForm,
    "maintenance.expense.link": ExpenseLinkForm,
    "maintenance.expense.archive": ChildReasonForm,
    "maintenance.quote.create": QuoteForm,
    "maintenance.quote.withdraw": ChildReasonForm,
    "maintenance.assignment.create": AssignmentForm,
    "maintenance.assignment.end": ChildReasonForm,
    "maintenance.follow_up.create": IssueFollowUpForm,
    "maintenance.journal.record": WorkJournalForm,
    "portfolio.occupancy.change": OccupancyChangeForm,
    "portfolio.occupancy.cancel": OccupancyCancelForm,
    "portfolio.occupancy.replace": OccupancyPeriodForm,
    "portfolio.occupancy.correct": OccupancyCorrectionForm,
    "portfolio.occupancy.reschedule": OccupancyPeriodForm,
    "portfolio.availability.change": AvailabilityChangeForm,
    "portfolio.space.classify": ClassificationForm,
    "lease.create": LeaseCreateForm,
    "lease.patch": LeasePatchForm,
    "lease.term.replace": LeaseTermMutationForm,
    "lease.participant.add": LeaseParticipantMutationForm,
    "lease.participant.update": LeaseParticipantEditForm,
    "lease.participant.remove": LeaseParticipantRemoveForm,
    "lease.execute": LeaseExecuteForm,
    "lease.end": LeaseEndForm,
    "lease.terminate": LeaseTerminateForm,
    "lease.void": LeaseTimelineForm,
    "lease.renewal.add": LeaseRenewalForm,
    "lease.renewal.update": LeaseRenewalEditForm,
    "lease.renewal.decide": LeaseRenewalDecisionForm,
    "lease.termination.create": LeaseTerminationCaseForm,
    "lease.termination.proposal.add": LeaseTerminationProposalForm,
    "lease.termination.proposal.accept": LeaseTerminationAcceptForm,
    "lease.termination.transition": LeaseTerminationTransitionForm,
    "lease.termination.complete": LeaseTerminationCompleteForm,
    "finance.rent_expectation.synchronize": ExpectationSynchronizeForm,
    "finance.rent_expectation.void": ExpectationVoidForm,
    "finance.rent_expectation.timeliness_review": TimelinessReviewForm,
    "finance.rent_receipt.create": RentReceiptCreateForm,
    "finance.rent_receipt.void": ReceiptVoidForm,
    "finance.prepaid_check.create": PrepaidCheckCreateForm,
    "finance.prepaid_check.deposit": PrepaidCheckDepositForm,
    "finance.prepaid_check.return": PrepaidCheckReturnForm,
    "finance.prepaid_check.void": PrepaidCheckVoidForm,
    "finance.prepaid_check.replace": PrepaidCheckReplaceForm,
}


def command_source_kind(form_key):
    selectors = (
        (INVENTORY_SCHEMAS, lambda key: None if key == "portfolio.property.create" else "property"),
        (AI_SCHEMAS, ai_source_kind),
        (CONCERN_SCHEMAS, lambda key: None if key == "owner_concern.create" else "owner_concern"),
        (IDENTITY_SCHEMAS, identity_source_kind),
        (PROVIDER_SCHEMAS, provider_source_kind),
        (INSPECTION_SCHEMAS, inspection_source_kind),
        (FILE_SCHEMAS, lambda key: None if key == "file.upload" else "file_link"),
        (
            INTAKE_SCHEMAS,
            lambda key: None if key.endswith((".admit", ".import")) else "intake_source",
        ),
    )
    for schemas, select_kind in selectors:
        if form_key in schemas:
            return select_kind(form_key)
    if form_key in FINANCIAL_SCHEMAS:
        return financial_source_kind(form_key)
    if form_key in {"communication.create", "lease.create"}:
        return None
    return {
        "task": "task",
        "communication": "communication",
        "maintenance": "maintenance_issue",
        "portfolio": "space",
        "lease": "lease",
        "finance": "lease",
    }[form_key.split(".")[0]]


def financial_source_kind(form_key):
    if form_key in {
        "finance.expense.create",
        "finance.expense_category.create",
        "finance.deposit_account.create",
        "owner_rent_report.create",
    }:
        return None
    if form_key.startswith("owner_rent_report."):
        return "owner_rent_report"
    if form_key.startswith("finance.expense_category."):
        return "expense_category"
    return (
        "expense"
        if form_key.startswith(("finance.expense.", "finance.expense_refund."))
        else "security_deposit_account"
    )
