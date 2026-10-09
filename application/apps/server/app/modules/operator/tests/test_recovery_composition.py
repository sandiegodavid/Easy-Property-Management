"""Slice 19: actual source outcomes, no dispatch, bounded reads and portability."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.bootstrap.communication_context import SQLiteCommunicationContextOperations
from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.communications.application.service import (
    CommunicationCommand,
    CommunicationService,
    ParticipantInput,
    PatchCommand,
)
from app.modules.communications.infrastructure.receipt_reader import (
    SQLiteCommunicationReceiptReader,
)
from app.modules.communications.infrastructure.unit_of_work import SQLiteCommunicationUnitOfWork
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.modules.maintenance.domain.models import AppointmentCreate, CostCreate
from app.modules.maintenance.infrastructure.receipt_reader import SQLiteIssueCommandReceiptReader
from app.modules.maintenance.tests import test_command_readiness as maintenance_fixtures
from app.modules.operator.api.router import build_router
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.recovery_schemas import registered_schemas, validate_payload
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError, OperatorTooLarge
from app.modules.operator.infrastructure.schema_validation import validate_command_recovery
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.parties.application.service import PartyCreateCommand
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.portfolio.application.service import AvailabilityCommand, OccupancyCommand
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.tasks.application.mutations import TaskMutationCommand, TaskMutationService
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.application.waiting import WaitingCommand
from app.modules.tasks.application.waiting_service import TaskWaitingService
from app.modules.tasks.infrastructure.creation_receipt_reader import SQLiteTaskCreationReceiptReader
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspacePaths
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.api_errors import register_api_error_handlers


@pytest.fixture
def ready():
    fixture = maintenance_fixtures.context.__wrapped__()
    context = next(fixture)
    workspace = context.workspace
    recorder = context.service.unit_of_work.recorder
    contexts = SQLiteCommunicationContextOperations(
        SQLiteTaskTransactionOperations(), SQLiteIntakeSourceReader()
    )
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(
            SQLitePortfolioContextReader(),
            SQLitePartyOperations(workspace.paths.database),
            contexts,
        ),
        SQLiteIssueCommandReceiptReader(),
        SQLiteCommunicationReceiptReader(),
        SQLiteTaskCreationReceiptReader(),
        commands=compose_recovery_bindings(),
    )
    uow = SQLiteOperatorUnitOfWork(
        workspace.paths.database, recorder, references, SQLiteAuditReadMarker()
    )
    identity = RuntimeIdentity("ready", workspace.open().workspace_id, str(uuid4()), True)
    support = OperatorService(uow, runtime=lambda: identity)
    tasks = TaskService(SQLiteTaskUnitOfWork(workspace.paths.database, recorder))
    mutations = TaskMutationService(tasks.unit_of_work, now=lambda: datetime.now(UTC))
    waiting = TaskWaitingService(
        tasks.unit_of_work, read_identity=lambda: (identity.workspace_id, identity.epoch)
    )
    communications = CommunicationService(
        SQLiteCommunicationUnitOfWork(workspace.paths.database, recorder, contexts)
    )
    yield context, support, tasks, mutations, waiting, communications
    uow.engine.dispose()
    tasks.unit_of_work.engine.dispose()
    communications.unit_of_work.engine.dispose()
    next(fixture, None)


@pytest.mark.parametrize("participants_case", ["omitted", "null", "empty"])
def test_incomplete_lease_participants_can_be_saved_but_not_attempted(ready, participants_case):
    context, support, _, _, _, _ = ready
    instant = datetime.now(UTC)
    support = OperatorService(support.unit_of_work, runtime=support.runtime, now=lambda: instant)
    start = instant.date().isoformat()
    payload = {
        "expectedRevision": 0,
        "spaceId": context.space_id,
        "leaseKind": "residential",
        "contractStartsOn": start,
        "occupancyStartsOn": start,
        "initialTerm": {
            "baseRentMinor": 10000,
            "currencyCode": "USD",
            "paymentFrequency": "monthly",
            "paymentDueDay": 1,
            "agreedSecurityDepositMinor": 0,
        },
    }
    if participants_case != "omitted":
        payload["participants"] = None if participants_case == "null" else []
    record_id = str(uuid4())
    request = {
        "formKey": "lease.create",
        "schemaVersion": 1,
        "payload": payload,
        "expectedRevision": 0,
        "idempotencyKey": str(uuid4()),
    }
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(support))
    with TestClient(app) as client:
        saved = client.put("/api/operator/recovery/" + record_id, json=request)
        assert saved.status_code == 200, saved.text
        assert saved.json()["payload"] == payload
        assert saved.json()["status"] == "active"
        assert saved.json()["reuseState"] == "available"
        assert (
            client.put("/api/operator/recovery/" + record_id, json=request).json() == saved.json()
        )
        detail = client.get("/api/operator/recovery/" + record_id)
        assert detail.status_code == 200, detail.text
        assert detail.json() == {**saved.json(), "operationId": None}
        with support.unit_of_work.engine.connect() as connection:
            before = {
                table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
                for table in ("operator_operations", "audit_events", "leases")
            }
        attempt = client.post(
            "/api/operator/recovery/" + record_id + "/attempt",
            json={
                "expectedRevision": saved.json()["revision"],
                "idempotencyKey": str(uuid4()),
                "attemptKey": str(uuid4()),
            },
        )
        assert attempt.status_code == 422, attempt.text
        assert client.get("/api/operator/recovery/" + record_id).json() == detail.json()
        with support.unit_of_work.engine.connect() as connection:
            for table, count in before.items():
                assert (
                    connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
                    == count
                )
    validate_latest_schema(context.workspace.paths.database)


def prepare(support, form_key, source_id, payload, *, key=None):
    binding = support.unit_of_work.references.commands[form_key]
    saved = support.save_recovery(
        str(uuid4()),
        form_key=form_key,
        schema_version=1,
        payload=payload,
        source_kind=binding.source_kind,
        source_id=source_id,
        base_source_revision=str(payload["expectedRevision"]) if source_id else None,
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key, receipt_key = key or str(uuid4()), str(uuid4())
    attempt = support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=receipt_key
    )
    assert attempt == support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=receipt_key
    )
    return attempt, key


def reconcile(support, attempt, original):
    # Every new workflow supplies exactly one source SELECT in the caller's snapshot.
    statements = []
    with support.unit_of_work.engine.begin() as connection:
        event.listen(connection, "before_cursor_execute", lambda *args: statements.append(args[2]))
        with patch(
            "sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Nested session")
        ):
            outcome = support.unit_of_work.references.resolve_attempt(
                connection,
                attempt["formKey"],
                attempt["attemptKey"],
                attempt["requestFingerprint"],
                source_id=attempt["sourceId"],
            )
    assert len(statements) == 1
    assert outcome["result"] == expected_projection(original)
    receipt_key = str(uuid4())
    result = support.reconcile_recovery(
        attempt["id"], expected_revision=2, idempotency_key=receipt_key
    )
    assert result == support.reconcile_recovery(
        attempt["id"], expected_revision=2, idempotency_key=receipt_key
    )
    assert result["receipt"]["result"] == expected_projection(original)
    assert result["receipt"]["receiptId"] == original["operationId"]
    return result


def expected_projection(original):
    target = original.get("task", original)
    return {
        "targetId": target["id"],
        "revision": original["revision"],
        "status": target.get("status"),
        "operationId": original["operationId"],
    }


@pytest.mark.parametrize(
    "action",
    [
        "start",
        "complete",
        "cancel",
        "reopen",
        "edit",
        "delete",
        "add_reminder",
        "acknowledge",
        "dismiss",
    ],
)
def test_task_mutations_have_explicit_real_receipt_recovery(ready, action):
    context, support, tasks, mutations, _, _ = ready
    task = tasks.create_command(
        {"title": "Original task"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    task_id, expected = task["id"], 1
    reminder_id = None
    if action in {"acknowledge", "dismiss"}:
        seeded = mutations.mutate(
            TaskMutationCommand(
                task_id,
                "add_reminder",
                expected,
                str(uuid4()),
                remind_at_utc=datetime.now(UTC).isoformat(),
            )
        )
        reminder_id, expected = seeded["reminder"]["id"], seeded["revision"]
    if action == "reopen":
        seeded = mutations.mutate(
            TaskMutationCommand(task_id, "cancel", expected, str(uuid4()), confirmed=True)
        )
        expected = seeded["revision"]
    form = (
        "task.reminder."
        + {"add_reminder": "add", "acknowledge": "acknowledge", "dismiss": "dismiss"}[action]
        if action in {"add_reminder", "acknowledge", "dismiss"}
        else "task." + action
    )
    payload = {"expectedRevision": expected}
    if action in {"complete", "cancel", "reopen", "delete", "acknowledge", "dismiss"}:
        payload["confirmed"] = True
    if action in {"complete", "cancel"}:
        payload["outcomeNote"] = "Private outcome"
    if reminder_id:
        payload["reminderId"] = reminder_id
    if action == "add_reminder":
        payload["remindAtUtc"] = datetime.now(UTC).isoformat()
    if action == "edit":
        payload["changes"] = {"title": "Edited task"}
    attempt, key = prepare(support, form, task_id, payload)
    command = TaskMutationCommand(
        task_id,
        action,
        expected,
        key,
        confirmed=payload.get("confirmed", False),
        outcome_note=payload.get("outcomeNote"),
        reminder_id=reminder_id,
        remind_at_utc=payload.get("remindAtUtc"),
        changes=(("title", "Edited task"),) if action == "edit" else (),
    )
    assert command.fingerprint() == attempt["requestFingerprint"]
    original = mutations.mutate(command)
    assert mutations.mutate(command) == original
    with patch.object(mutations, "mutate", side_effect=AssertionError("Automatic resubmission")):
        reconcile(support, attempt, original)
    validate_latest_schema(context.workspace.paths.database)


@pytest.mark.parametrize("action", ["set", "clear", "reschedule"])
def test_waiting_receipts_recover_without_reclassification(ready, action):
    context, support, tasks, _, waiting, _ = ready
    task = tasks.create_command(
        {"title": "Waiting"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    expected = 1
    if action != "set":
        expected = waiting.mutate(
            WaitingCommand(task["id"], "set", expected, str(uuid4()), kind="person", label="Owner")
        )["revision"]
    payload = {"expectedRevision": expected}
    extras = (
        {"kind": "person", "label": "Owner"}
        if action == "set"
        else {"confirmed": True}
        if action == "clear"
        else {"clearFollowUp": True}
    )
    payload.update(extras)
    attempt, key = prepare(support, "task.waiting." + action, task["id"], payload)
    command = WaitingCommand(
        task["id"],
        action,
        expected,
        key,
        kind=extras.get("kind"),
        label=extras.get("label"),
        confirmed=action == "clear",
        clear_follow_up=action == "reschedule",
    )
    assert command.fingerprint() == attempt["requestFingerprint"]
    original = waiting.mutate(command)
    reconcile(support, attempt, original)
    validate_latest_schema(context.workspace.paths.database)


@pytest.mark.parametrize("action", ["create", "patch", "draft.record", "correct"])
def test_communication_receipts_return_original_domain_result(ready, action):
    context, support, _, _, _, communications = ready
    party = context.portfolio.create_party(PartyCreateCommand("individual", "Reporter"))
    command = CommunicationCommand(
        "inbound",
        "phone",
        "Original",
        "Private body",
        datetime.now(UTC).isoformat(),
        "UTC",
        (ParticipantInput(party.id, "sender"),),
        record=action == "correct",
    )
    source = (
        None
        if action == "create"
        else communications.create(command, str(uuid4()), expected_revision=0)
    )
    payload = {"expectedRevision": 1 if source else 0}
    if action in {"create", "correct"}:
        payload.update(
            direction=command.direction,
            channel=command.channel,
            subject=command.subject,
            body=command.body,
            occurredAtUtc=command.occurred_at_utc,
            occurredTimezone="UTC",
            participants=[{"partyId": party.id, "role": "sender"}],
            record=command.record,
        )
    if action == "correct":
        payload["correctionReason"] = "Corrected context"
    if action == "patch":
        payload["subject"] = "Updated subject"
    attempt, key = prepare(
        support, "communication." + action, source["id"] if source else None, payload
    )
    if action == "create":
        original = communications.create(command, key, expected_revision=0)
    elif action == "patch":
        original = communications.patch(
            source["id"], PatchCommand(subject=payload["subject"]), key, 1
        )
    elif action == "draft.record":
        original = communications.record(source["id"], None, key, 1)
    else:
        original = communications.correct(
            source["id"], command, payload["correctionReason"], key, 1
        )
    reconciled = reconcile(support, attempt, original)
    assert reconciled["receipt"] == {
        "sourceKind": "communication",
        "sourceId": source["id"] if source else original["id"],
        "receiptId": original["operationId"],
        "attemptKey": key,
        "result": expected_projection(original),
    }
    validate_latest_schema(context.workspace.paths.database)


@pytest.mark.parametrize(
    "action",
    [
        "start",
        "return_to_open",
        "resolve",
        "cancel",
        "reopen",
        "patch",
        "reporter.correct",
        "appointment.create",
        "appointment.update",
        "appointment.finish",
        "cost.create",
        "cost.void",
        "follow_up.create",
        "journal.record",
    ],
)
def test_maintenance_issue_and_child_receipts_use_issue_scope(ready, action):
    context, support, _, _, _, _ = ready
    service = context.service
    issue = context.issue()
    issue_id, expected = issue["id"], issue["revision"]
    payload = {"expectedRevision": expected}
    target = None
    starts = datetime.now(UTC) + timedelta(days=1)
    appointment = AppointmentCreate(
        starts.isoformat(), (starts + timedelta(hours=1)).isoformat(), "Repair"
    )
    cost = CostCreate(
        "operator_estimate", "Repair estimate", "10.00", datetime.now(UTC).date().isoformat()
    )
    if action in {"return_to_open", "reopen"}:
        prior = service.transition(
            issue_id,
            "start" if action == "return_to_open" else "cancel",
            "Cancelled" if action == "reopen" else None,
            True if action == "reopen" else None,
            expected_revision=expected,
            idempotency_key=str(uuid4()),
        )
        payload["expectedRevision"] = expected = prior["revision"]
    if action.startswith("appointment.") and action != "appointment.create":
        prior = service.create_appointment(
            issue_id, appointment, str(uuid4()), expected_revision=expected
        )
        target = prior["id"]
        payload.update(targetId=target, expectedRevision=prior["revision"])
        expected = prior["revision"]
    if action == "cost.void":
        prior = service.create_cost(issue_id, cost, str(uuid4()), expected_revision=expected)
        target, expected = prior["id"], prior["revision"]
        payload.update(targetId=target, expectedRevision=expected)
    if action in {"resolve", "cancel", "reopen", "cost.void"}:
        payload.update(reason="Operator action", confirmed=True)
    if action == "patch":
        payload["changes"] = {"summary": "Updated repair"}
    if action == "reporter.correct":
        payload.update(
            reporter={"role": "staff", "subjectKind": "local_operator"},
            reason="Reporter corrected",
            confirmed=True,
        )
    if action in {"appointment.create", "appointment.update"}:
        payload.update(
            startsAtUtc=appointment.starts_at_utc,
            endsAtUtc=appointment.ends_at_utc,
            purpose=appointment.purpose,
        )
    if action == "appointment.finish":
        payload.update(cancelled=False, confirmed=True, reason="Work reported")
    if action == "cost.create":
        payload.update(
            contextKind=cost.context_kind,
            label=cost.label,
            amount="10.00",
            observedOn=cost.observed_on,
        )
    if action == "follow_up.create":
        payload["title"] = "Check repair"
    if action == "journal.record":
        payload.update(
            entryKind="general_note",
            sourceKind="operator_observation",
            occurredAtUtc=datetime.now(UTC).isoformat(),
            summary="Progress",
        )
    form = (
        "maintenance.issue." + action
        if action in {"start", "return_to_open", "resolve", "cancel", "reopen", "patch"}
        else "maintenance." + action
    )
    attempt, key = prepare(support, form, issue_id, payload)
    original = maintenance_dispatch(
        context, action, issue_id, target, expected, key, payload, appointment, cost
    )
    with patch.object(service, "transition", side_effect=AssertionError("Redispatch")):
        reconcile(support, attempt, original)
    validate_latest_schema(context.workspace.paths.database)


def maintenance_dispatch(
    context, action, issue_id, target, expected, key, payload, appointment, cost
):
    from app.modules.maintenance.domain.models import ReporterAttribution, ReporterCorrection
    from app.modules.maintenance.domain.work_journal import WorkJournalCreate

    options = {"expected_revision": expected, "idempotency_key": key}
    service = context.service
    calls = {
        "patch": lambda: service.patch_issue(
            issue_id, {"summary": payload["changes"]["summary"]}, **options
        ),
        "reporter.correct": lambda: service.correct_reporter(
            issue_id,
            ReporterCorrection(
                ReporterAttribution("staff", "local_operator"), True, payload["reason"]
            ),
            **options,
        ),
        "appointment.create": lambda: service.create_appointment(issue_id, appointment, **options),
        "appointment.update": lambda: service.update_appointment(target, appointment, **options),
        "appointment.finish": lambda: service.finish_appointment(
            target, cancelled=False, reason=payload["reason"], confirmed=True, **options
        ),
        "cost.create": lambda: service.create_cost(issue_id, cost, **options),
        "cost.void": lambda: service.void_cost(
            target, reason=payload["reason"], confirmed=True, **options
        ),
        "follow_up.create": lambda: service.create_follow_up(
            issue_id,
            title=payload["title"],
            notes=None,
            priority="normal",
            due_at_utc=None,
            due_timezone=None,
            **options,
        ),
        "journal.record": lambda: context.journal.record(
            issue_id,
            WorkJournalCreate(
                None, "general_note", "operator_observation", payload["occurredAtUtc"], "Progress"
            ),
            **options,
        ),
    }
    if action in calls:
        return calls[action]()
    return service.transition(
        issue_id, action, payload.get("reason"), payload.get("confirmed"), **options
    )


@pytest.mark.parametrize("action", ["availability.change", "occupancy.change", "space.classify"])
def test_manual_portfolio_results_keep_original_temporal_snapshot(ready, action):
    context, support, _, _, _, _ = ready
    portfolio = context.portfolio
    current = portfolio.get_space_status(context.space_id)
    expected = current["revision"]
    payload = {"expectedRevision": expected}
    if action == "availability.change":
        payload["availabilityStatus"] = "not_available"
    elif action == "occupancy.change":
        payload.update(
            occupancyStatus="vacant",
            effectiveOn=(datetime.fromisoformat(current["effectiveLocalDate"]) + timedelta(days=1))
            .date()
            .isoformat(),
        )
    else:
        payload["availability"] = {"availabilityStatus": "not_available"}
    attempt, key = prepare(support, "portfolio." + action, context.space_id, payload)
    if action == "availability.change":
        result = portfolio.change_availability(
            context.space_id,
            AvailabilityCommand("not_available"),
            expected_revision=expected,
            idempotency_key=key,
        )
    elif action == "occupancy.change":
        result = portfolio.change_occupancy(
            context.space_id,
            OccupancyCommand("vacant", payload["effectiveOn"]),
            expected_revision=expected,
            idempotency_key=key,
        )
    else:
        from app.modules.portfolio.application.service import SpaceClassificationCommand

        result = portfolio.classify_space(
            context.space_id,
            SpaceClassificationCommand(availability=AvailabilityCommand("not_available")),
            expected_revision=expected,
            idempotency_key=key,
        )
    portfolio.change_availability(
        context.space_id,
        AvailabilityCommand("available_now"),
        expected_revision=result["revision"],
        idempotency_key=str(uuid4()),
    )
    reconcile(support, attempt, result)
    validate_latest_schema(context.workspace.paths.database)


@pytest.mark.parametrize("action", ["cancel", "replace", "correct", "reschedule"])
def test_manual_occupancy_period_commands_recover_exact_receipts(ready, action):
    from app.modules.portfolio.application.service import OccupancyCorrectionCommand

    context, support, _, _, _, _ = ready
    portfolio, space_id = context.portfolio, context.space_id
    current = portfolio.get_space_status(space_id)
    today = datetime.fromisoformat(current["effectiveLocalDate"]).date()
    if action == "correct":
        period = current["currentOccupancy"]
        expected = current["revision"]
        when = period["startsOn"]
    else:
        seeded = portfolio.change_occupancy(
            space_id,
            OccupancyCommand("occupied", (today + timedelta(days=3)).isoformat()),
            expected_revision=current["revision"],
            idempotency_key=str(uuid4()),
        )
        period, expected = seeded["scheduledOccupancy"], seeded["revision"]
        when = (
            period["startsOn"] if action == "replace" else (today + timedelta(days=4)).isoformat()
        )
    payload = {"expectedRevision": expected, "periodId": period["id"]}
    if action != "cancel":
        payload.update(occupancyStatus="vacant", effectiveOn=when)
    if action == "correct":
        payload["reason"] = "Corrected observation"
    attempt, key = prepare(support, "portfolio.occupancy." + action, space_id, payload)
    command = OccupancyCommand("vacant", when)
    options = {"expected_revision": expected, "idempotency_key": key}
    if action == "cancel":
        result = portfolio.cancel_scheduled_occupancy(space_id, period["id"], **options)
    elif action == "correct":
        result = portfolio.correct_occupancy(
            space_id,
            period["id"],
            OccupancyCorrectionCommand(command, payload["reason"]),
            **options,
        )
    elif action == "replace":
        result = portfolio.replace_scheduled_occupancy(space_id, period["id"], command, **options)
    else:
        result = portfolio.reschedule_scheduled_occupancy(
            space_id, period["id"], command, **options
        )
    reconcile(support, attempt, result)
    validate_latest_schema(context.workspace.paths.database)


@pytest.mark.parametrize(
    "action",
    [
        "expense.link",
        "expense.archive",
        "quote.create",
        "quote.withdraw",
        "assignment.create",
        "assignment.end",
    ],
)
def test_maintenance_financial_and_provider_children_recover(ready, action):
    from app.modules.maintenance.domain.models import AssignmentCreate, QuoteCreate
    from zoneinfo import ZoneInfo

    context, support, _, _, _, _ = ready
    issue, target = context.issue(), None
    issue_id, expected = issue["id"], issue["revision"]
    local_day = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    if action.startswith("expense."):
        expense = context.expense()
        payload = {"expenseId": expense["id"]}
        if action == "expense.archive":
            prior = context.service.link_expense(
                issue_id, expense["id"], str(uuid4()), expected_revision=expected
            )
            target, expected = prior["id"], prior["revision"]
            payload = {"targetId": target, "confirmed": True, "reason": "Association correction"}
    else:
        provider = context.provider()
        quote = QuoteCreate(provider, "Repair quote", "Repair drain", "10.00", local_day)
        assignment = AssignmentCreate(
            provider, selection_reason="Selected directly", direct_assignment_confirmed=True
        )
        payload = {"providerPartyId": provider}
        if action == "quote.create":
            payload.update(
                label="Repair quote",
                scopeSummary="Repair drain",
                amount="10.00",
                receivedOn=local_day,
            )
        elif action == "assignment.create":
            payload.update(selectionReason="Selected directly", directAssignmentConfirmed=True)
        else:
            prior = (
                context.service.create_quote(
                    issue_id, quote, str(uuid4()), expected_revision=expected
                )
                if action == "quote.withdraw"
                else context.service.create_assignment(
                    issue_id, assignment, str(uuid4()), expected_revision=expected
                )
            )
            target, expected = prior["id"], prior["revision"]
            payload = {"targetId": target, "confirmed": True, "reason": "Operator ended context"}
    payload["expectedRevision"] = expected
    attempt, key = prepare(support, "maintenance." + action, issue_id, payload)
    options = {"expected_revision": expected, "idempotency_key": key}
    if action == "expense.link":
        original = context.service.link_expense(issue_id, payload["expenseId"], **options)
    elif action == "expense.archive":
        original = context.service.archive_expense_link(target, payload["reason"], True, **options)
    elif action == "quote.create":
        original = context.service.create_quote(issue_id, quote, **options)
    elif action == "quote.withdraw":
        original = context.service.withdraw_quote(target, payload["reason"], True, **options)
    elif action == "assignment.create":
        original = context.service.create_assignment(issue_id, assignment, **options)
    else:
        original = context.service.end_assignment(target, payload["reason"], True, **options)
    reconcile(support, attempt, original)
    validate_latest_schema(context.workspace.paths.database)


def test_registry_is_exact_and_incomplete_payloads_are_bounded_and_fail_closed(ready):
    _, support, tasks, _, _, _ = ready
    assert set(support.unit_of_work.references.commands) == set(COMMAND_SCHEMAS)
    assert len(registered_schemas()) == len(COMMAND_SCHEMAS) + 3
    for form in COMMAND_SCHEMAS:
        assert validate_payload(form, 1, {}) == {}
        with pytest.raises(OperatorError):
            validate_payload(form, 1, {"rawFileBytes": "secret"})
    with pytest.raises(OperatorTooLarge):
        validate_payload("communication.create", 1, {"body": "x" * 10001})
    task = tasks.create_command(
        {"title": "Existing"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    saved = support.save_recovery(
        str(uuid4()),
        form_key="task.edit",
        schema_version=1,
        payload={},
        source_kind="task",
        source_id=task["id"],
        base_source_revision="1",
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(OperatorError):
        support.prepare_attempt(
            saved["id"], attempt_key=str(uuid4()), expected_revision=1, idempotency_key=str(uuid4())
        )
    assert support.recovery(saved["id"])["status"] == "active"
    with pytest.raises(OperatorConflict):
        support.save_recovery(
            str(uuid4()),
            form_key="task.start",
            schema_version=1,
            payload={"expectedRevision": 2},
            source_kind="task",
            source_id=task["id"],
            base_source_revision="1",
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )


def test_unknown_attempt_cannot_be_discarded_and_changed_payload_is_not_admitted(ready):
    _, support, tasks, mutations, _, _ = ready
    task = tasks.create_command(
        {"title": "Existing"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    attempt, key = prepare(support, "task.start", task["id"], {"expectedRevision": 1})
    for method in (support.discard_recovery, support.reconcile_recovery):
        with pytest.raises(OperatorConflict):
            method(attempt["id"], expected_revision=2, idempotency_key=str(uuid4()))
    mutations.mutate(
        TaskMutationCommand(task["id"], "edit", 1, key, changes=(("title", "Changed"),))
    )
    with pytest.raises(OperatorConflict, match="different request"):
        support.reconcile_recovery(attempt["id"], expected_revision=2, idempotency_key=str(uuid4()))
    assert support.recovery(attempt["id"])["status"] == "outcome_unknown"


def test_api_forms_schema_and_server_fingerprint_without_source_dispatch(ready):
    _, support, tasks, _, _, _ = ready
    app = FastAPI()
    app.include_router(build_router(support))
    task = tasks.create_command(
        {"title": "Existing"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    with TestClient(app) as client:
        catalog = client.get("/api/operator/recovery-forms")
        assert catalog.status_code == 200
        assert {item["formKey"] for item in catalog.json()} == set(registered_schemas())
        assert (
            app.openapi()["paths"]["/api/operator/recovery-forms"]["get"]["operationId"]
            == "listOperatorRecoveryForms"
        )
        saved = client.put(
            "/api/operator/recovery/" + str(uuid4()),
            json={
                "formKey": "task.start",
                "schemaVersion": 1,
                "payload": {"expectedRevision": 1},
                "sourceKind": "task",
                "sourceId": task["id"],
                "baseSourceRevision": "1",
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert saved.status_code == 200, saved.text
        key = str(uuid4())
        with patch.object(tasks, "create_command", side_effect=AssertionError("Dispatch")):
            attempted = client.post(
                "/api/operator/recovery/" + saved.json()["id"] + "/attempt",
                json={"attemptKey": key, "expectedRevision": 1, "idempotencyKey": str(uuid4())},
            )
        assert attempted.status_code == 200, attempted.text
        assert (
            attempted.json()["requestFingerprint"]
            == TaskMutationCommand(task["id"], "start", 1, key).fingerprint()
        )


def test_reconciliation_audit_failure_preserves_source_receipt_and_original_attempt(ready):
    _, support, tasks, mutations, _, _ = ready
    task = tasks.create_command(
        {"title": "Existing"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    attempt, key = prepare(support, "task.start", task["id"], {"expectedRevision": 1})
    result = mutations.mutate(TaskMutationCommand(task["id"], "start", 1, key))
    with (
        patch.object(
            support.unit_of_work.recorder,
            "record_change",
            side_effect=RuntimeError("Audit unavailable"),
        ),
        pytest.raises(RuntimeError),
    ):
        support.reconcile_recovery(attempt["id"], expected_revision=2, idempotency_key=str(uuid4()))
    assert support.recovery(attempt["id"])["status"] == "outcome_unknown"
    reconcile(support, attempt, result)


def test_stale_saved_source_and_conflicting_supplied_fingerprint_do_not_begin_attempts(ready):
    _, support, tasks, mutations, _, _ = ready
    task = tasks.create_command(
        {"title": "Original"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    saved = support.save_recovery(
        str(uuid4()),
        form_key="task.start",
        schema_version=1,
        payload={"expectedRevision": 1},
        source_kind="task",
        source_id=task["id"],
        base_source_revision="1",
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(OperatorConflict, match="does not match"):
        support.prepare_attempt(
            saved["id"],
            attempt_key=str(uuid4()),
            request_fingerprint="a" * 64,
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert support.recovery(saved["id"])["status"] == "active"
    mutations.mutate(
        TaskMutationCommand(task["id"], "edit", 1, str(uuid4()), changes=(("title", "Changed"),))
    )
    with pytest.raises(OperatorConflict, match="Refresh"):
        support.prepare_attempt(
            saved["id"], attempt_key=str(uuid4()), expected_revision=1, idempotency_key=str(uuid4())
        )
    assert support.recovery(saved["id"])["status"] == "active"


def test_child_from_another_issue_is_not_a_reusable_recovery_target(ready):
    context, support, _, _, _, _ = ready
    first, second = context.issue(), context.issue()
    starts = datetime.now(UTC) + timedelta(days=1)
    appointment = context.service.create_appointment(
        second["id"],
        AppointmentCreate(starts.isoformat(), (starts + timedelta(hours=1)).isoformat(), "Work"),
        str(uuid4()),
        expected_revision=second["revision"],
    )
    with pytest.raises(OperatorConflict):
        support.save_recovery(
            str(uuid4()),
            form_key="maintenance.appointment.finish",
            schema_version=1,
            payload={
                "expectedRevision": first["revision"],
                "targetId": appointment["id"],
                "cancelled": False,
                "confirmed": True,
            },
            source_kind="maintenance_issue",
            source_id=first["id"],
            base_source_revision=str(first["revision"]),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )


@pytest.mark.parametrize("kind", ["task", "maintenance"])
def test_noop_commands_recover_their_actual_unchanged_source_revision(ready, kind):
    context, support, tasks, mutations, _, _ = ready
    if kind == "task":
        task = tasks.create_command(
            {"title": "Unchanged"}, expected_revision=0, idempotency_key=str(uuid4())
        )
        attempt, key = prepare(
            support,
            "task.edit",
            task["id"],
            {"expectedRevision": 1, "changes": {"title": "Unchanged"}},
        )
        original = mutations.mutate(
            TaskMutationCommand(task["id"], "edit", 1, key, changes=(("title", "Unchanged"),))
        )
    else:
        issue = context.issue()
        attempt, key = prepare(
            support,
            "maintenance.issue.patch",
            issue["id"],
            {"expectedRevision": 1, "changes": {"summary": issue["summary"]}},
        )
        original = context.service.patch_issue(
            issue["id"], {"summary": issue["summary"]}, expected_revision=1, idempotency_key=key
        )
    assert original["revision"] == 1
    reconcile(support, attempt, original)
    validate_latest_schema(context.workspace.paths.database)


def test_restart_and_encrypted_restore_keep_attempt_and_original_receipt(ready, tmp_path):
    context, support, tasks, mutations, _, communications = ready
    task = tasks.create_command(
        {"title": "Restore"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    attempt, key = prepare(
        support, "task.edit", task["id"], {"expectedRevision": 1, "changes": {"title": "Edited"}}
    )
    command = TaskMutationCommand(task["id"], "edit", 1, key, changes=(("title", "Edited"),))
    original = mutations.mutate(command)
    party = context.portfolio.create_party(PartyCreateCommand("individual", "Reporter"))
    reported = datetime.now(UTC).isoformat()
    communication_attempt, communication_key = prepare(
        support,
        "communication.create",
        None,
        {
            "expectedRevision": 0,
            "direction": "inbound",
            "channel": "phone",
            "subject": "Call",
            "body": "Private notes",
            "occurredAtUtc": reported,
            "occurredTimezone": "UTC",
            "participants": [{"partyId": party.id, "role": "sender"}],
            "record": True,
        },
    )
    communication_result = communications.create(
        CommunicationCommand(
            "inbound",
            "phone",
            "Call",
            "Private notes",
            reported,
            "UTC",
            (ParticipantInput(party.id, "sender"),),
            record=True,
        ),
        communication_key,
        expected_revision=0,
    )
    issue = context.issue()
    maintenance_attempt, maintenance_key = prepare(
        support, "maintenance.issue.start", issue["id"], {"expectedRevision": issue["revision"]}
    )
    maintenance_result = context.service.transition(
        issue["id"], "start", expected_revision=issue["revision"], idempotency_key=maintenance_key
    )
    reconcile(support, maintenance_attempt, maintenance_result)
    current_status = context.portfolio.get_space_status(context.space_id)
    portfolio_attempt, portfolio_key = prepare(
        support,
        "portfolio.availability.change",
        context.space_id,
        {"expectedRevision": current_status["revision"], "availabilityStatus": "not_available"},
    )
    portfolio_result = context.portfolio.change_availability(
        context.space_id,
        AvailabilityCommand("not_available"),
        expected_revision=current_status["revision"],
        idempotency_key=portfolio_key,
    )
    new_identity = replace(support.runtime(), epoch=str(uuid4()))
    support.runtime = lambda: new_identity
    support.unit_of_work.engine.dispose()
    assert support.recovery(attempt["id"])["requestFingerprint"] == attempt["requestFingerprint"]
    tables = (
        "operator_recovery_records",
        "operator_operations",
        "task_mutation_operations",
        "communication_operations",
        "maintenance_command_receipts",
        "space_status_operations",
    )
    with support.unit_of_work.engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings().all()
            for table in tables
        }
        audits = (
            connection.execute(
                text("SELECT * FROM audit_events WHERE entity_type LIKE 'operator_%' ORDER BY id")
            )
            .mappings()
            .all()
        )
    with fast_backup_encryption():
        backups = BackupService(
            context.workspace,
            support.unit_of_work.recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        archive = backups.create_backup(
            "correct horse battery staple", output_path=tmp_path / "archive.epmbak"
        )
        backups.restore(archive.archive_path, "correct horse battery staple", tmp_path / "restored")
    restored_path = WorkspacePaths(tmp_path / "restored").database
    validate_latest_schema(restored_path)
    restored_uow = SQLiteOperatorUnitOfWork(
        restored_path,
        AuditRecorder(SQLiteAuditRepository(restored_path)),
        support.unit_of_work.references,
        SQLiteAuditReadMarker(),
    )
    try:
        restored_support = OperatorService(restored_uow, runtime=support.runtime)
        with restored_uow.engine.connect() as connection:
            after = {
                table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))
                .mappings()
                .all()
                for table in tables
            }
            assert after == before
            assert (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events WHERE entity_type LIKE 'operator_%' ORDER BY id"
                    )
                )
                .mappings()
                .all()
                == audits
            )
        assert restored_support.recovery(attempt["id"])["payload"] == attempt["payload"]
        assert restored_support.recovery(attempt["id"])["attemptKey"] == key
        reconcile(restored_support, attempt, original)
        reconcile(restored_support, communication_attempt, communication_result)
        reconcile(restored_support, portfolio_attempt, portfolio_result)
        assert restored_support.recovery(maintenance_attempt["id"])["receipt"][
            "result"
        ] == expected_projection(maintenance_result)
        validate_latest_schema(restored_path)
    finally:
        restored_uow.engine.dispose()


def test_retained_reconciliation_must_match_the_source_owned_original(ready):
    context, support, tasks, mutations, _, _ = ready
    task = tasks.create_command(
        {"title": "Existing"}, expected_revision=0, idempotency_key=str(uuid4())
    )
    attempt, key = prepare(support, "task.start", task["id"], {"expectedRevision": 1})
    result = mutations.mutate(TaskMutationCommand(task["id"], "start", 1, key))
    reconciled = reconcile(support, attempt, result)
    changed = {
        **reconciled["receipt"],
        "result": {**reconciled["receipt"]["result"], "revision": 999},
    }
    with support.unit_of_work.engine.begin() as connection:
        connection.execute(
            text("UPDATE operator_recovery_records SET receipt_json=:value WHERE id=:id"),
            {
                "value": json.dumps(changed, sort_keys=True, separators=(",", ":")),
                "id": attempt["id"],
            },
        )
        with pytest.raises(MigrationSchemaError):
            validate_command_recovery(connection, compose_recovery_bindings())
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(context.workspace.paths.database)
