"""SQLite-backed INSP-001 workflow regressions."""
from __future__ import annotations
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from sqlalchemy import text
from fastapi.testclient import TestClient
from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.inspections.application.service import AreaInput, InspectionConflictError, InspectionService, ObservationInput
from app.modules.inspections.infrastructure.unit_of_work import SQLiteInspectionUnitOfWork
from app.modules.leases.application.service import LeaseCreateCommand, LeaseService, ParticipantCommand, TermCommand
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseUnitOfWork
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.tenants.application.service import TenantCreateCommand, TenantService
from app.modules.tenants.infrastructure.unit_of_work import SQLiteTenantUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.platform.config import LocalConfig


class InspectionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace", backup_destination_path=root / "backups")); self.workspace.initialize()
        self.audit = SQLiteAuditRepository(self.workspace.paths.database); self.recorder = AuditRecorder(self.audit)
        portfolio = PortfolioService(SQLitePortfolioUnitOfWork(self.workspace.paths.database, self.recorder))
        property_record = portfolio.create_property(PropertyCreateCommand("Home", "1 Main", "Portland", "US", "single_family_home", (OwnershipInput("local_operator"),)))
        self.space_id = portfolio.get_property(property_record.id)["spaces"][0]["id"]
        tenants = TenantService(SQLiteTenantUnitOfWork(self.workspace.paths.database, self.recorder), SharedPartyFactory())
        tenant = tenants.create(TenantCreateCommand("individual", "Tenant"))
        co_tenant = tenants.create(TenantCreateCommand("individual", "Co tenant"))
        today = date.today(); self.leases = LeaseService(SQLiteLeaseUnitOfWork(self.workspace.paths.database, self.recorder))
        draft = self.leases.create(LeaseCreateCommand(self.space_id, "residential", today, today + timedelta(days=30), today, TermCommand(100000,"USD","monthly",1,0), (ParticipantCommand(tenant["id"],"primary_tenant"), ParticipantCommand(co_tenant["id"],"co_tenant"))))
        self.lease = self.leases.execute(draft["id"], executed_on=today, confirmed=True)
        self.files = FileService(self.workspace, FilesystemContentStore(self.workspace.paths.files), SQLiteFileUnitOfWork(self.workspace.paths.database, self.recorder))
        self.inspections = InspectionService(SQLiteInspectionUnitOfWork(self.workspace.paths.database, self.recorder), self.files)
        self.backups = BackupService(self.workspace, self.recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database)))
        self.checklist = (AreaInput("Kitchen", (ObservationInput("Floor", "good", is_completed=True),)),)

    def _finalize_pre(self):
        report = self.inspections.create(self.lease["id"], report_kind="pre_move_in", walkthrough_on=date.today(), conducted_by="Operator", areas=self.checklist)
        self.inspections.acknowledge(report["id"], self._acknowledge_all(report))
        return self.inspections.finalize(report["id"], confirmed=True)

    @staticmethod
    def _acknowledge_all(report):
        return {
            item["leaseParticipantId"]: {"status": "acknowledged"}
            for item in report["acknowledgments"]
        }

    def test_pre_post_correction_and_pair_scoped_comparison_history(self):
        pre = self._finalize_pre()
        with self.leases.unit_of_work.engine.begin() as connection:
            connection.execute(text("UPDATE leases SET status='ended', actual_move_out_on=:day, end_reason='contract_completed' WHERE id=:id"), {"day": date.today().isoformat(), "id": self.lease["id"]})
        post = self.inspections.create(self.lease["id"], report_kind="post_move_out", walkthrough_on=date.today(), conducted_by="Operator", areas=self.checklist)
        self.inspections.acknowledge(post["id"], self._acknowledge_all(post))
        post = self.inspections.finalize(post["id"], confirmed=True)
        pre_observation = pre["areas"][0]["observations"][0]["id"]; post_observation = post["areas"][0]["observations"][0]["id"]
        self.inspections.save_comparisons(self.lease["id"], [{"pre_observation_id": pre_observation, "post_observation_id": post_observation, "comparison_state":"unchanged", "operator_notes":None}])
        correction = self.inspections.create(self.lease["id"], report_kind="pre_move_in", walkthrough_on=date.today(), conducted_by="Operator", areas=self.checklist, correction_of=pre["id"], correction_reason="Corrected photo")
        self.inspections.acknowledge(correction["id"], self._acknowledge_all(correction))
        correction = self.inspections.finalize(correction["id"], confirmed=True)
        corrected_observation = correction["areas"][0]["observations"][0]["id"]
        current = self.inspections.save_comparisons(self.lease["id"], [{"pre_observation_id": corrected_observation, "post_observation_id": post_observation, "comparison_state":"normal_wear", "operator_notes":None}])
        self.assertEqual(current[0]["preReportId"], correction["id"])
        rows = self.inspections.unit_of_work.write(lambda tx: tx.comparisons(self.lease["id"]))
        self.assertEqual(len(rows), 2)
        self.assertGreaterEqual(len(self.audit.history("condition_comparison")), 2)

    def test_configured_generic_file_api_rejects_inspection_evidence_links(self):
        config = Path(self.temp.name) / "api-config.json"
        config.write_text(json.dumps({"localWorkspacePath": str(Path(self.temp.name) / "api-workspace")}), encoding="utf-8")
        with TestClient(create_app(config)) as client:
            self.assertEqual(client.post("/api/workspace/initialize").status_code, 201)
            response = client.post("/api/files", data={"entity_type":"condition_observation", "entity_id":"observation", "purpose":"condition_photo"}, files={"file": ("evidence.txt", b"evidence", "text/plain")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("No owning-domain validator", response.json()["detail"])

    def test_post_move_out_draft_precedes_confirmed_move_out_but_cannot_finalize(self):
        report = self.inspections.create(self.lease["id"], report_kind="post_move_out", walkthrough_on=date.today(), conducted_by="Operator", areas=self.checklist)
        self.assertEqual(report["status"], "draft")
        self.inspections.acknowledge(report["id"], self._acknowledge_all(report))
        with self.assertRaises(InspectionConflictError): self.inspections.finalize(report["id"], confirmed=True)

    def test_inspection_dataset_evidence_and_correlated_audit_round_trip_through_backup(self):
        template = self.inspections.create_template(
            display_name="Move-in checklist",
            applicability="residential",
            areas=self.checklist,
        )
        pre = self.inspections.create(
            self.lease["id"],
            report_kind="pre_move_in",
            walkthrough_on=date.today(),
            conducted_by="Operator",
            template_id=template["id"],
        )
        self.assertEqual(pre["areas"][0]["observations"][0]["itemName"], "Floor")
        pre = self.inspections.replace_areas(pre["id"], self.checklist)
        observation_id = pre["areas"][0]["observations"][0]["id"]
        evidence_source = Path(self.temp.name) / "move-in-photo.txt"
        evidence_source.write_bytes(b"move-in evidence")
        evidence = self.inspections.attach_evidence(
            observation_id,
            evidence_source,
            "move-in-photo.txt",
            "text/plain",
            "condition_photo",
        )
        self.assertEqual(evidence["links"][0]["entityType"], "condition_observation")
        pre = self.inspections.acknowledge(pre["id"], self._acknowledge_all(pre))
        pre = self.inspections.finalize(pre["id"], confirmed=True)
        with self.leases.unit_of_work.engine.begin() as connection:
            connection.execute(text("UPDATE leases SET status='ended', actual_move_out_on=:day, end_reason='contract_completed' WHERE id=:id"), {"day": date.today().isoformat(), "id": self.lease["id"]})
        post = self.inspections.create(
            self.lease["id"],
            report_kind="post_move_out",
            walkthrough_on=date.today(),
            conducted_by="Operator",
            areas=self.checklist,
        )
        post = self.inspections.acknowledge(post["id"], self._acknowledge_all(post))
        post = self.inspections.finalize(post["id"], confirmed=True)
        comparisons = self.inspections.save_comparisons(self.lease["id"], [{
            "pre_observation_id": pre["areas"][0]["observations"][0]["id"],
            "post_observation_id": post["areas"][0]["observations"][0]["id"],
            "comparison_state": "unchanged",
            "operator_notes": None,
        }])
        attachment_events = self.audit.history(entity_id=observation_id, action="evidence_attached")
        file_events = self.audit.history(entity_type="file", entity_id=evidence["id"])
        link_events = self.audit.history(entity_type="file_link", entity_id=evidence["links"][0]["id"])
        self.assertEqual({event.correlation_id for event in attachment_events + file_events + link_events}, {attachment_events[0].correlation_id})

        backup = self.backups.create_backup("a long test backup passphrase")
        restored_path = Path(self.temp.name) / "restored-workspace"
        self.backups.restore(backup.archive_path, "a long test backup passphrase", restored_path)
        with sqlite3.connect(restored_path / "database" / "property-management.sqlite") as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM condition_checklist_templates").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM condition_checklist_template_items").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM condition_reports").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM condition_report_acknowledgments").fetchone()[0], 4)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM condition_comparisons").fetchone()[0], len(comparisons))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events WHERE correlation_id=?", (attachment_events[0].correlation_id,)).fetchone()[0], 3)
        restored_workspace = WorkspaceService(LocalConfig(Path(self.temp.name) / "restored-config.json", restored_path))
        restored_database = restored_workspace.paths.database
        restored_inspections = InspectionService(
            SQLiteInspectionUnitOfWork(restored_database, AuditRecorder(SQLiteAuditRepository(restored_database)))
        )
        restored_files = FileService(
            restored_workspace,
            FilesystemContentStore(restored_workspace.paths.files),
            SQLiteFileUnitOfWork(restored_database, AuditRecorder(SQLiteAuditRepository(restored_database))),
        )
        restored_pre = restored_inspections.get(pre["id"])
        restored_observation = restored_pre["areas"][0]["observations"][0]
        self.assertEqual(restored_observation["id"], observation_id)
        self.assertEqual(restored_observation["files"], [evidence])
        restored_file = restored_files.get(evidence["id"])
        self.assertEqual(restored_file.content_sha256, evidence["contentSha256"])
        self.assertEqual(restored_file.storage_state, "available")
        self.assertEqual(restored_file.links, tuple(evidence["links"]))
        self.assertEqual(restored_files.content_path(restored_file).read_bytes(), b"move-in evidence")
