from __future__ import annotations

import tempfile
import unittest
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import event, text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.files.application.ports import FileLink
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
from app.modules.maintenance.application.work_journal_service import WorkJournalService
from app.modules.maintenance.domain.audit_policy import MAINTENANCE_ACTIVITY_POLICY
from app.modules.maintenance.domain.models import AppointmentCreate, AssignmentCreate, IssueCreate, QuoteCreate, ReporterAttribution, ReporterCorrection, MaintenanceConflictError, MaintenanceError
from app.modules.maintenance.domain.work_journal import WorkJournalCreate
from app.modules.maintenance.infrastructure.unit_of_work import SQLiteMaintenanceUnitOfWork
from app.modules.maintenance.infrastructure.file_links import SQLiteMaintenanceFileLinkOperations
from app.modules.maintenance.application.file_links import MaintenanceFileLinkValidator
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
from app.modules.vendors.application.service import ProviderProfileCommand, ProviderService
from app.modules.vendors.infrastructure.unit_of_work import SQLiteProviderUnitOfWork
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
            SQLiteProviderContextReader(),
        ))
        self.journal = WorkJournalService(self.service.unit_of_work)

    def provider(self, status="neutral"):
        providers=ProviderService(SQLiteProviderUnitOfWork(
            self.workspace.paths.database, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
            self.party_operations, SQLitePortfolioLeaseOperations(self.workspace.paths.database),
        ))
        return providers.create(PartyCreateCommand("organization", "Fast Plumbing"), ProviderProfileCommand(status, selection_reason="Legacy concern" if status == "avoid" else None))["party"]["id"]

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
        journal_entry = self.journal.record(issue["id"], WorkJournalCreate(
            None, "work_completed", "operator_observation", datetime.now(UTC).isoformat(), "Backup repair completed",
            outcome_status="completed", outcome_summary="The repair is complete.", follow_up_required=False, operator_verified=True,
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
        restored_journal = WorkJournalService(restored.unit_of_work)
        journal_page = restored_journal.issue_journal(issue["id"])
        self.assertEqual([journal_entry["id"]], [item["id"] for item in journal_page["items"]])
        self.assertEqual("work_completed", detail["actualWorkCompleted"]["effectiveKind"])
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

    def test_append_only_work_journal_correction_and_terminal_history(self) -> None:
        issue = self.issue()
        start = self.journal.record(issue["id"], WorkJournalCreate(
            None, "work_started", "operator_observation", datetime.now(UTC).isoformat(), "Work began",
        ), str(uuid4()))
        completed = self.journal.record(issue["id"], WorkJournalCreate(
            None, "work_completed", "operator_observation", datetime.now(UTC).isoformat(), "Repair completed",
            outcome_status="completed", outcome_summary="Leak stopped", follow_up_required=False, operator_verified=True,
        ), str(uuid4()))
        correction = self.journal.record(issue["id"], WorkJournalCreate(
            None, "correction", "operator_observation", datetime.now(UTC).isoformat(), "Corrected completion",
            outcome_status="partially_completed", outcome_summary="Leak reduced", follow_up_required=True, operator_verified=True,
            corrects_entry_id=completed["id"], corrected_entry_kind="work_completed", correction_reason="Initial observation overstated repair",
        ), str(uuid4()))
        page = self.journal.issue_journal(issue["id"])
        states = {item["id"]: item["isEffective"] for item in page["items"]}
        self.assertTrue(states[start["id"]]); self.assertFalse(states[completed["id"]]); self.assertTrue(states[correction["id"]])
        with self.assertRaises(MaintenanceConflictError):
            self.journal.record(issue["id"], WorkJournalCreate(
                None, "correction", "operator_observation", datetime.now(UTC).isoformat(), "Second correction",
                outcome_status="completed", outcome_summary="No leak", follow_up_required=False, operator_verified=True,
                corrects_entry_id=completed["id"], corrected_entry_kind="work_completed", correction_reason="Duplicate",
            ), str(uuid4()))
        self.service.transition(issue["id"], "resolve", "Issue addressed", True)
        with self.assertRaises(MaintenanceConflictError):
            self.journal.record(issue["id"], WorkJournalCreate(None, "general_note", "other_report", datetime.now(UTC).isoformat(), "Late note"), str(uuid4()))
        historical = self.journal.record(issue["id"], WorkJournalCreate(None, "general_note", "other_report", datetime.now(UTC).isoformat(), "Late note", historical_entry_confirmed=True), str(uuid4()))
        self.assertEqual(historical["entryKind"], "general_note")
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                with self.assertRaises(Exception):
                    connection.execute(text("DELETE FROM maintenance_work_journal_entries WHERE id=:id"), {"id": start["id"]})
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
            journal = client.post(f"/api/maintenance-issues/{created.json()['id']}/work-journal", json={
                "entryKind": "work_completed", "sourceKind": "operator_observation",
                "occurredAtUtc": datetime.now(UTC).isoformat(), "summary": "Outlet repaired",
                "outcomeStatus": "completed", "outcomeSummary": "Cover secured.",
                "followUpRequired": False, "operatorVerified": True,
                "idempotencyKey": str(uuid4()),
            })
            self.assertEqual(journal.status_code, 201, journal.text)
            detail = client.get(f"/api/maintenance-issues/{created.json()['id']}")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(1, detail.json()["workJournalEntryCount"])
            self.assertEqual("work_completed", detail.json()["actualWorkCompleted"]["effectiveKind"])

    def test_quotes_assignments_replacement_and_avoid_override(self) -> None:
        issue = self.issue(); provider = self.provider(); today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        quote = self.service.create_quote(issue["id"], QuoteCreate(provider, "Standard repair", "Replace the failed valve.", "125.00", today), str(uuid4()))
        assignment = self.service.create_assignment(issue["id"], AssignmentCreate(provider, quote["id"]), str(uuid4()))
        replacement = self.service.create_assignment(issue["id"], AssignmentCreate(provider, quote["id"], replaces_assignment_id=assignment["id"], replacement_confirmed=True, end_reason="Reissued authorization"), str(uuid4()))
        self.assertEqual(replacement["replacesAssignmentId"], assignment["id"])
        self.assertEqual(self.service.quote_comparison(issue["id"])["quotes"][0]["id"], quote["id"])
        avoided = self.provider("avoid")
        with self.assertRaises(MaintenanceConflictError):
            self.service.create_assignment(issue["id"], AssignmentCreate(avoided, selection_reason="Emergency", direct_assignment_confirmed=True), str(uuid4()))
        self.workspace.open()

    def test_quote_schedule_dates_are_paired_and_persisted(self) -> None:
        issue = self.issue(); provider = self.provider(); today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        quote = self.service.create_quote(issue["id"], QuoteCreate(
            provider, "Scheduled repair", "Repair the valve.", "125.00", today.isoformat(),
            earliest_work_start_on=(today + timedelta(days=2)).isoformat(),
            estimated_work_finish_on=(today + timedelta(days=4)).isoformat(),
        ), str(uuid4()))
        self.assertEqual((today + timedelta(days=2)).isoformat(), quote["earliestWorkStartOn"])
        with self.assertRaises(MaintenanceError):
            QuoteCreate(provider, "Incomplete", "Scope.", "1.00", today.isoformat(), earliest_work_start_on=today.isoformat())
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "UPDATE maintenance_quotes SET earliest_work_start_on=:on WHERE id=:id",
                ), {"on": (today + timedelta(days=3)).isoformat(), "id": quote["id"]})
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_work_journal_audit_history_is_exact_and_orphans_fail_validation(self) -> None:
        issue = self.issue()
        entry = self.journal.record(issue["id"], WorkJournalCreate(
            None, "general_note", "operator_observation", datetime.now(UTC).isoformat(), "Journal note",
        ), str(uuid4()))
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                event = connection.execute(text(
                    "SELECT occurred_at, before_snapshot, after_snapshot, changed_fields, reason, actor_kind, "
                    "actor_reference, correlation_id, schema_version FROM audit_events "
                    "WHERE entity_type='maintenance_work_journal_entry' AND entity_id=:id"
                ), {"id": entry["id"]}).mappings().one()
                connection.execute(text(
                    "INSERT INTO audit_events (id, occurred_at, entity_type, entity_id, action, before_snapshot, "
                    "after_snapshot, changed_fields, reason, actor_kind, actor_reference, correlation_id, schema_version) "
                    "VALUES (:id, :occurred_at, 'maintenance_work_journal_entry', :entry_id, 'created', "
                    ":before_snapshot, :after_snapshot, :changed_fields, :reason, :actor_kind, :actor_reference, "
                    ":correlation_id, :schema_version)"
                ), {**dict(event), "id": str(uuid4()), "entry_id": entry["id"]})
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
            with engine.begin() as connection:
                connection.execute(text("DROP TRIGGER audit_events_no_delete"))
                connection.execute(text("DELETE FROM audit_events WHERE entity_type='maintenance_work_journal_entry' AND entity_id=:id AND id != (SELECT min(id) FROM audit_events WHERE entity_type='maintenance_work_journal_entry' AND entity_id=:id)"), {"id": entry["id"]})
                connection.execute(text("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"))
                connection.execute(text("DROP TRIGGER audit_events_no_update"))
                connection.execute(text("UPDATE audit_events SET after_snapshot='{}' WHERE entity_type='maintenance_work_journal_entry' AND entity_id=:id"), {"id": entry["id"]})
                connection.execute(text("CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"))
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_missing_work_journal_audit_and_future_occurrence_fail_restore_validation(self) -> None:
        issue = self.issue()
        entry = self.journal.record(issue["id"], WorkJournalCreate(
            None, "general_note", "operator_observation", datetime.now(UTC).isoformat(), "Journal note",
        ), str(uuid4()))
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.execute(text("DROP TRIGGER audit_events_no_delete"))
                connection.execute(text("DELETE FROM audit_events WHERE entity_type='maintenance_work_journal_entry' AND entity_id=:id"), {"id": entry["id"]})
                connection.execute(text("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"))
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

        # A separate clean workspace checks the retained future-occurrence
        # relationship rather than relying on command-time validation alone.
        fresh = tempfile.TemporaryDirectory(); self.addCleanup(fresh.cleanup)
        other = WorkspaceService(LocalConfig(Path(fresh.name) / "config.json", Path(fresh.name) / "workspace"))
        other.initialize()
        other.config.config_path.write_text(json.dumps({"localWorkspacePath": str(other.paths.root)}), encoding="utf-8")
        recorder = AuditRecorder(SQLiteAuditRepository(other.paths.database))
        portfolio = PortfolioService(SQLitePortfolioUnitOfWork(other.paths.database, recorder), time_zone_resolver=BundledAddressTimeZoneResolver())
        property_record = portfolio.create_property(PropertyCreateCommand("Future validation home", "1 Main Street", "Portland", "US", "single_family_home", (OwnershipInput("local_operator"),), region="OR"))
        service = MaintenanceService(SQLiteMaintenanceUnitOfWork(other.paths.database, recorder, SQLitePortfolioContextReader(), SQLiteExpenseContextReader(), SQLiteTaskContextReader(), SQLiteTaskTransactionOperations(), SQLiteFileLinkReader(), SQLitePartyOperations(other.paths.database), SQLiteLeaseContextReader(), SQLiteCommunicationLinkReader(), SQLiteProviderContextReader()))
        second_issue = service.create_issue(IssueCreate(property_record.id, None, "Future entry", "Validate retained future occurrence.", "plumbing", None, "normal", datetime.now(UTC).isoformat(), ReporterAttribution("manager", "local_operator")), str(uuid4()))
        second_entry = WorkJournalService(service.unit_of_work).record(second_issue["id"], WorkJournalCreate(None, "general_note", "operator_observation", datetime.now(UTC).isoformat(), "Recorded note"), str(uuid4()))
        second_engine = create_sqlite_engine(other.paths.database)
        try:
            with second_engine.begin() as connection:
                connection.execute(text("DROP TRIGGER maintenance_work_journal_entries_no_update"))
                connection.execute(text("UPDATE maintenance_work_journal_entries SET occurred_at_utc=:at WHERE id=:id"), {"at": (datetime.now(UTC) + timedelta(minutes=6)).isoformat(), "id": second_entry["id"]})
                connection.execute(text("CREATE TRIGGER maintenance_work_journal_entries_no_update BEFORE UPDATE ON maintenance_work_journal_entries BEGIN SELECT RAISE(ABORT, 'maintenance work journal entries are immutable'); END"))
            with self.assertRaises(WorkspaceError):
                other.open()
        finally:
            second_engine.dispose()

    def test_orphaned_work_journal_audit_fails_restore_validation(self) -> None:
        issue = self.issue()
        entry = self.journal.record(issue["id"], WorkJournalCreate(
            None, "general_note", "operator_observation", datetime.now(UTC).isoformat(), "Journal note",
        ), str(uuid4()))
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                source = connection.execute(text(
                    "SELECT occurred_at, before_snapshot, after_snapshot, changed_fields, reason, actor_kind, "
                    "actor_reference, correlation_id, schema_version FROM audit_events "
                    "WHERE entity_type='maintenance_work_journal_entry' AND entity_id=:id"
                ), {"id": entry["id"]}).mappings().one()
                connection.execute(text(
                    "INSERT INTO audit_events (id, occurred_at, entity_type, entity_id, action, before_snapshot, "
                    "after_snapshot, changed_fields, reason, actor_kind, actor_reference, correlation_id, schema_version) "
                    "VALUES (:id, :occurred_at, 'maintenance_work_journal_entry', :entry_id, 'created', "
                    ":before_snapshot, :after_snapshot, :changed_fields, :reason, :actor_kind, :actor_reference, "
                    ":correlation_id, :schema_version)"
                ), {**dict(source), "id": str(uuid4()), "entry_id": str(uuid4())})
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_work_journal_link_rules_and_all_entry_evidence_count(self) -> None:
        issue = self.issue()
        entries = [self.journal.record(issue["id"], WorkJournalCreate(
            None, "general_note", "operator_observation", datetime.now(UTC).isoformat(), f"Note {index}",
        ), str(uuid4())) for index in range(11)]
        engine = create_sqlite_engine(self.workspace.paths.database)
        file_id, link_id = str(uuid4()), str(uuid4())
        try:
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO file_records (id, original_name, media_type, size_bytes, content_sha256, created_at) VALUES (:id, 'report.txt', 'text/plain', 1, :hash, :at)"), {"id": file_id, "hash": "a" * 64, "at": datetime.now(UTC).isoformat()})
                connection.execute(text("INSERT INTO file_links (id, file_id, entity_type, entity_id, purpose, created_at) VALUES (:id, :file, 'maintenance_work_journal_entry', :entry, 'supporting_document', :at)"), {"id": link_id, "file": file_id, "entry": entries[0]["id"], "at": datetime.now(UTC).isoformat()})
            detail = self.service.detail(issue["id"])
            self.assertEqual(1, detail["activeCompletionEvidenceCount"])
            journal_page = self.journal.issue_journal(issue["id"])
            linked = next(item for item in journal_page["items"] if item["id"] == entries[0]["id"])
            self.assertEqual(link_id, linked["files"][0]["id"])
            with engine.begin() as connection:
                connection.execute(text("UPDATE file_links SET purpose='not_allowed' WHERE id=:id"), {"id": link_id})
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_provider_work_journal_uses_assignment_snapshot_and_start_timing(self) -> None:
        issue = self.issue()
        provider = self.provider()
        today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        quote = self.service.create_quote(issue["id"], QuoteCreate(
            provider, "Repair quote", "Repair the affected fixture.", "100.00", today,
        ), str(uuid4()))
        assignment = self.service.create_assignment(issue["id"], AssignmentCreate(provider, quote["id"]), str(uuid4()))
        self.journal.record(issue["id"], WorkJournalCreate(
            assignment["id"], "work_started", "provider_report", datetime.now(UTC).isoformat(), "Provider started work",
        ), str(uuid4()))
        page = self.journal.provider_history(provider)
        item = page["items"][0]
        self.assertEqual("Fast Plumbing", item["providerDisplayNameSnapshot"])
        self.assertEqual(assignment["id"], item["assignmentId"])
        self.assertIsNotNone(item["recordedAssignmentToWorkStartSeconds"])

    def test_superseded_work_journal_entries_reject_new_evidence_at_creation_and_restore(self) -> None:
        issue = self.issue()
        original = self.journal.record(issue["id"], WorkJournalCreate(
            None, "work_completed", "operator_observation", datetime.now(UTC).isoformat(), "First completion",
            outcome_status="completed", outcome_summary="Original outcome", follow_up_required=False, operator_verified=True,
        ), str(uuid4()))
        correction = self.journal.record(issue["id"], WorkJournalCreate(
            None, "correction", "operator_observation", datetime.now(UTC).isoformat(), "Corrected completion",
            outcome_status="partially_completed", outcome_summary="Correction outcome", follow_up_required=True, operator_verified=True,
            corrects_entry_id=original["id"], corrected_entry_kind="work_completed", correction_reason="New evidence changed the conclusion",
        ), str(uuid4()))
        validator = MaintenanceFileLinkValidator(SQLiteMaintenanceFileLinkOperations(SQLiteFileLinkReader()))
        engine = create_sqlite_engine(self.workspace.paths.database)
        file_id = str(uuid4())
        try:
            with engine.begin() as connection:
                with self.assertRaises(ValueError):
                    validator.validate_create(connection, FileLink(
                        id=str(uuid4()), entity_type="maintenance_work_journal_entry", entity_id=original["id"],
                        purpose="completion_photo", created_at=datetime.now(UTC).isoformat(), file_id=file_id,
                    ))
                connection.execute(text("INSERT INTO file_records (id, original_name, media_type, size_bytes, content_sha256, created_at) VALUES (:id, 'new-proof.txt', 'text/plain', 1, :hash, :at)"), {"id": file_id, "hash": "b" * 64, "at": datetime.now(UTC).isoformat()})
                connection.execute(text("INSERT INTO file_links (id, file_id, entity_type, entity_id, purpose, created_at) VALUES (:id, :file, 'maintenance_work_journal_entry', :entry, 'completion_photo', :at)"), {"id": str(uuid4()), "file": file_id, "entry": original["id"], "at": (datetime.fromisoformat(correction["recordedAtUtc"]) + timedelta(seconds=1)).isoformat()})
            with self.assertRaises(WorkspaceError):
                self.workspace.open()
        finally:
            engine.dispose()

    def test_quote_replacement_is_single_use_and_audit_snapshots_detect_tampering(self) -> None:
        issue = self.issue(); provider = self.provider(); today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        original = self.service.create_quote(issue["id"], QuoteCreate(provider, "Original", "Original scope.", "100.00", today), str(uuid4()))
        self.service.withdraw_quote(original["id"], "Provider corrected the offer.", True)
        self.service.create_quote(issue["id"], QuoteCreate(provider, "Replacement", "Corrected scope.", "120.00", today, replaces_quote_id=original["id"]), str(uuid4()))
        with self.assertRaisesRegex(MaintenanceConflictError, "already has a replacement") as error:
            self.service.create_quote(issue["id"], QuoteCreate(provider, "Duplicate", "Duplicate scope.", "130.00", today, replaces_quote_id=original["id"]), str(uuid4()))
        self.assertEqual("quote_replaced", error.exception.code)
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.execute(text("UPDATE maintenance_quotes SET amount_minor=999 WHERE id=:id"), {"id": original["id"]})
            with self.assertRaises(WorkspaceError): self.workspace.open()
        finally: engine.dispose()

    def test_quote_comparison_orders_active_nonexpired_before_expired_and_withdrawn_and_surfaces_current_state(self) -> None:
        issue = self.issue(); provider = self.provider(); today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        expired = self.service.create_quote(issue["id"], QuoteCreate(provider, "Expired", "Expired scope.", "1.00", (today - timedelta(days=2)).isoformat(), (today - timedelta(days=1)).isoformat()), str(uuid4()))
        valid = self.service.create_quote(issue["id"], QuoteCreate(provider, "Valid", "Valid scope.", "100.00", today.isoformat(), today.isoformat()), str(uuid4()))
        withdrawn = self.service.create_quote(issue["id"], QuoteCreate(provider, "Withdrawn", "Withdrawn scope.", "2.00", today.isoformat()), str(uuid4()))
        self.service.withdraw_quote(withdrawn["id"], "No longer offered.", True)
        self.portfolio.archive_party(provider, confirmed=True)
        comparison = self.service.quote_comparison(issue["id"])["quotes"]
        self.assertEqual([valid["id"], expired["id"], withdrawn["id"]], [item["id"] for item in comparison])
        self.assertEqual("archived", comparison[0]["currentPartyState"])
        detail = self.service.detail(issue["id"])
        self.assertEqual("archived", detail["quotes"][0]["currentPartyState"])

    def test_quote_comparison_uses_only_its_bounded_projection_and_document_counts(self) -> None:
        issue = self.issue(); provider = self.provider(); today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        quote = self.service.create_quote(issue["id"], QuoteCreate(provider, "Minimal", "Minimal comparison scope.", "75.00", today), str(uuid4()))
        class Unused:
            def __getattr__(self, _name): raise AssertionError("comparison must not load unrelated projections")
        class CountOnlyFiles:
            def __init__(self, delegate): self.delegate, self.calls = delegate, []
            def active_link_counts_for_entities(self, connection, entity_type, entity_ids):
                self.calls.append((entity_type, tuple(entity_ids))); return self.delegate.active_link_counts_for_entities(connection, entity_type, entity_ids)
        files = CountOnlyFiles(self.service.unit_of_work.files)
        self.service.unit_of_work.files = files
        self.service.unit_of_work.portfolio = Unused(); self.service.unit_of_work.finance = Unused(); self.service.unit_of_work.tasks = Unused(); self.service.unit_of_work.communications = Unused()
        comparison = self.service.quote_comparison(issue["id"])
        self.assertEqual(quote["id"], comparison["quotes"][0]["id"])
        self.assertEqual(0, comparison["quotes"][0]["documentCount"])
        self.assertEqual([("maintenance_quote", (quote["id"],))], files.calls)

    def test_default_list_projection_has_a_constant_budget_without_quote_assignment_file_or_provider_reads(self) -> None:
        issues = [self.issue() for _ in range(3)]
        provider = self.provider(); today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        quote = self.service.create_quote(issues[0]["id"], QuoteCreate(provider, "Listed", "Listed quote scope.", "50.00", today), str(uuid4()))
        self.service.create_assignment(issues[0]["id"], AssignmentCreate(provider, quote["id"]), str(uuid4()))
        class FileSpy:
            def __init__(self, delegate): self.delegate, self.calls = delegate, []
            def links_for_entities(self, connection, entity_type, entity_ids):
                self.calls.append(entity_type); return self.delegate.links_for_entities(connection, entity_type, entity_ids)
            def active_link_counts_for_entity_groups(self, connection, entity_ids_by_type):
                self.calls.append("summary_counts"); return self.delegate.active_link_counts_for_entity_groups(connection, entity_ids_by_type)
        class FailingProviders:
            def profile_contexts(self, *_args): raise AssertionError("list must not read provider state")
        class FailingFinance:
            def expense_contexts(self, *_args): raise AssertionError("list must not load expense contexts")
        spy = FileSpy(self.service.unit_of_work.files)
        self.service.unit_of_work.files = spy; self.service.unit_of_work.providers = FailingProviders(); self.service.unit_of_work.finance = FailingFinance()
        import app.modules.maintenance.infrastructure.unit_of_work as adapter
        engine = create_sqlite_engine(self.workspace.paths.database); statements = []; original = adapter.create_engine
        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"): statements.append(args[2].upper())
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch.object(adapter, "create_engine", return_value=engine):
                first = len(statements); self.service.list_issues(page_size=1); one = len(statements) - first
                first = len(statements); self.service.list_issues(page_size=3); three = len(statements) - first
        finally:
            event.remove(engine, "before_cursor_execute", capture); engine.dispose()
        self.assertEqual(one, three)
        self.assertFalse(any("MAINTENANCE_QUOTE" in statement and "SELECT" in statement and "SCOPE_SUMMARY" in statement for statement in statements))
        self.assertFalse(any("MAINTENANCE_ASSIGNMENT" in statement and "MAINTENANCE_QUOTE" in statement for statement in statements))
        self.assertFalse(any("EXPENSES" in statement or "EXPENSE_REFUNDS" in statement for statement in statements))
        self.assertNotIn("maintenance_quote", spy.calls)
        self.assertNotIn("maintenance_assignment", spy.calls)
        self.assertEqual(2, spy.calls.count("summary_counts"))

    def test_quote_and_assignment_http_contract(self) -> None:
        provider = self.provider()
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            issue = client.post("/api/maintenance-issues", json={"propertyId": self.property_id, "summary": "Faucet", "description": "Faucet is dripping continuously.", "category": "plumbing", "priority": "normal", "reportedAtUtc": datetime.now(UTC).isoformat(), "reporter": {"role": "manager", "subjectKind": "local_operator"}, "idempotencyKey": str(uuid4())}).json()
            quote = client.post(f"/api/maintenance-issues/{issue['id']}/quotes", json={"providerPartyId": provider, "label": "Repair", "scopeSummary": "Repair faucet cartridge.", "amount": "85.00", "receivedOn": datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat(), "idempotencyKey": str(uuid4())})
            self.assertEqual(quote.status_code, 201, quote.text)
            assignment = client.post(f"/api/maintenance-issues/{issue['id']}/assignments", json={"providerPartyId": provider, "quoteId": quote.json()["id"], "idempotencyKey": str(uuid4())})
            self.assertEqual(assignment.status_code, 201, assignment.text)
            comparison = client.get(f"/api/maintenance-issues/{issue['id']}/quote-comparison")
            self.assertEqual(comparison.status_code, 200)
            self.assertNotIn("files", comparison.json()["quotes"][0])
            self.assertEqual(client.post(f"/api/maintenance-quotes/{quote.json()['id']}/withdraw", json={"confirmed": True, "reason": "Corrected quote."}).status_code, 200)
            replacement = {"providerPartyId": provider, "label": "Replacement", "scopeSummary": "Repair with corrected parts.", "amount": "90.00", "receivedOn": datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat(), "replacesQuoteId": quote.json()["id"], "idempotencyKey": str(uuid4())}
            self.assertEqual(client.post(f"/api/maintenance-issues/{issue['id']}/quotes", json=replacement).status_code, 201)
            duplicate = {**replacement, "idempotencyKey": str(uuid4())}
            response = client.post(f"/api/maintenance-issues/{issue['id']}/quotes", json=duplicate)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"]["code"], "quote_replaced")
