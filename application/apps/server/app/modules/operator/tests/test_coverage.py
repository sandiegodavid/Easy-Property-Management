"""Coverage uses actual source records, atomic acknowledgments and portable history."""

from app.modules.finance.tests.commands import deposit_command, rent_command

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import UTC, datetime, timedelta, date
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app.bootstrap.operator_coverage import compose_coverage_sources
from app.modules.operator.application.coverage_models import CoverageReview, CoverageResult
from app.modules.operator.application.coverage_service import OperatorCoverageService
from app.modules.operator.api.router import build_router
from app.modules.operator.domain.models import OperatorConflict, OperatorError, OperatorNotFound
from app.modules.operator.tests import test_directories as fixtures
from app.modules.operator.tests import test_context_sources as populated_fixtures
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspacePaths
from app.modules.workspace.application.service import WorkspaceError
from app.modules.portfolio.application.service import AvailabilityCommand
from app.modules.leases.tests.commands import lease_command
from app.modules.leases.application.service import (
    LeaseCreateCommand,
    TermCommand,
    ParticipantCommand,
)
from app.modules.finance.domain.deposit_models import DepositAccountCreateCommand
from app.modules.finance.domain.models import SynchronizeExpectationsCommand
from app.modules.finance.tests.test_money_summary import FixtureLeaseDate
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.modules.operator.domain.models import canonical

READ_BUDGET = 8


@pytest.fixture
def context(tmp_path):
    base = fixtures.directory.__wrapped__(tmp_path)
    workspace, portfolio, directories, support, _ = next(base)
    uow = support.unit_of_work
    uow.sources = replace(uow.sources, coverage=compose_coverage_sources())
    service = OperatorCoverageService(uow, runtime=support.runtime, now=directories.now)
    property_record = fixtures.property_record(portfolio)
    space_id = portfolio.unit_of_work.spaces(property_record.id)[0].id
    yield workspace, portfolio, support, service, property_record.id, space_id
    next(base, None)


def review(service, kind, subject_id, area, **changes):
    current = service.read(kind, subject_id, area)
    values = {
        "subject_kind": kind,
        "subject_id": subject_id,
        "area": area,
        "expected_evidence_revision": current["evidenceRevision"],
        "reason": "Checked current source information",
        "idempotency_key": str(uuid4()),
    }
    values.update(changes)
    command = CoverageReview(**values)
    return command, service.review(command)


def test_source_derived_areas_and_acknowledgment_cannot_fill_missing(context):
    workspace, _, _, service, property_id, space_id = context
    for area in ("lease", "rent", "deposit"):
        result = service.read("space", space_id, area)
        assert result["state"] == "not_applicable"
        CoverageResult.model_validate(result)
    occupancy = service.read("space", space_id, "occupancy")
    assert occupancy["state"] == "missing_required_information"
    _, acknowledged = review(service, "space", space_id, "occupancy")
    assert acknowledged["state"] == "missing_required_information"
    maintenance = service.read("property", property_id, "maintenance")
    assert maintenance["state"] == "needs_review"
    _, acknowledged = review(service, "property", property_id, "maintenance")
    assert acknowledged["state"] == "recorded"
    validate_latest_schema(workspace.paths.database)


def test_review_replay_precedes_source_and_date_checks(context):
    workspace, _, support, service, property_id, _ = context
    command, first = review(
        service, "property", property_id, "maintenance", next_review_on="2026-10-08"
    )
    service.now = lambda: datetime(2026, 10, 8, 18, tzinfo=UTC)
    assert service.read("property", property_id, "maintenance")["trigger"] == "review_date_reached"
    with patch.object(
        support.unit_of_work.sources.coverage.maintenance,
        "evidence_revisions",
        return_value={property_id: "f" * 64},
    ):
        assert service.review(command) == first
        assert service.read("property", property_id, "maintenance")["state"] == "needs_review"
        with pytest.raises(OperatorConflict):
            service.review(command.model_copy(update={"reason": "Changed"}))
        with pytest.raises(OperatorConflict):
            service.review(command.model_copy(update={"idempotency_key": uuid4()}))
    validate_latest_schema(workspace.paths.database)


def test_property_local_date_controls_review_deadline(context):
    _, _, _, service, property_id, _ = context
    service.now = lambda: datetime(2026, 10, 8, 1, tzinfo=UTC)
    _, result = review(service, "property", property_id, "maintenance", next_review_on="2026-10-08")
    assert result["effectiveLocalDate"] == "2026-10-07"
    service.now = lambda: datetime(2026, 10, 8, 7, tzinfo=UTC)
    assert service.read("property", property_id, "maintenance")["trigger"] == "review_date_reached"


