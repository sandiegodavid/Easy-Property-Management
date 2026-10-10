"""Slice 34: real Inspection commands and original OPS outcomes."""

import hashlib
import sqlite3
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.inspections.api.router import build_router as inspection_router
from app.modules.inspections.infrastructure.recovery_reader import SQLiteInspectionRecoveryReader
from app.modules.inspections.tests import test_workflow as inspection_fixtures
from app.modules.inspections.tests.commands import inspection_command
from app.modules.operator.api.router import build_router
from app.modules.operator.application.inspection_forms import (
    INSPECTION_SCHEMAS,
    inspection_source_kind,
)
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError


@pytest.fixture
def ready():
    fixture = inspection_fixtures.InspectionWorkflowTests()
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
        fixture.recorder,
        references,
        SQLiteAuditReadMarker(),
    )
    ops = OperatorService(
        uow,
        runtime=lambda: RuntimeIdentity(
            "ready",
            fixture.workspace.open().workspace_id,
            str(uuid4()),
            True,
        ),
    )
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(ops))
    app.include_router(
        inspection_router(
            fixture.inspections,
            SimpleNamespace(require_ready=lambda **kwargs: None),
        )
    )
    try:
        with TestClient(app) as client:
            yield fixture, ops, client
    finally:
        uow.engine.dispose()
        fixture.doCleanups()


def begin(ops, form, values, source=None):
    record, key = str(uuid4()), str(uuid4())
    ops.save_recovery(
        record,
        form_key=form,
        schema_version=1,
        payload=values,
        expected_revision=0,
        idempotency_key=str(uuid4()),
        source_kind=inspection_source_kind(form),
        source_id=source,
        base_source_revision=str(values["expectedRevision"]) if source else None,
    )
    ops.prepare_attempt(record, attempt_key=key, expected_revision=1, idempotency_key=str(uuid4()))
    return record, key


def resolved(ops, record):
    return ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))


def run(ready, form, method, path, values, source=None):
    fixture, ops, client = ready
    record, key = begin(ops, form, values, source)
    pending = client.post(
        f"/api/operator/recovery/{record}/reconcile",
        json={"expectedRevision": 2, "idempotencyKey": str(uuid4())},
    )
    assert pending.status_code == 409
    response = client.request(method, path, json=values | {"idempotencyKey": key})
    assert response.status_code in {200, 201}, response.text
    original = response.json()
    recovery = resolved(ops, record)
    receipt = recovery["receipt"]
    assert receipt["receiptId"] == original["operationId"]
    assert receipt["result"]["revision"] == original["revision"]
    assert receipt["result"]["targetId"] == original.get("id", source)
    retry = client.request(method, path, json=values | {"idempotencyKey": key})
    assert retry.json() == original
    return original, record


def checklist():
    return [
        {
            "displayName": " Kitchen ",
            "observations": [
                {
                    "itemName": " Floor ",
                    "conditionState": "good",
                    "isCompleted": True,
                }
            ],
        }
    ]


def create_values(revision=0):
    return {
        "expectedRevision": revision,
        "reportKind": "pre_move_in",
        "walkthroughOn": date.today().isoformat(),
        "conductedBy": " Local  operator ",
        "areas": checklist(),
    }


