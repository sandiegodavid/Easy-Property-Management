from __future__ import annotations

import tempfile
import unittest
import json
from datetime import date, timedelta
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.leases.application.service import (
    LeaseCreateCommand,
    LeasePatchCommand,
    LeaseService,
    ParticipantCommand,
    RenewalCommand,
    TermCommand,
    TerminationCaseCommand,
    TerminationProposalCommand,
)
from app.modules.leases.application.file_links import LeaseFileLinkValidator
from app.modules.leases.application.ports import LeaseConflictError
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseUnitOfWork
from app.modules.files.application.service import FileError, FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.tenants.application.service import TenantCreateCommand, TenantService
from app.modules.tenants.infrastructure.unit_of_work import SQLiteTenantProfileAvailability, SQLiteTenantUnitOfWork
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations, SQLitePartyReadOperations
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.platform.config import LocalConfig


class LeaseTerminationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        config_path = root / "config.json"
        config_path.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8")
        self.workspace = WorkspaceService(LocalConfig(config_path, root / "workspace"))
        self.workspace.initialize()
        audit = SQLiteAuditRepository(self.workspace.paths.database)
        recorder = AuditRecorder(audit)
        self.portfolio = PortfolioService(SQLitePortfolioUnitOfWork(self.workspace.paths.database, recorder))
        property_record = self.portfolio.create_property(PropertyCreateCommand(
            "Relocation home", "1 Main Street", "Portland", "US", "single_family_home",
            (OwnershipInput("local_operator"),),
        ))
        self.space_id = self.portfolio.get_property(property_record.id)["spaces"][0]["id"]
        self.tenants = TenantService(
            SQLiteTenantUnitOfWork(
                self.workspace.paths.database, recorder, SQLiteLeaseParticipationGuard(),
                SQLitePartyOperations(self.workspace.paths.database),
                SQLitePartyReadOperations(SQLitePartyOperations(self.workspace.paths.database)),
            ), SharedPartyFactory()
        )
        tenant = self.tenants.create(TenantCreateCommand("individual", "Relocating Tenant"))
        self.tenant_id = tenant["id"]
        self.audit = audit
        self.service = LeaseService(SQLiteLeaseUnitOfWork(
            self.workspace.paths.database, recorder, SQLiteTenantProfileAvailability(),
            SQLitePortfolioLeaseOperations(self.workspace.paths.database),
        ))
        today = date.today()
        self.lease = self.service.create(LeaseCreateCommand(
            self.space_id, "residential", today, today + timedelta(days=365), today,
            TermCommand(200_000, "USD", "monthly", 1, 200_000),
            (ParticipantCommand(self.tenant_id, "primary_tenant"),),
        ))
        self.lease = self.service.execute(self.lease["id"], executed_on=today, confirmed=True)

    def _new_draft(self, *, starts_on: date | None = None) -> dict[str, object]:
        start = starts_on or date.today()
        return self.service.create(LeaseCreateCommand(
            self.space_id, "residential", start, start + timedelta(days=365), start,
            TermCommand(210_000, "USD", "monthly", 1, 210_000),
            (ParticipantCommand(self.tenant_id, "primary_tenant"),),
        ))

    def _move_executed_lease_to_yesterday(self, *, contract_ends_on: date) -> None:
        yesterday = date.today() - timedelta(days=1)
        database = self.workspace.paths.database
        with self.service.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE leases SET contract_starts_on=:start, contract_ends_on=:end, "
                "occupancy_starts_on=:start WHERE id=:lease"
            ), {"start": yesterday.isoformat(), "end": contract_ends_on.isoformat(), "lease": self.lease["id"]})
            connection.execute(text(
                "UPDATE lease_term_versions SET effective_on=:start, ends_on=:end WHERE lease_id=:lease"
            ), {"start": yesterday.isoformat(), "end": contract_ends_on.isoformat(), "lease": self.lease["id"]})
            connection.execute(text(
                "UPDATE lease_participants SET starts_on=:start, ends_on=:end WHERE lease_id=:lease"
            ), {"start": yesterday.isoformat(), "end": contract_ends_on.isoformat(), "lease": self.lease["id"]})
            connection.execute(text(
                "UPDATE space_occupancy_periods SET starts_on=:start WHERE source_kind='lease' AND source_id=:lease"
            ), {"start": yesterday.isoformat(), "lease": self.lease["id"]})

    def test_accepting_job_relocation_case_does_not_create_vacancy(self) -> None:
        today = date.today()
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today + timedelta(days=45), today + timedelta(days=40),
            "Employer is relocating the tenant.", "Early termination section",
        ))
        proposal = self.service.add_termination_proposal(case["id"], TerminationProposalCommand(
            today + timedelta(days=45), today + timedelta(days=40),
            rent_responsibility_ends_on=today + timedelta(days=45),
            termination_fee_minor=100_000, currency_code="usd", access_arrangement="24-hour notice",
        ))
        accepted = self.service.accept_termination_proposal(
            case["id"], proposal["proposals"][0]["id"], accepted_on=today, confirmed=True,
        )
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(self.service.get(self.lease["id"])["status"], "executed")
        self.assertEqual(self.service.get(self.lease["id"])["occupancyState"], "current")
        events = self.audit.history(correlation_id=self.audit.history("lease_termination_case", case["id"])[-1].correlation_id)
        self.assertEqual({event.entity_type for event in events}, {"lease_termination_case", "lease_termination_proposal"})

    def test_completed_lease_vacancy_can_be_superseded_by_the_next_lease(self) -> None:
        today = date.today()
        self._move_executed_lease_to_yesterday(contract_ends_on=today)
        ended = self.service.end(self.lease["id"], actual_move_out_on=today, confirmed=True)
        self.assertEqual(ended["status"], "ended")
        successor = self._new_draft(starts_on=today)
        executed = self.service.execute(successor["id"], executed_on=today, confirmed=True)
        self.assertEqual(executed["status"], "executed")
        self.assertEqual(executed["occupancyState"], "current")

    def test_completed_termination_vacancy_can_be_superseded_by_the_next_lease(self) -> None:
        today = date.today()
        self._move_executed_lease_to_yesterday(contract_ends_on=today + timedelta(days=90))
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today, today,
        ))
        proposed = self.service.add_termination_proposal(case["id"], TerminationProposalCommand(today, today))
        self.service.accept_termination_proposal(
            case["id"], proposed["proposals"][0]["id"], accepted_on=today, confirmed=True,
        )
        completed = self.service.complete_termination_case(
            case["id"], actual_move_out_on=today, confirmed=True,
        )
        self.assertEqual(completed["status"], "terminated")
        successor = self._new_draft(starts_on=today)
        self.assertEqual(
            self.service.execute(successor["id"], executed_on=today, confirmed=True)["status"],
            "executed",
        )

    def test_execution_rechecks_active_tenant_profiles(self) -> None:
        draft = self._new_draft(starts_on=date.today() + timedelta(days=1))
        # Simulate a concurrent/external lifecycle change after draft validation.
        with self.service.unit_of_work.engine.begin() as connection:
            connection.execute(
                text("UPDATE tenant_profiles SET archived_at=:now WHERE party_id=:party"),
                {"now": "2026-01-01T00:00:00+00:00", "party": self.tenant_id},
            )
        with self.assertRaises(LeaseConflictError):
            self.service.execute(draft["id"], executed_on=date.today(), confirmed=True)

    def test_draft_date_patch_keeps_the_initial_term_aligned(self) -> None:
        tomorrow = date.today() + timedelta(days=1)
        draft = self._new_draft(starts_on=tomorrow)
        new_end = tomorrow + timedelta(days=400)
        updated = self.service.patch(draft["id"], LeasePatchCommand(
            contract_ends_on=new_end,
            supplied_fields=frozenset({"contract_ends_on"}),
        ))
        self.assertEqual(updated["contractEndsOn"], new_end.isoformat())
        self.assertEqual(updated["terms"][0]["endsOn"], new_end.isoformat())

    def test_contract_and_renewal_due_filters_are_available(self) -> None:
        today = date.today()
        due = today + timedelta(days=10)
        self.service.add_renewal_option(self.lease["id"], RenewalCommand(
            today + timedelta(days=365), response_due_on=due,
        ))
        self.assertEqual(self.service.list(contract_start_from=today), [self.service.get(self.lease["id"])])
        self.assertEqual(self.service.list(renewal_due_on_or_before=due - timedelta(days=1)), [])
        self.assertEqual(
            [item["id"] for item in self.service.list(renewal_due_on_or_before=due)],
            [self.lease["id"]],
        )

    def test_ordinary_end_rejects_early_move_out(self) -> None:
        tomorrow = date.today() + timedelta(days=1)
        self._move_executed_lease_to_yesterday(contract_ends_on=tomorrow)
        with self.assertRaises(LeaseConflictError):
            self.service.end(self.lease["id"], actual_move_out_on=date.today(), confirmed=True)

    def test_termination_case_review_and_decline_close_open_proposals(self) -> None:
        today = date.today()
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today + timedelta(days=30), today + timedelta(days=30),
        ))
        reviewed = self.service.transition_termination_case(case["id"], status="under_review")
        self.assertEqual(reviewed["status"], "under_review")
        proposed = self.service.add_termination_proposal(case["id"], TerminationProposalCommand(
            today + timedelta(days=30), today + timedelta(days=30),
        ))
        declined = self.service.transition_termination_case(
            case["id"], status="declined", operator_notes="Request declined after review."
        )
        self.assertEqual(declined["status"], "declined")
        self.assertEqual(declined["proposals"][0]["status"], "rejected")

    def test_termination_reason_must_match_the_accepted_case(self) -> None:
        today = date.today()
        self._move_executed_lease_to_yesterday(contract_ends_on=today + timedelta(days=90))
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today, today,
        ))
        proposal = self.service.add_termination_proposal(case["id"], TerminationProposalCommand(today, today))
        self.service.accept_termination_proposal(
            case["id"], proposal["proposals"][0]["id"], accepted_on=today, confirmed=True,
        )
        with self.assertRaises(LeaseConflictError):
            self.service.terminate(
                self.lease["id"], actual_move_out_on=today,
                end_reason="mutual_termination", confirmed=True,
            )

    def test_database_rejects_unknown_lease_end_reason(self) -> None:
        with self.assertRaises(IntegrityError):
            with self.service.unit_of_work.engine.begin() as connection:
                connection.execute(text(
                    "UPDATE leases SET status='ended', actual_move_out_on='2099-01-01', "
                    "end_reason='unrecognized' WHERE id=:id"
                ), {"id": self.lease["id"]})

    def test_database_rejects_end_reason_that_conflicts_with_status(self) -> None:
        invalid_pairs = (
            ("ended", "mutual_termination"),
            ("terminated", "contract_completed"),
            ("ended", None),
            ("terminated", None),
        )
        for status, end_reason in invalid_pairs:
            with self.subTest(status=status, end_reason=end_reason):
                with self.assertRaises(IntegrityError):
                    with self.service.unit_of_work.engine.begin() as connection:
                        connection.execute(
                            text(
                                "UPDATE leases SET status=:status, "
                                "actual_move_out_on='2099-01-01', end_reason=:end_reason "
                                "WHERE id=:id"
                            ),
                            {
                                "id": self.lease["id"],
                                "status": status,
                                "end_reason": end_reason,
                            },
                        )

    def test_lease_history_and_documents_round_trip_through_backup_restore(self) -> None:
        today = date.today()
        self.service.add_renewal_option(self.lease["id"], RenewalCommand(
            today + timedelta(days=365), notice_due_on=today + timedelta(days=30),
        ))
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today + timedelta(days=45), today + timedelta(days=40),
        ))
        proposal = self.service.add_termination_proposal(case["id"], TerminationProposalCommand(
            today + timedelta(days=45), today + timedelta(days=40),
        ))
        self.service.accept_termination_proposal(
            case["id"], proposal["proposals"][0]["id"], accepted_on=today, confirmed=True,
        )
        source = Path(self.temp.name) / "relocation-letter.pdf"
        source.write_bytes(b"relocation support")
        files = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)),
            link_validators=(LeaseFileLinkValidator(self.service.unit_of_work),),
        )
        files.add(source, source.name, "application/pdf", entity_type="lease_termination_case",
                  entity_id=case["id"], purpose="relocation_support")

        archive = Path(self.temp.name) / "lease.epm-backup"
        backups = BackupService(
            self.workspace,
            AuditRecorder(self.audit),
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        backups.create_backup("a sufficiently long test passphrase", output_path=archive)
        restored_root = Path(self.temp.name) / "restored"
        backups.restore(archive, "a sufficiently long test passphrase", restored_root)

        restored_audit = SQLiteAuditRepository(restored_root / "database" / "property-management.sqlite")
        restored = LeaseService(SQLiteLeaseUnitOfWork(
            restored_root / "database" / "property-management.sqlite",
            AuditRecorder(restored_audit),
            SQLiteTenantProfileAvailability(),
            SQLitePortfolioLeaseOperations(restored_root / "database" / "property-management.sqlite"),
        ))
        lease = restored.get(self.lease["id"])
        restored_case = restored.get_termination_case(case["id"])
        self.assertEqual(len(lease["terms"]), 1)
        self.assertEqual(len(lease["participants"]), 1)
        self.assertEqual(len(lease["renewalOptions"]), 1)
        self.assertEqual(restored_case["status"], "accepted")
        self.assertEqual(restored_case["files"][0]["purpose"], "relocation_support")
        self.assertTrue(restored_audit.history("space_occupancy"))
        self.assertTrue(restored_audit.history("lease_termination_proposal", proposal["proposals"][0]["id"]))

    def test_lease_file_links_require_an_existing_target_and_allowed_purpose(self) -> None:
        source = Path(self.temp.name) / "lease.pdf"
        source.write_bytes(b"lease")
        files = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)),
            link_validators=(LeaseFileLinkValidator(self.service.unit_of_work),),
        )
        for entity_id, purpose in (("missing", "executed_lease"), (self.lease["id"], "receipt")):
            with self.assertRaises(FileError):
                files.add(source, "lease.pdf", "application/pdf", entity_type="lease",
                          entity_id=entity_id, purpose=purpose)
        stored = files.add(source, "lease.pdf", "application/pdf", entity_type="lease",
                           entity_id=self.lease["id"], purpose="executed_lease")
        self.assertEqual(stored.original_name, "lease.pdf")

        today = date.today()
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today + timedelta(days=30), today + timedelta(days=30),
        ))
        files.add(source, "relocation-letter.pdf", "application/pdf",
                  entity_type="lease_termination_case", entity_id=case["id"],
                  purpose="relocation_support")
        refreshed = self.service.get_termination_case(case["id"])
        self.assertEqual(refreshed["files"][0]["originalName"], "relocation-letter.pdf")

    def test_lease_api_maps_malformed_missing_conflict_and_rule_errors(self) -> None:
        from app.bootstrap.api import create_app

        with TestClient(create_app(self.workspace.config.config_path)) as client:
            malformed = client.post("/api/leases", json={"leaseKind": "residential"})
            missing = client.get("/api/leases/missing")
            conflict = client.post(
                f"/api/leases/{self.lease['id']}/execute",
                json={"executedOn": date.today().isoformat(), "confirmed": True},
            )
            rule = client.post(
                f"/api/leases/{self.lease['id']}/end",
                json={"actualMoveOutOn": (date.today() + timedelta(days=1)).isoformat(), "confirmed": True},
            )
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(rule.status_code, 400)


if __name__ == "__main__":
    unittest.main()