def test_invalid_subject_non_applicability_and_date(context):
    _, _, _, service, property_id, space_id = context
    with pytest.raises(OperatorError):
        service.read("property", property_id, "rent")
    with pytest.raises(OperatorNotFound):
        service.read("space", str(uuid4()), "lease")
    with pytest.raises(OperatorError):
        review(service, "property", property_id, "maintenance", basis="not_applicable")
    with pytest.raises(OperatorError):
        review(service, "property", property_id, "maintenance", next_review_on="2026-10-07")
    _, result = review(service, "space", space_id, "deposit", basis="not_applicable")
    assert result["state"] == "not_applicable"


def test_audit_failure_rolls_back_decision(context):
    _, _, support, service, property_id, _ = context
    with patch.object(
        support.unit_of_work.recorder,
        "record_change",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            review(service, "property", property_id, "maintenance")
    with support.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM operator_coverage_reviews")).scalar_one()
            == 0
        )


def test_same_key_concurrent_reviews_commit_one_decision(context):
    _, _, support, service, property_id, _ = context
    current = service.read("property", property_id, "maintenance")
    command = CoverageReview(
        subject_kind="property",
        subject_id=property_id,
        area="maintenance",
        expected_evidence_revision=current["evidenceRevision"],
        reason="Reviewed",
        idempotency_key=uuid4(),
    )
    barrier = Barrier(2)

    def submit():
        barrier.wait()
        return service.review(command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert results[0] == results[1]
    assert service.operation(str(command.idempotency_key)) == results[0]
    with support.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM operator_coverage_reviews")).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE entity_type='operator_coverage_review'"
                )
            ).scalar_one()
            == 1
        )


def test_source_changed_before_review_rejects_without_writes(context):
    _, portfolio, support, service, _, space_id = context
    current = service.read("space", space_id, "occupancy")
    command = CoverageReview(
        subject_kind="space",
        subject_id=space_id,
        area="occupancy",
        expected_evidence_revision=current["evidenceRevision"],
        reason="Reviewed",
        idempotency_key=uuid4(),
    )
    portfolio.change_availability(
        space_id,
        AvailabilityCommand("available_on", "2026-10-08"),
        expected_revision=portfolio.get_space_status(space_id)["revision"],
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(OperatorConflict):
        service.review(command)
    with support.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM operator_coverage_reviews")).scalar_one()
            == 0
        )
    next_revision = service.read("space", space_id, "occupancy")["evidenceRevision"]
    service.now = lambda: datetime(2026, 10, 8, 19, tzinfo=UTC)
    assert service.read("space", space_id, "occupancy")["evidenceRevision"] != next_revision


def test_readiness_unavailability_and_fixed_query_budget(context):
    _, _, support, service, property_id, space_id = context
    statements, connections = [], []
    event.listen(
        support.unit_of_work.engine,
        "before_cursor_execute",
        lambda *args: statements.append(args[2]),
    )
    event.listen(
        support.unit_of_work.engine,
        "engine_connect",
        lambda connection: connections.append(connection),
    )
    for area in ("occupancy", "lease", "rent", "deposit", "maintenance"):
        statements.clear()
        connections.clear()
        service.read(
            "property" if area == "maintenance" else "space",
            property_id if area == "maintenance" else space_id,
            area,
        )
        assert sum(sql.lstrip().upper().startswith("SELECT") for sql in statements) <= READ_BUDGET
        assert len(connections) == 1
        assert not any(
            sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
        )
    import sqlite3

    with patch.object(
        support.unit_of_work.sources.coverage.maintenance,
        "evidence_revisions",
        side_effect=DBAPIError("query", {}, sqlite3.OperationalError("failed")),
    ):
        result = service.read("property", property_id, "maintenance")
        assert result["availability"] == "unavailable" and result["state"] is None
    with patch.object(
        support.unit_of_work.sources.coverage.maintenance,
        "evidence_revisions",
        side_effect=TypeError("bug"),
    ):
        with pytest.raises(TypeError):
            service.read("property", property_id, "maintenance")


@pytest.fixture
def populated():
    yield from populated_fixtures.populated.__wrapped__()