def test_real_report_template_child_and_evidence_recovery(ready):
    fixture, ops, client = ready
    template, _ = run(
        ready,
        "inspection.template.create",
        "POST",
        "/api/condition-checklist-templates",
        {"expectedRevision": 0, "displayName": " Checklist ", "areas": checklist()},
    )
    run(
        ready,
        "inspection.template.patch",
        "PATCH",
        f"/api/condition-checklist-templates/{template['id']}",
        {"expectedRevision": 1, "notes": None},
        template["id"],
    )
    lease_id = fixture.lease["id"]
    report, create_record = run(
        ready,
        "inspection.report.create",
        "POST",
        f"/api/leases/{lease_id}/condition-reports",
        create_values(),
        lease_id,
    )
    report_id = report["id"]
    report, _ = run(
        ready,
        "inspection.report.patch",
        "PATCH",
        f"/api/condition-reports/{report_id}",
        {"expectedRevision": 1, "generalNotes": None},
        report_id,
    )
    report, _ = run(
        ready,
        "inspection.report.areas.replace",
        "PUT",
        f"/api/condition-reports/{report_id}/areas",
        {"expectedRevision": 2, "areas": checklist()},
        report_id,
    )
    acknowledgments = {
        item["leaseParticipantId"]: {"status": "acknowledged"} for item in report["acknowledgments"]
    }
    report, _ = run(
        ready,
        "inspection.report.acknowledge",
        "PUT",
        f"/api/condition-reports/{report_id}/acknowledgments",
        {"expectedRevision": 3, "acknowledgments": acknowledgments},
        report_id,
    )
    observation = report["areas"][0]["observations"][0]["id"]
    values = {
        "expectedRevision": 4,
        "originalName": "cafe\u0301.txt",
        "mediaType": "text/plain",
        "contentSha256": hashlib.sha256(b"Evidence").hexdigest(),
        "sizeBytes": 8,
        "purpose": "supporting_document",
    }
    record, key = begin(ops, "inspection.evidence.attach", values, observation)
    response = client.post(
        f"/api/condition-observations/{observation}/evidence",
        data={"expected_revision": 4, "idempotency_key": key, "purpose": "supporting_document"},
        files={"file": ("cafe\u0301.txt", b"Evidence", "text/plain")},
    )
    assert response.status_code == 201, response.text
    receipt = resolved(ops, record)["receipt"]
    assert receipt["result"]["targetId"] == response.json()["id"]
    report, _ = run(
        ready,
        "inspection.report.finalize",
        "POST",
        f"/api/condition-reports/{report_id}/finalize",
        {"expectedRevision": 5, "confirmed": True},
        report_id,
    )
    correction, _ = run(
        ready,
        "inspection.report.correct",
        "POST",
        f"/api/condition-reports/{report_id}/corrections",
        create_values(6) | {"correctionReason": "Correct the checklist"},
        report_id,
    )
    inspection_command(
        fixture.inspections, "acknowledge", correction["id"], fixture._acknowledge_all(correction)
    )
    inspection_command(fixture.inspections, "finalize", correction["id"], confirmed=True)
    original_receipt = ops.recovery(create_record)["receipt"]
    assert original_receipt["result"]["status"] == "draft"
    assert original_receipt["result"]["revision"] == 1
    validate_latest_schema(fixture.workspace.paths.database)


def test_comparison_original_recovery_after_replacement(ready):
    fixture, ops, client = ready
    pre = fixture._finalize_pre()
    post = fixture._terminate_and_create_post_report()
    inspection_command(
        fixture.inspections, "acknowledge", post["id"], fixture._acknowledge_all(post)
    )
    post = inspection_command(fixture.inspections, "finalize", post["id"], confirmed=True)
    values = {
        "expectedRevision": post["revision"],
        "comparisons": [
            {
                "preObservationId": pre["areas"][0]["observations"][0]["id"],
                "postObservationId": post["areas"][0]["observations"][0]["id"],
                "comparisonState": "unchanged",
            }
        ],
    }
    result, record = run(
        ready,
        "inspection.comparison.review",
        "PUT",
        f"/api/leases/{fixture.lease['id']}/condition-comparison",
        values,
        fixture.lease["id"],
    )
    inspection_command(fixture.inspections, "save_comparisons", fixture.lease["id"], [])
    assert ops.recovery(record)["receipt"]["result"]["revision"] == result["revision"]
    validate_latest_schema(fixture.workspace.paths.database)


@pytest.mark.parametrize("form", tuple(INSPECTION_SCHEMAS))
def test_incomplete_forms_and_forbidden_fields(form):
    model = INSPECTION_SCHEMAS[form]
    assert model.model_validate({}).model_dump(exclude_unset=True) == {}
    for values in (
        {"expectedRevision": True},
        {"expectedRevision": -1},
        {"path": "/secret"},
        {"bytes": "content"},
    ):
        with pytest.raises(ValueError):
            model.model_validate(values)


