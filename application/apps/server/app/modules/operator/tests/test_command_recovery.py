"""Lost-response recovery uses real owning-command receipts, never resubmits."""

from unittest.mock import patch
from uuid import uuid4
from dataclasses import replace

import pytest

from app.bootstrap.communication_context import SQLiteCommunicationContextOperations
from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.modules.communications.application.service import (
    CommunicationCommand,
    CommunicationService,
    ParticipantInput,
    command_fingerprint,
)
from app.modules.communications.infrastructure.receipt_reader import (
    SQLiteCommunicationReceiptReader,
)
from app.modules.communications.infrastructure.unit_of_work import SQLiteCommunicationUnitOfWork
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.modules.maintenance.infrastructure.receipt_reader import SQLiteIssueCommandReceiptReader
from app.modules.operator.domain.models import OperatorConflict
from app.modules.operator.tests import test_directories as directory_fixtures
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.portfolio.application.service import PartyCreateCommand
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.tasks.infrastructure.creation_receipt_reader import SQLiteTaskCreationReceiptReader
from app.modules.tasks.application.service import TaskCreateCommand, TaskService
from app.modules.tasks.application.creation import creation_fingerprint
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def directory(tmp_path):
    yield from directory_fixtures.directory.__wrapped__(tmp_path)


@pytest.fixture
def commands(directory):
    workspace, portfolio, _, support, _ = directory
    party = portfolio.create_party(PartyCreateCommand("individual", "Reporter"))
    contexts = SQLiteCommunicationContextOperations(
        SQLiteTaskTransactionOperations(), SQLiteIntakeSourceReader()
    )
    support.unit_of_work.references = OperatorRecoveryReferences(
        RecoverySourcePorts(
            SQLitePortfolioContextReader(),
            SQLitePartyOperations(workspace.paths.database),
            contexts,
        ),
        SQLiteIssueCommandReceiptReader(),
        SQLiteCommunicationReceiptReader(),
        SQLiteTaskCreationReceiptReader(),
    )
    communications = CommunicationService(
        SQLiteCommunicationUnitOfWork(
            workspace.paths.database, support.unit_of_work.recorder, contexts
        )
    )
    command = CommunicationCommand(
        "inbound",
        "phone",
        "Update",
        "Operator notes",
        "2026-01-01T12:00:00+00:00",
        "UTC",
        (ParticipantInput(party.id, "sender"),),
        record=True,
    )
    saved = support.save_recovery(
        str(uuid4()),
        form_key="communication.record",
        schema_version=1,
        payload={
            "subject": command.subject,
            "participants": [{"partyId": party.id, "role": "sender"}],
        },
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key = str(uuid4())
    attempt = support.prepare_attempt(
        saved["id"],
        attempt_key=key,
        request_fingerprint=command_fingerprint("created", None, command, 0),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    yield support, communications, command, key, attempt
    communications.unit_of_work.engine.dispose()


def test_lost_response_resolves_real_receipt_without_another_domain_write(commands):
    support, communications, command, key, attempt = commands
    with pytest.raises(OperatorConflict, match="still unknown"):
        support.reconcile_recovery(attempt["id"], expected_revision=2, idempotency_key=str(uuid4()))
    with pytest.raises(OperatorConflict, match="cannot be discarded"):
        support.discard_recovery(attempt["id"], expected_revision=2, idempotency_key=str(uuid4()))
    committed = communications.create(command, key, expected_revision=0)
    operation_key = str(uuid4())
    with patch.object(communications, "create", side_effect=AssertionError("Resubmitted command")):
        result = support.reconcile_recovery(
            attempt["id"], expected_revision=2, idempotency_key=operation_key
        )
        assert result == support.reconcile_recovery(
            attempt["id"], expected_revision=2, idempotency_key=operation_key
        )
    assert result["receipt"]["sourceId"] == committed["id"]
    assert result["receipt"]["attemptKey"] == key
    assert communications.create(command, key, expected_revision=0)["id"] == committed["id"]


def test_audit_failure_rolls_back_reconciliation_but_not_committed_domain_command(commands):
    support, communications, command, key, attempt = commands
    committed = communications.create(command, key, expected_revision=0)
    operation_key = str(uuid4())
    with (
        patch.object(
            support.unit_of_work.recorder,
            "record_change",
            side_effect=RuntimeError("Audit unavailable"),
        ),
        pytest.raises(RuntimeError),
    ):
        support.reconcile_recovery(
            attempt["id"], expected_revision=2, idempotency_key=operation_key
        )
    assert support.recovery(attempt["id"])["status"] == "outcome_unknown"
    assert support.recovery(attempt["id"])["revision"] == attempt["revision"]
    assert support.unit_of_work.read(lambda tx: tx.operation(operation_key)) is None
    assert communications.get(committed["id"])["status"] == "recorded"
    result = support.reconcile_recovery(
        attempt["id"], expected_revision=2, idempotency_key=operation_key
    )
    assert result["receipt"]["sourceId"] == committed["id"]


def test_receipt_with_different_semantic_payload_is_not_reconciled(commands):
    support, communications, command, key, attempt = commands
    communications.create(replace(command, subject="Changed submission"), key, expected_revision=0)
    with pytest.raises(OperatorConflict, match="different request"):
        support.reconcile_recovery(attempt["id"], expected_revision=2, idempotency_key=str(uuid4()))
    assert support.recovery(attempt["id"])["status"] == "outcome_unknown"


def test_task_attempt_resolves_real_creation_receipt_without_redispatch(commands, directory):
    support, _, _, _, _ = commands
    workspace, _, _, _, _ = directory
    tasks = TaskService(
        SQLiteTaskUnitOfWork(workspace.paths.database, support.unit_of_work.recorder)
    )
    key = str(uuid4())
    command = TaskCreateCommand.from_mapping({"title": "Call owner"})
    try:
        saved = support.save_recovery(
            str(uuid4()),
            form_key="task.create",
            schema_version=1,
            payload={"title": command.title},
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        attempt = support.prepare_attempt(
            saved["id"],
            attempt_key=key,
            request_fingerprint=creation_fingerprint(command),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
        with pytest.raises(OperatorConflict, match="still unknown"):
            support.reconcile_recovery(
                attempt["id"], expected_revision=2, idempotency_key=str(uuid4())
            )
        result = tasks.create_command(command, expected_revision=0, idempotency_key=key)
        with patch.object(tasks, "create_command", side_effect=AssertionError("Redispatch")):
            reconciled = support.reconcile_recovery(
                attempt["id"], expected_revision=2, idempotency_key=str(uuid4())
            )
        assert reconciled["receipt"] == {
            "sourceKind": "task",
            "sourceId": result["id"],
            "receiptId": result["operationId"],
            "attemptKey": key,
        }
        validate_latest_schema(workspace.paths.database)
    finally:
        tasks.unit_of_work.engine.dispose()


def test_task_attempt_rejects_mismatched_receipt(commands, directory):
    support, _, _, _, _ = commands
    workspace, _, _, _, _ = directory
    tasks = TaskService(
        SQLiteTaskUnitOfWork(workspace.paths.database, support.unit_of_work.recorder)
    )
    key = str(uuid4())
    try:
        saved = support.save_recovery(
            str(uuid4()),
            form_key="task.create",
            schema_version=1,
            payload={"title": "Original"},
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        attempt = support.prepare_attempt(
            saved["id"],
            attempt_key=key,
            request_fingerprint=creation_fingerprint(
                TaskCreateCommand.from_mapping({"title": "Original"})
            ),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
        tasks.create_command({"title": "Changed"}, expected_revision=0, idempotency_key=key)
        with pytest.raises(OperatorConflict, match="different request"):
            support.reconcile_recovery(
                attempt["id"], expected_revision=2, idempotency_key=str(uuid4())
            )
        assert support.recovery(attempt["id"])["status"] == "outcome_unknown"
    finally:
        tasks.unit_of_work.engine.dispose()
