"""Slice 31C–E registration, real source receipts and interrupted-attempt recovery."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, text

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.domain.deposit_models import CreditCommand, DeductionCommand
from app.modules.finance.domain.expense_models import (
    CategoryCreateCommand,
    CategoryPatchCommand,
    ExpensePatchCommand,
    RefundCreateCommand,
)
from app.modules.finance.domain.models import (
    VoidCommand,
    SynchronizeExpectationsCommand,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
)
from app.modules.owner_accounting.domain.models import VerifyOwnerRentReportCommand
from app.modules.finance.tests import test_consumer_commands as consumer_fixtures
from app.modules.finance.tests import test_expenses as expense_fixtures
from app.modules.finance.tests import test_finance as deposit_fixtures
from app.modules.owner_accounting.tests import test_owner_accounting as owner_fixtures
from app.modules.operator.api.router import build_router
from app.modules.operator.application.financial_forms import FINANCIAL_SCHEMAS
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.recovery_schemas import validate_payload
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.product_migrations import validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine

ID = str(UUID(int=1))
KEY = str(UUID(int=2))


def camel(values):
    return {
        key.split("_")[0] + "".join(p.title() for p in key.split("_")[1:]): value
        for key, value in values.items()
    }


def sample(form):
    payload = {"expectedRevision": 1}
    if form.endswith(".create") and form in {
        "finance.expense.create",
        "finance.expense_category.create",
        "finance.deposit_account.create",
        "owner_rent_report.create",
    }:
        payload["expectedRevision"] = 0
    specific = {
        "finance.expense.create": {
            "propertyId": ID,
            "categoryId": ID,
            "paidByKind": "local_operator",
            "paidOn": "2026-10-01",
            "amount": "10.00",
            "currencyCode": "USD",
            "description": "Repair",
            "payeeName": "Shop",
        },
        "finance.expense.patch": {"changes": {"notes": None}},
        "finance.expense_refund.create": {
            "receivedOn": "2026-10-01",
            "amount": "1.00",
            "currencyCode": "USD",
        },
        "finance.expense_category.create": {"displayName": "Repairs"},
        "finance.expense_category.patch": {"changes": {"description": None}},
        "finance.deposit_account.create": {"leaseId": ID, "leaseTermId": ID},
        "finance.deposit_receipt.create": {
            "receivedOn": "2026-10-01",
            "amount": "10.00",
            "currencyCode": "USD",
            "receivedByKind": "local_operator",
        },
        "finance.deposit_settlement.create": {"settlementDueOn": "2026-11-01"},
        "finance.deposit_settlement.patch": {"targetId": ID, "changes": {"reviewNotes": None}},
        "finance.deposit_settlement.approve": {"targetId": ID, "confirmed": True},
        "finance.deposit_settlement.complete": {"targetId": ID, "zeroRefundConfirmed": True},
        "finance.deposit_deduction_source.add": {
            "targetId": ID,
            "sourceKind": "expense",
            "sourceId": ID,
        },
        "finance.deposit_refund.create": {
            "targetId": ID,
            "recipientPartyId": ID,
            "paidOn": "2026-10-01",
            "amount": "1.00",
            "currencyCode": "USD",
        },
        "owner_rent_report.create": {
            "leaseId": ID,
            "ownerPartyId": ID,
            "receivedOn": "2026-10-01",
            "amountMinor": 100,
            "paymentMethodKind": "cash",
            "reportedAtUtc": "2026-10-01T12:00:00Z",
        },
        "owner_rent_report.patch": {"changes": {"sourceNote": None}},
        "owner_rent_report.verify": {
            "confirmed": True,
            "reviewNote": "Reviewed",
            "existingReceiptId": ID,
            "expectedLedgerRevision": 1,
        },
    }
    if form in specific:
        payload.update(specific[form])
    elif form.endswith((".void", ".archive", ".restore", ".reject")):
        payload.update(confirmed=True, reason="Correction")
        if "targetId" in FINANCIAL_SCHEMAS[form].model_fields:
            payload["targetId"] = ID
    elif form.endswith(".delete"):
        payload["targetId"] = ID
    elif "deposit_deduction." in form:
        payload.update(
            targetId=ID, category="damage", amount="1.00", description="Repair", rationale="Damage"
        )
    else:
        payload.update(targetId=ID, kind="other", amount="1.00", description="Credit")
    return payload


@pytest.mark.parametrize("form", sorted(FINANCIAL_SCHEMAS))
def test_exact_batch_contract_and_incomplete_autosave(form):
    bindings = compose_recovery_bindings()
    assert len(FINANCIAL_SCHEMAS) == 31
    assert validate_payload(form, 1, {}) == {}
    supplied = validate_payload(form, 1, sample(form))
    binding = bindings[form]
    source = None if binding.source_kind is None else ID
    assert len(binding.fingerprint(source, supplied, KEY)) == 64
    for invalid in ({"unexpected": True}, {"expectedRevision": True}):
        with pytest.raises(OperatorError):
            validate_payload(form, 1, invalid)
    with pytest.raises((OperatorError, KeyError)):
        binding.fingerprint(source, {}, KEY)


def retained_form(row, family):
    request = json.loads(row["request_json"])
    body = dict(request["payload"])
    body.pop("idempotency_key", None)
    if family == "owner_rent_report" and row["action"] == "patch":
        body = {"changes": camel(body["values"])}
    elif family == "owner_rent_report" and row["action"] == "verify":
        body["allocations"] = [camel(item) for item in body["allocations"]]
    elif row["action"] == "patch_expense":
        selected = body.pop("fields")
        body = {
            "changes": camel(
                {
                    k: v
                    for k, v in body.items()
                    if k in selected or (v is not None and v is not False)
                }
            )
        }
    elif row["action"] == "patch_settlement":
        body = {"changes": camel({field: body[field] for field in body["fields"]})}
    elif family == "expense_category" and row["action"] == "patch":
        body = {"changes": camel(body)}
    payload = camel(body) | {"expectedRevision": row["expected_revision"]}
    if family == "deposit":
        if row["action"] == "create_account":
            payload["leaseId"] = row["target_id"]
        elif row["action"] not in {"record_receipt", "create_settlement"}:
            payload["targetId"] = row["target_id"]
    if family == "expense" and row["action"] == "void_refund":
        payload["targetId"] = row["target_id"]
    return payload


def assert_receipts(engine, family):
    table = {
        "expense_category": "expense_category_command_operations",
        "owner_rent_report": "owner_rent_report_operations",
    }.get(family, "finance_command_operations")
    bindings = {
        b.action: (form, b) for form, b in compose_recovery_bindings().items() if b.family == family
    }
    with engine.connect() as connection:
        rows = connection.execute(text(f"SELECT * FROM {table}")).mappings().all()
        if family in {"expense", "deposit"}:
            rows = [
                r
                for r in rows
                if r["scope_kind"] == ("expense" if family == "expense" else "deposit_account")
            ]
        assert rows
        for row in rows:
            form, binding = bindings[row["action"]]
            payload = validate_payload(form, 1, retained_form(row, family))
            source = row.get("scope_id") or row.get("category_id") or row.get("report_id")
            selected = None if binding.source_kind is None else source
            expected = binding.fingerprint(selected, payload, row["idempotency_key"])
            statements = []

            def count(_conn, _cursor, sql, _parameters, _context, _many):
                if sql.lstrip().upper().startswith("SELECT"):
                    statements.append(sql)

            event.listen(engine, "before_cursor_execute", count)
            try:
                with patch.object(
                    engine, "connect", side_effect=AssertionError("nested connection")
                ):
                    outcome = binding.reader.outcome(
                        connection, row["idempotency_key"], family=family
                    )
            finally:
                event.remove(engine, "before_cursor_execute", count)
            assert len(statements) == 1
            assert outcome.request_fingerprint == expected, form
            assert outcome.source_id == source
            assert outcome.operation_id == row["id"]
            result = json.loads(row.get("response_json") or row["result_json"])
            assert outcome.result.target_id == result["id"]
            assert outcome.result.revision == row.get(
                "result_revision", row.get("resulting_revision")
            )


@pytest.mark.parametrize(
    "case", ["expense", "deposit", "owner_create", "owner_adopt", "owner_reject", "category"]
)
def test_real_source_receipts_preserve_original_results_and_fingerprints(case):
    if case == "expense":
        fixture = consumer_fixtures.ExpenseCommandTests()
        action = "test_original_replay_noop_and_refund_share_one_expense_revision"
        service, family = "expenses", "expense"
    elif case == "deposit":
        fixture = consumer_fixtures.DepositCommandTests()
        action = "test_child_deletion_replay_noop_and_terminal_replay_preserve_original_results"
        service, family = "deposits", "deposit"
    elif case.startswith("owner"):
        fixture = owner_fixtures.OwnerRentReportSQLiteIntegrationTests()
        action = {
            "owner_create": "test_verification_creates_receipt_allocations_and_correlated_audits",
            "owner_adopt": "test_verification_adopts_existing_receipt_and_retries_idempotently",
            "owner_reject": "test_original_create_patch_and_reject_replay_and_single_read_recovery",
        }[case]
        service, family = "service", "owner_rent_report"
    else:
        fixture = expense_fixtures.ExpenseWorkflowTests()
        action, service, family = None, "expenses", "expense_category"
    fixture.setUp()
    try:
        if action:
            getattr(fixture, action)()
        else:
            exercise_category(fixture.expenses)
        assert_receipts(getattr(fixture, service).unit_of_work.engine, family)
    finally:
        fixture.doCleanups()


def exercise_category(service):
    item = service.create_category(
        CategoryCreateCommand("OPS Specialty"), expected_revision=0, idempotency_key=str(uuid4())
    )
    service.patch_category(
        item["id"],
        CategoryPatchCommand(frozenset({"description"}), description=None),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    service.archive_category(
        item["id"], VoidCommand(True, "Retired"), expected_revision=1, idempotency_key=str(uuid4())
    )
    service.restore_category(
        item["id"], VoidCommand(True, "Required"), expected_revision=2, idempotency_key=str(uuid4())
    )


def support_for(fixture, service):
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_recovery_bindings(),
    )
    uow = SQLiteOperatorUnitOfWork(
        fixture.workspace.paths.database,
        service.unit_of_work.recorder,
        references,
        SQLiteAuditReadMarker(),
    )
    identity = RuntimeIdentity("ready", fixture.workspace.open().workspace_id, str(uuid4()), True)
    return OperatorService(uow, runtime=lambda: identity)


def prepare(support, form, payload, *, source=None):
    record, key = str(uuid4()), str(uuid4())
    binding = support.unit_of_work.references.commands[form]
    support.save_recovery(
        record,
        form_key=form,
        schema_version=1,
        payload=payload,
        source_kind=binding.source_kind,
        source_id=source,
        base_source_revision=str(payload["expectedRevision"]) if source else None,
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    attempt = support.prepare_attempt(
        record, attempt_key=key, expected_revision=1, idempotency_key=str(uuid4())
    )
    return record, key, attempt


def reconcile(support, record):
    return support.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))


def test_expense_create_patch_refund_recovery_and_encrypted_restore():
    fixture = expense_fixtures.ExpenseWorkflowTests()
    fixture.setUp()
    support = support_for(fixture, fixture.expenses)
    try:
        command = fixture.command()
        payload = camel(asdict(command))
        payload.pop("idempotencyKey")
        payload["expectedRevision"] = 0
        record, key, _ = prepare(support, "finance.expense.create", payload)
        result = fixture.expenses.record_expense(
            replace(command, idempotency_key=key), expected_revision=0
        )
        patch_record, patch_key, _ = prepare(
            support,
            "finance.expense.patch",
            {"expectedRevision": 1, "changes": {"notes": None}},
            source=result["id"],
        )
        noop = fixture.expenses.patch_expense(
            result["id"],
            ExpensePatchCommand(frozenset({"notes"}), notes=None),
            expected_revision=1,
            idempotency_key=patch_key,
        )
        assert noop["expenseRevision"] == 1
        refund_record, refund_key, _ = prepare(
            support,
            "finance.expense_refund.create",
            {
                "expectedRevision": 1,
                "receivedOn": command.paid_on,
                "amount": "1.00",
                "currencyCode": "USD",
            },
            source=result["id"],
        )
        refund = fixture.expenses.record_refund(
            result["id"],
            RefundCreateCommand(refund_key, command.paid_on, "1.00", "USD"),
            expected_revision=1,
        )
        receipts = [
            reconcile(support, record),
            reconcile(support, patch_record),
            reconcile(support, refund_record),
        ]
        assert receipts[0]["receipt"]["result"]["revision"] == 1
        assert receipts[2]["receipt"]["result"]["targetId"] == refund["id"]
        validate_latest_schema(fixture.workspace.paths.database)
        with fast_backup_encryption():
            backup = BackupService(
                fixture.workspace,
                fixture.expenses.unit_of_work.recorder,
                lambda db: AuditRecorder(SQLiteAuditRepository(db)),
            )
            archive = backup.create_backup(
                "a sufficiently long passphrase",
                output_path=Path(fixture.temp.name) / "financial.epm-backup",
            )
            destination = Path(fixture.temp.name) / "restored"
            backup.restore(archive.archive_path, "a sufficiently long passphrase", destination)
        database = destination / "database" / "property-management.sqlite"
        validate_latest_schema(database)
        restored = create_sqlite_engine(database)
        try:
            assert_receipts(restored, "expense")
            with support.unit_of_work.engine.connect() as source, restored.connect() as target:
                for table in (
                    "expenses",
                    "expense_refunds",
                    "finance_command_operations",
                    "finance_command_revisions",
                    "operator_recovery_records",
                    "operator_operations",
                ):
                    assert (
                        source.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                        == target.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                    )
                audit_query = "SELECT * FROM audit_events WHERE entity_type IN ('expense', 'expense_refund', 'finance_command_scope', 'finance_command_operation', 'operator_recovery', 'operator_operation') ORDER BY id"
                assert (
                    source.exec_driver_sql(audit_query).all()
                    == target.exec_driver_sql(audit_query).all()
                )
        finally:
            restored.dispose()
    finally:
        support.unit_of_work.engine.dispose()
        fixture.doCleanups()


def test_source_rollback_keeps_attempt_unresolved_and_exact_retry_recovers():
    fixture = expense_fixtures.ExpenseWorkflowTests()
    fixture.setUp()
    support = support_for(fixture, fixture.expenses)
    try:
        command = fixture.command()
        payload = camel(asdict(command))
        payload.pop("idempotencyKey")
        payload["expectedRevision"] = 0
        record, key, _ = prepare(support, "finance.expense.create", payload)
        command = replace(command, idempotency_key=key)
        with fixture.expenses.unit_of_work.engine.connect() as connection:
            before = {
                table: connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                for table in (
                    "expenses",
                    "finance_command_revisions",
                    "finance_command_operations",
                    "audit_events",
                )
            }
        with (
            patch.object(
                fixture.expenses.unit_of_work.recorder,
                "record_change",
                side_effect=RuntimeError("audit failure"),
            ),
            pytest.raises(RuntimeError, match="audit failure"),
        ):
            fixture.expenses.record_expense(command, expected_revision=0)
        with fixture.expenses.unit_of_work.engine.connect() as connection:
            assert before == {
                table: connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                for table in before
            }
        with pytest.raises(OperatorConflict, match="still unknown"):
            reconcile(support, record)
        result = fixture.expenses.record_expense(command, expected_revision=0)
        assert (
            reconcile(support, record)["receipt"]["result"]["operationId"] == result["operationId"]
        )
        binding = support.unit_of_work.references.commands["finance.expense.create"]
        altered = binding.fingerprint(None, {**payload, "description": "Different repair"}, key)
        with support.unit_of_work.engine.connect() as connection, pytest.raises(OperatorConflict):
            support.unit_of_work.references.resolve_attempt(
                connection, "finance.expense.create", key, altered
            )
    finally:
        support.unit_of_work.engine.dispose()
        fixture.doCleanups()


def test_api_discovery_and_new_source_kinds_need_no_workspace():
    app = FastAPI()
    app.include_router(build_router(None))
    first = app.openapi()
    assert first == app.openapi()
    assert {"expense", "expense_category", "security_deposit_account", "owner_rent_report"} <= set(
        first["components"]["schemas"]["RecoveryInput"]["properties"]["sourceKind"]["anyOf"][0][
            "enum"
        ]
    )


def test_new_forms_are_discovered_at_the_http_boundary():
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(None))
    with TestClient(app) as client:
        forms = client.get("/api/operator/recovery-forms").json()
    assert set(FINANCIAL_SCHEMAS) <= {item["formKey"] for item in forms}


@pytest.mark.parametrize(
    "method",
    [
        "test_security_deposit_account_receipt_and_zero_settlement_lifecycle",
        "test_completed_settlement_refund_must_be_corrected_through_settlement_replacement",
    ],
)
def test_deposit_lifecycle_and_replacement_receipts(method):
    fixture = deposit_fixtures.FinanceWorkflowTests()
    fixture.setUp()
    try:
        getattr(fixture, method)()
        assert_receipts(fixture.deposits.unit_of_work.engine, "deposit")
    finally:
        fixture.doCleanups()


def test_deposit_children_deleted_sources_and_draft_patches_recover():
    fixture = consumer_fixtures.DepositCommandTests()
    fixture.setUp()
    service = fixture.deposits
    try:
        instant = datetime.now(UTC)
        expectations = fixture.finance.synchronize(
            fixture.lease["id"],
            SynchronizeExpectationsCommand(
                fixture.lease["terms"][0]["id"],
                (instant.date() + timedelta(days=60)).isoformat(),
                instant.date().replace(day=1).isoformat(),
            ),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        credit = service.add_credit(
            fixture.settlement["id"],
            CreditCommand("other", "1.00", "Credit"),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
        service.update_credit(
            credit["id"],
            CreditCommand("other", "1.00", "Updated"),
            expected_revision=3,
            idempotency_key=str(uuid4()),
        )
        service.delete_credit(credit["id"], expected_revision=4, idempotency_key=str(uuid4()))
        service.patch_settlement(
            fixture.settlement["id"],
            fields=frozenset({"review_notes"}),
            review_notes="Reviewed",
            expected_revision=5,
            idempotency_key=str(uuid4()),
        )
        deduction = service.add_deduction(
            fixture.settlement["id"],
            DeductionCommand("unpaid_rent", "1.00", "Rent", "Unpaid rent"),
            expected_revision=6,
            idempotency_key=str(uuid4()),
        )
        source = service.add_deduction_source(
            deduction["id"],
            "rent_expectation",
            expectations["items"][0]["id"],
            expected_revision=7,
            idempotency_key=str(uuid4()),
        )
        service.delete_deduction_source(
            source["id"], expected_revision=8, idempotency_key=str(uuid4())
        )
        service.void_settlement(
            fixture.settlement["id"],
            VoidCommand(True, "Correction"),
            expected_revision=9,
            idempotency_key=str(uuid4()),
        )
        assert_receipts(service.unit_of_work.engine, "deposit")
        validate_latest_schema(fixture.workspace.paths.database)
    finally:
        fixture.doCleanups()


def test_deposit_ops_replays_after_deleted_child_and_rejects_stale_parent():
    fixture = consumer_fixtures.DepositCommandTests()
    fixture.setUp()
    service = fixture.deposits
    support = support_for(fixture, service)
    try:
        command = CreditCommand("other", "1.00", "Credit")
        payload = {
            "expectedRevision": 2,
            "targetId": fixture.settlement["id"],
            **camel(asdict(command)),
        }
        record, key, _ = prepare(
            support, "finance.deposit_credit.create", payload, source=fixture.account["id"]
        )
        credit = service.add_credit(
            fixture.settlement["id"], command, expected_revision=2, idempotency_key=key
        )
        delete_record, delete_key, _ = prepare(
            support,
            "finance.deposit_credit.delete",
            {"expectedRevision": 3, "targetId": credit["id"]},
            source=fixture.account["id"],
        )
        service.delete_credit(credit["id"], expected_revision=3, idempotency_key=delete_key)
        assert reconcile(support, record)["receipt"]["result"]["revision"] == 3
        assert reconcile(support, delete_record)["receipt"]["result"]["targetId"] == credit["id"]
        with pytest.raises(OperatorConflict):
            prepare(support, "finance.deposit_credit.create", payload, source=fixture.account["id"])
        with pytest.raises(OperatorConflict):
            prepare(
                support,
                "finance.deposit_credit.delete",
                {"expectedRevision": 4, "targetId": str(uuid4())},
                source=fixture.account["id"],
            )
        validate_latest_schema(fixture.workspace.paths.database)
        assert_recovery_archive(fixture, service, support, "deposit")
    finally:
        support.unit_of_work.engine.dispose()
        fixture.doCleanups()


@pytest.mark.parametrize("adopt", [True, False])
def test_owner_verification_recovers_both_report_and_finance_handoff(adopt):
    fixture = owner_fixtures.OwnerRentReportSQLiteIntegrationTests()
    fixture.setUp()
    support = support_for(fixture, fixture.service)
    try:
        expectation = fixture._expectation()
        amount = expectation["expectedAmountMinor"]
        report = fixture._report_with_evidence(amount)
        if adopt:
            receipt = fixture.finance.record_receipt(
                RecordReceiptCommand(
                    fixture.lease["id"],
                    str(uuid4()),
                    fixture.now.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat(),
                    amount,
                    "USD",
                    (ReceiptAllocationCommand(expectation["id"], amount),),
                    "cash",
                    received_by_party_id=fixture.owner_id,
                ),
                expected_revision=1,
            )
            command = VerifyOwnerRentReportCommand(
                True, "Matched", existing_receipt_id=receipt["id"]
            )
            ledger_revision = 2
        else:
            command = VerifyOwnerRentReportCommand(
                True,
                "Matched",
                receipt_idempotency_key=str(uuid4()),
                allocations=(ReceiptAllocationCommand(expectation["id"], amount),),
            )
            ledger_revision = 1
        payload = camel(asdict(command)) | {
            "expectedRevision": 1,
            "expectedLedgerRevision": ledger_revision,
        }
        payload["allocations"] = [camel(item) for item in asdict(command)["allocations"]]
        with pytest.raises(OperatorConflict):
            prepare(
                support,
                "owner_rent_report.verify",
                {**payload, "expectedLedgerRevision": 0},
                source=report["id"],
            )
        record, key, _ = prepare(support, "owner_rent_report.verify", payload, source=report["id"])
        verified = fixture.service.verify(
            report["id"],
            command,
            key,
            expected_revision=1,
            expected_ledger_revision=ledger_revision,
        )
        assert (
            fixture.service.verify(
                report["id"],
                command,
                key,
                expected_revision=1,
                expected_ledger_revision=ledger_revision,
            )
            == verified
        )
        recovered = reconcile(support, record)["receipt"]
        assert recovered["result"] == {
            "targetId": report["id"],
            "revision": verified["reportRevision"],
            "status": "verified",
            "operationId": verified["operationId"],
        }
        assert_receipts(fixture.service.unit_of_work.engine, "owner_rent_report")
        validate_latest_schema(fixture.workspace.paths.database)
        if not adopt:
            assert_recovery_archive(fixture, fixture.service, support, "owner_rent_report")
    finally:
        support.unit_of_work.engine.dispose()
        fixture.doCleanups()


def assert_recovery_archive(fixture, service, support, family):
    backup = BackupService(
        fixture.workspace,
        service.unit_of_work.recorder,
        lambda db: AuditRecorder(SQLiteAuditRepository(db)),
    )
    with fast_backup_encryption():
        archive = backup.create_backup(
            "a sufficiently long passphrase",
            output_path=Path(fixture.temp.name) / (family + ".epm-backup"),
        )
        destination = Path(fixture.temp.name) / ("restored-" + family)
        backup.restore(archive.archive_path, "a sufficiently long passphrase", destination)
    database = destination / "database" / "property-management.sqlite"
    validate_latest_schema(database)
    restored = create_sqlite_engine(database)
    try:
        assert_receipts(restored, family)
        with support.unit_of_work.engine.connect() as source, restored.connect() as target:
            for table in ("operator_recovery_records", "operator_operations"):
                assert (
                    source.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                    == target.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
                )
            audit_query = "SELECT * FROM audit_events WHERE entity_type LIKE 'security_deposit_%' OR entity_type LIKE 'owner_rent_report%' OR entity_type IN ('finance_command_scope', 'finance_command_operation', 'rent_receipt', 'rent_receipt_allocation', 'operator_recovery', 'operator_operation', 'file', 'file_link') ORDER BY id"
            assert (
                source.exec_driver_sql(audit_query).all()
                == target.exec_driver_sql(audit_query).all()
            )
    finally:
        restored.dispose()


def test_category_http_attempts_recover_after_archival_and_restore():
    fixture = expense_fixtures.ExpenseWorkflowTests()
    fixture.setUp()
    support = support_for(fixture, fixture.expenses)
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(support))
    try:
        with TestClient(app) as client:
            record, key = str(uuid4()), str(uuid4())
            saved = client.put(
                "/api/operator/recovery/" + record,
                json={
                    "formKey": "finance.expense_category.create",
                    "schemaVersion": 1,
                    "payload": {"expectedRevision": 0, "displayName": "OPS category"},
                    "expectedRevision": 0,
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert saved.status_code == 200, saved.text
            prepared = client.post(
                "/api/operator/recovery/" + record + "/attempt",
                json={"attemptKey": key, "expectedRevision": 1, "idempotencyKey": str(uuid4())},
            )
            assert prepared.status_code == 200, prepared.text
            created = fixture.expenses.create_category(
                CategoryCreateCommand("OPS category"), expected_revision=0, idempotency_key=key
            )
            archived = fixture.expenses.archive_category(
                created["id"],
                VoidCommand(True, "Retired"),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
            fixture.expenses.restore_category(
                created["id"],
                VoidCommand(True, "Required"),
                expected_revision=2,
                idempotency_key=str(uuid4()),
            )
            request = {"expectedRevision": 2, "idempotencyKey": str(uuid4())}
            reconciled = client.post(
                "/api/operator/recovery/" + record + "/reconcile", json=request
            )
            assert reconciled.status_code == 200, reconciled.text
            assert reconciled.json()["receipt"]["result"]["revision"] == 1
            assert reconciled.json()["receipt"]["result"]["status"] == "active"
            assert (
                client.post("/api/operator/recovery/" + record + "/reconcile", json=request).json()
                == reconciled.json()
            )
            with pytest.raises(OperatorConflict):
                prepare(
                    support,
                    "finance.expense_category.restore",
                    {
                        "expectedRevision": archived["revision"],
                        "confirmed": True,
                        "reason": "Required",
                    },
                    source=created["id"],
                )
        validate_latest_schema(fixture.workspace.paths.database)
    finally:
        support.unit_of_work.engine.dispose()
        fixture.doCleanups()
