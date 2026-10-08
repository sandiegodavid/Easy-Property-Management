"""Explicit bounded incomplete inputs, never official drafts or dispatch commands."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract
from app.modules.operator.application.recovery_schemas import (
    CommunicationForm,
    ReporterForm,
    TaskForm,
    ParticipantForm,
    LinkForm,
)


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


# Each entry is an explicit reviewed workflow, not a command discovery/dispatcher.
COMMAND_SCHEMAS = {
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
}


def command_source_kind(form_key):
    if form_key == "communication.create":
        return None
    return {
        "task": "task",
        "communication": "communication",
        "maintenance": "maintenance_issue",
        "portfolio": "space",
    }[form_key.split(".")[0]]