def test_outcome_single_query_and_encrypted_portability(ready):
    fixture, ops, client = ready
    result, record = run(
        ready,
        "inspection.report.create",
        "POST",
        f"/api/leases/{fixture.lease['id']}/condition-reports",
        create_values(),
        fixture.lease["id"],
    )
    database = fixture.workspace.paths.database
    with sqlite3.connect(database) as connection:
        key = connection.execute(
            "SELECT idempotency_key FROM inspection_command_operations WHERE id = ?",
            (result["operationId"],),
        ).fetchone()[0]
        before = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "inspection_command_operations",
                "operator_recovery_records",
                "operator_operations",
            )
        }
    engine = fixture.inspections.unit_of_work.engine
    statements = []

    def track(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with engine.connect() as connection:
        event.listen(engine, "before_cursor_execute", track)
        try:
            with patch.object(engine, "connect", side_effect=AssertionError("nested connection")):
                outcome = SQLiteInspectionRecoveryReader("inspection_lease").outcome(
                    connection, key, family="inspection"
                )
        finally:
            event.remove(engine, "before_cursor_execute", track)
    assert len(statements) == 1
    assert outcome.result.revision == 1
    destination = fixture.workspace.paths.root.parent / "restored"
    with fast_backup_encryption():
        archive = fixture.backups.create_backup("a sufficiently long passphrase")
        fixture.backups.restore(archive.archive_path, "a sufficiently long passphrase", destination)
    restored = destination / "database/property-management.sqlite"
    validate_latest_schema(restored)
    with sqlite3.connect(restored) as connection:
        for table, rows in before.items():
            assert connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() == rows


def test_deterministic_no_workspace_openapi():
    first, second = FastAPI(), FastAPI()
    first.include_router(build_router(None))
    second.include_router(build_router(None))
    assert first.openapi() == second.openapi()
    assert set(INSPECTION_SCHEMAS) <= set(compose_recovery_bindings())


@pytest.mark.parametrize(
    "form,values",
    [
        ("inspection.evidence.attach", {"sizeBytes": 50 * 1024 * 1024 + 1}),
        ("inspection.evidence.attach", {"contentSha256": "A" * 64}),
        ("inspection.report.areas.replace", {"areas": [{"displayName": "Area"}] * 101}),
        (
            "inspection.report.acknowledge",
            {
                "acknowledgments": {
                    f"00000000-0000-0000-0000-{index:012d}": {"status": "pending"}
                    for index in range(101)
                }
            },
        ),
        ("inspection.comparison.review", {"comparisons": [{"comparisonState": "unchanged"}] * 101}),
    ],
)
def test_explicit_form_bounds(form, values):
    with pytest.raises(ValueError):
        INSPECTION_SCHEMAS[form].model_validate(values)


def test_stale_scope_and_draft_only_gates(ready):
    fixture, ops, client = ready
    report, _ = run(
        ready,
        "inspection.report.create",
        "POST",
        f"/api/leases/{fixture.lease['id']}/condition-reports",
        create_values(),
        fixture.lease["id"],
    )
    record, key = begin(ops, "inspection.report.patch", {"expectedRevision": 1}, report["id"])
    inspection_command(fixture.inspections, "patch_report", report["id"], conducted_by="Changed")
    assert ops.recovery(record)["reuseState"] == "outcome_unknown"
    with pytest.raises(OperatorConflict):
        begin(ops, "inspection.report.patch", {"expectedRevision": 1}, report["id"])
    inspection_command(
        fixture.inspections, "acknowledge", report["id"], fixture._acknowledge_all(report)
    )
    final = inspection_command(fixture.inspections, "finalize", report["id"], confirmed=True)
    with pytest.raises(OperatorConflict):
        begin(ops, "inspection.report.patch", {"expectedRevision": final["revision"]}, report["id"])
    with pytest.raises(OperatorConflict):
        begin(
            ops,
            "inspection.evidence.attach",
            {"expectedRevision": final["revision"]},
            report["areas"][0]["observations"][0]["id"],
        )


def test_changed_receipt_and_failed_attachment_leave_attempt_unknown(ready):
    fixture, ops, client = ready
    values = create_values()
    record, key = begin(ops, "inspection.report.create", values, fixture.lease["id"])
    response = client.post(
        f"/api/leases/{fixture.lease['id']}/condition-reports",
        json=values | {"conductedBy": "Different", "idempotencyKey": key},
    )
    assert response.status_code == 201
    with pytest.raises(OperatorConflict):
        resolved(ops, record)
    assert ops.recovery(record)["status"] == "outcome_unknown"
    report = response.json()
    observation = report["areas"][0]["observations"][0]["id"]
    values = {
        "expectedRevision": 1,
        "originalName": "evidence.txt",
        "mediaType": "text/plain",
        "contentSha256": hashlib.sha256(b"Evidence").hexdigest(),
        "sizeBytes": 8,
        "purpose": "supporting_document",
    }
    record, key = begin(ops, "inspection.evidence.attach", values, observation)
    with patch.object(
        fixture.recorder, "record_change", side_effect=RuntimeError("audit unavailable")
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            client.post(
                f"/api/condition-observations/{observation}/evidence",
                data={
                    "expected_revision": 1,
                    "idempotency_key": key,
                    "purpose": "supporting_document",
                },
                files={"file": ("evidence.txt", b"Evidence", "text/plain")},
            )
    with sqlite3.connect(fixture.workspace.paths.database) as connection:
        assert connection.execute("SELECT count(*) FROM file_records").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM inspection_command_operations WHERE idempotency_key = ?",
                (key,),
            ).fetchone()[0]
            == 0
        )
    assert not list((fixture.workspace.paths.files / "managed").glob("*"))
    with pytest.raises(OperatorConflict):
        resolved(ops, record)


