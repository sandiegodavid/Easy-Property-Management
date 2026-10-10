"""Slice 36: real Provider/category receipts, gates and portable OPS recovery."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.operator.api.router import build_router
from app.modules.operator.application.provider_forms import PROVIDER_SCHEMAS, provider_source_kind
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.parties.application.service import PartyCreateCommand, PartyIdentityService
from app.modules.parties.infrastructure.recovery_reader import SQLitePartyRecoveryReader
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
    SQLitePartyUnitOfWork,
)
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations
from app.modules.vendors.api.router import build_router as provider_router, build_category_router
from app.modules.vendors.application.service import ProviderService
from app.modules.vendors.infrastructure.recovery_reader import SQLiteProviderRecoveryReader
from app.modules.vendors.infrastructure.unit_of_work import SQLiteProviderUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.config import LocalConfig
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError
from app.modules.operator.application.recovery_schemas import validate_payload
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS


@pytest.fixture
def ready(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    manifest = workspace.initialize()
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    parties = SQLitePartyOperations(workspace.paths.database)
    uow = SQLiteProviderUnitOfWork(
        workspace.paths.database,
        recorder,
        parties,
        SQLitePortfolioLeaseOperations(workspace.paths.database),
    )
    providers = ProviderService(uow)
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_recovery_bindings(),
    )
    ops_uow = SQLiteOperatorUnitOfWork(
        workspace.paths.database, recorder, references, SQLiteAuditReadMarker()
    )
    ops = OperatorService(
        ops_uow, runtime=lambda: RuntimeIdentity("ready", manifest.workspace_id, str(uuid4()), True)
    )
    app = FastAPI()
    register_api_error_handlers(app)
    runtime = SimpleNamespace(ready=True, error=None, can_write=True)
    app.include_router(build_router(ops))
    app.include_router(provider_router(providers, runtime))
    app.include_router(build_category_router(providers, runtime))
    with TestClient(app) as client:
        yield workspace, ops, client, recorder, uow
    for engine in (parties.engine, uow.engine, ops_uow.engine):
        engine.dispose()


def begin(ops, form, values, source=None):
    record, key = str(uuid4()), str(uuid4())
    ops.save_recovery(
        record,
        form_key=form,
        schema_version=1,
        payload=values,
        expected_revision=0,
        idempotency_key=str(uuid4()),
        source_kind=provider_source_kind(form),
        source_id=source,
        base_source_revision=str(values["expectedRevision"]) if source else None,
    )
    ops.prepare_attempt(record, attempt_key=key, expected_revision=1, idempotency_key=str(uuid4()))
    return record, key


def run(ready, form, method, path, values, source=None):
    workspace, ops, client, recorder, uow = ready
    record, key = begin(ops, form, values, source)
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    request = {
        name: value for name, value in values.items() if name not in {"itemId", "assignmentId"}
    } | {"idempotencyKey": key}
    response = client.request(method, path, json=request)
    assert response.status_code in {200, 201}, response.text
    original = response.json()
    receipt = ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))[
        "receipt"
    ]
    assert receipt["receiptId"] == original["operationId"]
    target = original.get("item", original.get("category", original.get("profile")))
    assert receipt["result"]["targetId"] == target.get("id", target.get("partyId"))
    assert receipt["result"]["revision"] == original["revision"]
    assert receipt["result"]["status"] == ("archived" if target.get("archivedAt") else "active")
    assert client.request(method, path, json=request).json() == original
    return original, record


def new_provider(ready, name="Provider"):
    return run(
        ready,
        "provider.create",
        "POST",
        "/api/providers",
        {
            "expectedRevision": 0,
            "party": {"partyKind": "organization", "displayName": name},
        },
    )


def new_category(ready):
    return run(
        ready,
        "provider.category.create",
        "POST",
        "/api/provider-categories",
        {
            "expectedRevision": 0,
            "displayName": "Custom service",
            "displayOrder": 2,
        },
    )


def test_compound_creation_uses_source_normalization(ready):
    category, _ = new_category(ready)
    result, _ = run(
        ready,
        "provider.create",
        "POST",
        "/api/providers",
        {
            "expectedRevision": 0,
            "party": {"partyKind": "organization", "displayName": " Compound "},
            "selectionStatus": "avoid",
            "selectionReason": " Not selected ",
            "contacts": [{"methodKind": "email", "value": "USER@example.com"}],
            "services": [{"displayName": " Repairs "}],
            "serviceAreas": [{"displayName": " Portland ", "countryCode": "us"}],
            "workHistory": [{"performedOn": "2025-01-01", "summary": " Completed "}],
            "references": [{"referenceName": " Contact "}],
            "categoryIds": [category["category"]["id"]],
            "confirmedNewParty": True,
        },
    )
    assert result["profile"]["revision"] == 1
    assert result["profile"]["selectionReason"] == "Not selected"
    validate_latest_schema(ready[0].paths.database)


def test_profile_and_designation_forms(ready):
    workspace, ops, client, recorder, uow = ready
    first, first_record = new_provider(ready)
    source = first["profile"]["partyId"]
    run(
        ready,
        "provider.profile.patch",
        "PATCH",
        f"/api/providers/{source}",
        {"expectedRevision": 1, "selectionStatus": "preferred", "notes": " revised "},
        source,
    )
    run(
        ready,
        "provider.archive",
        "POST",
        f"/api/providers/{source}/archive",
        {"expectedRevision": 2, "confirmed": True},
        source,
    )
    run(
        ready,
        "provider.restore",
        "POST",
        f"/api/providers/{source}/restore",
        {"expectedRevision": 3},
        source,
    )
    assert ops.recovery(first_record)["receipt"]["result"]["revision"] == 1
    party_uow = SQLitePartyUnitOfWork(workspace.paths.database, recorder)
    identity = PartyIdentityService(party_uow, SQLitePartyReadOperations(uow.party_operations))
    party = identity.create(
        PartyCreateCommand("organization", "Existing party"),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    designated, _ = run(
        ready,
        "provider.designate",
        "POST",
        f"/api/providers/from-party/{party['id']}",
        {"expectedRevision": 0, "selectionStatus": "neutral"},
        party["id"],
    )
    assert designated["revision"] == 1
    party_uow.engine.dispose()
    validate_latest_schema(workspace.paths.database)


def test_stale_provider_category_and_cross_provider_children(ready):
    _, ops, _, _, _ = ready
    with pytest.raises(OperatorConflict):
        begin(
            ops,
            "provider.create",
            {
                "expectedRevision": 0,
                "party": {"partyKind": "organization", "displayName": "New"},
                "categoryIds": [str(uuid4())],
            },
        )
    provider, _ = new_provider(ready)
    other, _ = new_provider(ready, "Other")
    source, other_id = provider["profile"]["partyId"], other["profile"]["partyId"]
    child, child_record = run(
        ready,
        "provider.service.add",
        "POST",
        f"/api/providers/{other_id}/services",
        {"expectedRevision": 1, "displayName": "Plumbing"},
        other_id,
    )
    with pytest.raises(OperatorConflict):
        begin(
            ops,
            "provider.service.update",
            {"expectedRevision": 1, "itemId": child["item"]["id"], "displayName": "Changed"},
            source,
        )
    with pytest.raises(OperatorConflict):
        begin(ops, "provider.profile.patch", {"expectedRevision": 99, "notes": "Stale"}, source)
    category, _ = new_category(ready)
    target = category["category"]["id"]
    with pytest.raises(OperatorConflict):
        begin(
            ops,
            "provider.category_assignment.assign",
            {"expectedRevision": 1, "categoryId": target, "expectedCategoryRevision": 99},
            source,
        )
    assignment, _ = run(
        ready,
        "provider.category_assignment.assign",
        "POST",
        f"/api/providers/{source}/category-assignments",
        {"expectedRevision": 1, "categoryId": target, "expectedCategoryRevision": 1},
        source,
    )
    item = assignment["item"]["id"]
    run(
        ready,
        "provider.category_assignment.archive",
        "POST",
        f"/api/providers/{source}/category-assignments/{item}/archive",
        {"expectedRevision": 2, "assignmentId": item, "confirmed": True, "reason": "Inactive"},
        source,
    )
    run(
        ready,
        "provider.category.patch",
        "PATCH",
        f"/api/provider-categories/{target}",
        {"expectedRevision": 1, "displayName": "Changed category"},
        target,
    )
    with pytest.raises(OperatorConflict):
        begin(
            ops,
            "provider.category_assignment.restore",
            {
                "expectedRevision": 3,
                "assignmentId": item,
                "confirmed": True,
                "expectedCategoryRevision": 1,
            },
            source,
        )


@pytest.mark.parametrize(
    "form,payload",
    [
        ("provider.create", {"expectedRevision": True}),
        ("provider.create", {"contacts": [{"methodKind": "email", "value": "x"}] * 101}),
        ("provider.profile.patch", {"unknown": "value"}),
        ("provider.category.patch", {"displayOrder": "1"}),
        ("provider.category_assignment.assign", {"expectedCategoryRevision": False}),
        ("provider.reference.add", {"notes": "x" * 4001}),
    ],
)
def test_bounded_typed_forms(form, payload):
    with pytest.raises(OperatorError):
        validate_payload(form, 1, payload)


@pytest.mark.parametrize(
    "form,payload",
    [
        ("provider.create", {"expectedRevision": 0}),
        (
            "provider.create",
            {
                "expectedRevision": 0,
                "party": {"partyKind": "organization", "displayName": "New"},
                "services": None,
            },
        ),
        ("provider.category.create", {"expectedRevision": 0, "displayName": "Incomplete"}),
        ("provider.category.restore", {"expectedRevision": 1, "confirmed": False}),
        (
            "provider.reputation_link.add",
            {"expectedRevision": 1, "sourceKind": "other", "url": "not-a-url"},
        ),
    ],
)
def test_partial_forms_save_but_cannot_dispatch(ready, form, payload):
    _, ops, _, _, _ = ready
    source = None
    if provider_source_kind(form) == "provider_category":
        category, _ = new_category(ready)
        source = category["category"]["id"]
    elif provider_source_kind(form) == "provider":
        provider, _ = new_provider(ready)
        source = provider["profile"]["partyId"]
    with pytest.raises(OperatorError):
        begin(ops, form, payload, source)


def test_mismatched_command_receipt_remains_unknown(ready):
    _, ops, client, _, _ = ready
    provider, _ = new_provider(ready)
    source = provider["profile"]["partyId"]
    record, key = begin(
        ops, "provider.profile.patch", {"expectedRevision": 1, "notes": "Intended"}, source
    )
    response = client.patch(
        f"/api/providers/{source}",
        json={"expectedRevision": 1, "notes": "Different", "idempotencyKey": key},
    )
    assert response.status_code == 200
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert ops.recovery(record)["reuseState"] == "outcome_unknown"


def portable_rows(database):
    with sqlite3.connect(database) as connection:
        rows = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "provider_command_operations",
                "provider_category_command_operations",
                "provider_profiles",
                "provider_categories",
                "provider_category_assignments",
                "provider_services",
                "provider_service_areas",
                "provider_work_history",
                "provider_references",
                "provider_reputation_links",
                "operator_recovery_records",
                "operator_operations",
            )
        }
        rows["audit_events"] = connection.execute(
            "SELECT * FROM audit_events WHERE entity_type LIKE 'provider%' OR entity_type LIKE 'operator%' ORDER BY rowid"
        ).fetchall()
        return rows


def test_indexed_original_outcomes_and_encrypted_restore(ready, tmp_path):
    workspace, ops, client, recorder, uow = ready
    provider, provider_record = new_provider(ready)
    category, category_record = new_category(ready)
    source = provider["profile"]["partyId"]
    child, child_record = run(
        ready,
        "provider.service.add",
        "POST",
        f"/api/providers/{source}/services",
        {"expectedRevision": 1, "displayName": "Plumbing"},
        source,
    )
    target = category["category"]["id"]
    run(
        ready,
        "provider.category.patch",
        "PATCH",
        f"/api/provider-categories/{target}",
        {"expectedRevision": 1, "displayName": "Changed category"},
        target,
    )
    outcomes = [
        (family, result, ops.recovery(record)["receipt"]["attemptKey"])
        for family, result, record in (
            ("provider", provider, provider_record),
            ("provider", child, child_record),
            ("provider_category", category, category_record),
        )
    ]
    reader = SQLiteProviderRecoveryReader(SQLitePartyRecoveryReader())
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with uow.engine.connect() as connection:
        event.listen(uow.engine, "before_cursor_execute", capture)
        try:
            with patch.object(
                uow.engine, "connect", side_effect=AssertionError("nested connection")
            ):
                for family, result, key in outcomes:
                    before = len(statements)
                    outcome = reader.outcome(connection, key, family=family)
                    assert len(statements) - before == 1
                    assert outcome.result.revision == result["revision"]
                    assert outcome.result.status == "active"
                    assert outcome.operation_id == result["operationId"]
        finally:
            event.remove(uow.engine, "before_cursor_execute", capture)
    before = portable_rows(workspace.paths.database)
    backup = BackupService(
        workspace, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
    )
    with fast_backup_encryption():
        archive = backup.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "providers.epm-backup"
        )
        backup.restore(
            archive.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    restored = tmp_path / "restored/database/property-management.sqlite"
    validate_latest_schema(restored)
    assert portable_rows(restored) == before
    with sqlite3.connect(restored) as connection:
        connection.execute(
            "UPDATE operator_recovery_records SET request_fingerprint=? WHERE id=?",
            ("0" * 64, provider_record),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(restored)


def test_no_workspace_deterministic_registration_contract():
    first, second = FastAPI(), FastAPI()
    first.include_router(build_router(None))
    second.include_router(build_router(None))
    for app in (first, second):
        service = ProviderService(None)
        app.include_router(provider_router(service, None))
        app.include_router(build_category_router(service, None))
    assert first.openapi() == second.openapi()
    assert len(PROVIDER_SCHEMAS) == 32
    assert set(PROVIDER_SCHEMAS) <= set(compose_recovery_bindings())
    assert set(PROVIDER_SCHEMAS) <= set(COMMAND_SCHEMAS)
    literal = first.openapi()["components"]["schemas"]["RecoveryInput"]["properties"]["formKey"][
        "enum"
    ]
    assert set(PROVIDER_SCHEMAS) <= set(literal)
    schema = first.openapi()
    commands = [
        operation
        for path, methods in schema["paths"].items()
        if path.startswith(("/api/providers", "/api/provider-categories"))
        for verb, operation in methods.items()
        if verb in {"post", "patch"}
    ]
    assert len(commands) == len(PROVIDER_SCHEMAS)
    for operation in commands:
        assert operation["operationId"]
        request = operation["requestBody"]["content"]["application/json"]["schema"]
        contract = schema["components"]["schemas"][request["$ref"].rsplit("/", 1)[1]]
        assert {"expectedRevision", "idempotencyKey"} <= set(contract["required"])
        assert "409" in operation["responses"]
        response = next(
            value for key, value in operation["responses"].items() if key.startswith("2")
        )
        result = response["content"]["application/json"]["schema"]
        contract = schema["components"]["schemas"][result["$ref"].rsplit("/", 1)[1]]
        assert {"revision", "operationId"} <= set(contract["required"])


@pytest.mark.parametrize(
    "kind,path,fields,changed",
    [
        ("service", "services", {"displayName": " Plumbing "}, {"displayName": "Electrical"}),
        (
            "area",
            "service-areas",
            {"displayName": " Portland ", "countryCode": "us"},
            {"displayName": "Seattle", "countryCode": None},
        ),
        (
            "work_history",
            "work-history",
            {"performedOn": "2025-01-01", "summary": " Work "},
            {"performedOn": "2025-01-02", "summary": "Updated", "propertyId": None},
        ),
        (
            "reference",
            "references",
            {"referenceName": " A "},
            {"organizationName": "Company", "notes": None},
        ),
        (
            "reputation_link",
            "reputation-links",
            {"sourceKind": "other", "sourceName": " Site ", "url": "https://example.com/review"},
            {"notes": "Checked", "lastCheckedOn": None},
        ),
    ],
)
def test_all_child_forms(ready, kind, path, fields, changed):
    original, _ = new_provider(ready)
    source = original["profile"]["partyId"]
    base = f"/api/providers/{source}/{path}"
    child, _ = run(
        ready, f"provider.{kind}.add", "POST", base, {"expectedRevision": 1, **fields}, source
    )
    item = child["item"]["id"]
    run(
        ready,
        f"provider.{kind}.update",
        "PATCH",
        f"{base}/{item}",
        {"expectedRevision": 2, "itemId": item, **changed},
        source,
    )
    archived, _ = run(
        ready,
        f"provider.{kind}.archive",
        "POST",
        f"{base}/{item}/archive",
        {"expectedRevision": 3, "itemId": item, "confirmed": True},
        source,
    )
    assert archived["item"]["archivedAt"] is not None
    run(
        ready,
        f"provider.{kind}.restore",
        "POST",
        f"{base}/{item}/restore",
        {"expectedRevision": 4, "itemId": item},
        source,
    )
    validate_latest_schema(ready[0].paths.database)


def test_categories_and_assignment_dual_revision_forms(ready):
    category, _ = new_category(ready)
    target = category["category"]["id"]
    provider, _ = new_provider(ready)
    source = provider["profile"]["partyId"]
    base = f"/api/providers/{source}/category-assignments"
    assignment, _ = run(
        ready,
        "provider.category_assignment.assign",
        "POST",
        base,
        {"expectedRevision": 1, "categoryId": target, "expectedCategoryRevision": 1},
        source,
    )
    item = assignment["item"]["id"]
    run(
        ready,
        "provider.category.patch",
        "PATCH",
        f"/api/provider-categories/{target}",
        {"expectedRevision": 1, "description": " Revised "},
        target,
    )
    run(
        ready,
        "provider.category_assignment.archive",
        "POST",
        f"{base}/{item}/archive",
        {"expectedRevision": 2, "assignmentId": item, "confirmed": True, "reason": " ended "},
        source,
    )
    run(
        ready,
        "provider.category_assignment.restore",
        "POST",
        f"{base}/{item}/restore",
        {
            "expectedRevision": 3,
            "assignmentId": item,
            "confirmed": True,
            "expectedCategoryRevision": 2,
        },
        source,
    )
    run(
        ready,
        "provider.category.archive",
        "POST",
        f"/api/provider-categories/{target}/archive",
        {"expectedRevision": 2, "confirmed": True, "reason": " retired "},
        target,
    )
    run(
        ready,
        "provider.category.restore",
        "POST",
        f"/api/provider-categories/{target}/restore",
        {"expectedRevision": 3, "confirmed": True},
        target,
    )
    validate_latest_schema(ready[0].paths.database)


def test_assignment_audit_failure_rolls_back_and_retry_recovers(ready):
    workspace, ops, client, recorder, uow = ready
    provider, _ = new_provider(ready)
    category, _ = new_category(ready)
    source = provider["profile"]["partyId"]
    values = {
        "expectedRevision": 1,
        "categoryId": category["category"]["id"],
        "expectedCategoryRevision": 1,
    }
    record, key = begin(ops, "provider.category_assignment.assign", values, source)
    original = recorder.record_change

    def fail(connection, **change):
        if change["entity_type"] == "provider_command_operation":
            raise RuntimeError("receipt unavailable")
        return original(connection, **change)

    request = {**values, "idempotencyKey": key}
    path = f"/api/providers/{source}/category-assignments"
    with patch.object(recorder, "record_change", side_effect=fail):
        with pytest.raises(RuntimeError, match="receipt unavailable"):
            client.post(path, json=request)
    with sqlite3.connect(workspace.paths.database) as connection:
        assert connection.execute(
            "SELECT revision FROM provider_profiles WHERE party_id=?", (source,)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM provider_category_assignments"
        ).fetchone() == (0,)
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    result = client.post(path, json=request)
    assert result.status_code == 201, result.text
    recovered = ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert recovered["receipt"]["receiptId"] == result.json()["operationId"]
    validate_latest_schema(workspace.paths.database)
