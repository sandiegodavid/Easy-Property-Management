"""Actual SQLite/API command safety, retained evidence and portability proofs."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.infrastructure.expense_unit_of_work import (
    _Transaction as FinanceTransaction,
)
from app.modules.maintenance.application.commands import canonical_payload, command_fingerprint
from app.modules.maintenance.application.service import MaintenanceService
from app.modules.maintenance.domain.models import (
    AppointmentCreate,
    AssignmentCreate,
    CostCreate,
    IssueCreate,
    MaintenanceConflictError,
    QuoteCreate,
    ReporterAttribution,
    ReporterCorrection,
)
from app.modules.maintenance.domain.work_journal import WorkJournalCreate
from app.modules.maintenance.domain.audit_policy import MAINTENANCE_ACTIVITY_POLICY
from app.modules.maintenance.infrastructure.receipt_reader import SQLiteIssueCommandReceiptReader
from app.modules.maintenance.infrastructure.schema_validation import (
    COMMAND_RECEIPT_TRIGGERS,
    validate_maintenance_schema,
)
from app.modules.maintenance.infrastructure.sqlalchemy_models import MaintenanceCommandReceiptModel
from app.modules.maintenance.infrastructure.unit_of_work import SQLiteMaintenanceTransaction
from app.modules.maintenance.tests import test_workflow
from app.modules.tasks.application.mutations import TaskMutationCommand, TaskMutationService
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine


@pytest.fixture
def context():
    fixture = test_workflow.MaintenanceWorkflowTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def test_original_issue_and_lifecycle_replay_before_current_policy(context):
    issue = context.issue()
    key = str(uuid4())
    started = context.service.transition(
        issue["id"], "start", expected_revision=1, idempotency_key=key
    )
    context.service.transition(
        issue["id"], "resolve", "Repaired", True, expected_revision=2, idempotency_key=str(uuid4())
    )
    assert (
        context.service.transition(issue["id"], "start", expected_revision=1, idempotency_key=key)
        == started
    )
    original = context.service.command_receipt(issue["operationId"])
    assert original["response"] == issue
    with pytest.raises(MaintenanceConflictError) as stale:
        context.service.patch_issue(
            issue["id"], {"summary": "Changed"}, expected_revision=1, idempotency_key=str(uuid4())
        )
    assert (stale.value.code, stale.value.current_revision) == ("stale_revision", 3)
    with pytest.raises(MaintenanceConflictError) as conflict:
        context.service.transition(issue["id"], "start", expected_revision=2, idempotency_key=key)
    assert (conflict.value.code, conflict.value.current_revision) == ("idempotency_conflict", 3)
    context.workspace.open()


def test_creation_source_recovery_uses_receipt_identity_and_public_digest(context):
    command = IssueCreate(
        context.property_id,
        None,
        "Recovery",
        "Recovery repair",
        "plumbing",
        None,
        "normal",
        datetime.now(UTC).isoformat(),
        ReporterAttribution("manager", "local_operator"),
    )
    key = str(uuid4())
    digest = command_fingerprint(
        action="create_issue",
        target_kind="issue",
        target_id=None,
        payload={"command": command},
        expected_revision=0,
    )
    result = context.service.create_issue(command, key, expected_revision=0)
    context.service.patch_issue(
        result["id"], {"summary": "Later write"}, expected_revision=1, idempotency_key=str(uuid4())
    )
    assert context.service.create_issue(command, key, expected_revision=0) == result
    app = create_app(context.workspace.config.config_path)
    with TestClient(app):
        references = app.state.operator_service.unit_of_work.references
        engine = create_sqlite_engine(context.workspace.paths.database)
        try:
            with engine.connect() as connection:
                receipt = SQLiteIssueCommandReceiptReader().receipt(connection, key)
                assert receipt["id"] == result["operationId"] != result["id"]
                assert receipt["request_fingerprint"] == digest
                assert json.loads(receipt["response_payload"]) == result
                recovered = references.resolve_attempt(
                    connection, "maintenance.issue.create", key, digest
                )
                assert recovered == {
                    "sourceKind": "maintenance_issue",
                    "sourceId": result["id"],
                    "receiptId": result["operationId"],
                    "attemptKey": key,
                }
        finally:
            engine.dispose()


def test_all_child_workflows_keep_original_receipts_after_later_actions(context):
    issue = context.issue()
    service = context.service
    provider = context.provider()
    local_today = datetime.now(ZoneInfo(issue["reportedTimezone"])).date().isoformat()
    calls = []
    revision = 1

    # Named call-site helper records explicit command preconditions and replay arguments.
    def apply(method, *args, **kwargs):
        nonlocal revision
        kwargs.update(expected_revision=revision)
        result = method(*args, **kwargs)
        assert result["revision"] == revision + 1
        revision = result["revision"]
        calls.append((method, args, dict(kwargs), result))
        return result

    appointment = apply(
        service.create_appointment,
        issue["id"],
        AppointmentCreate(
            datetime.now(UTC).isoformat(),
            (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "Initial visit",
        ),
        str(uuid4()),
    )
    apply(
        service.update_appointment,
        appointment["id"],
        AppointmentCreate(appointment["startsAtUtc"], appointment["endsAtUtc"], "Updated visit"),
        idempotency_key=str(uuid4()),
    )
    apply(
        service.finish_appointment,
        appointment["id"],
        cancelled=True,
        reason="Replanned",
        confirmed=True,
        idempotency_key=str(uuid4()),
    )
    cost = apply(
        service.create_cost,
        issue["id"],
        CostCreate("operator_estimate", "Estimate", "25.00", local_today),
        str(uuid4()),
    )
    apply(service.void_cost, cost["id"], "Corrected estimate", True, idempotency_key=str(uuid4()))
    apply(
        service.create_cost,
        issue["id"],
        CostCreate(
            "operator_estimate",
            "Replacement",
            "30.00",
            local_today,
            replaces_cost_context_id=cost["id"],
        ),
        str(uuid4()),
    )
    link = apply(service.link_expense, issue["id"], context.expense()["id"], str(uuid4()))
    apply(
        service.archive_expense_link,
        link["id"],
        "Corrected linkage",
        True,
        idempotency_key=str(uuid4()),
    )
    quote = apply(
        service.create_quote,
        issue["id"],
        QuoteCreate(provider, "Offer", "Repair", "35.00", local_today),
        str(uuid4()),
    )
    assignment = apply(
        service.create_assignment,
        issue["id"],
        AssignmentCreate(provider, quote_id=quote["id"]),
        str(uuid4()),
    )
    replacement = apply(
        service.create_assignment,
        issue["id"],
        AssignmentCreate(
            provider,
            quote_id=quote["id"],
            replaces_assignment_id=assignment["id"],
            replacement_confirmed=True,
            end_reason="Reassigned",
        ),
        str(uuid4()),
    )
    apply(
        service.end_assignment,
        replacement["id"],
        "Work complete",
        True,
        idempotency_key=str(uuid4()),
    )
    apply(
        service.withdraw_quote, quote["id"], "Offer corrected", True, idempotency_key=str(uuid4())
    )
    apply(
        service.create_quote,
        issue["id"],
        QuoteCreate(
            provider,
            "New offer",
            "Repair",
            "40.00",
            local_today,
            replaces_quote_id=quote["id"],
        ),
        str(uuid4()),
    )
    entry = apply(
        context.journal.record,
        issue["id"],
        WorkJournalCreate(
            None,
            "general_note",
            "operator_observation",
            datetime.now(UTC).isoformat(),
            "Observation",
        ),
        str(uuid4()),
    )
    apply(
        context.journal.record,
        issue["id"],
        WorkJournalCreate(
            None,
            "correction",
            "operator_observation",
            datetime.now(UTC).isoformat(),
            "Corrected observation",
            corrects_entry_id=entry["id"],
            corrected_entry_kind="general_note",
            correction_reason="Clarified",
        ),
        str(uuid4()),
    )
    apply(
        service.correct_reporter,
        issue["id"],
        ReporterCorrection(
            ReporterAttribution("staff", "local_operator"), True, "Corrected operator role"
        ),
        idempotency_key=str(uuid4()),
    )
    apply(service.transition, issue["id"], "cancel", "Closed", True, idempotency_key=str(uuid4()))
    for method, args, kwargs, result in calls:
        assert method(*args, **kwargs) == result
        assert service.command_receipt(result["operationId"])["response"] == result
    assert service.detail(issue["id"])["revision"] == revision
    context.workspace.open()


def test_child_replay_and_noop_receipts_share_issue_revision(context):
    issue = context.issue()
    key = str(uuid4())
    command = AppointmentCreate(
        datetime.now(UTC).isoformat(), (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "Visit"
    )
    appointment = context.service.create_appointment(issue["id"], command, key, expected_revision=1)
    finished = context.service.finish_appointment(
        appointment["id"],
        cancelled=False,
        reason="Inspected",
        confirmed=True,
        expected_revision=2,
        idempotency_key=str(uuid4()),
    )
    assert finished["revision"] == 3
    assert (
        context.service.create_appointment(issue["id"], command, key, expected_revision=1)
        == appointment
    )
    noop_key = str(uuid4())
    noop = context.service.patch_issue(
        issue["id"], {"summary": issue["summary"]}, expected_revision=3, idempotency_key=noop_key
    )
    assert noop["revision"] == 3
    assert context.service.command_receipt(noop["operationId"])["effective"] is False
    context.service.patch_issue(
        issue["id"], {"summary": "Later title"}, expected_revision=3, idempotency_key=str(uuid4())
    )
    assert (
        context.service.patch_issue(
            issue["id"],
            {"summary": issue["summary"]},
            expected_revision=3,
            idempotency_key=noop_key,
        )
        == noop
    )
    context.workspace.open()


def test_followup_replay_after_task_tombstone(context):
    issue = context.issue()
    key = str(uuid4())
    task = context.service.create_follow_up(
        issue["id"], "Call plumber", None, "normal", None, None, key, expected_revision=1
    )
    tasks = TaskMutationService(
        SQLiteTaskUnitOfWork(
            context.workspace.paths.database,
            AuditRecorder(SQLiteAuditRepository(context.workspace.paths.database)),
        ),
        now=lambda: datetime.now(UTC),
    )
    tasks.mutate(TaskMutationCommand(task["id"], "delete", 1, str(uuid4()), confirmed=True))
    assert (
        context.service.create_follow_up(
            issue["id"], "Call plumber", None, "normal", None, None, key, expected_revision=1
        )
        == task
    )
    context.workspace.open()


def test_caller_transaction_rolls_back_finance_task_issue_receipts_and_audits(context):
    issue = context.issue()
    expense = context.expense()
    uow = context.service.unit_of_work
    engine = create_sqlite_engine(context.workspace.paths.database)
    try:
        with engine.connect() as connection:
            before = connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
        key = str(uuid4())

        def caller(tx):
            finance = FinanceTransaction(tx.connection, tx.recorder, tx.portfolio, None, None, None)
            original = finance.expense(expense["id"])
            finance.replace_expense(replace(original, payee_name="Uncommitted payee"))
            context.service.link_expense(
                issue["id"], expense["id"], str(uuid4()), expected_revision=1, transaction=tx
            )
            context.service.create_follow_up(
                issue["id"],
                "Uncommitted task",
                None,
                "normal",
                None,
                None,
                key,
                expected_revision=2,
                transaction=tx,
            )
            raise RuntimeError("caller rollback")

        with (
            pytest.raises(RuntimeError, match="caller rollback"),
            patch.object(uow, "write", wraps=uow.write) as write,
        ):
            uow.write(caller)
        assert write.call_count == 1
        assert context.service.detail(issue["id"])["revision"] == 1
        assert context.service.detail(issue["id"])["expenseLinks"] == []
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM tasks")).scalar_one() == 0
            assert (
                connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == before
            )
            assert (
                connection.execute(
                    text("SELECT payee_name FROM expenses WHERE id=:id"), {"id": expense["id"]}
                ).scalar_one()
                == expense["payeeName"]
            )
            assert (
                connection.execute(
                    select(func.count()).select_from(MaintenanceCommandReceiptModel)
                ).scalar_one()
                == 1
            )
        context.workspace.open()
    finally:
        engine.dispose()


def test_receipt_insert_failure_rolls_back_task_and_revision(context):
    issue = context.issue()
    with patch.object(
        SQLiteMaintenanceTransaction,
        "insert_command_receipt",
        side_effect=RuntimeError("receipt failure"),
    ):
        with pytest.raises(RuntimeError, match="receipt failure"):
            context.service.create_follow_up(
                issue["id"], "Call", None, "normal", None, None, str(uuid4()), expected_revision=1
            )
    assert context.service.detail(issue["id"])["tasks"] == []
    assert context.service.detail(issue["id"])["revision"] == 1
    context.workspace.open()


@pytest.mark.parametrize("tamper", ["trigger", "response", "revision", "audit", "request"])
def test_schema_and_retained_evidence_tampering_rejected(context, tamper):
    issue = context.issue()
    engine = create_sqlite_engine(context.workspace.paths.database)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA recursive_triggers=OFF")
            original = dict(
                connection.execute(select(MaintenanceCommandReceiptModel)).mappings().one()
            )
            # Independently collide with PK, key, and the effective revision index.
            for replacement in (
                {
                    **original,
                    "idempotency_key": str(uuid4()),
                    "effective": 0,
                    "expected_revision": 1,
                    "action": "patch_issue",
                    "target_id": issue["id"],
                },
                {
                    **original,
                    "id": str(uuid4()),
                    "effective": 0,
                    "expected_revision": 1,
                    "action": "patch_issue",
                    "target_id": issue["id"],
                },
                {**original, "id": str(uuid4()), "idempotency_key": str(uuid4())},
            ):
                with pytest.raises(
                    IntegrityError, match="maintenance command receipts are immutable"
                ):
                    connection.execute(
                        MaintenanceCommandReceiptModel.__table__.insert()
                        .prefix_with("OR REPLACE")
                        .values(**replacement)
                    )
            assert (
                dict(connection.execute(select(MaintenanceCommandReceiptModel)).mappings().one())
                == original
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    MaintenanceCommandReceiptModel.__table__.update().values(action="patch_issue")
                )
            with pytest.raises(IntegrityError):
                connection.execute(MaintenanceCommandReceiptModel.__table__.delete())
            if tamper == "trigger":
                connection.exec_driver_sql("DROP TRIGGER maintenance_command_receipts_no_delete")
            elif tamper == "revision":
                connection.exec_driver_sql("UPDATE maintenance_issues SET revision=2")
            elif tamper == "audit":
                connection.exec_driver_sql("DROP TRIGGER audit_events_no_delete")
                connection.execute(text("DELETE FROM audit_events WHERE action='command_recorded'"))
            else:
                connection.exec_driver_sql("DROP TRIGGER maintenance_command_receipts_no_update")
                receipt = (
                    connection.execute(select(MaintenanceCommandReceiptModel)).mappings().one()
                )
                prefix = tamper
                payload = json.loads(receipt[f"{prefix}_payload"])
                if prefix == "response":
                    payload["summary"] = "Forged immutable result"
                else:
                    payload["payload"]["command"]["summary"] = "Forged request"
                encoded = canonical_payload(payload)
                connection.execute(
                    MaintenanceCommandReceiptModel.__table__.update().values(
                        **{
                            f"{prefix}_payload": encoded,
                            f"{prefix}_fingerprint": sha256(encoded.encode()).hexdigest(),
                        }
                    )
                )
                connection.exec_driver_sql(
                    COMMAND_RECEIPT_TRIGGERS["maintenance_command_receipts_no_update"]
                )
            with pytest.raises(MigrationSchemaError):
                validate_maintenance_schema(connection)
        assert issue["revision"] == 1
    finally:
        engine.dispose()


def test_encrypted_restore_retains_original_receipts_and_source_reader(context):
    issue = context.issue()
    context.service.patch_issue(
        issue["id"], {"summary": "Later"}, expected_revision=1, idempotency_key=str(uuid4())
    )
    archive = Path(context.temp.name) / "commands.epm-backup"
    backup = BackupService(
        context.workspace,
        AuditRecorder(SQLiteAuditRepository(context.workspace.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    root = Path(context.temp.name) / "restored-commands"
    with fast_backup_encryption():
        backup.create_backup("a sufficiently long test passphrase", output_path=archive)
        backup.restore(archive, "a sufficiently long test passphrase", root)
    database = root / "database" / "property-management.sqlite"
    context.service.unit_of_work.database = database
    restored = MaintenanceService(context.service.unit_of_work)
    receipt = restored.command_receipt(issue["operationId"])
    assert receipt["response"] == issue
    assert restored.detail(issue["id"])["revision"] == 2
    engine = create_sqlite_engine(database)
    try:
        with engine.connect() as connection:
            result = SQLiteIssueCommandReceiptReader().receipt(
                connection, receipt["idempotencyKey"]
            )
            assert result["id"] == issue["operationId"]
            assert result["result_issue_id"] == issue["id"]
            assert json.loads(result["response_payload"]) == issue
            validate_maintenance_schema(connection)
    finally:
        engine.dispose()


def test_quote_schedule_documents_and_assignment_survive_encrypted_restore(context):
    issue = context.issue()
    provider = context.provider()
    on = datetime.now(ZoneInfo(issue["reportedTimezone"])).date().isoformat()
    quote = context.service.create_quote(
        issue["id"],
        QuoteCreate(
            provider,
            "Portable offer",
            "Repair scope",
            "35.00",
            on,
            earliest_work_start_on=on,
            estimated_work_finish_on=on,
        ),
        str(uuid4()),
        expected_revision=1,
    )
    assignment = context.service.create_assignment(
        issue["id"],
        AssignmentCreate(provider, quote_id=quote["id"]),
        str(uuid4()),
        expected_revision=2,
    )
    with TestClient(create_app(context.workspace.config.config_path)) as client:
        upload = client.post(
            "/api/files",
            data={
                "entity_type": "maintenance_quote",
                "entity_id": quote["id"],
                "purpose": "quote_document",
                "idempotency_key": str(uuid4()),
            },
            files={"file": ("offer.txt", b"Immutable quoted scope", "text/plain")},
        )
    assert upload.status_code == 201, upload.text
    before = context.service.detail(issue["id"])
    archive = Path(context.temp.name) / "quote.epm-backup"
    root = Path(context.temp.name) / "restored-quote"
    backup = BackupService(
        context.workspace,
        AuditRecorder(SQLiteAuditRepository(context.workspace.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        backup.create_backup("a sufficiently long test passphrase", output_path=archive)
        backup.restore(archive, "a sufficiently long test passphrase", root)
    context.service.unit_of_work.database = root / "database" / "property-management.sqlite"
    restored = MaintenanceService(context.service.unit_of_work)
    after = restored.detail(issue["id"])
    assert after["quotes"] == before["quotes"]
    assert after["assignments"] == before["assignments"]
    assert after["quotes"][0]["earliestWorkStartOn"] == on
    assert after["quotes"][0]["files"][0]["fileId"] == before["quotes"][0]["files"][0]["fileId"]
    assert restored.command_receipt(assignment["operationId"])["response"] == assignment


def test_journal_correction_evidence_history_survives_encrypted_restore(context):
    issue = context.issue()
    at = datetime.now(UTC).isoformat()
    original = context.journal.record(
        issue["id"],
        WorkJournalCreate(
            None,
            "work_completed",
            "operator_observation",
            at,
            "Initial observation",
            outcome_status="completed",
            outcome_summary="Initially dry",
            follow_up_required=False,
            operator_verified=True,
        ),
        str(uuid4()),
        expected_revision=1,
    )
    with TestClient(create_app(context.workspace.config.config_path)) as client:
        upload = client.post(
            "/api/files",
            data={
                "entity_type": "maintenance_work_journal_entry",
                "entity_id": original["id"],
                "purpose": "completion_photo",
                "idempotency_key": str(uuid4()),
            },
            files={"file": ("condition.txt", b"Initial observed condition", "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        metadata = client.get(f"/api/files/{upload.json()['id']}").json()
        link = metadata["links"][0]
        archived = client.post(
            f"/api/file-links/{link['id']}/archive",
            json={
                "confirmed": True,
                "reason": "Retain original evidence in history",
                "expectedRevision": link["revision"],
                "idempotencyKey": str(uuid4()),
            },
        )
        assert archived.status_code == 200, archived.text
    correction = context.journal.record(
        issue["id"],
        WorkJournalCreate(
            None,
            "correction",
            "operator_observation",
            at,
            "Corrected observation",
            outcome_status="partially_completed",
            outcome_summary="Residual leak",
            follow_up_required=True,
            operator_verified=True,
            corrects_entry_id=original["id"],
            corrected_entry_kind="work_completed",
            correction_reason="Recheck changed conclusion",
        ),
        str(uuid4()),
        expected_revision=2,
    )
    before = context.journal.issue_journal(issue["id"])
    repository = SQLiteAuditRepository(context.workspace.paths.database)
    before_audits = {
        entry_id: repository.history("maintenance_work_journal_entry", entry_id)
        for entry_id in (original["id"], correction["id"])
    }
    event_after = before_audits[correction["id"]][0]
    assert event_after.after_snapshot["correctionReason"] == "Recheck changed conclusion"
    assert event_after.after_snapshot["outcomeSummary"] == "Residual leak"
    activity = event_after.to_dict(MAINTENANCE_ACTIVITY_POLICY)["after"]
    assert "correctionReason" not in activity
    assert "outcomeSummary" not in activity
    backup = BackupService(
        context.workspace,
        AuditRecorder(SQLiteAuditRepository(context.workspace.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    archive, root = (
        Path(context.temp.name) / "journal.epm-backup",
        Path(context.temp.name) / "journal-restored",
    )
    with fast_backup_encryption():
        backup.create_backup("a sufficiently long test passphrase", output_path=archive)
        backup.restore(archive, "a sufficiently long test passphrase", root)
    context.service.unit_of_work.database = root / "database" / "property-management.sqlite"
    assert context.journal.issue_journal(issue["id"]) == before
    assert context.service.command_receipt(correction["operationId"])["response"] == correction
    assert context.service.detail(issue["id"])["status"] == "open"
    repository = SQLiteAuditRepository(context.service.unit_of_work.database)
    assert {
        entry_id: repository.history("maintenance_work_journal_entry", entry_id)
        for entry_id in before_audits
    } == before_audits
    engine = create_sqlite_engine(context.service.unit_of_work.database)
    try:
        with engine.connect() as connection:
            retained = (
                connection.execute(
                    text(
                        "SELECT file_id, archived_at, archive_reason FROM file_links WHERE id=:id"
                    ),
                    {"id": link["id"]},
                )
                .mappings()
                .one()
            )
            assert retained["file_id"] == metadata["id"]
            assert retained["archived_at"]
            assert retained["archive_reason"] == "Retain original evidence in history"
            assert datetime.fromisoformat(
                connection.execute(
                    text("SELECT verified_at FROM file_content_locations WHERE file_id=:id"),
                    {"id": metadata["id"]},
                ).scalar_one()
            ) == datetime.fromisoformat(metadata["verifiedAt"])
            assert (
                root / "files" / "managed" / sha256(b"Initial observed condition").hexdigest()
            ).read_bytes() == b"Initial observed condition"
            validate_maintenance_schema(connection)
    finally:
        engine.dispose()


def test_journal_page_query_budget_is_constant(context):
    issue = context.issue()
    for index in range(21):
        context.journal.record(
            issue["id"],
            WorkJournalCreate(
                None,
                "general_note",
                "operator_observation",
                datetime.now(UTC).isoformat(),
                f"Fact {index}",
            ),
            str(uuid4()),
            expected_revision=index + 1,
        )
    import app.modules.maintenance.infrastructure.unit_of_work as adapter

    engine = create_sqlite_engine(context.workspace.paths.database)
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with patch.object(adapter, "create_engine", return_value=engine):
            context.journal.issue_journal(issue["id"], page_size=1)
            one = len(statements)
            statements.clear()
            page = context.journal.issue_journal(issue["id"], page_size=20)
            assert len(statements) == one
            assert len(statements) <= 6
            assert len(page["items"]) == 20
            assert page["nextCursor"]
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        engine.dispose()


def test_api_required_metadata_receipt_and_conflict_schema(context):
    issue = context.issue()
    with TestClient(create_app(context.workspace.config.config_path)) as client:
        url = f"/api/maintenance-issues/{issue['id']}/start"
        for payload in (
            {},
            {"expectedRevision": 1},
            {"idempotencyKey": str(uuid4())},
            {"expectedRevision": True, "idempotencyKey": str(uuid4())},
        ):
            assert client.post(url, json=payload).status_code == 422
        payload = {"expectedRevision": 1, "idempotencyKey": str(uuid4())}
        result = client.post(url, json=payload)
        assert result.status_code == 200, result.text
        original = result.json()
        assert original["revision"] == 2
        assert client.post(url, json=payload).json() == original
        stale = client.patch(
            f"/api/maintenance-issues/{issue['id']}",
            json={"summary": "Stale", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["currentRevision"] == 2
        assert (
            client.get(f"/api/maintenance-command-receipts/{original['operationId']}").json()[
                "response"
            ]
            == original
        )
        schema = client.get("/openapi.json").json()
        expected_commands = {
            ("post", "/api/maintenance-issues"): "createMaintenanceIssue",
            ("patch", "/api/maintenance-issues/{issue_id}"): "editMaintenanceIssue",
            (
                "post",
                "/api/maintenance-issues/{issue_id}/reporter/correct",
            ): "correctMaintenanceIssueReporter",
            ("post", "/api/maintenance-issues/{issue_id}/start"): "startMaintenanceIssue",
            (
                "post",
                "/api/maintenance-issues/{issue_id}/return-to-open",
            ): "returnMaintenanceIssueToOpen",
            ("post", "/api/maintenance-issues/{issue_id}/resolve"): "resolveMaintenanceIssue",
            ("post", "/api/maintenance-issues/{issue_id}/cancel"): "cancelMaintenanceIssue",
            ("post", "/api/maintenance-issues/{issue_id}/reopen"): "reopenMaintenanceIssue",
            (
                "post",
                "/api/maintenance-issues/{issue_id}/appointments",
            ): "createMaintenanceAppointment",
            (
                "patch",
                "/api/maintenance-appointments/{appointment_id}",
            ): "editMaintenanceAppointment",
            (
                "post",
                "/api/maintenance-appointments/{appointment_id}/complete",
            ): "completeMaintenanceAppointment",
            (
                "post",
                "/api/maintenance-appointments/{appointment_id}/cancel",
            ): "cancelMaintenanceAppointment",
            (
                "post",
                "/api/maintenance-issues/{issue_id}/cost-contexts",
            ): "createMaintenanceCostContext",
            (
                "post",
                "/api/maintenance-cost-contexts/{context_id}/void",
            ): "voidMaintenanceCostContext",
            ("post", "/api/maintenance-issues/{issue_id}/expense-links"): "linkMaintenanceExpense",
            (
                "post",
                "/api/maintenance-expense-links/{link_id}/archive",
            ): "archiveMaintenanceExpenseLink",
            ("post", "/api/maintenance-issues/{issue_id}/quotes"): "createMaintenanceQuote",
            ("post", "/api/maintenance-quotes/{quote_id}/withdraw"): "withdrawMaintenanceQuote",
            (
                "post",
                "/api/maintenance-issues/{issue_id}/assignments",
            ): "createMaintenanceAssignment",
            (
                "post",
                "/api/maintenance-assignments/{assignment_id}/end",
            ): "endMaintenanceAssignment",
            ("post", "/api/maintenance-issues/{issue_id}/follow-ups"): "createMaintenanceFollowUp",
            (
                "post",
                "/api/maintenance-issues/{issue_id}/work-journal",
            ): "recordMaintenanceWorkJournalEntry",
        }
        actual_commands = {
            (method, path): operation["operationId"]
            for path, operations in schema["paths"].items()
            if path.startswith("/api/maintenance")
            for method, operation in operations.items()
            if method in {"post", "patch"}
        }
        assert actual_commands == expected_commands
        receipt_path = "/api/maintenance-command-receipts/{operation_id}"
        assert schema["paths"][receipt_path]["get"]["operationId"] == "getMaintenanceCommandReceipt"
        command_ids = [*actual_commands.values(), "getMaintenanceCommandReceipt"]
        assert len(command_ids) == len(set(command_ids))
        # FastAPI must receive explicit IDs, so handler renames cannot change clients.
        for route in client.app.routes:
            if getattr(route, "path", None) == receipt_path or (
                getattr(route, "path", "").startswith("/api/maintenance")
                and getattr(route, "methods", set()) & {"POST", "PATCH"}
            ):
                assert route.operation_id in command_ids
        for path, operations in schema["paths"].items():
            if not path.startswith("/api/maintenance"):
                continue
            for method, operation in operations.items():
                if method not in {"post", "patch"}:
                    continue
                ref = operation["requestBody"]["content"]["application/json"]["schema"][
                    "$ref"
                ].split("/")[-1]
                assert {"expectedRevision", "idempotencyKey"} <= set(
                    schema["components"]["schemas"][ref]["required"]
                )
                assert "409" in operation["responses"]