def test_real_lease_rent_deposit_and_area_revisions(populated):
    fixture, overview, _, _, _, _, _, _ = populated
    uow = overview.unit_of_work
    uow.sources = replace(uow.sources, coverage=compose_coverage_sources())
    service = OperatorCoverageService(uow, runtime=overview.runtime, now=overview.now)
    space_id = fixture.lease["spaceId"]
    results = {area: service.read("space", space_id, area) for area in ("lease", "rent", "deposit")}
    assert results["lease"]["state"] == "recorded"
    assert results["deposit"]["state"] == "not_applicable"
    assert results["rent"]["state"] in ("recorded", "needs_review")
    assert all(result["leaseId"] == fixture.lease["id"] for result in results.values())
    _, rent_review = review(service, "space", space_id, "rent")
    command, _ = review(service, "property", fixture.property_id, "maintenance")
    # Preference/review changes advance global audit provenance, not rent evidence.
    for area, result in results.items():
        assert (
            service.read("space", space_id, area)["evidenceRevision"] == result["evidenceRevision"]
        )
    assert service.review(command)["state"] == "recorded"
    assert rent_review["evidenceRevision"] == results["rent"]["evidenceRevision"]
    validate_latest_schema(fixture.db)


def test_rent_acknowledgment_does_not_replace_source_synchronization(populated):
    fixture, overview, _, _, _, _, _, _ = populated
    overview.unit_of_work.sources = replace(
        overview.unit_of_work.sources, coverage=compose_coverage_sources()
    )
    service = OperatorCoverageService(
        overview.unit_of_work, runtime=overview.runtime, now=overview.now
    )
    space_id = fixture.lease["spaceId"]
    maintenance = service.read("property", fixture.property_id, "maintenance")
    command, acknowledged = review(service, "space", space_id, "rent")
    assert acknowledged["state"] == "needs_review"
    assert "rent_synchronization_required" in acknowledged["causes"]
    rent_command(
        fixture.finance,
        "synchronize",
        fixture.lease["id"],
        SynchronizeExpectationsCommand(fixture.lease["terms"][0]["id"], "2026-12-30", "2026-01-01"),
    )
    current = service.read("space", space_id, "rent")
    assert current["evidenceRevision"] != acknowledged["evidenceRevision"]
    assert current["trigger"] == "source_changed"
    assert "rent_synchronization_required" not in current["causes"]
    _, confirmed = review(service, "space", space_id, "rent")
    assert confirmed["state"] == "recorded"
    assert service.review(command) == acknowledged
    assert (
        service.read("property", fixture.property_id, "maintenance")["evidenceRevision"]
        == maintenance["evidenceRevision"]
    )
    validate_latest_schema(fixture.db)


def test_required_deposit_account_and_ended_lease_context(populated):
    fixture, overview, _, _, _, _, _, _ = populated
    overview.unit_of_work.sources = replace(
        overview.unit_of_work.sources, coverage=compose_coverage_sources()
    )
    service = OperatorCoverageService(
        overview.unit_of_work, runtime=overview.runtime, now=overview.now
    )
    property_record = fixtures.property_record(fixture.portfolio, "Deposit home")
    space_id = fixture.portfolio.get_property(property_record.id)["spaces"][0]["id"]
    lease = lease_command(
        fixture.leases,
        "create",
        LeaseCreateCommand(
            space_id,
            "residential",
            date(2026, 1, 1),
            date(2026, 9, 30),
            date(2026, 1, 1),
            TermCommand(100000, "USD", "monthly", 1, 100000),
            (ParticipantCommand(fixture.tenant["id"], "primary_tenant"),),
        ),
    )
    with (
        patch("app.modules.leases.application.service.date", FixtureLeaseDate),
        patch(
            "app.modules.leases.application.service._now", return_value="2026-01-01T12:00:00+00:00"
        ),
    ):
        executed = lease_command(
            fixture.leases,
            "execute",
            lease["id"],
            executed_on="2026-01-01",
            confirmed=True,
            expected_revision=fixture.portfolio.get_space_status(space_id)["revision"],
            idempotency_key=str(uuid4()),
        )
    first = service.read("space", space_id, "deposit")
    assert first["state"] == "missing_required_information" and first["causes"] == [
        "deposit_account_missing"
    ]
    deposit_command(
        fixture.deposits,
        "create_account",
        executed["id"],
        DepositAccountCreateCommand(executed["terms"][0]["id"]),
    )
    current = service.read("space", space_id, "deposit")
    assert current["state"] == "recorded"  # No premature requirement for a full receipt.
    with patch(
        "app.modules.leases.application.service._now", return_value="2026-10-06T12:00:00+00:00"
    ):
        lease_command(
            fixture.leases,
            "end",
            executed["id"],
            actual_move_out_on="2026-09-30",
            confirmed=True,
            expected_revision=fixture.portfolio.get_space_status(space_id)["revision"],
            idempotency_key=str(uuid4()),
        )
    historical = service.read("space", space_id, "deposit")
    assert historical["state"] != "not_applicable"
    assert historical["leaseId"] == executed["id"]
    assert historical["evidenceRevision"] != current["evidenceRevision"]
    assert service.read("space", space_id, "lease")["state"] == "not_applicable"
    validate_latest_schema(fixture.db)


