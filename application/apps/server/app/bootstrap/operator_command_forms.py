"""Explicit read-only recovery composition; never dispatches a domain command."""

from dataclasses import fields, MISSING, replace
from datetime import datetime
from hashlib import sha256
from json import dumps
import re
from typing import get_args, get_type_hints

from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.application.command_forms import MAX_FINANCE_RECEIPT_ALLOCATIONS
from app.modules.operator.domain.models import OperatorError
from app.modules.tasks.application.mutations import TaskMutationCommand
from app.modules.tasks.application.waiting import WaitingCommand
from app.modules.communications.application.service import (
    CommunicationCommand,
    PatchCommand,
    FollowUpInput,
    ParticipantInput,
    LinkInput,
    command_fingerprint as communication_fingerprint,
)
from app.modules.maintenance.application.commands import command_fingerprint as issue_fingerprint
from app.modules.maintenance.domain.models import (
    AppointmentCreate,
    CostCreate,
    QuoteCreate,
    AssignmentCreate,
    ReporterAttribution,
    ReporterCorrection,
)
from app.modules.maintenance.domain.work_journal import WorkJournalCreate
from app.modules.portfolio.application.service import (
    OccupancyCommand,
    OccupancyCorrectionCommand,
    AvailabilityCommand,
    SpaceClassificationCommand,
)
from app.modules.leases.infrastructure.recovery_reader import SQLiteLeaseRecoveryReader
from app.bootstrap.operator_lease_commands import lease_request, termination_completion_payload
from app.bootstrap.operator_finance_commands import finance_request
from app.modules.finance.infrastructure.recovery_reader import SQLiteFinanceRecoveryReader
from app.modules.finance.infrastructure.aggregate_recovery_reader import (
    SQLiteFinancialAggregateRecoveryReader,
    SQLiteExpenseCategoryRecoveryReader,
)
from app.modules.owner_accounting.infrastructure.recovery_reader import (
    SQLiteOwnerReportRecoveryReader,
)
from app.bootstrap.operator_financial_batches import compose_financial_batches
from app.bootstrap.operator_intake_commands import compose_intake_forms
from app.bootstrap.operator_file_commands import compose_file_forms
from app.bootstrap.operator_inspection_commands import compose_inspection_forms
from app.bootstrap.operator_identity_commands import compose_identity_forms
from app.bootstrap.operator_provider_commands import compose_provider_forms
from app.bootstrap.operator_concern_commands import compose_concern_forms
from app.bootstrap.operator_ai_commands import compose_ai_forms
from app.bootstrap.operator_inventory_commands import compose_inventory_forms


def snake_values(payload):
    values = {re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): value for key, value in payload.items()}
    # Match the owning HTTP commands' datetime.isoformat(), including UTC +00:00.
    # Pydantic JSON uses Z for UTC; source fingerprints may retain textual offsets.
    return {
        key: datetime.fromisoformat(value).isoformat()
        if key.endswith("_at_utc") and value is not None
        else value
        for key, value in values.items()
    }


def command(model, values):
    """Reconstruct only source-declared fields; source validation remains authoritative."""
    arguments = {}
    annotations = get_type_hints(model)
    for field in fields(model):
        if field.name in values:
            arguments[field.name] = values[field.name]
        elif field.default is MISSING and field.default_factory is MISSING:
            if type(None) in get_args(annotations[field.name]):
                arguments[field.name] = None
            else:
                raise OperatorError("Complete the command fields before starting an attempt.")
    return model(**arguments)


def revision(payload):
    value = payload.get("expectedRevision")
    if type(value) is not int or value < 0:
        raise OperatorError("Complete the expected source revision before starting an attempt.")
    return value


def task_fingerprint(action, source_id, payload, key):
    values = snake_values(payload)
    if "changes" in values:
        values["changes"] = tuple(snake_values(values["changes"] or {}).items())
    return TaskMutationCommand(
        task_id=source_id, action=action, idempotency_key=key, **values
    ).fingerprint()


def waiting_fingerprint(action, source_id, payload, key):
    values = snake_values(payload)
    for old, new in (("follow_up_at_utc", "follow_up_at"), ("follow_up_timezone", "timezone")):
        if old in values:
            values[new] = values.pop(old)
    return WaitingCommand(
        task_id=source_id, action=action, idempotency_key=key, **values
    ).fingerprint()


