"""Coverage forms share OPS receipts and remain portable after source changes."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4
import pytest
from sqlalchemy import text

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.modules.operator.application.coverage_models import CoverageReview
from app.modules.operator.infrastructure.coverage_recovery import validate_coverage_recovery
from app.modules.operator.domain.models import OperatorConflict
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.operator.tests import test_coverage
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspacePaths
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository


@pytest.fixture
def ready(tmp_path):
    source = test_coverage.context.__wrapped__(tmp_path)
    values = next(source)
    support = values[2]
    support.unit_of_work.references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
    )
    try:
        yield values
    finally:
        next(source, None)


def save(support, service, property_id):
    current = service.read("property", property_id, "maintenance")
    payload = {
        "subjectKind": "property",
        "subjectId": property_id,
        "area": "maintenance",
        "expectedEvidenceRevision": current["evidenceRevision"],
        "basis": "acknowledged",
        "reason": "Reviewed the recorded issues",
        "nextReviewOn": None,
    }
    form = support.save_recovery(
        str(uuid4()),
        form_key="coverage.review",
        schema_version=1,
        payload=payload,
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    return form, payload


def test_review_recovery_receipt_and_portability(ready):
    workspace, _, support, service, property_id, _ = ready
    form, payload = save(support, service, property_id)
    key = str(uuid4())
    prepared = support.prepare_attempt(
        form["id"],
        attempt_key=key,
        expected_revision=form["revision"],
        idempotency_key=str(uuid4()),
    )
    command = CoverageReview(
        subject_kind=payload["subjectKind"],
        subject_id=payload["subjectId"],
        area=payload["area"],
        expected_evidence_revision=payload["expectedEvidenceRevision"],
        reason=payload["reason"],
        idempotency_key=key,
    )
    result = service.review(command)
    assert service.review(command) == result
    reconciled = support.reconcile_recovery(
        form["id"],
        expected_revision=prepared["revision"],
        idempotency_key=str(uuid4()),
    )
    assert reconciled["receipt"]["receiptId"] == result["operationId"]
    validate_latest_schema(workspace.paths.database)
    backup = BackupService(
        workspace,
        support.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    target = workspace.paths.root.parent / "restored"
    tables = ("operator_recovery_records", "operator_operations", "operator_coverage_reviews")

    def records(database):
        with closing(sqlite3.connect(database)) as connection:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in tables
            }

    before = records(workspace.paths.database)
    with fast_backup_encryption():
        archive = backup.create_backup(
            "portable coverage passphrase",
            output_path=workspace.paths.root.parent / "coverage.epmbackup",
        )
        backup.restore(archive.archive_path, "portable coverage passphrase", target)
    assert records(WorkspacePaths(target).database) == before
    validate_latest_schema(WorkspacePaths(target).database)
    with support.unit_of_work.engine.begin() as connection:
        connection.execute(
            text("UPDATE operator_recovery_records SET request_fingerprint=:digest WHERE id=:id"),
            {"digest": "0" * 64, "id": form["id"]},
        )
    with support.unit_of_work.engine.connect() as connection, pytest.raises(MigrationSchemaError):
        validate_coverage_recovery(connection)


def test_stale_evidence_cannot_prepare_and_incomplete_reason_cannot_dispatch(ready):
    _, _, support, service, property_id, _ = ready
    form, payload = save(support, service, property_id)
    payload["expectedEvidenceRevision"] = "0" * 64
    with pytest.raises(OperatorConflict):
        support.save_recovery(
            form["id"],
            form_key="coverage.review",
            schema_version=1,
            payload=payload,
            expected_revision=form["revision"],
            idempotency_key=str(uuid4()),
        )
    with support.unit_of_work.engine.connect() as connection:
        retained = connection.execute(
            text("SELECT payload_json FROM operator_recovery_records WHERE id=:id"),
            {"id": form["id"]},
        ).scalar_one()
        assert json.loads(retained)["reason"] == payload["reason"]
