"""Real SQLite proof for Inspection's lease-scoped command recovery boundary."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.modules.inspections.api.router import build_router
from app.modules.inspections.application.commands import (
    InspectionError,
    InspectionConflictError,
    InspectionRevisionConflict,
)
from app.modules.inspections.tests import test_workflow
from app.platform.api_errors import register_api_error_handlers
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def workflow():
    fixture = test_workflow.InspectionWorkflowTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.tearDown()


def create_request(workflow, **changes):
    return {
        "expected_revision": 0,
        "idempotency_key": str(uuid4()),
        "report_kind": "pre_move_in",
        "walkthrough_on": date.today().isoformat(),
        "conducted_by": "Operator",
        "areas": workflow.checklist,
    } | changes


def test_create_patch_original_replay_and_bounded_lookup(workflow):
    service = workflow.inspections
    request = create_request(workflow)
    first = service.create(workflow.lease["id"], **request)
    patched = service.patch_report(
        first["id"],
        expected_revision=1,
        idempotency_key=str(uuid4()),
        conducted_by="Updated operator",
    )
    assert patched["revision"] == 2
    assert service.create(workflow.lease["id"], **request) == first
    assert service.get(first["id"])["conductedBy"] == "Updated operator"
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert service.recover_command(operation_id=first["operationId"]) == first
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    with pytest.raises(InspectionConflictError):
        service.create(workflow.lease["id"], **(request | {"conducted_by": "Changed"}))
    with pytest.raises(InspectionRevisionConflict) as conflict:
        service.patch_report(
            first["id"], expected_revision=1, idempotency_key=str(uuid4()), conducted_by="Stale"
        )
    assert conflict.value.current["report"]["conductedBy"] == "Updated operator"
    assert conflict.value.current["revision"] == 2


@pytest.mark.parametrize(
    "revision,key",
    [
        pytest.param(True, "00000000-0000-4000-8000-000000000001", id="boolean-revision"),
        pytest.param(-1, "00000000-0000-4000-8000-000000000002", id="negative-revision"),
        pytest.param("0", "00000000-0000-4000-8000-000000000003", id="string-revision"),
        pytest.param(0, "not-a-key", id="invalid-key"),
    ],
)
def test_direct_call_validation(workflow, revision, key):
    with pytest.raises(InspectionError):
        workflow.inspections.create(
            workflow.lease["id"],
            **create_request(workflow, expected_revision=revision, idempotency_key=key),
        )
    assert workflow.inspections.unit_of_work.command_revision("lease", workflow.lease["id"]) == 0


def test_concurrent_duplicate_has_one_result_and_one_revision(workflow):
    request = create_request(workflow)
    barrier = Barrier(2)

    def submit():
        barrier.wait()
        return workflow.inspections.create(workflow.lease["id"], **request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0] == results[1]
    assert workflow.inspections.unit_of_work.command_revision("lease", workflow.lease["id"]) == 1
    assert len(workflow.inspections.list_for_lease(workflow.lease["id"])["reports"]) == 1


def test_templates_are_independent_and_retry_original_result(workflow):
    service = workflow.inspections
    key = str(uuid4())
    first = service.create_template(
        expected_revision=0, idempotency_key=key, display_name="Original"
    )
    second = service.patch_template(
        first["id"], expected_revision=1, idempotency_key=str(uuid4()), display_name="Edited"
    )
    assert second["revision"] == 2
    assert (
        service.create_template(expected_revision=0, idempotency_key=key, display_name="Original")
        == first
    )
    assert service.unit_of_work.command_revision("lease", workflow.lease["id"]) == 0


def test_noop_and_checklist_replacement_have_immutable_receipts(workflow):
    service = workflow.inspections
    first = service.create(workflow.lease["id"], **create_request(workflow))
    key = str(uuid4())
    noop = service.patch_report(first["id"], expected_revision=1, idempotency_key=key)
    assert noop["updatedAt"] == first["updatedAt"]
    assert noop["revision"] == 2
    replaced = service.replace_areas(
        first["id"], workflow.checklist, expected_revision=2, idempotency_key=str(uuid4())
    )
    assert replaced["revision"] == 3
    assert replaced["areas"][0]["id"] != first["areas"][0]["id"]
    assert service.patch_report(first["id"], expected_revision=1, idempotency_key=key) == noop
    with pytest.raises(InspectionRevisionConflict):
        service.acknowledge(first["id"], {}, expected_revision=2, idempotency_key=str(uuid4()))
    validate_latest_schema(workflow.workspace.paths.database)


def test_finalization_replay_after_supersession_and_comparison_replay(workflow):
    service = workflow.inspections
    first = service.create(workflow.lease["id"], **create_request(workflow))
    ack = service.acknowledge(
        first["id"],
        workflow._acknowledge_all(first),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    key = str(uuid4())
    final = service.finalize(
        first["id"], expected_revision=ack["revision"], idempotency_key=key, confirmed=True
    )
    post = workflow._terminate_and_create_post_report()
    ack = service.acknowledge(
        post["id"],
        workflow._acknowledge_all(post),
        expected_revision=post["revision"],
        idempotency_key=str(uuid4()),
    )
    post = service.finalize(
        post["id"], expected_revision=ack["revision"], idempotency_key=str(uuid4()), confirmed=True
    )
    comparison_key = str(uuid4())
    values = [
        {
            "pre_observation_id": final["areas"][0]["observations"][0]["id"],
            "post_observation_id": post["areas"][0]["observations"][0]["id"],
            "comparison_state": "unchanged",
        }
    ]
    reviewed = service.save_comparisons(
        workflow.lease["id"],
        values,
        expected_revision=post["revision"],
        idempotency_key=comparison_key,
    )
    correction = service.create(
        workflow.lease["id"],
        **create_request(
            workflow,
            expected_revision=reviewed["revision"],
            correction_of=first["id"],
            correction_reason="Corrected evidence",
        ),
    )
    ack = service.acknowledge(
        correction["id"],
        workflow._acknowledge_all(correction),
        expected_revision=correction["revision"],
        idempotency_key=str(uuid4()),
    )
    service.finalize(
        correction["id"],
        expected_revision=ack["revision"],
        idempotency_key=str(uuid4()),
        confirmed=True,
    )
    assert service.get(first["id"])["status"] == "superseded"
    assert (
        service.finalize(first["id"], expected_revision=2, idempotency_key=key, confirmed=True)
        == final
    )
    assert (
        service.save_comparisons(
            workflow.lease["id"],
            values,
            expected_revision=post["revision"],
            idempotency_key=comparison_key,
        )
        == reviewed
    )
    validate_latest_schema(workflow.workspace.paths.database)


def test_attachment_replay_and_transaction_failure_roll_back_publication(workflow):
    service = workflow.inspections
    report = service.create(workflow.lease["id"], **create_request(workflow))
    observation = report["areas"][0]["observations"][0]["id"]
    source = workflow.workspace.paths.files.parent / "evidence.txt"
    source.write_bytes(b"Inspection evidence")
    kwargs = {"expected_revision": 1, "idempotency_key": str(uuid4())}
    original_record = workflow.recorder.record_change

    def fail_receipt(*args, **changes):
        if changes["entity_type"] == "inspection_command_operation":
            raise RuntimeError("receipt audit failed")
        return original_record(*args, **changes)

    with patch.object(workflow.recorder, "record_change", side_effect=fail_receipt):
        with pytest.raises(RuntimeError, match="receipt audit failed"):
            service.attach_evidence(
                observation, source, "evidence.txt", "text/plain", "condition_photo", **kwargs
            )
    with sqlite3.connect(workflow.workspace.paths.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM file_records").fetchone()[0] == 0
    assert not list((workflow.workspace.paths.files / "managed").glob("*"))
    assert service.unit_of_work.command_revision("lease", workflow.lease["id"]) == 1
    attached = service.attach_evidence(
        observation, source, "evidence.txt", "text/plain", "condition_photo", **kwargs
    )
    with patch.object(
        workflow.files.content_store, "store", side_effect=AssertionError("must not publish again")
    ):
        assert (
            service.attach_evidence(
                observation, source, "evidence.txt", "text/plain", "condition_photo", **kwargs
            )
            == attached
        )
    assert attached["revision"] == 2
    validate_latest_schema(workflow.workspace.paths.database)


def test_schema_and_receipt_audit_tampering_rejected(workflow):
    service = workflow.inspections
    first = service.create(workflow.lease["id"], **create_request(workflow))
    validate_latest_schema(workflow.workspace.paths.database)
    with sqlite3.connect(workflow.workspace.paths.database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE inspection_command_operations SET revision=2")
        connection.execute("DROP TRIGGER inspection_commands_no_update")
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workflow.workspace.paths.database)
    from app.modules.inspections.infrastructure.command_models import INSPECTION_COMMAND_TRIGGERS

    with sqlite3.connect(workflow.workspace.paths.database) as connection:
        connection.execute(INSPECTION_COMMAND_TRIGGERS["inspection_commands_no_update"])
        audit_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='audit_events_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute(
            "UPDATE audit_events SET correlation_id=? WHERE entity_type='inspection_command_operation' AND entity_id=?",
            (str(uuid4()), first["operationId"]),
        )
        connection.execute(audit_trigger)
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workflow.workspace.paths.database)


def test_missing_correlated_domain_audit_rejected_with_intact_schema(workflow):
    result = workflow.inspections.create(workflow.lease["id"], **create_request(workflow))
    with sqlite3.connect(workflow.workspace.paths.database) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='audit_events_no_delete'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER audit_events_no_delete")
        connection.execute(
            "DELETE FROM audit_events WHERE entity_type='condition_report' AND entity_id=? AND action='created'",
            (result["id"],),
        )
        connection.execute(trigger)
    with pytest.raises(MigrationSchemaError, match="Inspection command history"):
        validate_latest_schema(workflow.workspace.paths.database)


def test_attachment_commit_failure_rolls_back_database_and_bytes(workflow):
    service = workflow.inspections
    report = service.create(workflow.lease["id"], **create_request(workflow))
    source = workflow.workspace.paths.files.parent / "commit-evidence.txt"
    source.write_bytes(b"commit-failure bytes")

    def fail_commit(_connection):
        raise RuntimeError("commit failed")

    event.listen(service.unit_of_work.engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            service.attach_evidence(
                report["areas"][0]["observations"][0]["id"],
                source,
                "commit-evidence.txt",
                "text/plain",
                "condition_photo",
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
    finally:
        event.remove(service.unit_of_work.engine, "commit", fail_commit)
    with sqlite3.connect(workflow.workspace.paths.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM file_records").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM inspection_command_operations").fetchone()[0]
            == 1
        )
    assert not list((workflow.workspace.paths.files / "managed").glob("*"))


def test_api_contract_and_stale_snapshot(workflow):
    class Runtime:
        def require_ready(self, **_kwargs):
            return None

    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(workflow.inspections, Runtime()))
    client = TestClient(app)
    endpoint = f"/api/leases/{workflow.lease['id']}/condition-reports"
    payload = {
        "reportKind": "pre_move_in",
        "walkthroughOn": date.today().isoformat(),
        "conductedBy": "Operator",
    }
    assert client.post(endpoint, json=payload).status_code == 422
    payload.update(expectedRevision=0, idempotencyKey=str(uuid4()))
    created = client.post(endpoint, json=payload)
    assert created.status_code == 201, created.text
    original = created.json()
    assert (
        client.get(f"/api/inspection-commands/{original['operationId']}").json()["result"]
        == original
    )
    stale = client.patch(
        f"/api/condition-reports/{original['id']}",
        json={"expectedRevision": 0, "idempotencyKey": str(uuid4()), "conductedBy": "Changed"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["revision"] == 1
    schema = app.openapi()
    assert (
        schema["paths"][endpoint.replace(workflow.lease["id"], "{lease_id}")]["post"]["operationId"]
        == "createConditionReport"
    )
    assert "operationId" in schema["components"]["schemas"]["ReportCommandResponse"]["required"]


def test_command_activity_redacts_request_and_evidence(workflow):
    from app.modules.inspections.domain.audit_policy import INSPECTION_COMMAND_ACTIVITY_POLICY

    first = workflow.inspections.create(
        workflow.lease["id"], **create_request(workflow, general_notes="Private notes")
    )
    with sqlite3.connect(workflow.workspace.paths.database) as connection:
        raw = json.loads(
            connection.execute(
                "SELECT after_snapshot FROM audit_events WHERE entity_type='inspection_command_operation' AND entity_id=?",
                (first["operationId"],),
            ).fetchone()[0]
        )
    assert "Private notes" in raw["request_json"]
    assert set(INSPECTION_COMMAND_ACTIVITY_POLICY.redact(raw)) == {
        "action",
        "revision",
        "created_at",
    }