def communication_command(payload, *, patch=False):
    values = snake_values(payload)
    if "participants" in values:
        values["participants"] = tuple(
            ParticipantInput(**snake_values(item)) for item in values["participants"]
        )
    if "links" in values:
        values["links"] = tuple(LinkInput(**snake_values(item)) for item in values["links"])
    if values.get("follow_up") is not None:
        values["follow_up"] = command(FollowUpInput, snake_values(values["follow_up"]))
    return command(PatchCommand if patch else CommunicationCommand, values)


def communication_request(action, source_id, payload, key):
    expected = revision(payload)
    if action == "recorded":
        follow_up = payload.get("followUp")
        value = command(FollowUpInput, snake_values(follow_up)) if follow_up else None
    else:
        value = communication_command(payload, patch=action == "patched")
        if action == "corrected":
            reason = payload.get("correctionReason")
            if not isinstance(reason, str) or not reason.strip():
                raise OperatorError("Complete the correction reason.")
            value = (value, reason.strip())
    return communication_fingerprint(action, source_id, value, expected)


ISSUE_CHILDREN = {
    "create_appointment": ("issue", AppointmentCreate),
    "update_appointment": ("appointment", AppointmentCreate),
    "create_cost": ("issue", CostCreate),
    "create_quote": ("issue", QuoteCreate),
    "create_assignment": ("issue", AssignmentCreate),
    "record": ("issue", WorkJournalCreate),
}
ISSUE_ENDINGS = {
    "void_cost": ("cost_context", "context_id"),
    "archive_expense_link": ("expense_link", "link_id"),
    "withdraw_quote": ("quote", "quote_id"),
    "end_assignment": ("assignment", "assignment_id"),
}


def issue_command_payload(action, source_id, payload):
    values = snake_values(payload)
    if action in ISSUE_CHILDREN:
        kind, model = ISSUE_CHILDREN[action]
        target = source_id if kind == "issue" else values.get("target_id")
        target_field = "issue_id" if kind == "issue" else "appointment_id"
        result = {target_field: target, "command": command(model, values)}
        if action == "update_appointment":
            result["reschedule_reason"] = values.get("reschedule_reason")
        return kind, target, result
    if action in ISSUE_ENDINGS:
        kind, target_field = ISSUE_ENDINGS[action]
        return (
            kind,
            values.get("target_id"),
            {
                target_field: values.get("target_id"),
                "reason": values.get("reason"),
                "confirmed": values.get("confirmed", False),
            },
        )
    return issue_core_payload(action, source_id, values)


def issue_core_payload(action, source_id, values):
    if action == "patch_issue":
        result = {"issue_id": source_id, "values": snake_values(values.get("changes") or {})}
    elif action == "correct_reporter":
        reporter = command(ReporterAttribution, snake_values(values.get("reporter") or {}))
        correction = command(ReporterCorrection, {**values, "reporter": reporter})
        result = {"issue_id": source_id, "command": correction}
    elif action == "link_expense":
        result = {"issue_id": source_id, "expense_id": values.get("expense_id")}
    elif action == "finish_appointment":
        return (
            "appointment",
            values.get("target_id"),
            {
                "appointment_id": values.get("target_id"),
                "cancelled": values.get("cancelled"),
                "reason": values.get("reason"),
                "confirmed": values.get("confirmed", False),
            },
        )
    elif action == "create_follow_up":
        result = {
            "issue_id": source_id,
            "title": values.get("title"),
            "notes": values.get("notes"),
            "priority": values.get("priority", "normal"),
            "due_at_utc": values.get("due_at_utc"),
            "due_timezone": values.get("due_timezone"),
        }
    else:
        result = {
            "issue_id": source_id,
            "action": action,
            "reason": values.get("reason"),
            "confirmed": values.get("confirmed"),
        }
        action = "transition"
    return "issue", source_id, result


def maintenance_request(action, source_id, payload, key):
    kind, target, values = issue_command_payload(action, source_id, payload)
    if target is None:
        raise OperatorError("Complete the command target.")
    recorded_action = (
        "transition"
        if action in {"start", "return_to_open", "resolve", "cancel", "reopen"}
        else action
    )
    return issue_fingerprint(
        action=recorded_action,
        target_kind=kind,
        target_id=target,
        payload=values,
        expected_revision=revision(payload),
    )


