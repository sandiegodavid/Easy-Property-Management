from __future__ import annotations

import tempfile
import unittest
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.finance.application.expense_service import ExpenseService
from app.modules.finance.domain.expense_models import ExpenseCreateCommand
from app.modules.finance.domain.models import VoidCommand
from app.modules.finance.infrastructure.expense_context_reader import SQLiteExpenseContextReader
from app.modules.finance.infrastructure.expense_unit_of_work import SQLiteExpenseUnitOfWork
from app.modules.maintenance.application.service import MaintenanceService
from app.modules.maintenance.domain.models import AppointmentCreate, CostCreate, IssueCreate, MaintenanceConflictError, MaintenanceError
from app.modules.maintenance.infrastructure.unit_of_work import SQLiteMaintenanceUnitOfWork
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.workspace.application.service import WorkspaceError, WorkspaceService
from app.platform.config import LocalConfig
from app.platform.sqlite_engine import create_sqlite_engine
from app.modules.vendors.infrastructure.context_reader import SQLiteProviderContextReader
from app.bootstrap.api import create_app
from fastapi.testclient import TestClient


class MaintenanceWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace"))
        self.workspace.initialize()
        self.workspace.config.config_path.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        database = self.workspace.paths.database
        recorder = AuditRecorder(SQLiteAuditRepository(database))
        portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(database, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        property_record = portfolio.create_property(PropertyCreateCommand(
            "Maintenance home", "1 Main Street", "Portland", "US", "single_family_home",
            (OwnershipInput("local_operator"),), region="OR",
        ))
        self.property_id = property_record.id
        self.space_id = portfolio.get_property(property_record.id)["spaces"][0]["id"]
        self.expenses = ExpenseService(SQLiteExpenseUnitOfWork(
            database, recorder, SQLitePortfolioContextReader(),
            SQLiteProviderContextReader(), SQLitePartyOperations(database),
            SQLiteFileLinkReader(),
        ), now=lambda: datetime.now(UTC))
        self.category_id = self.expenses.list_categories()[0]["id"]
        self.service = MaintenanceService(SQLiteMaintenanceUnitOfWork(
            database, recorder, SQLitePortfolioContextReader(), SQLiteExpenseContextReader(),
            SQLiteTaskContextReader(), SQLiteTaskTransactionOperations(), SQLiteFileLinkReader(),
        ))

    def issue(self):
        return self.service.create_issue(IssueCreate(
            self.property_id, None, "Drain leak", "Water is collecting below the sink.",
            "plumbing", None, "high", datetime.now(UTC).isoformat(),
        ), str(uuid4()))

    def expense(self):
        return self.expenses.record_expense(ExpenseCreateCommand(
            idempotency_key=str(uuid4()), property_id=self.property_id,
            space_id=self.space_id, category_id=self.category_id,
            paid_by_kind="local_operator", paid_on=datetime.now(UTC).date().isoformat(),
            amount="42.00", currency_code="USD", description="Repair supply",
            payee_name="Local hardware",
        ))

    def test_lifecycle_parent_scoped_idempotency_and_projection(self) -> None:
        item = self.issue()
        self.assertEqual(item["status"], "open")
        started = self.service.transition(item["id"], "start")
        self.assertEqual(started["status"], "in_progress")
        returned = self.service.transition(item["id"], "return_to_open")
        self.assertEqual(returned["status"], "open")
        key = str(uuid4())
        command = AppointmentCreate(
            datetime.now(UTC).isoformat(), (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "Plumber visit",
        )
        first = self.service.create_appointment(item["id"], command, key)
        second = self.service.create_appointment(item["id"], command, key)
        self.assertEqual(first["id"], second["id"])
        page = self.service.list_issues(priority="high", has_active_task=False)
        self.assertEqual(page["items"][0]["id"], item["id"])
        self.assertNotIn("description", page["items"][0])
        # Retained maintenance rows and their matching audit evidence survive
        # the same validation boundary used by workspace open and restore.
        self.workspace.open()

    def test_cost_rejects_datetime_observed_on(self) -> None:
        with self.assertRaises(MaintenanceError):
            CostCreate("operator_estimate", "Plumber", "12.00", "2026-09-20T12:30:00")

    def test_future_appointment_blocks_resolution(self) -> None:
        item = self.issue()
        self.service.create_appointment(item["id"], AppointmentCreate(
            (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(), "Inspection",
        ), str(uuid4()))
        with self.assertRaises(MaintenanceConflictError):
            self.service.transition(item["id"], "resolve", "Confirmed repaired", True)

    def test_follow_up_uses_task_command_validation(self) -> None:
        item = self.issue()
        with self.assertRaises(MaintenanceError):
            self.service.create_follow_up(item["id"], "Call electrician", None, "normal", None, "America/Los_Angeles", str(uuid4()))
        task = self.service.create_follow_up(item["id"], "Call electrician", None, "normal", None, None, str(uuid4()))
        self.assertEqual(task["relatedEntityType"], "maintenance_issue")

    def test_later_voided_expense_remains_visible_through_active_link(self) -> None:
        issue = self.issue()
        expense = self.expense()
        self.service.link_expense(issue["id"], expense["id"], str(uuid4()))
        self.expenses.void_expense(expense["id"], VoidCommand(True, "Duplicate receipt"))
        detail = self.service.detail(issue["id"])
        self.assertEqual(detail["expenseLinks"][0]["expense"]["lifecycleStatus"], "voided")
        self.workspace.open()

    def test_missing_expense_link_creation_audit_fails_workspace_validation(self) -> None:
        issue = self.issue()
        link = self.service.link_expense(issue["id"], self.expense()["id"], str(uuid4()))
        self.service.archive_expense_link(link["id"], "Replaced by a corrected expense link", True)
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.execute(text("DROP TRIGGER audit_events_no_delete"))
                connection.execute(text("DELETE FROM audit_events WHERE entity_type='maintenance_expense_link' AND entity_id=:id AND action='created'"), {"id": link["id"]})
                connection.execute(text("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"))
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_follow_up_operation_immutability_and_trigger_validation(self) -> None:
        issue = self.issue()
        self.service.create_follow_up(issue["id"], "Call plumber", None, "normal", None, None, str(uuid4()))
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                key = connection.execute(text("SELECT idempotency_key FROM maintenance_follow_up_operations")).scalar_one()
                with self.assertRaises(Exception):
                    connection.execute(text("UPDATE maintenance_follow_up_operations SET issue_id=:id WHERE idempotency_key=:key"), {"id": issue["id"], "key": key})
                with self.assertRaises(Exception):
                    connection.execute(text("DELETE FROM maintenance_follow_up_operations WHERE idempotency_key=:key"), {"key": key})
                connection.execute(text("DROP TRIGGER maintenance_follow_up_operations_no_delete"))
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_invalid_archived_expense_link_reason_fails_workspace_validation(self) -> None:
        issue = self.issue()
        link = self.service.link_expense(issue["id"], self.expense()["id"], str(uuid4()))
        self.service.archive_expense_link(link["id"], "No longer relevant", True)
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            for invalid_reason in (" ", "x" * 1_001):
                with engine.begin() as connection:
                    connection.execute(text("UPDATE maintenance_issue_expense_links SET archive_reason=:reason WHERE id=:id"), {"reason": invalid_reason, "id": link["id"]})
                with self.assertRaises(WorkspaceError):
                    self.workspace.open()
                with engine.begin() as connection:
                    connection.execute(text("UPDATE maintenance_issue_expense_links SET archive_reason='No longer relevant' WHERE id=:id"), {"id": link["id"]})
        finally:
            engine.dispose()

    def test_documented_api_paths_and_category_detail_patch(self) -> None:
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            created = client.post("/api/maintenance-issues", json={
                "propertyId": self.property_id, "summary": "Outlet", "description": "Loose outlet cover.",
                "category": "electrical", "priority": "normal", "reportedAtUtc": datetime.now(UTC).isoformat(),
                "idempotencyKey": str(uuid4()),
            })
            self.assertEqual(created.status_code, 201, created.text)
            changed = client.patch(f"/api/maintenance-issues/{created.json()['id']}", json={
                "category": "other", "categoryDetail": "Specialty fixture",
            })
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(changed.json()["categoryDetail"], "Specialty fixture")
            scheduled = client.post(f"/api/maintenance-issues/{created.json()['id']}/appointments", json={
                "startsAtUtc": datetime.now(UTC).isoformat(),
                "endsAtUtc": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "purpose": "Electrician visit", "idempotencyKey": str(uuid4()),
            })
            self.assertEqual(scheduled.status_code, 201, scheduled.text)
            self.assertTrue(client.get("/api/maintenance-issues", params={"hasEvidence": False}).json()["items"])
