from __future__ import annotations

import tempfile
import unittest
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.communications.infrastructure.link_reader import SQLiteCommunicationLinkReader
from app.modules.communications.application.service import CommunicationCommand, CommunicationService, LinkInput, ParticipantInput
from app.modules.communications.infrastructure.unit_of_work import SQLiteCommunicationUnitOfWork
from app.bootstrap.communication_context import SQLiteCommunicationContextOperations
from app.modules.finance.application.expense_service import ExpenseService
from app.modules.finance.domain.expense_models import ExpenseCreateCommand
from app.modules.finance.domain.models import VoidCommand
from app.modules.finance.infrastructure.expense_context_reader import SQLiteExpenseContextReader
from app.modules.finance.infrastructure.expense_unit_of_work import SQLiteExpenseUnitOfWork
from app.modules.maintenance.application.service import MaintenanceService
from app.modules.maintenance.domain.audit_policy import MAINTENANCE_ACTIVITY_POLICY
from app.modules.maintenance.domain.models import AppointmentCreate, IssueCreate, ReporterAttribution, ReporterCorrection, MaintenanceConflictError, MaintenanceError
from app.modules.maintenance.infrastructure.unit_of_work import SQLiteMaintenanceUnitOfWork
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.parties.application.service import PartyCreateCommand
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.leases.application.service import LeaseCreateCommand, LeaseService, ParticipantCommand, TermCommand
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseUnitOfWork
from app.modules.tenants.application.service import TenantCreateCommand, TenantService
from app.modules.tenants.infrastructure.unit_of_work import SQLiteTenantProfileAvailability, SQLiteTenantUnitOfWork
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyReadOperations
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations
from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.workspace.application.service import WorkspaceError, WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.sqlite_engine import create_sqlite_engine
from app.modules.vendors.infrastructure.context_reader import SQLiteProviderContextReader
from app.bootstrap.api import create_app
from fastapi.testclient import TestClient