def portfolio_request(action, source_id, payload, key):
    values = snake_values(payload)
    request = {"action": action, "expectedRevision": revision(payload)}
    if action not in {"availability_changed", "space_classified", "occupancy_cancelled"}:
        value = command(OccupancyCommand, values)
        if action == "occupancy_corrected":
            value = command(
                OccupancyCorrectionCommand, {"occupancy": value, "reason": values.get("reason")}
            )
        request["command"] = repr(value)
    elif action == "availability_changed":
        request["command"] = repr(command(AvailabilityCommand, values))
    elif action == "space_classified":
        occupancy = values.get("occupancy")
        availability = values.get("availability")
        value = SpaceClassificationCommand(
            command(OccupancyCommand, snake_values(occupancy)) if occupancy else None,
            command(AvailabilityCommand, snake_values(availability)) if availability else None,
        )
        request["command"] = repr(value)
    if action in {
        "occupancy_cancelled",
        "occupancy_replaced",
        "occupancy_corrected",
        "occupancy_rescheduled",
    }:
        if not values.get("period_id"):
            raise OperatorError("Complete the occupancy period identity.")
        request["periodId"] = values["period_id"]
    return sha256(dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def bind(reader, source_kind: str, family, actions, calculate):
    return {
        key: RecoveryBinding(
            source_kind,
            action,
            family,
            reader,
            lambda source, payload, key, action=action: calculate(action, source, payload, key),
            result_kind=source_kind,
        )
        for key, action in actions.items()
    }


def bind_related(reader, source_kind, family, actions, calculate):
    return {
        key: replace(binding, related_state=reader.related_state)
        for key, binding in bind(reader, source_kind, family, actions, calculate).items()
    }


def require_complete_form(form_key, payload):
    """Incomplete autosaves are valid; dispatch attempts require the full choice."""
    required = {
        "task.complete": ("confirmed",),
        "task.cancel": ("confirmed",),
        "task.reopen": ("confirmed",),
        "task.delete": ("confirmed",),
        "task.reminder.acknowledge": ("reminderId", "confirmed"),
        "task.reminder.dismiss": ("reminderId", "confirmed"),
        "task.waiting.clear": ("confirmed",),
        "maintenance.issue.resolve": ("reason", "confirmed"),
        "maintenance.issue.cancel": ("reason", "confirmed"),
        "maintenance.issue.reopen": ("reason", "confirmed"),
        "maintenance.appointment.finish": ("targetId", "cancelled", "confirmed"),
        "maintenance.cost.void": ("targetId", "reason", "confirmed"),
        "maintenance.expense.archive": ("targetId", "reason", "confirmed"),
        "maintenance.quote.withdraw": ("targetId", "reason", "confirmed"),
        "maintenance.assignment.end": ("targetId", "reason", "confirmed"),
        "maintenance.expense.link": ("expenseId",),
        "maintenance.follow_up.create": ("title",),
        "lease.create": (
            "spaceId",
            "leaseKind",
            "contractStartsOn",
            "occupancyStartsOn",
            "initialTerm",
            "participants",
        ),
        "lease.term.replace": (
            "baseRentMinor",
            "currencyCode",
            "paymentFrequency",
            "agreedSecurityDepositMinor",
        ),
        "lease.participant.add": ("tenantPartyId", "participantRole"),
        "lease.participant.update": ("participantId", "tenantPartyId", "participantRole"),
        "lease.participant.remove": ("participantId",),
        "lease.execute": ("executedOn", "confirmed", "expectedSpaceRevision"),
        "lease.end": ("actualMoveOutOn", "confirmed", "expectedSpaceRevision"),
        "lease.terminate": ("actualMoveOutOn", "endReason", "confirmed", "expectedSpaceRevision"),
        "lease.void": ("confirmed", "expectedSpaceRevision"),
        "lease.renewal.add": ("proposedStartsOn",),
        "lease.renewal.update": ("optionId",),
        "lease.renewal.decide": ("optionId", "status", "decidedOn"),
        "lease.termination.create": (
            "reason",
            "noticeReceivedOn",
            "requestedTerminationOn",
            "expectedMoveOutOn",
        ),
        "lease.termination.proposal.add": ("caseId", "proposedTerminationOn", "expectedMoveOutOn"),
        "lease.termination.proposal.accept": ("caseId", "proposalId", "acceptedOn", "confirmed"),
        "lease.termination.transition": ("caseId", "status"),
        "lease.termination.complete": (
            "caseId",
            "actualMoveOutOn",
            "confirmed",
            "expectedSpaceRevision",
        ),
        "finance.rent_expectation.synchronize": ("leaseTermId", "throughOn"),
        "finance.rent_expectation.void": ("expectationId", "confirmed", "voidReason"),
        "finance.rent_expectation.timeliness_review": (
            "expectationId",
            "decision",
            "reason",
            "confirmed",
        ),
        "finance.rent_receipt.create": (
            "receivedOn",
            "amountMinor",
            "currencyCode",
            "allocations",
            "paymentMethodKind",
        ),
        "finance.rent_receipt.void": ("receiptId", "confirmed", "voidReason"),
        "finance.prepaid_check.create": (
            "expectationId",
            "payerPartyId",
            "receivedOn",
            "checkDatedOn",
        ),
        "finance.prepaid_check.deposit": ("prepaidCheckId", "confirmed"),
        "finance.prepaid_check.return": (
            "prepaidCheckId",
            "confirmed",
            "reason",
            "returnedOn",
        ),
        "finance.prepaid_check.void": ("prepaidCheckId", "confirmed", "reason"),
        "finance.prepaid_check.replace": (
            "prepaidCheckId",
            "expectationId",
            "payerPartyId",
            "receivedOn",
            "checkDatedOn",
            "confirmed",
            "reason",
        ),
    }
    for field in required.get(form_key, ()):
        value = payload.get(field)
        if (
            value is None
            or (field == "confirmed" and value is not True)
            or (isinstance(value, str) and not value.strip())
        ):
            raise OperatorError("Complete and confirm the command before starting an attempt.")
    if form_key == "finance.rent_receipt.create":
        allocations = payload.get("allocations") or ()
        if not 1 <= len(allocations) <= MAX_FINANCE_RECEIPT_ALLOCATIONS or any(
            not item.get("expectationId") or type(item.get("amountMinor")) is not int
            for item in allocations
        ):
            raise OperatorError("Complete each receipt allocation before starting an attempt.")
        if payload.get("duplicateConfirmed") and not (payload.get("duplicateReason") or "").strip():
            raise OperatorError("Provide a reason for confirming a possible duplicate.")
    if form_key == "lease.create" and payload.get("expectedRevision") != 0:
        raise OperatorError("Lease creation requires revision zero.")
    if form_key == "communication.create" and revision(payload) != 0:
        raise OperatorError("Communication creation requires source revision zero.")


def compose_command_forms(tasks, communications, issues, portfolio):
    lease_reader = SQLiteLeaseRecoveryReader()
    finance_reader = SQLiteFinanceRecoveryReader(lease_reader)
    return {
        **compose_inventory_forms(),
        **compose_file_forms(),
        **compose_inspection_forms(),
        **compose_identity_forms(),
        **compose_provider_forms(),
        **compose_concern_forms(),
        **compose_ai_forms(),
        **compose_intake_forms(),
        **compose_financial_batches(
            SQLiteFinancialAggregateRecoveryReader("expense", lease_reader),
            SQLiteFinancialAggregateRecoveryReader("deposit", lease_reader),
            SQLiteExpenseCategoryRecoveryReader(),
            SQLiteOwnerReportRecoveryReader(lease_reader, finance_reader),
        ),
        **bind_related(
            tasks,
            "task",
            "mutation",
            {
                "task.edit": "edit",
                "task.delete": "delete",
                "task.start": "start",
                "task.complete": "complete",
                "task.cancel": "cancel",
                "task.reopen": "reopen",
                "task.reminder.add": "add_reminder",
                "task.reminder.acknowledge": "acknowledge",
                "task.reminder.dismiss": "dismiss",
            },
            task_fingerprint,
        ),
        **bind(
            tasks,
            "task",
            "waiting",
            {
                "task.waiting.set": "set",
                "task.waiting.clear": "clear",
                "task.waiting.reschedule": "reschedule",
            },
            waiting_fingerprint,
        ),
        **bind(
            communications,
            "communication",
            "communication",
            {
                "communication.patch": "patched",
                "communication.draft.record": "recorded",
                "communication.correct": "corrected",
            },
            communication_request,
        ),
        "communication.create": RecoveryBinding(
            None,
            "created",
            "communication",
            communications,
            lambda source, payload, key: communication_request("created", source, payload, key),
            result_kind="communication",
        ),
        **bind_related(
            issues,
            "maintenance_issue",
            "issue",
            {
                "maintenance.issue.patch": "patch_issue",
                "maintenance.reporter.correct": "correct_reporter",
                "maintenance.issue.start": "start",
                "maintenance.issue.return_to_open": "return_to_open",
                "maintenance.issue.resolve": "resolve",
                "maintenance.issue.cancel": "cancel",
                "maintenance.issue.reopen": "reopen",
                "maintenance.appointment.create": "create_appointment",
                "maintenance.appointment.update": "update_appointment",
                "maintenance.appointment.finish": "finish_appointment",
                "maintenance.cost.create": "create_cost",
                "maintenance.cost.void": "void_cost",
                "maintenance.expense.link": "link_expense",
                "maintenance.expense.archive": "archive_expense_link",
                "maintenance.quote.create": "create_quote",
                "maintenance.quote.withdraw": "withdraw_quote",
                "maintenance.assignment.create": "create_assignment",
                "maintenance.assignment.end": "end_assignment",
                "maintenance.follow_up.create": "create_follow_up",
                "maintenance.journal.record": "record",
            },
            maintenance_request,
        ),
        **bind_related(
            portfolio,
            "space",
            "status",
            {
                "portfolio.occupancy.change": "occupancy_changed",
                "portfolio.occupancy.cancel": "occupancy_cancelled",
                "portfolio.occupancy.replace": "occupancy_replaced",
                "portfolio.occupancy.correct": "occupancy_corrected",
                "portfolio.occupancy.reschedule": "occupancy_rescheduled",
                "portfolio.availability.change": "availability_changed",
                "portfolio.space.classify": "space_classified",
            },
            portfolio_request,
        ),
        **bind(
            lease_reader,
            "lease",
            "lease",
            {
                "lease.patch": "patch",
                "lease.term.replace": "replace_initial_term",
                "lease.participant.add": "add_participant",
                "lease.participant.update": "update_participant",
                "lease.participant.remove": "remove_participant",
                "lease.execute": "execute",
                "lease.end": "ended",
                "lease.terminate": "terminated",
                "lease.void": "void",
                "lease.renewal.add": "add_renewal_option",
                "lease.renewal.update": "update_renewal_option",
                "lease.renewal.decide": "decide_renewal_option",
                "lease.termination.create": "create_termination_case",
                "lease.termination.proposal.add": "add_termination_proposal",
                "lease.termination.proposal.accept": "accept_termination_proposal",
                "lease.termination.transition": "transition_termination_case",
            },
            lease_request,
        ),
        "lease.termination.complete": RecoveryBinding(
            "lease",
            "complete_termination_case",
            "lease",
            lease_reader,
            lambda source, payload, key: lease_request(
                "complete_termination_case", source, payload, key
            ),
            result_kind="lease",
            fingerprint_payload=lambda connection, source, payload: termination_completion_payload(
                lease_reader, connection, source, payload
            ),
        ),
        "lease.create": RecoveryBinding(
            None,
            "create",
            "lease",
            lease_reader,
            lambda source, payload, key: lease_request("create", source, payload, key),
            result_kind="lease",
        ),
        **bind(
            finance_reader,
            "lease",
            "finance",
            {
                "finance.rent_expectation.synchronize": "synchronize_expectations",
                "finance.rent_expectation.void": "void_expectation",
                "finance.rent_expectation.timeliness_review": "review_timeliness",
                "finance.rent_receipt.create": "record_receipt",
                "finance.rent_receipt.void": "void_receipt",
                "finance.prepaid_check.create": "create_prepaid_check",
                "finance.prepaid_check.deposit": "deposit_prepaid_check",
                "finance.prepaid_check.return": "return_prepaid_check",
                "finance.prepaid_check.void": "void_prepaid_check",
                "finance.prepaid_check.replace": "replace_prepaid_check",
            },
            finance_request,
        ),
    }