def test_incomplete_prepare_and_tampered_fingerprint_rejected(ready):
    fixture, ops, client = ready
    record = str(uuid4())
    ops.save_recovery(
        record,
        form_key="inspection.template.create",
        schema_version=1,
        payload={},
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(OperatorError):
        ops.prepare_attempt(
            record, attempt_key=str(uuid4()), expected_revision=1, idempotency_key=str(uuid4())
        )
    result, record = run(
        ready,
        "inspection.report.create",
        "POST",
        f"/api/leases/{fixture.lease['id']}/condition-reports",
        create_values(),
        fixture.lease["id"],
    )
    with sqlite3.connect(fixture.workspace.paths.database) as connection:
        connection.execute(
            "UPDATE operator_recovery_records SET request_fingerprint = ? WHERE id = ?",
            ("a" * 64, record),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(fixture.workspace.paths.database)


def test_attachment_commit_failure_retry_and_no_republication(ready):
    fixture, ops, client = ready
    report, _ = run(
        ready,
        "inspection.report.create",
        "POST",
        f"/api/leases/{fixture.lease['id']}/condition-reports",
        create_values(),
        fixture.lease["id"],
    )
    observation = report["areas"][0]["observations"][0]["id"]
    values = {
        "expectedRevision": 1,
        "originalName": "evidence.txt",
        "mediaType": "text/plain",
        "contentSha256": hashlib.sha256(b"Evidence").hexdigest(),
        "sizeBytes": 8,
        "purpose": "supporting_document",
    }
    record, key = begin(ops, "inspection.evidence.attach", values, observation)
    engine = fixture.inspections.unit_of_work.engine

    def fail_commit(connection):
        raise RuntimeError("database commit unavailable")

    def attach():
        return client.post(
            f"/api/condition-observations/{observation}/evidence",
            data={"expected_revision": 1, "idempotency_key": key, "purpose": "supporting_document"},
            files={"file": ("evidence.txt", b"Evidence", "text/plain")},
        )

    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="database commit unavailable"):
            attach()
    finally:
        event.remove(engine, "commit", fail_commit)
    assert not list((fixture.workspace.paths.files / "managed").glob("*"))
    with pytest.raises(OperatorConflict):
        resolved(ops, record)
    original = attach()
    assert original.status_code == 201, original.text
    with patch.object(
        fixture.files.content_store, "store", side_effect=AssertionError("republished")
    ):
        assert attach().json() == original.json()
    recovered = client.post(
        f"/api/operator/recovery/{record}/reconcile",
        json={"expectedRevision": 2, "idempotencyKey": str(uuid4())},
    )
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()["receipt"]["result"]
    assert result["fileId"] == original.json()["id"]
    assert result["linkId"] == original.json()["links"][0]["id"]
    assert result["revision"] == 2
