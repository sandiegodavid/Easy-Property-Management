"""SQLite command-safety proofs for Expense, prepaid and Deposit consumers."""

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.application.prepaid_check_service import PrepaidCheckService
from app.modules.finance.domain.deposit_models import (
    CreditCommand,
    DeductionCommand,
    DepositAccountCreateCommand,
    SettlementCreateCommand,
)
from app.modules.finance.domain.expense_models import ExpensePatchCommand, RefundCreateCommand
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceValidationError,
    PrepaidCheckCommand,
    PrepaidCheckTransitionCommand,
    SynchronizeExpectationsCommand,
    VoidCommand,
)
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.finance.tests import test_expenses as expenses
from app.modules.finance.tests import test_finance as finance
from app.modules.finance.tests.commands import rent_command
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.sqlite_engine import create_sqlite_engine
from pathlib import Path
import json
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


class ExpenseCommandTests(unittest.TestCase):
    command = expenses.ExpenseWorkflowTests.command

    def setUp(self):
        expenses.ExpenseWorkflowTests.setUp(self)
        self.request = self.command()
        self.original = self.expenses.record_expense(self.request, expected_revision=0)

    def test_original_replay_noop_and_refund_share_one_expense_revision(self):
        key = str(uuid4())
        command = ExpensePatchCommand(frozenset({"notes"}), notes=None)
        noop = self.expenses.patch_expense(
            self.original["id"], command, expected_revision=1, idempotency_key=key
        )
        self.assertEqual(noop["expenseRevision"], 1)
        self.assertEqual(noop["updatedAt"], self.original["updatedAt"])
        refund_command = RefundCreateCommand(str(uuid4()), self.request.paid_on, "25.00", "USD")
        refund = self.expenses.record_refund(
            self.original["id"], refund_command, expected_revision=1
        )
        self.assertEqual(refund["expenseRevision"], 2)
        self.expenses.void_refund(
            refund["id"],
            VoidCommand(True, "Correction"),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(
            self.expenses.record_refund(self.original["id"], refund_command, expected_revision=1),
            refund,
        )
        self.assertEqual(
            self.expenses.patch_expense(
                self.original["id"], command, expected_revision=1, idempotency_key=key
            ),
            noop,
        )
        self.assertEqual(
            self.expenses.record_expense(self.request, expected_revision=0), self.original
        )
        self.assertEqual(self.expenses.revision(self.original["id"]), 3)
        validate_latest_schema(self.workspace.paths.database)

    def test_stale_changed_reuse_and_invalid_revision_fail_without_writes(self):
        with self.assertRaises(FinanceConflictError):
            self.expenses.record_expense(
                replace(self.request, notes="Changed"), expected_revision=0
            )
        with self.assertRaises(FinanceConflictError) as error:
            self.expenses.void_expense(
                self.original["id"],
                VoidCommand(True, "Correction"),
                expected_revision=0,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(error.exception.details["currentRevision"], 1)
        with self.assertRaises(TypeError):
            self.expenses.record_expense(self.request)
        for revision in (True, -1, "1", None):
            with self.subTest(revision=revision), self.assertRaises(FinanceValidationError):
                self.expenses.record_expense(self.request, expected_revision=revision)
        self.assertEqual(self.expenses.revision(self.original["id"]), 1)

    def test_result_persistence_failure_rolls_back_refund_and_business_audit(self):
        with self.expenses.unit_of_work.engine.connect() as connection:
            before = connection.scalar(text("SELECT count(*) FROM audit_events"))
        with (
            patch(
                "app.modules.finance.infrastructure.command_operations.SQLiteFinanceCommandTransaction.store_command",
                side_effect=RuntimeError("receipt unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.expenses.record_refund(
                self.original["id"],
                RefundCreateCommand(str(uuid4()), self.request.paid_on, "25.00", "USD"),
                expected_revision=1,
            )
        self.assertEqual(self.expenses.expense(self.original["id"])["refunds"], [])
        self.assertEqual(self.expenses.revision(self.original["id"]), 1)
        with self.expenses.unit_of_work.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM audit_events")), before)

    def test_http_recovery_is_original_typed_result_and_one_read(self):
        with TestClient(create_app(self.config)) as client:
            response = client.get(f"/api/finance/command-operations/{self.request.idempotency_key}")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["result"]["id"], self.original["id"])
            self.assertEqual(response.json()["result"]["expenseRevision"], 1)
        validate_latest_schema(self.workspace.paths.database)

    def test_selected_http_mutations_require_concurrency_and_operation_metadata(self):
        document = create_app(self.config).openapi()
        schemas = document["components"]["schemas"]
        operations = {
            operation["operationId"]: operation
            for methods in document["paths"].values()
            for method, operation in methods.items()
            if method in {"post", "patch", "delete"}
        }
        families = {
            "rentLedgerRevision": (
                "synchronizeRentExpectations",
                "recordRentReceipt",
                "voidRentReceipt",
                "voidRentExpectation",
                "reviewRentExpectationTimeliness",
                "createPrepaidCheck",
                "depositPrepaidCheck",
                "returnPrepaidCheck",
                "voidPrepaidCheck",
                "replacePrepaidCheck",
            ),
            "expenseRevision": (
                "recordExpense",
                "patchExpense",
                "voidExpense",
                "recordExpenseRefund",
                "voidExpenseRefund",
            ),
            "depositAccountRevision": (
                "createSecurityDepositAccount",
                "recordSecurityDepositReceipt",
                "voidSecurityDepositReceipt",
                "createSecurityDepositSettlement",
                "patchSecurityDepositSettlement",
                "addSecurityDepositDeduction",
                "patchSecurityDepositDeduction",
                "deleteSecurityDepositDeduction",
                "addSecurityDepositDeductionSource",
                "deleteSecurityDepositDeductionSource",
                "addSecurityDepositCredit",
                "patchSecurityDepositCredit",
                "deleteSecurityDepositCredit",
                "approveSecurityDepositSettlement",
                "completeSecurityDepositSettlement",
                "voidSecurityDepositSettlement",
                "recordSecurityDepositRefund",
                "voidSecurityDepositRefund",
            ),
            "reportRevision": (
                "createOwnerRentReport",
                "patchOwnerRentReport",
                "verifyOwnerRentReport",
                "rejectOwnerRentReport",
            ),
        }
        for revision_field, names in families.items():
            for name in names:
                with self.subTest(operation=name):
                    operation = operations[name]
                    request = operation["requestBody"]["content"]["application/json"]["schema"]
                    request = schemas[request["$ref"].split("/")[-1]]
                    self.assertTrue(
                        {"expectedRevision", "idempotencyKey"} <= set(request["required"])
                    )
                    response = next(
                        value
                        for code, value in operation["responses"].items()
                        if code.startswith("2")
                    )
                    response = response["content"]["application/json"]["schema"]
                    response = schemas[response["$ref"].split("/")[-1]]
                    self.assertTrue({revision_field, "operationId"} <= set(response["required"]))
                    if name == "verifyOwnerRentReport":
                        self.assertIn("expectedRentLedgerRevision", request["required"])
                        self.assertIn("rentLedgerRevision", response["required"])

    def test_missing_correlated_expense_audit_is_rejected(self):
        engine = self.expenses.unit_of_work.engine
        with engine.begin() as connection:
            connection.execute(text("DROP TRIGGER audit_events_no_delete"))
            connection.execute(text("DELETE FROM audit_events WHERE entity_type='expense'"))
        from app.modules.finance.infrastructure.command_validation import validate_finance_commands

        with engine.connect() as connection, self.assertRaises(MigrationSchemaError):
            validate_finance_commands(connection)


class DepositCommandTests(unittest.TestCase):
    def setUp(self):
        finance.FinanceWorkflowTests.setUp(self)
        self.account_key = str(uuid4())
        self.account_command = DepositAccountCreateCommand(self.lease["terms"][0]["id"])
        self.account = self.deposits.create_account(
            self.lease["id"],
            self.account_command,
            expected_revision=0,
            idempotency_key=self.account_key,
        )
        self.settlement_key = str(uuid4())
        self.settlement_command = SettlementCreateCommand(
            (date.today() + timedelta(days=30)).isoformat(),
            eligibility_override_confirmed=True,
            eligibility_override_reason="Early review requested",
        )
        self.settlement = self.deposits.create_settlement(
            self.account["id"],
            self.settlement_command,
            expected_revision=1,
            idempotency_key=self.settlement_key,
        )

    def test_child_deletion_replay_noop_and_terminal_replay_preserve_original_results(self):
        key = str(uuid4())
        command = DeductionCommand("damage", "1.00", "Repair", "Recorded damage")
        line = self.deposits.add_deduction(
            self.settlement["id"], command, expected_revision=2, idempotency_key=key
        )
        noop_key = str(uuid4())
        noop = self.deposits.update_deduction(
            line["id"], command, expected_revision=3, idempotency_key=noop_key
        )
        self.assertEqual(noop["depositAccountRevision"], 3)
        delete_key = str(uuid4())
        deleted = self.deposits.delete_deduction(
            line["id"], expected_revision=3, idempotency_key=delete_key
        )
        self.assertEqual(deleted["depositAccountRevision"], 4)
        self.assertEqual(
            self.deposits.add_deduction(
                self.settlement["id"], command, expected_revision=2, idempotency_key=key
            ),
            line,
        )
        self.assertEqual(
            self.deposits.delete_deduction(
                line["id"], expected_revision=3, idempotency_key=delete_key
            ),
            deleted,
        )
        approved_key = str(uuid4())
        approved = self.deposits.approve_settlement(
            self.settlement["id"],
            True,
            zero_dollar_closure_confirmed=True,
            expected_revision=4,
            idempotency_key=approved_key,
        )
        self.deposits.complete_settlement(
            self.settlement["id"], True, expected_revision=5, idempotency_key=str(uuid4())
        )
        self.assertEqual(
            self.deposits.approve_settlement(
                self.settlement["id"],
                True,
                zero_dollar_closure_confirmed=True,
                expected_revision=4,
                idempotency_key=approved_key,
            ),
            approved,
        )
        self.assertEqual(
            self.deposits.create_account(
                self.lease["id"],
                self.account_command,
                expected_revision=0,
                idempotency_key=self.account_key,
            ),
            self.account,
        )
        self.assertEqual(
            self.deposits.create_settlement(
                self.account["id"],
                self.settlement_command,
                expected_revision=1,
                idempotency_key=self.settlement_key,
            ),
            self.settlement,
        )
        validate_latest_schema(self.workspace.paths.database)

    def test_credit_failure_rolls_back_child_revision_and_audits(self):
        with (
            patch(
                "app.modules.finance.infrastructure.command_operations.SQLiteFinanceCommandTransaction.store_command",
                side_effect=RuntimeError("receipt unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.deposits.add_credit(
                self.settlement["id"],
                CreditCommand("other", "5.00", "Credit"),
                expected_revision=2,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(self.deposits.settlement(self.settlement["id"])["credits"], [])
        self.assertEqual(self.deposits.revision(self.account["id"]), 2)
        validate_latest_schema(self.workspace.paths.database)


class PrepaidCommandTests(unittest.TestCase):
    def setUp(self):
        finance.FinanceWorkflowTests.setUp(self)
        expectations = rent_command(
            self.finance,
            "synchronize",
            self.lease["id"],
            SynchronizeExpectationsCommand(
                self.lease["terms"][0]["id"],
                (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
        )
        self.expectation = next(item for item in expectations if not item["isProrated"])
        self.instant = datetime.combine(
            date.fromisoformat(self.expectation["periodStartsOn"]), datetime.min.time(), UTC
        ) + timedelta(hours=12)
        database = self.workspace.paths.database
        self.prepaid = PrepaidCheckService(
            SQLiteFinanceUnitOfWork(
                database,
                AuditRecorder(SQLiteAuditRepository(database)),
                SQLiteLeaseContextReader(),
                SQLitePortfolioContextReader(),
                SQLitePartyOperations(database),
                SQLiteTaskTransactionOperations(),
            ),
            now=lambda: self.instant,
        )
        self.command = PrepaidCheckCommand(
            self.expectation["id"],
            self.lease["participants"][0]["tenantPartyId"],
            date.today().isoformat(),
            (date.today() + timedelta(days=1)).isoformat(),
            "Check •••• 1234",
            str(uuid4()),
        )

    def test_create_deposit_return_are_original_replays_and_increment_once_each(self):
        first = self.prepaid.create(self.command, expected_revision=1)
        deposited_command = PrepaidCheckTransitionCommand(str(uuid4()), True)
        deposited = self.prepaid.deposit(first["id"], deposited_command, expected_revision=2)
        returned_command = PrepaidCheckTransitionCommand(str(uuid4()), True, "Returned by bank")
        returned = self.prepaid.return_check(first["id"], returned_command, expected_revision=3)
        self.assertEqual(
            [
                first["rentLedgerRevision"],
                deposited["rentLedgerRevision"],
                returned["rentLedgerRevision"],
            ],
            [2, 3, 4],
        )
        self.assertEqual(self.prepaid.create(self.command, expected_revision=1), first)
        self.assertEqual(
            self.prepaid.deposit(first["id"], deposited_command, expected_revision=2), deposited
        )
        self.assertEqual(
            self.prepaid.return_check(first["id"], returned_command, expected_revision=3), returned
        )
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"], 4
        )
        validate_latest_schema(self.workspace.paths.database)

    def test_task_failure_rolls_back_check_and_ledger_reservation(self):
        with (
            patch(
                "app.modules.tasks.infrastructure.transaction_operations.SQLiteTaskTransactionOperations.insert_reminder",
                side_effect=RuntimeError("reminder unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.prepaid.create(self.command, expected_revision=1)
        self.assertEqual(self.prepaid.list()["items"], [])
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"], 1
        )
        validate_latest_schema(self.workspace.paths.database)

    def test_stale_and_changed_reuse_do_not_mutate_checks_or_ledger(self):
        with self.assertRaises(FinanceConflictError) as stale:
            self.prepaid.create(self.command, expected_revision=0)
        self.assertEqual(stale.exception.details["currentRevision"], 1)
        first = self.prepaid.create(self.command, expected_revision=1)
        with self.assertRaises(FinanceConflictError):
            self.prepaid.create(
                replace(self.command, masked_reference="Check •••• 9999"), expected_revision=1
            )
        with self.assertRaises(FinanceValidationError):
            self.prepaid.create(self.command, expected_revision=True)
        with self.assertRaises(TypeError):
            self.prepaid.create(self.command)
        self.assertEqual(self.prepaid.create(self.command, expected_revision=1), first)
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"], 2
        )
        validate_latest_schema(self.workspace.paths.database)

    @fast_backup_encryption()
    def test_replacement_receipts_and_tasks_survive_encrypted_restore(self):
        first = self.prepaid.create(self.command, expected_revision=1)
        void_command = PrepaidCheckTransitionCommand(str(uuid4()), True, "Spoiled check")
        voided = self.prepaid.void(first["id"], void_command, expected_revision=2)
        replacement_command = replace(
            self.command, idempotency_key=str(uuid4()), masked_reference="Check •••• 5678"
        )
        replacement = self.prepaid.replace(
            first["id"],
            replacement_command,
            expected_revision=3,
            confirmed=True,
            reason="Corrected check received",
        )
        self.assertEqual(self.prepaid.void(first["id"], void_command, expected_revision=2), voided)
        self.assertEqual(
            self.prepaid.replace(
                first["id"],
                replacement_command,
                expected_revision=3,
                confirmed=True,
                reason="Corrected check received",
            ),
            replacement,
        )

        def recorder(database):
            return AuditRecorder(SQLiteAuditRepository(database))

        backups = BackupService(self.workspace, recorder(self.workspace.paths.database), recorder)
        archive = backups.create_backup(
            "a sufficiently long backup passphrase",
            output_path=Path(self.temp.name) / "prepaid.epm-backup",
        )
        target = Path(self.temp.name) / "restored-prepaid"
        backups.restore(archive.archive_path, "a sufficiently long backup passphrase", target)
        database = target / "database" / "property-management.sqlite"
        validate_latest_schema(database)
        restored = create_sqlite_engine(database)
        try:
            with (
                self.prepaid.unit_of_work.engine.connect() as source,
                restored.connect() as destination,
            ):
                for table, order in (
                    ("finance_command_operations", "sequence"),
                    ("finance_command_revisions", "scope_id"),
                    ("prepaid_check_operations", "id"),
                    ("prepaid_checks", "id"),
                    ("tasks", "id"),
                    ("task_reminders", "id"),
                ):
                    query = f"SELECT * FROM {table} ORDER BY {order}"
                    self.assertEqual(
                        source.exec_driver_sql(query).all(),
                        destination.exec_driver_sql(query).all(),
                    )
                query = (
                    "SELECT response_json FROM finance_command_operations WHERE idempotency_key=?"
                )
                self.assertEqual(
                    json.loads(
                        destination.exec_driver_sql(
                            query, (replacement_command.idempotency_key,)
                        ).scalar_one()
                    ),
                    replacement,
                )
        finally:
            restored.dispose()