class MaintenanceWorkflowTests(unittest.TestCase):
    @staticmethod
    def _local_midday(value: date) -> datetime:
        return datetime.combine(value, time(12), tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(UTC)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace"))
        self.workspace.initialize()
        self.workspace.config.config_path.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        database = self.workspace.paths.database
        recorder = AuditRecorder(SQLiteAuditRepository(database))
        self.portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(database, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        property_record = self.portfolio.create_property(PropertyCreateCommand(
            "Maintenance home", "1 Main Street", "Portland", "US", "single_family_home",
            (OwnershipInput("local_operator"),), region="OR",
        ))
        self.property_id = property_record.id
        self.space_id = self.portfolio.get_property(property_record.id)["spaces"][0]["id"]
        self.expenses = ExpenseService(SQLiteExpenseUnitOfWork(
            database, recorder, SQLitePortfolioContextReader(),
            SQLiteProviderContextReader(), SQLitePartyOperations(database),
            SQLiteFileLinkReader(),
        ), now=lambda: datetime.now(UTC))
        self.category_id = self.expenses.list_categories()[0]["id"]
        self.party_operations = SQLitePartyOperations(database)
        self.service = MaintenanceService(SQLiteMaintenanceUnitOfWork(
            database, recorder, SQLitePortfolioContextReader(), SQLiteExpenseContextReader(),
            SQLiteTaskContextReader(), SQLiteTaskTransactionOperations(), SQLiteFileLinkReader(),
            self.party_operations, SQLiteLeaseContextReader(), SQLiteCommunicationLinkReader(),
        ))

    def issue(self):
        return self.service.create_issue(IssueCreate(
            self.property_id, None, "Drain leak", "Water is collecting below the sink.",
            "plumbing", None, "high", datetime.now(UTC).isoformat(), ReporterAttribution("manager", "local_operator"),
        ), str(uuid4()))

    def expense(self):
        return self.expenses.record_expense(ExpenseCreateCommand(
            idempotency_key=str(uuid4()), property_id=self.property_id,
            space_id=self.space_id, category_id=self.category_id,
            paid_by_kind="local_operator", paid_on=datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat(),
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

    def test_list_uses_stored_reporter_facts_without_detail_only_readers(self) -> None:
        self.issue()
        class FailingParties:
            def party_map(self, *_args): raise AssertionError("list must not read party state")
        class FailingCommunications:
            def summaries_for_entities(self, *_args): raise AssertionError("list must not read communications")
        self.service.unit_of_work.parties = FailingParties()
        self.service.unit_of_work.communications = FailingCommunications()
        page = self.service.list_issues()
        self.assertEqual(page["items"][0]["reporter"]["displayName"], "Local operator")
        self.assertNotIn("currentPartyState", page["items"][0]["reporter"])

    def test_reporter_correction_is_audited_and_tampering_is_rejected_on_open(self) -> None:
        issue = self.issue()
        corrected = self.service.correct_reporter(
            issue["id"], ReporterCorrection(ReporterAttribution("staff", "local_operator"), True, "Correct reporter role"),
        )
        self.assertEqual(corrected["reporter"]["role"], "staff")
        event = next(
            item for item in SQLiteAuditRepository(self.workspace.paths.database).history("maintenance_issue", issue["id"])
            if item.action == "reporter_corrected"
        )
        self.assertEqual(event.after_snapshot["reporterRole"], "staff")
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "UPDATE maintenance_issues SET reporter_role='manager' WHERE id=:id"
                ), {"id": issue["id"]})
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_party_owner_and_archived_selection_preserve_auditable_attribution(self) -> None:
        local_today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        class Yesterday(date):
            @classmethod
            def today(cls): return local_today - timedelta(days=1)
        # Establish yesterday's relationship using the owning module's normal
        # creation path, then close it today through the normal lifecycle.
        with patch("app.modules.portfolio.application.service.date", Yesterday):
            owned = self.portfolio.create_property(PropertyCreateCommand(
                "Owner home", "2 Main Street", "Portland", "US", "single_family_home",
                (OwnershipInput("client_owner", inline_party=PartyCreateCommand("individual", "Casey Owner")),), region="OR",
            ))
        owner_id = self.portfolio.get_property(owned.id)["ownerships"][0]["partyId"]
        active = self.service.create_issue(IssueCreate(
            owned.id, None, "Owner report", "The owner reported a plumbing concern.", "plumbing", None,
            "normal", self._local_midday(local_today - timedelta(days=1)).isoformat(), ReporterAttribution("owner", "party", owner_id),
        ), str(uuid4()))
        self.assertEqual("Casey Owner", active["reporter"]["displayName"])

        self.portfolio.replace_ownerships(owned.id, (OwnershipInput("local_operator"),), local_today.isoformat())
        self.portfolio.archive_party(owner_id, confirmed=True)
        reported = self._local_midday(local_today - timedelta(days=1))
        archived = self.service.create_issue(IssueCreate(
            owned.id, None, "Historical report", "The formerly active owner reported this historical issue.", "plumbing", None,
            "normal", reported.isoformat(), ReporterAttribution("owner", "party", owner_id, True, "Selected from prior ownership records"),
        ), str(uuid4()))
        event = SQLiteAuditRepository(self.workspace.paths.database).history("maintenance_issue", archived["id"])[0]
        self.assertEqual("Selected from prior ownership records", event.after_snapshot["historicalSelectionReason"])
        self.assertNotIn("historicalSelectionReason", event.to_dict(__import__("app.modules.maintenance.domain.audit_policy", fromlist=["MAINTENANCE_ACTIVITY_POLICY"]).MAINTENANCE_ACTIVITY_POLICY)["after"])

    def test_archived_party_correction_retains_context_but_redacts_activity(self) -> None:
        local_today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        reported_at = self._local_midday(local_today - timedelta(days=1))
        class Yesterday(date):
            @classmethod
            def today(cls): return local_today - timedelta(days=1)
        with patch("app.modules.portfolio.application.service.date", Yesterday):
            owned = self.portfolio.create_property(PropertyCreateCommand(
                "Correction home", "4 Main Street", "Portland", "US", "single_family_home",
                (OwnershipInput("client_owner", inline_party=PartyCreateCommand("individual", "Archived Owner")),), region="OR",
            ))
        owner_id = self.portfolio.get_property(owned.id)["ownerships"][0]["partyId"]
        issue = self.service.create_issue(IssueCreate(
            owned.id, None, "Reporter correction", "Correct an issue reporter after historical ownership ends.",
            "plumbing", None, "normal", reported_at.isoformat(), ReporterAttribution("manager", "local_operator"),
        ), str(uuid4()))
        self.portfolio.replace_ownerships(owned.id, (OwnershipInput("local_operator"),), local_today.isoformat())
        self.portfolio.archive_party(owner_id, confirmed=True)
        self.service.correct_reporter(issue["id"], ReporterCorrection(
            ReporterAttribution("owner", "party", owner_id, True, "Historical owner was the reporter"),
            True, "Corrected after reviewing prior ownership records",
        ))
        event = next(
            item for item in SQLiteAuditRepository(self.workspace.paths.database).history("maintenance_issue", issue["id"])
            if item.action == "reporter_corrected"
        )
        self.assertEqual("Historical owner was the reporter", event.after_snapshot["historicalSelectionReason"])
        self.assertEqual("Corrected after reviewing prior ownership records", event.after_snapshot["operatorNarrative"])
        activity = event.to_dict(MAINTENANCE_ACTIVITY_POLICY)["after"]
        for key in ("historicalSelectionReason", "operatorNarrative", "reporterPartyId", "reporterDisplayNameSnapshot"):
            self.assertNotIn(key, activity)

    def test_tenant_reporting_uses_lease_relationship_dates_and_reporter_affects_idempotency(self) -> None:
        database = self.workspace.paths.database
        tenants = TenantService(SQLiteTenantUnitOfWork(
            database, AuditRecorder(SQLiteAuditRepository(database)), SQLiteTenantProfileAvailability(),
            self.party_operations, SQLitePartyReadOperations(self.party_operations),
        ), SharedPartyFactory())
        tenant = tenants.create(TenantCreateCommand("individual", "Taylor Tenant"))
        leases = LeaseService(SQLiteLeaseUnitOfWork(
            database, AuditRecorder(SQLiteAuditRepository(database)), SQLiteTenantProfileAvailability(),
            SQLitePortfolioLeaseOperations(database),
        ))
        today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        lease = leases.create(LeaseCreateCommand(
            self.space_id, "residential", today, today + timedelta(days=365), today,
            TermCommand(200_000, "USD", "monthly", 1, 200_000),
            (ParticipantCommand(tenant["id"], "primary_tenant"),),
        ))
        leases.execute(lease["id"], executed_on=today.isoformat(), confirmed=True)
        command = IssueCreate(
            self.property_id, self.space_id, "Tenant report", "The tenant reported an active occupancy issue.",
            "plumbing", None, "normal", self._local_midday(today).isoformat(), ReporterAttribution("tenant", "party", tenant["id"]),
        )
        self.assertEqual("tenant", self.service.create_issue(command, str(uuid4()))["reporter"]["role"])
        with self.assertRaises(MaintenanceConflictError):
            self.service.create_issue(IssueCreate(
                self.property_id, self.space_id, "Too early", "This predates the tenant occupancy period.", "plumbing", None,
                "normal", self._local_midday(today - timedelta(days=1)).isoformat(), ReporterAttribution("tenant", "party", tenant["id"]),
            ), str(uuid4()))
        key = str(uuid4())
        reported_at = self._local_midday(today).isoformat()
        original = self.service.create_issue(IssueCreate(
            self.property_id, None, "Idempotent report", "An operator report for idempotency verification.", "plumbing", None,
            "normal", reported_at, ReporterAttribution("manager", "local_operator"),
        ), key)
        retry = self.service.create_issue(IssueCreate(
            self.property_id, None, "Idempotent report", "An operator report for idempotency verification.", "plumbing", None,
            "normal", reported_at, ReporterAttribution("manager", "local_operator"),
        ), key)
        self.assertEqual(original["id"], retry["id"])
        with self.assertRaises(MaintenanceConflictError):
            self.service.create_issue(IssueCreate(
                self.property_id, None, "Idempotent report", "An operator report for idempotency verification.", "plumbing", None,
                "normal", reported_at, ReporterAttribution("staff", "local_operator"),
            ), key)

    def test_maintenance_issue_communications_are_created_corrected_listed_and_detailed(self) -> None:
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            party = client.post("/api/parties", json={"partyKind": "individual", "displayName": "Communicating Tenant", "confirmedNewParty": True}).json()
            issue = client.post("/api/maintenance-issues", json={
                "propertyId": self.property_id, "summary": "Communication link", "description": "An issue with linked communications.",
                "category": "plumbing", "priority": "normal", "reportedAtUtc": datetime.now(UTC).isoformat(),
                "reporter": {"role": "manager", "subjectKind": "local_operator"}, "idempotencyKey": str(uuid4()),
            }).json()
            payload = {
                "direction": "inbound", "channel": "phone", "subject": "Initial repair call", "body": "The tenant reported a leak.",
                "occurredAtUtc": datetime.now(UTC).isoformat(), "occurredTimezone": "America/Los_Angeles", "record": True,
                "participants": [{"partyId": party["id"], "role": "reporter"}],
                "links": [{"entityType": "maintenance_issue", "entityId": issue["id"]}], "idempotencyKey": str(uuid4()),
            }
            created = client.post("/api/communications", json=payload)
            self.assertEqual(200, created.status_code, created.text)
            correction = {key: value for key, value in payload.items() if key != "record"}
            correction.update(subject="Corrected repair call", correctionReason="Clarified the subject", idempotencyKey=str(uuid4()))
            corrected = client.post(f"/api/communications/{created.json()['id']}/correct", json=correction)
            self.assertEqual(200, corrected.status_code, corrected.text)
            listed = client.get("/api/communications", params={"entityType": "maintenance_issue", "entityId": issue["id"]})
            self.assertEqual(2, len(listed.json()["items"]))
            detail = client.get(f"/api/maintenance-issues/{issue['id']}")
            self.assertEqual({"Initial repair call", "Corrected repair call"}, {item["subject"] for item in detail.json()["communications"]})

    @fast_backup_encryption()
    def test_reporter_attribution_survives_backup_restore(self) -> None:
        issue = self.issue()
        party_property = self.portfolio.create_property(PropertyCreateCommand(
            "Communication party home", "3 Main Street", "Portland", "US", "single_family_home",
            (OwnershipInput("client_owner", inline_party=PartyCreateCommand("individual", "Backup Contact")),), region="OR",
        ))
        party_id = self.portfolio.get_property(party_property.id)["ownerships"][0]["partyId"]
        communications = CommunicationService(SQLiteCommunicationUnitOfWork(
            self.workspace.paths.database, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
            SQLiteCommunicationContextOperations(SQLiteTaskTransactionOperations()),
        ))
        communication = communications.create(CommunicationCommand(
            "inbound", "phone", "Backup repair call", "A recorded maintenance communication.",
            self._local_midday(datetime.now(ZoneInfo("America/Los_Angeles")).date()).isoformat(), "America/Los_Angeles",
            (ParticipantInput(party_id, "reporter"),), (LinkInput("maintenance_issue", issue["id"]),), record=True,
        ), str(uuid4()))
        archive = Path(self.temp.name) / "maintenance.epm-backup"
        backups = BackupService(self.workspace, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)), lambda database: AuditRecorder(SQLiteAuditRepository(database)))
        backups.create_backup("a sufficiently long test passphrase", output_path=archive)
        restored_root = Path(self.temp.name) / "restored-maintenance"
        backups.restore(archive, "a sufficiently long test passphrase", restored_root)
        database = restored_root / "database" / "property-management.sqlite"
        restored = MaintenanceService(SQLiteMaintenanceUnitOfWork(
            database, AuditRecorder(SQLiteAuditRepository(database)), SQLitePortfolioContextReader(), SQLiteExpenseContextReader(),
            SQLiteTaskContextReader(), SQLiteTaskTransactionOperations(), SQLiteFileLinkReader(),
            SQLitePartyOperations(database), SQLiteLeaseContextReader(), SQLiteCommunicationLinkReader(),
        ))
        detail = restored.detail(issue["id"])
        self.assertEqual("Local operator", detail["reporter"]["displayName"])
        self.assertEqual(["Backup repair call"], [item["subject"] for item in detail["communications"]])
        restored_communications = CommunicationService(SQLiteCommunicationUnitOfWork(
            database, AuditRecorder(SQLiteAuditRepository(database)),
            SQLiteCommunicationContextOperations(SQLiteTaskTransactionOperations()),
        ))
        listed, _ = restored_communications.list(entity_type="maintenance_issue", entity_id=issue["id"])
        self.assertEqual([communication["id"]], [item["id"] for item in listed])

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
                "reporter": {"role": "manager", "subjectKind": "local_operator"},
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
