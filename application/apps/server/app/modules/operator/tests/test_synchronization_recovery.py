"""Slice 31B: generated Finance results recover without repeating synchronization."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery import synchronization_term_state
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.domain.models import FinanceConflictError, SynchronizeExpectationsCommand
from app.modules.finance.tests import test_finance as finance_fixtures
from app.modules.operator.api.router import build_router
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.product_migrations import validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine

FORM = "finance.rent_expectation.synchronize"


@pytest.fixture
def ready():
    fixture = finance_fixtures.FinanceWorkflowTests()
    fixture.setUp()
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_recovery_bindings(),
    )
    uow = SQLiteOperatorUnitOfWork(
        fixture.workspace.paths.database,
        fixture.finance.unit_of_work.recorder,
        references,
        SQLiteAuditReadMarker(),
    )
    identity = RuntimeIdentity("ready", fixture.workspace.open().workspace_id, str(uuid4()), True)
    support = OperatorService(uow, runtime=lambda: identity)
    instant = datetime.now(UTC)
    command = SynchronizeExpectationsCommand(
        fixture.lease["terms"][0]["id"],
        (instant.date() + timedelta(days=60)).isoformat(),
        instant.date().replace(day=1).isoformat(),
    )
    try:
        yield fixture, support, command
    finally:
        uow.engine.dispose()
        fixture.doCleanups()


def save_and_prepare(client, lease_id, command, revision, *, save_status=200):
    record_id, key = str(uuid4()), str(uuid4())
    payload = {
        "expectedRevision": revision,
        "leaseTermId": command.lease_term_id,
        "throughOn": command.through_on,
        "scheduleAnchorOn": command.schedule_anchor_on,
    }
    saved = client.put(
        "/api/operator/recovery/" + record_id,
        json={
            "formKey": FORM,
            "schemaVersion": 1,
            "payload": payload,
            "sourceKind": "lease",
            "sourceId": lease_id,
            "baseSourceRevision": str(revision),
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        },
    )
    assert saved.status_code == save_status, saved.text
    if save_status != 200:
        return record_id, key, None, saved
    request = {"attemptKey": key, "expectedRevision": 1, "idempotencyKey": str(uuid4())}
    attempt = client.post("/api/operator/recovery/" + record_id + "/attempt", json=request)
    return record_id, key, request, attempt


def client_for(support):
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(support))
    return TestClient(app)


@pytest.mark.parametrize("noop", [False, True])
def test_generated_and_empty_results_recover_original_receipt_and_survive_backup(ready, noop):
    fixture, support, command = ready
    lease_id = fixture.lease["id"]
    revision = 0
    if noop:
        fixture.finance.synchronize(
            lease_id, command, expected_revision=0, idempotency_key=str(uuid4())
        )
        revision = 1
    with client_for(support) as client:
        forms = client.get("/api/operator/recovery-forms").json()
        assert any(item["formKey"] == FORM for item in forms)
        record_id, key, request, attempt = save_and_prepare(client, lease_id, command, revision)
        assert attempt.status_code == 200, attempt.text
        assert (
            client.post("/api/operator/recovery/" + record_id + "/attempt", json=request).json()
            == attempt.json()
        )
        original = fixture.finance.synchronize(
            lease_id, command, expected_revision=revision, idempotency_key=key
        )
        assert bool(original["items"]) is not noop
        assert original["rentLedgerRevision"] == revision + int(not noop)
        fixture.finance.synchronize(
            lease_id,
            replace(
                command, through_on=(datetime.now(UTC).date() + timedelta(days=120)).isoformat()
            ),
            expected_revision=original["rentLedgerRevision"],
            idempotency_key=str(uuid4()),
        )
        with patch(
            "app.modules.finance.application.service._schedule",
            side_effect=AssertionError("Replay generated rows"),
        ):
            assert (
                fixture.finance.synchronize(
                    lease_id, command, expected_revision=revision, idempotency_key=key
                )
                == original
            )
        binding = support.unit_of_work.references.commands[FORM]
        statements = []
        with support.unit_of_work.engine.begin() as connection:
            event.listen(
                connection, "before_cursor_execute", lambda *args: statements.append(args[2])
            )
            with patch(
                "sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Nested connection")
            ):
                outcome = binding.reader.outcome(connection, key, family="finance")
        assert len(statements) == 1
        assert outcome.request_fingerprint == attempt.json()["requestFingerprint"]
        assert outcome.result.target_id == lease_id
        assert outcome.result.revision == original["rentLedgerRevision"]
        expected_receipt = {
            "sourceKind": "lease",
            "sourceId": lease_id,
            "receiptId": original["operationId"],
            "attemptKey": key,
            "result": {
                "targetId": lease_id,
                "revision": original["rentLedgerRevision"],
                "status": None,
                "operationId": original["operationId"],
            },
        }
        reconciliation = {"expectedRevision": 2, "idempotencyKey": str(uuid4())}
        response = client.post(
            "/api/operator/recovery/" + record_id + "/reconcile", json=reconciliation
        )
        assert response.status_code == 200, response.text
        assert response.json()["receipt"] == expected_receipt
        assert (
            client.post(
                "/api/operator/recovery/" + record_id + "/reconcile", json=reconciliation
            ).json()
            == response.json()
        )
    validate_latest_schema(fixture.workspace.paths.database)
    with fast_backup_encryption():

        def repository(database):
            return AuditRecorder(SQLiteAuditRepository(database))

        backup = BackupService(
            fixture.workspace, repository(fixture.workspace.paths.database), repository
        )
        archive = backup.create_backup(
            "a sufficiently long backup passphrase",
            output_path=Path(fixture.temp.name) / "sync.epm-backup",
        )
        target = Path(fixture.temp.name) / "restored-sync"
        backup.restore(archive.archive_path, "a sufficiently long backup passphrase", target)
    database = target / "database" / "property-management.sqlite"
    validate_latest_schema(database)
    restored = create_sqlite_engine(database)
    try:
        with support.unit_of_work.engine.connect() as source, restored.connect() as destination:
            for table in (
                "rent_expectations",
                "finance_command_operations",
                "finance_command_revisions",
                "operator_recovery_records",
                "operator_operations",
            ):
                assert (
                    source.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                    == destination.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                )
            audit_query = (
                "SELECT * FROM audit_events WHERE entity_type IN "
                "('rent_expectation', 'finance_command_scope', 'finance_command_operation', "
                "'operator_recovery', 'operator_operation') ORDER BY id"
            )
            assert (
                source.exec_driver_sql(audit_query).all()
                == destination.exec_driver_sql(audit_query).all()
            )
            assert binding.reader.outcome(destination, key, family="finance") == outcome
    finally:
        restored.dispose()


def test_missing_term_and_stale_ledger_prevent_attempts(ready):
    fixture, support, command = ready
    with client_for(support) as client:
        _, _, _, missing = save_and_prepare(
            client,
            fixture.lease["id"],
            replace(command, lease_term_id=str(uuid4())),
            0,
            save_status=409,
        )
        assert missing.status_code == 409
        fixture.finance.synchronize(
            fixture.lease["id"], command, expected_revision=0, idempotency_key=str(uuid4())
        )
        _, _, _, stale = save_and_prepare(client, fixture.lease["id"], command, 0, save_status=409)
        assert stale.status_code == 409
    assert fixture.finance.rent_ledger_revision(fixture.lease["id"])["rentLedgerRevision"] == 1
    with support.unit_of_work.engine.connect() as connection:
        assert (
            synchronization_term_state(
                connection,
                support.unit_of_work.references.commands[FORM].reader,
                str(uuid4()),
                {"leaseTermId": command.lease_term_id},
            )
            == "source_unavailable"
        )


def test_synchronization_openapi_has_stable_operations_and_typed_lease_source():
    with client_for(object()) as client:
        first = client.get("/openapi.json").json()
        assert client.get("/openapi.json").json() == first
    schemas = first["components"]["schemas"]
    assert "lease" in schemas["RecoveryInput"]["properties"]["sourceKind"]["anyOf"][0]["enum"]
    assert FORM in schemas["RecoveryInput"]["properties"]["formKey"]["enum"]
    paths = first["paths"]
    assert (
        paths["/api/operator/recovery/{record_id}"]["put"]["operationId"] == "saveOperatorRecovery"
    )
    assert (
        paths["/api/operator/recovery/{record_id}/attempt"]["post"]["operationId"]
        == "prepareOperatorRecoveryAttempt"
    )
    assert (
        paths["/api/operator/recovery/{record_id}/reconcile"]["post"]["operationId"]
        == "reconcileOperatorRecovery"
    )


def test_synchronization_rolls_back_generated_rows_receipt_and_audit(ready):
    fixture, support, command = ready
    with client_for(support) as client:
        _, key, _, attempt = save_and_prepare(client, fixture.lease["id"], command, 0)
        assert attempt.status_code == 200, attempt.text
    engine = fixture.finance.unit_of_work.engine
    tables = (
        "rent_expectations",
        "finance_command_operations",
        "finance_command_revisions",
        "audit_events",
    )
    with engine.connect() as connection:
        before = {
            table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
            for table in tables
        }
    with patch.object(
        fixture.finance.unit_of_work.recorder,
        "record_change",
        side_effect=RuntimeError("Audit failure"),
    ):
        with pytest.raises(RuntimeError, match="Audit failure"):
            fixture.finance.synchronize(
                fixture.lease["id"], command, expected_revision=0, idempotency_key=key
            )
    with engine.connect() as connection:
        assert before == {
            table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
            for table in tables
        }
    original = fixture.finance.synchronize(
        fixture.lease["id"], command, expected_revision=0, idempotency_key=key
    )
    with pytest.raises(FinanceConflictError):
        fixture.finance.synchronize(
            fixture.lease["id"],
            replace(
                command, through_on=(datetime.now(UTC).date() + timedelta(days=90)).isoformat()
            ),
            expected_revision=0,
            idempotency_key=key,
        )
    assert fixture.finance.command_operation(key)["result"] == original
    validate_latest_schema(fixture.workspace.paths.database)