@pytest.mark.parametrize(
    "field,value",
    [("request_fingerprint", "a" * 64), ("reason", "rewritten"), ("correlation_id", str(uuid4()))],
    ids=["request-fingerprint", "reason", "correlation-id"],
)
def test_rewritten_review_rejected_on_open_and_backup(context, field, value):
    workspace, _, support, service, property_id, _ = context
    _, result = review(service, "property", property_id, "maintenance")
    with support.unit_of_work.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER operator_coverage_reviews_no_update"))
        connection.execute(
            text(f"UPDATE operator_coverage_reviews SET {field}=:value WHERE id=:id"),
            {"value": value, "id": result["operationId"]},
        )
        from app.modules.operator.infrastructure.sqlalchemy_models import trigger_sql

        connection.execute(text(trigger_sql("operator_coverage_reviews", "UPDATE")))
    with pytest.raises(MigrationSchemaError, match="Retained Operator"):
        validate_latest_schema(workspace.paths.database)
    with pytest.raises(WorkspaceError, match="Retained Operator"):
        workspace.open()
    backup = BackupService(
        workspace,
        support.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with pytest.raises(WorkspaceError, match="Retained Operator"):
        backup.create_backup(
            "tampered coverage passphrase",
            output_path=workspace.paths.root.parent / "invalid.epmbackup",
        )


def test_append_only_and_encrypted_round_trip(context):
    workspace, _, support, service, property_id, _ = context
    command, original = review(
        service, "property", property_id, "maintenance", next_review_on="2026-10-09"
    )
    tables = ("operator_coverage_reviews",)

    def records(engine):
        with engine.connect() as connection:
            return {
                table: [
                    dict(row)
                    for row in connection.execute(
                        text(f"SELECT * FROM {table} ORDER BY id")
                    ).mappings()
                ]
                for table in tables
            } | {
                "audits": [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM audit_events WHERE entity_type='operator_coverage_review' ORDER BY rowid"
                        )
                    ).mappings()
                ]
            }

    before = records(support.unit_of_work.engine)
    with pytest.raises(DBAPIError), support.unit_of_work.engine.begin() as connection:
        connection.execute(text("DELETE FROM operator_coverage_reviews"))
    backup = BackupService(
        workspace,
        support.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    target = workspace.paths.root.parent / "restored"
    with fast_backup_encryption():
        archive = backup.create_backup(
            "coverage portable passphrase",
            output_path=workspace.paths.root.parent / "coverage.epmbackup",
        )
        backup.restore(archive.archive_path, "coverage portable passphrase", target)
    restored = SQLiteOperatorUnitOfWork(
        WorkspacePaths(target).database,
        AuditRecorder(SQLiteAuditRepository(WorkspacePaths(target).database)),
        fixtures.NoReferences(),
        SQLiteAuditReadMarker(),
        sources=support.unit_of_work.sources,
    )
    try:
        assert records(restored.engine) == before
        runtime = RuntimeIdentity("ready", support.runtime().workspace_id, str(uuid4()), True)
        restored_service = OperatorCoverageService(
            restored, runtime=lambda: runtime, now=lambda: service.now() + timedelta(days=7)
        )
        assert restored_service.review(command) == original
        validate_latest_schema(WorkspacePaths(target).database)
    finally:
        restored.engine.dispose()


def test_typed_api_and_openapi(context):
    _, _, support, service, property_id, _ = context
    app = FastAPI()
    app.include_router(build_router(support, coverage=service))
    client = TestClient(app)
    route = f"/api/operator/coverage/property/{property_id}/maintenance"
    current = client.get(route)
    assert current.status_code == 200
    data = {
        "expectedEvidenceRevision": current.json()["evidenceRevision"],
        "reason": "Reviewed",
        "idempotencyKey": str(uuid4()),
    }
    first = client.post(route + "/reviews", json=data)
    assert first.status_code == 200
    assert client.post(route + "/reviews", json=data).json() == first.json()
    assert client.post(route + "/reviews", json={**data, "unexpected": True}).status_code == 422
    assert client.post(route + "/reviews", json={**data, "reason": "Different"}).status_code == 409
    assert (
        app.openapi()["paths"]["/api/operator/coverage/{kind}/{subject_id}/{area}"]["get"][
            "operationId"
        ]
        == "getOperatorCoverage"
    )
    assert "Reviewed" not in canonical(first.json())
