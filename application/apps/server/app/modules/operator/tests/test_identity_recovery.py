"""Slice 35 real Party/Tenant command receipts, coordination and portability."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard
from app.modules.operator.api.router import build_router
from app.modules.operator.application.identity_forms import IDENTITY_SCHEMAS, identity_source_kind
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.parties.api.router import build_router as party_router
from app.modules.parties.application.service import (
    PartyContactService,
    PartyIdentityService,
    SharedPartyFactory,
)
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
    SQLitePartyUnitOfWork,
)
from app.modules.parties.infrastructure.recovery_reader import SQLitePartyRecoveryReader
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.tenants.api.router import build_router as tenant_router
from app.modules.tenants.application.service import TenantService
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantUnitOfWork,
    SQLiteTenantContactReferenceGuard,
    SQLiteTenantRoleActivityGuard,
)
from app.modules.tenants.infrastructure.recovery_reader import SQLiteTenantRecoveryReader
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.config import LocalConfig
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError


@pytest.fixture
def ready(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    manifest = workspace.initialize()
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    parties = SQLitePartyOperations(workspace.paths.database)
    party_uow = SQLitePartyUnitOfWork(
        workspace.paths.database,
        recorder,
        (SQLiteTenantContactReferenceGuard(recorder),),
        (SQLiteTenantRoleActivityGuard(),),
    )
    identity = PartyIdentityService(party_uow, SQLitePartyReadOperations(parties))
    contacts = PartyContactService(party_uow)
    tenant_uow = SQLiteTenantUnitOfWork(
        workspace.paths.database,
        recorder,
        SQLiteLeaseParticipationGuard(),
        parties,
        SQLitePartyReadOperations(parties),
    )
    tenants = TenantService(tenant_uow, SharedPartyFactory())
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
    app.include_router(party_router(identity, contacts, runtime))
    app.include_router(tenant_router(tenants, runtime))
    try:
        with TestClient(app) as client:
            yield workspace, ops, client, recorder, party_uow
    finally:
        for engine in (parties.engine, party_uow.engine, tenant_uow.engine, ops_uow.engine):
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
        source_kind=identity_source_kind(form),
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
    request = {name: value for name, value in values.items() if name != "methodId"} | {
        "idempotencyKey": key
    }
    response = client.request(method, path, json=request)
    assert response.status_code in {200, 201}, response.text
    original = response.json()
    receipt = ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))[
        "receipt"
    ]
    assert receipt["receiptId"] == original["operationId"]
    assert receipt["result"]["targetId"] == original["id"]
    assert receipt["result"]["revision"] == original["revision"]
    assert client.request(method, path, json=request).json() == original
    return original, record


def new_party(ready, name="Party"):
    return run(
        ready,
        "party.create",
        "POST",
        "/api/parties",
        {"expectedRevision": 0, "partyKind": "individual", "displayName": name},
    )


def test_all_party_identity_and_contact_forms(ready):
    workspace, ops, client, recorder, uow = ready
    party, first_record = new_party(ready)
    source = party["id"]
    run(
        ready,
        "party.patch",
        "PATCH",
        f"/api/parties/{source}",
        {"expectedRevision": 1, "displayName": " Changed "},
        source,
    )
    contact, _ = run(
        ready,
        "party.contact.add",
        "POST",
        f"/api/parties/{source}/contact-methods",
        {"expectedRevision": 2, "methodKind": "phone", "value": "5035550199"},
        source,
    )
    method = contact["id"]
    run(
        ready,
        "party.contact.update",
        "PATCH",
        f"/api/parties/{source}/contact-methods/{method}",
        {
            "expectedRevision": 3,
            "methodId": method,
            "methodKind": "email",
            "value": "USER@example.com",
            "label": None,
        },
        source,
    )
    run(
        ready,
        "party.contact.archive",
        "POST",
        f"/api/parties/{source}/contact-methods/{method}/archive",
        {"expectedRevision": 4, "methodId": method, "confirmed": True},
        source,
    )
    run(
        ready,
        "party.contact.restore",
        "POST",
        f"/api/parties/{source}/contact-methods/{method}/restore",
        {"expectedRevision": 5, "methodId": method},
        source,
    )
    run(
        ready,
        "party.archive",
        "POST",
        f"/api/parties/{source}/archive",
        {"expectedRevision": 6, "confirmed": True},
        source,
    )
    run(
        ready,
        "party.restore",
        "POST",
        f"/api/parties/{source}/restore",
        {"expectedRevision": 7},
        source,
    )
    assert ops.recovery(first_record)["receipt"]["result"]["revision"] == 1
    validate_latest_schema(workspace.paths.database)


def test_all_tenant_forms_and_independent_revision(ready):
    workspace, ops, client, recorder, uow = ready
    tenant, record = run(
        ready,
        "tenant.create",
        "POST",
        "/api/tenants",
        {
            "expectedRevision": 0,
            "partyKind": "individual",
            "displayName": " Tenant ",
            "notes": " Initial ",
        },
    )
    source = tenant["id"]
    run(
        ready,
        "party.patch",
        "PATCH",
        f"/api/parties/{source}",
        {"expectedRevision": 1, "displayName": "Party revision two"},
        source,
    )
    patched, _ = run(
        ready,
        "tenant.profile.patch",
        "PATCH",
        f"/api/tenants/{source}",
        {"expectedRevision": 1, "notes": None, "doNotContact": True},
        source,
    )
    assert patched["partyRevision"] == 2
    run(
        ready,
        "tenant.archive",
        "POST",
        f"/api/tenants/{source}/archive",
        {"expectedRevision": 2, "confirmed": True},
        source,
    )
    run(
        ready,
        "tenant.restore",
        "POST",
        f"/api/tenants/{source}/restore",
        {"expectedRevision": 3},
        source,
    )
    party, _ = new_party(ready, "Designated")
    run(
        ready,
        "tenant.designate",
        "POST",
        f"/api/tenants/from-party/{party['id']}",
        {"expectedRevision": 0, "notes": " Designation "},
        party["id"],
    )
    assert ops.recovery(record)["receipt"]["result"]["revision"] == 1
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize("form", tuple(IDENTITY_SCHEMAS))
def test_incomplete_and_strict_forms(form):
    model = IDENTITY_SCHEMAS[form]
    assert model.model_validate({}).model_dump(exclude_unset=True) == {}
    for values in ({"expectedRevision": True}, {"expectedRevision": -1}, {"unexpected": "field"}):
        with pytest.raises(ValueError):
            model.model_validate(values)


def test_contact_archival_coordinates_tenant_receipt_and_rollback(ready):
    workspace, ops, client, recorder, uow = ready
    tenant, _ = run(
        ready,
        "tenant.create",
        "POST",
        "/api/tenants",
        {
            "expectedRevision": 0,
            "partyKind": "individual",
            "displayName": "Tenant",
            "contacts": [{"methodKind": "email", "value": "tenant@example.com"}],
        },
    )
    source = tenant["id"]
    method = tenant["contactMethods"][0]["id"]
    run(
        ready,
        "tenant.profile.patch",
        "PATCH",
        f"/api/tenants/{source}",
        {"expectedRevision": 1, "preferredContactMethodId": method},
        source,
    )
    values = {
        "expectedRevision": 1,
        "methodId": method,
        "confirmed": True,
        "referenceResolutions": [
            {"role": "tenant", "roleRecordId": source, "clear": True, "expectedTenantRevision": 2}
        ],
    }
    record, key = begin(ops, "party.contact.archive", values, source)
    original = recorder.record_change

    def fail_receipt(connection, **change):
        if change["entity_type"] == "party_command_operation":
            raise RuntimeError("receipt unavailable")
        return original(connection, **change)

    request = {name: value for name, value in values.items() if name != "methodId"} | {
        "idempotencyKey": key
    }
    with patch.object(recorder, "record_change", side_effect=fail_receipt):
        with pytest.raises(RuntimeError, match="receipt unavailable"):
            client.post(f"/api/parties/{source}/contact-methods/{method}/archive", json=request)
    current = client.get(f"/api/tenants/{source}").json()
    assert current["profile"]["revision"] == 2
    assert current["profile"]["preferredContactMethodId"] == method
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    response = client.post(f"/api/parties/{source}/contact-methods/{method}/archive", json=request)
    assert response.status_code == 200, response.text
    recovered = ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert recovered["receipt"]["result"]["revision"] == 2
    current = client.get(f"/api/tenants/{source}").json()
    assert current["profile"]["revision"] == 3
    assert current["profile"]["preferredContactMethodId"] is None
    with sqlite3.connect(workspace.paths.database) as connection:
        correlation = connection.execute(
            "SELECT correlation_id FROM party_command_operations WHERE idempotency_key=?", (key,)
        ).fetchone()[0]
        assert (
            connection.execute(
                "SELECT count(*) FROM tenant_command_operations WHERE action='resolve_contact' AND correlation_id=?",
                (correlation,),
            ).fetchone()[0]
            == 1
        )
    validate_latest_schema(workspace.paths.database)


def test_indexed_outcomes_and_backup_preservation(ready, tmp_path):
    workspace, ops, client, recorder, uow = ready
    party, record = new_party(ready)
    tenant, tenant_record = run(
        ready,
        "tenant.create",
        "POST",
        "/api/tenants",
        {"expectedRevision": 0, "partyKind": "individual", "displayName": "Tenant"},
    )
    with sqlite3.connect(workspace.paths.database) as connection:
        keys = [
            connection.execute(
                f"SELECT idempotency_key FROM {family}_command_operations WHERE id=?",
                (result["operationId"],),
            ).fetchone()[0]
            for family, result in (("party", party), ("tenant", tenant))
        ]
        before = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "party_command_operations",
                "tenant_command_operations",
                "operator_recovery_records",
                "operator_operations",
                "parties",
                "tenant_profiles",
            )
        }
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    parties = SQLitePartyRecoveryReader()
    with uow.engine.connect() as connection:
        event.listen(uow.engine, "before_cursor_execute", capture)
        try:
            with patch.object(
                uow.engine, "connect", side_effect=AssertionError("nested connection")
            ):
                assert parties.outcome(connection, keys[0], family="party").result.revision == 1
                assert (
                    SQLiteTenantRecoveryReader(parties)
                    .outcome(connection, keys[1], family="tenant")
                    .result.revision
                    == 1
                )
        finally:
            event.remove(uow.engine, "before_cursor_execute", capture)
    assert len(statements) == 2
    backup = BackupService(
        workspace, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
    )
    with fast_backup_encryption():
        archive = backup.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "portable.epm-backup"
        )
        backup.restore(
            archive.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    restored = tmp_path / "restored/database/property-management.sqlite"
    validate_latest_schema(restored)
    with sqlite3.connect(restored) as connection:
        for table, rows in before.items():
            assert connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() == rows
    with sqlite3.connect(workspace.paths.database) as connection:
        connection.execute(
            "UPDATE operator_recovery_records SET request_fingerprint=? WHERE id=?",
            ("a" * 64, record),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_no_workspace_deterministic_contracts():
    first, second = FastAPI(), FastAPI()
    first.include_router(build_router(None))
    second.include_router(build_router(None))
    assert first.openapi() == second.openapi()
    assert set(IDENTITY_SCHEMAS) <= set(compose_recovery_bindings())


def test_stale_and_cross_party_contact_selection(ready):
    workspace, ops, client, recorder, uow = ready
    party, _ = new_party(ready)
    other, _ = new_party(ready, "Other")
    contact, _ = run(
        ready,
        "party.contact.add",
        "POST",
        f"/api/parties/{other['id']}/contact-methods",
        {"expectedRevision": 1, "methodKind": "email", "value": "other@example.com"},
        other["id"],
    )
    with pytest.raises(OperatorConflict):
        begin(
            ops,
            "party.contact.update",
            {
                "expectedRevision": 1,
                "methodId": contact["id"],
                "methodKind": "email",
                "value": "new@example.com",
            },
            party["id"],
        )
    with pytest.raises(OperatorConflict):
        begin(ops, "party.patch", {"expectedRevision": 999, "displayName": "Stale"}, party["id"])
    tenant, _ = run(
        ready,
        "tenant.designate",
        "POST",
        f"/api/tenants/from-party/{party['id']}",
        {"expectedRevision": 0},
        party["id"],
    )
    with pytest.raises(OperatorConflict):
        begin(
            ops,
            "tenant.profile.patch",
            {"expectedRevision": 1, "preferredContactMethodId": contact["id"]},
            party["id"],
        )
    with pytest.raises(OperatorConflict):
        begin(ops, "tenant.designate", {"expectedRevision": 0}, party["id"])


def test_changed_request_receipt_is_not_reconciled(ready):
    workspace, ops, client, recorder, uow = ready
    values = {"expectedRevision": 0, "partyKind": "individual", "displayName": "Expected"}
    record, key = begin(ops, "party.create", values)
    response = client.post(
        "/api/parties", json=values | {"displayName": "Different", "idempotencyKey": key}
    )
    assert response.status_code == 201
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert ops.recovery(record)["status"] == "outcome_unknown"


@pytest.mark.parametrize(
    "form,values",
    [
        (
            "party.contact.archive",
            {
                "referenceResolutions": [
                    {
                        "role": "tenant",
                        "roleRecordId": "00000000-0000-0000-0000-000000000001",
                        "clear": True,
                    }
                ]
            },
        ),
        (
            "party.contact.archive",
            {
                "referenceResolutions": [
                    {
                        "role": "tenant",
                        "roleRecordId": "00000000-0000-0000-0000-000000000001",
                        "clear": True,
                        "replacementContactMethodId": "00000000-0000-0000-0000-000000000002",
                        "expectedTenantRevision": 1,
                    }
                ]
            },
        ),
        ("party.create", {"contacts": [{}] * 101}),
        ("tenant.create", {"doNotContact": "false"}),
    ],
)
def test_invalid_combinations_and_bounds(form, values):
    with pytest.raises(ValueError):
        IDENTITY_SCHEMAS[form].model_validate(values)


def test_incomplete_attempt_and_stale_tenant_resolution(ready):
    workspace, ops, client, recorder, uow = ready
    record = str(uuid4())
    ops.save_recovery(
        record,
        form_key="party.create",
        schema_version=1,
        payload={},
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(OperatorError):
        ops.prepare_attempt(
            record, attempt_key=str(uuid4()), expected_revision=1, idempotency_key=str(uuid4())
        )
    tenant, _ = run(
        ready,
        "tenant.create",
        "POST",
        "/api/tenants",
        {
            "expectedRevision": 0,
            "partyKind": "individual",
            "displayName": "Tenant",
            "contacts": [{"methodKind": "email", "value": "tenant@example.com"}],
        },
    )
    method = tenant["contactMethods"][0]["id"]
    values = {
        "expectedRevision": 1,
        "methodId": method,
        "confirmed": True,
        "referenceResolutions": [
            {
                "role": "tenant",
                "roleRecordId": tenant["id"],
                "clear": True,
                "expectedTenantRevision": 99,
            }
        ],
    }
    with pytest.raises(OperatorConflict):
        begin(ops, "party.contact.archive", values, tenant["id"])
