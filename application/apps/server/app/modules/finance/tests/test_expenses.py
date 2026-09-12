from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.service import FileError, FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.expense_operations import SQLiteFileExpenseOperations
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.finance.application.expense_service import ExpenseService, PossibleDuplicateExpenseError
from app.modules.finance.application.file_links import ExpenseFileLinkValidator
from app.modules.finance.domain.expense_models import (
    CategoryCreateCommand,
    CategoryPatchCommand,
    ExpenseCreateCommand,
    ExpensePatchCommand,
    ExpenseQueryCommand,
    RefundCreateCommand,
    expense_request_fingerprint,
)
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, VoidCommand
from app.modules.finance.infrastructure.expense_unit_of_work import SQLiteExpenseUnitOfWork
from app.modules.finance.infrastructure.file_links import SQLiteExpenseFileLinkOperations
from app.modules.finance.infrastructure.schema_validation import validate_finance_schema
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.expense_operations import SQLitePortfolioExpenseOperations
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.vendors.infrastructure.expense_operations import SQLiteProviderExpenseOperations
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine
from app.platform.config import LocalConfig


class ExpenseWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "config.json"
        self.workspace = WorkspaceService(LocalConfig(
            self.config, root / "workspace", backup_destination_path=root / "backups"
        ))
        self.workspace.initialize()
        self.config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        database = self.workspace.paths.database
        self.audit = SQLiteAuditRepository(database)
        recorder = AuditRecorder(self.audit)
        portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(database, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        property_record = portfolio.create_property(PropertyCreateCommand(
            "Expense home", "1 Main Street", "Portland", "US",
            "single_family_home", (OwnershipInput("local_operator"),), region="OR",
        ))
        self.property_id = property_record.id
        self.space_id = portfolio.get_property(property_record.id)["spaces"][0]["id"]
        party_operations = SQLitePartyOperations(database)
        self.expenses = ExpenseService(SQLiteExpenseUnitOfWork(
            database, recorder, SQLitePortfolioExpenseOperations(),
            SQLiteProviderExpenseOperations(party_operations), party_operations,
            SQLiteFileExpenseOperations(),
        ), now=lambda: datetime.now(UTC))
        self.files = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(database, recorder),
            link_validators=(ExpenseFileLinkValidator(SQLiteExpenseFileLinkOperations(SQLiteFileExpenseOperations())),),
        )
        self.category_id = self.expenses.list_categories()[0]["id"]

    def command(self, **changes):
        values = {
            "idempotency_key": str(uuid4()),
            "property_id": self.property_id,
            "space_id": self.space_id,
            "category_id": self.category_id,
            "paid_by_kind": "local_operator",
            "paid_on": date.today().isoformat(),
            "amount": "125.00",
            "currency_code": "USD",
            "description": "Replaced a failed fixture",
            "payee_name": "Neighborhood Hardware",
        }
        values.update(changes)
        return ExpenseCreateCommand(**values)

    def test_record_idempotency_duplicate_refund_and_replacement_lifecycle(self):
        command = self.command()
        first = self.expenses.record_expense(command)
        self.assertEqual(self.expenses.record_expense(command)["id"], first["id"])
        self.assertEqual(len(self.audit.history("expense", first["id"])), 1)
        with self.assertRaises(PossibleDuplicateExpenseError):
            self.expenses.record_expense(self.command())

        refund = self.expenses.record_refund(first["id"], RefundCreateCommand(
            str(uuid4()), date.today().isoformat(), "25.00", "USD",
        ))
        self.assertEqual(self.expenses.expense(first["id"])["netAmount"], "100.00")
        with self.assertRaises(FinanceConflictError):
            self.expenses.record_refund(first["id"], RefundCreateCommand(
                str(uuid4()), date.today().isoformat(), "101.00", "USD",
            ))
        with self.assertRaises(FinanceConflictError):
            self.expenses.void_expense(first["id"], VoidCommand(True, "Incorrect record"))
        self.expenses.void_refund(refund["id"], VoidCommand(True, "Refund was entered twice"))
        voided = self.expenses.void_expense(first["id"], VoidCommand(True, "Incorrect property"))
        replacement = self.expenses.record_expense(self.command(
            replaces_expense_id=voided["id"], duplicate_confirmed=True,
        ))
        self.assertEqual(replacement["replacesExpenseId"], first["id"])
        self.assertEqual(
            [row["id"] for row in replacement["correctionChain"]],
            [first["id"], replacement["id"]],
        )

    def test_idempotency_rejects_changed_payload_without_another_audit_event(self):
        command = self.command()
        recorded = self.expenses.record_expense(command)
        with self.assertRaises(FinanceConflictError):
            self.expenses.record_expense(self.command(
                idempotency_key=command.idempotency_key,
                amount="126.00",
            ))
        self.assertEqual(len(self.audit.history("expense", recorded["id"])), 1)

    def test_historical_idempotency_includes_confirmation_metadata(self):
        self.expenses.archive_category(
            self.category_id,
            VoidCommand(True, "Retired category"),
        )
        key = str(uuid4())
        original = self.command(
            idempotency_key=key,
            historical_entry_confirmed=True,
            historical_entry_reason="Entered from an old receipt",
        )
        recorded = self.expenses.record_expense(original)
        with self.assertRaises(FinanceConflictError):
            self.expenses.record_expense(self.command(
                idempotency_key=key,
                historical_entry_confirmed=True,
                historical_entry_reason="Different historical reason",
            ))
        with self.assertRaises(FinanceConflictError):
            self.expenses.record_expense(self.command(idempotency_key=key))
        self.assertEqual(len(self.audit.history("expense", recorded["id"])), 1)
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.connect() as connection:
                fingerprint = connection.execute(text(
                    "SELECT request_fingerprint FROM expenses WHERE id = :id"
                ), {"id": recorded["id"]}).scalar_one()
        finally:
            engine.dispose()
        self.assertEqual(fingerprint, expense_request_fingerprint(original))
        self.assertNotIn(
            "requestFingerprint",
            self.audit.history("expense", recorded["id"])[0].after_snapshot,
        )

    def test_category_lifecycle_allows_name_reuse_but_prevents_ambiguous_restore(self):
        original = self.expenses.create_category(CategoryCreateCommand("Landscaping"))
        with self.assertRaises(FinanceConflictError):
            self.expenses.create_category(CategoryCreateCommand("  LANDSCAPING  "))
        archived = self.expenses.archive_category(
            original["id"], VoidCommand(True, "No longer used"),
        )
        self.assertIsNotNone(archived["archivedAt"])
        replacement = self.expenses.create_category(CategoryCreateCommand("landscaping"))
        with self.assertRaises(FinanceConflictError):
            self.expenses.restore_category(
                original["id"], VoidCommand(True, "Restore category"),
            )
        updated = self.expenses.patch_category(
            replacement["id"],
            CategoryPatchCommand(frozenset({"description"}), description="Grounds work"),
        )
        self.assertEqual(updated["description"], "Grounds work")

    def test_expense_patch_is_limited_to_category_and_notes(self):
        expense = self.expenses.record_expense(self.command())
        updated = self.expenses.patch_expense(
            expense["id"],
            ExpensePatchCommand(frozenset({"notes"}), notes="Reviewed by operator"),
        )
        self.assertEqual(updated["notes"], "Reviewed by operator")
        self.assertEqual(updated["amount"], expense["amount"])
        with self.assertRaises(FinanceError):
            ExpensePatchCommand(frozenset({"amount"}))

    def test_expense_evidence_and_activity_privacy(self):
        expense = self.expenses.record_expense(self.command())
        source = Path(self.temp.name) / "private-invoice.pdf"
        source.write_bytes(b"invoice")
        stored = self.files.add(
            source, source.name, "application/pdf", entity_type="expense",
            entity_id=expense["id"], purpose="invoice",
        )
        detail = self.expenses.expense(expense["id"])
        self.assertEqual(detail["activeEvidence"][0]["fileId"], stored.id)
        with TestClient(create_app(self.config)) as client:
            activity = client.get("/api/audit/events").json()["events"]
            contextual = client.get(f"/api/audit/events/expense/{expense['id']}").json()["events"]
        event = next(row for row in activity if row["entityType"] == "expense")
        self.assertNotIn("amountMinor", event["after"])
        self.assertNotIn("payeeName", event["after"])
        self.assertEqual(contextual[0]["after"]["payeeName"], "Neighborhood Hardware")

    def test_http_contract_rejects_numeric_amount_and_returns_typed_expense(self):
        payload = {
            "idempotencyKey": str(uuid4()), "propertyId": self.property_id,
            "spaceId": self.space_id, "categoryId": self.category_id,
            "payeeName": "Neighborhood Hardware", "paidByKind": "local_operator",
            "paidOn": date.today().isoformat(), "amount": "125.00",
            "currencyCode": "USD", "description": "Replaced a fixture",
        }
        with TestClient(create_app(self.config)) as client:
            created = client.post("/api/expenses", json=payload)
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["amount"], "125.00")
            invalid = client.post("/api/expenses", json={**payload, "idempotencyKey": str(uuid4()), "amount": 125.0})
            self.assertEqual(invalid.status_code, 422)

    def test_expense_link_limit_is_enforced_but_archival_remains_available(self):
        expense = self.expenses.record_expense(self.command())
        source = Path(self.temp.name) / "evidence.txt"
        source.write_bytes(b"evidence")
        links = []
        for number in range(20):
            item = self.files.add(source, f"evidence-{number}.txt", "text/plain",
                                  entity_type="expense", entity_id=expense["id"], purpose="supporting_document")
            links.append(self.files.get(item.id).links[0]["id"])
        with self.assertRaisesRegex(FileError, "twenty"):
            self.files.add(source, "extra.txt", "text/plain", entity_type="expense",
                           entity_id=expense["id"], purpose="supporting_document")
        self.files.archive_link(links[0], confirmed=True, reason="Wrong supporting document")
        self.files.add(source, "replacement.txt", "text/plain", entity_type="expense",
                       entity_id=expense["id"], purpose="supporting_document")

    def test_commands_enforce_exact_decimal_and_usd_contracts(self):
        for invalid in (125, 125.0, "125", "125.0", " 125.00", "+125.00", "1e2", "0.00"):
            with self.subTest(amount=invalid), self.assertRaises(FinanceError):
                self.command(amount=invalid)
        with self.assertRaises(FinanceError):
            self.command(currency_code="usd")
        with self.assertRaisesRegex(FinanceError, "Normalized category name"):
            CategoryCreateCommand("ﬃ" * 34)

    def test_provider_snapshot_limit_returns_a_business_validation_error(self):
        provider_id = str(uuid4())
        stamp = datetime.now(UTC).isoformat()
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO parties "
                    "(id, party_kind, display_name, created_at, updated_at, archived_at) "
                    "VALUES (:id, 'organization', :name, :stamp, :stamp, NULL)"
                ), {"id": provider_id, "name": "P" * 201, "stamp": stamp})
                connection.execute(text(
                    "INSERT INTO provider_profiles "
                    "(party_id, selection_status, selection_reason, notes, created_at, updated_at, archived_at) "
                    "VALUES (:id, 'neutral', NULL, NULL, :stamp, :stamp, NULL)"
                ), {"id": provider_id, "stamp": stamp})
        finally:
            engine.dispose()
        with self.assertRaisesRegex(FinanceError, "display-name snapshot"):
            self.expenses.record_expense(self.command(
                provider_party_id=provider_id,
                payee_name=None,
            ))

    def test_expense_query_command_rejects_untyped_and_inconsistent_filters(self):
        for values in (
            {"include_voided": "false"},
            {"has_evidence": "false"},
            {"property_id": "not-a-uuid"},
            {"paid_from": "2026-02-02", "paid_to": "2026-02-01"},
            {"paid_by_kind": "somebody"},
            {"paid_by_kind": "local_operator", "paid_by_party_id": str(uuid4())},
        ):
            with self.subTest(values=values), self.assertRaises(FinanceError):
                ExpenseQueryCommand(**values)
        with self.assertRaises(FinanceError):
            self.expenses.list_expenses(object())

    def test_list_projection_uses_constant_statement_count_per_page(self):
        for number in range(60):
            self.expenses.record_expense(self.command(
                amount=f"{number + 1}.00",
                description=f"Expense {number}",
            ))

        counts = []
        expense_selects = []
        engine = self.expenses.unit_of_work.engine

        def count_statement(*args):
            statement = args[2].upper()
            if statement.lstrip().startswith("SELECT"):
                counts[-1] += 1
            if "FROM EXPENSES" in statement:
                expense_selects.append(statement)

        event.listen(engine, "before_cursor_execute", count_statement)
        try:
            counts.append(0)
            self.expenses.list_expenses(ExpenseQueryCommand(page_size=1))
            counts.append(0)
            result = self.expenses.list_expenses(ExpenseQueryCommand(page_size=5))
        finally:
            event.remove(engine, "before_cursor_execute", count_statement)
        self.assertEqual(len(result["items"]), 5)
        self.assertEqual(counts[1], counts[0])
        self.assertTrue(expense_selects)
        self.assertTrue(all(
            "WHERE " in statement or "LIMIT " in statement
            for statement in expense_selects
        ))

    def test_exact_schema_rejects_missing_finance_index(self):
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.execute(text("DROP INDEX expenses_duplicate_lookup"))
            with engine.connect() as connection, self.assertRaises(MigrationSchemaError):
                validate_finance_schema(connection)
        finally:
            engine.dispose()

    def test_expense_evidence_refund_and_audit_round_trip_through_backup(self):
        expense = self.expenses.record_expense(self.command())
        refund = self.expenses.record_refund(expense["id"], RefundCreateCommand(
            str(uuid4()), date.today().isoformat(), "20.00", "USD", notes="Partial return",
        ))
        source = Path(self.temp.name) / "invoice.txt"
        source.write_bytes(b"expense evidence")
        stored = self.files.add(source, "invoice.txt", "text/plain", entity_type="expense",
                                entity_id=expense["id"], purpose="invoice")
        recorder = AuditRecorder(self.audit)
        backups = BackupService(
            self.workspace, recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        archive = backups.create_backup("a sufficiently long passphrase")
        restored_root = Path(self.temp.name) / "restored"
        backups.restore(archive.archive_path, "a sufficiently long passphrase", restored_root)
        restored_database = restored_root / "database" / "property-management.sqlite"
        party_operations = SQLitePartyOperations(restored_database)
        restored = ExpenseService(SQLiteExpenseUnitOfWork(
            restored_database, AuditRecorder(SQLiteAuditRepository(restored_database)),
            SQLitePortfolioExpenseOperations(), SQLiteProviderExpenseOperations(party_operations),
            party_operations, SQLiteFileExpenseOperations(),
        ))
        detail = restored.expense(expense["id"])
        self.assertEqual(detail["refunds"][0]["id"], refund["id"])
        self.assertEqual(detail["activeEvidence"][0]["fileId"], stored.id)
        self.assertEqual(
            (restored_root / "files" / stored.local_relative_path).read_bytes(),
            b"expense evidence",
        )
        restored_audit = SQLiteAuditRepository(restored_database)
        self.assertTrue(restored_audit.history("expense", expense["id"]))
        self.assertTrue(restored_audit.history("expense_refund", refund["id"]))
