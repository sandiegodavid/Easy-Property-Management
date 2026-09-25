from __future__ import annotations

import tempfile
import unittest
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import event, inspect
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

from app.bootstrap.api import create_app
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
from app.modules.inspections.infrastructure.context_reader import SQLiteInspectionContextReader
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.leases.infrastructure.schema_validation import _normalise, validate_lease_schema
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
from app.modules.portfolio.application.source_timeline import SourceTimelineChangeSet
from app.modules.portfolio.domain.models import SpaceOccupancyPeriod
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError


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
        self.portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(self.workspace.paths.database, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        property_record = self.portfolio.create_property(PropertyCreateCommand(
            "Relocation home", "1 Main Street", "Portland", "US", "single_family_home",
            (OwnershipInput("local_operator"),), region="OR",
        ))
        self.property_id = property_record.id
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
            SQLiteInspectionContextReader(),
        ))
        today = date.today()
        self.lease = self.service.create(LeaseCreateCommand(
            self.space_id, "residential", today, today + timedelta(days=365), today,
            TermCommand(200_000, "USD", "monthly", 1, 200_000),
            (ParticipantCommand(self.tenant_id, "primary_tenant"),),
        ))
        self._execute_revision = self.portfolio.get_space_status(self.space_id)["revision"]
        self._execute_key = str(uuid4())
        self.lease = self.service.execute(
            self.lease["id"], executed_on=today, confirmed=True,
            expected_revision=self._execute_revision, idempotency_key=self._execute_key,
        )

    def _new_draft(self, *, starts_on: date | None = None) -> dict[str, object]:
        start = starts_on or date.today()
        return self.service.create(LeaseCreateCommand(
            self.space_id, "residential", start, start + timedelta(days=365), start,
            TermCommand(210_000, "USD", "monthly", 1, 210_000),
            (ParticipantCommand(self.tenant_id, "primary_tenant"),),
        ))

    def _timeline_kwargs(self) -> dict[str, object]:
        return {
            "expected_revision": self.portfolio.get_space_status(self.space_id)["revision"],
            "idempotency_key": str(uuid4()),
        }

    def _source_change(self, *, replacements, inserts=(), action, expected_revision,
                       idempotency_key, committed_at="2025-01-01T12:00:00+00:00"):
        return SourceTimelineChangeSet(
            space_id=self.space_id, replacements=tuple(replacements), inserts=tuple(inserts),
            source_kind="lease", source_id=self.lease["id"], action=action, expected_revision=expected_revision,
            idempotency_key=idempotency_key, correlation_id="correlation", committed_at=committed_at,
            request_context={"action": action},
        )

    def test_lease_source_timeline_is_replayable_and_advances_one_revision(self) -> None:
        """Lease-owned timeline writes share one revisioned portfolio operation."""
        before = self.portfolio.get_space_status(self.space_id)
        key = "lease-source-timeline-replay"

        def apply(tx):
            period = next(item for item in tx.occupancy_periods(self.space_id)
                          if item.source_kind == "lease" and item.source_id == self.lease["id"])
            changed = replace(period, note="Lease timeline source operation")
            return tx.apply_source_timeline(self._source_change(
                replacements=(changed,), action="test", expected_revision=before["revision"], idempotency_key=key,
            ))

        first = self.service.unit_of_work.write(apply)
        self.assertEqual(first["revision"], before["revision"] + 1)
        self.assertEqual(first["updatedAt"], "2025-01-01T12:00:00+00:00")
        replay = self.service.unit_of_work.write(apply)
        self.assertEqual(replay, first)
        self.assertEqual(self.portfolio.get_space_status(self.space_id)["revision"], first["revision"])

        def changed_reuse(tx):
            period = next(item for item in tx.occupancy_periods(self.space_id)
                          if item.source_kind == "lease" and item.source_id == self.lease["id"])
            return tx.apply_source_timeline(self._source_change(
                replacements=(replace(period, note="Changed request"),), action="test",
                expected_revision=first["revision"], idempotency_key=key,
                committed_at="2025-01-01T12:05:00+00:00",
            ))

        with self.assertRaises(LeaseConflictError):
            self.service.unit_of_work.write(changed_reuse)

    def test_execute_records_post_mutation_inspection_attention_and_replays_it(self) -> None:
        self.assertEqual(self.lease["inspectionAttention"], {
            "preMoveIn": "due", "postMoveOut": "not_due",
        })
        replay = self.service.execute(
            self.lease["id"], executed_on=date.today(), confirmed=True,
            expected_revision=self._execute_revision, idempotency_key=self._execute_key,
        )
        self.assertEqual(replay, self.lease)

    def test_lease_source_timeline_rejects_stale_or_invalid_timeline_before_writing(self) -> None:
        before = self.portfolio.get_space_status(self.space_id)

        def stale(tx):
            period = next(item for item in tx.occupancy_periods(self.space_id)
                          if item.source_kind == "lease" and item.source_id == self.lease["id"])
            return tx.apply_source_timeline(self._source_change(
                replacements=(period,), action="stale", expected_revision=before["revision"] - 1,
                idempotency_key="lease-source-stale", committed_at=datetime.now(UTC).isoformat(),
            ))

        with self.assertRaises(LeaseConflictError) as stale_error:
            self.service.unit_of_work.write(stale)
        self.assertEqual(stale_error.exception.current_status["revision"], before["revision"])

        def invalid(tx):
            period = next(item for item in tx.occupancy_periods(self.space_id)
                          if item.source_kind == "lease" and item.source_id == self.lease["id"])
            invalid_period = replace(period, ends_on=period.starts_on)
            return tx.apply_source_timeline(self._source_change(
                replacements=(invalid_period,), action="invalid", expected_revision=before["revision"],
                idempotency_key="lease-source-invalid",
            ))

        with self.assertRaises(LeaseConflictError):
            self.service.unit_of_work.write(invalid)
        self.assertEqual(self.portfolio.get_space_status(self.space_id)["revision"], before["revision"])

    def test_source_change_set_validates_non_http_concurrency_inputs_and_linkage(self) -> None:
        before = self.portfolio.get_space_status(self.space_id)["revision"]

        def invalid_key(tx):
            period = next(item for item in tx.occupancy_periods(self.space_id)
                          if item.source_kind == "lease" and item.source_id == self.lease["id"])
            return tx.apply_source_timeline(self._source_change(
                replacements=(period,), action="invalid-key", expected_revision=True, idempotency_key=" ",
            ))

        with self.assertRaises(LeaseConflictError):
            self.service.unit_of_work.write(invalid_key)

        period = next(item for item in self.service.unit_of_work.write(
            lambda tx: tx.occupancy_periods(self.space_id)
        ) if item.source_kind == "lease" and item.source_id == self.lease["id"])
        successor = SpaceOccupancyPeriod(
            str(uuid4()), self.space_id, "occupied", period.starts_on, None, "valid", None,
            "lease", self.lease["id"], "successor", "2025-01-01T12:00:00+00:00", None, None,
        )
        linked = SourceTimelineChangeSet(
            space_id=self.space_id, replacements=(replace(period, superseded_by_id=successor.id),),
            inserts=(successor,), source_kind="lease", source_id=self.lease["id"], action="linkage",
            expected_revision=before, idempotency_key="linkage", correlation_id="correlation",
            committed_at="2025-01-01T12:00:00+00:00", request_context={},
        )
        unlinked = replace(linked, replacements=(replace(period, superseded_by_id=None),))
        self.assertNotEqual(linked.fingerprint(), unlinked.fingerprint())

    def test_execute_close_and_void_each_commit_one_source_revision(self) -> None:
        today = date.today()
        self._move_executed_lease_to_yesterday(contract_ends_on=today)
        before = self.portfolio.get_space_status(self.space_id)["revision"]
        ended = self.service.end(self.lease["id"], actual_move_out_on=today, confirmed=True,
                                 **self._timeline_kwargs())
        self.assertEqual(self.portfolio.get_space_status(self.space_id)["revision"], before + 1)

        successor = self._new_draft(starts_on=today + timedelta(days=1))
        executed = self.service.execute(successor["id"], executed_on=today, confirmed=True,
                                        **self._timeline_kwargs())
        self.assertEqual(executed["status"], "executed")
        self.assertEqual(self.portfolio.get_space_status(self.space_id)["revision"], before + 2)

        voided = self.service.void(successor["id"], confirmed=True, **self._timeline_kwargs())
        self.assertEqual(voided["status"], "void")
        self.assertEqual(self.portfolio.get_space_status(self.space_id)["revision"], before + 3)

    def test_close_replays_the_recorded_operation_before_lifecycle_validation(self) -> None:
        today = date.today()
        self._move_executed_lease_to_yesterday(contract_ends_on=today)
        revision = self.portfolio.get_space_status(self.space_id)["revision"]
        key = str(uuid4())
        first = self.service.end(
            self.lease["id"], actual_move_out_on=today, confirmed=True,
            expected_revision=revision, idempotency_key=key,
        )
        replay = self.service.end(
            self.lease["id"], actual_move_out_on=today, confirmed=True,
            expected_revision=revision, idempotency_key=key,
        )
        self.assertEqual(first["inspectionAttention"]["postMoveOut"], "due")
        self.assertEqual(replay, first)
        with self.assertRaises(LeaseConflictError):
            self.service.end(
                self.lease["id"], actual_move_out_on=today + timedelta(days=1), confirmed=True,
                expected_revision=revision, idempotency_key=key,
            )

    def test_terminate_records_post_mutation_inspection_attention_and_replays_it(self) -> None:
        today = date.today()
        self._move_executed_lease_to_yesterday(contract_ends_on=today + timedelta(days=90))
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today, today,
        ))
        proposal = self.service.add_termination_proposal(case["id"], TerminationProposalCommand(today, today))
        self.service.accept_termination_proposal(
            case["id"], proposal["proposals"][0]["id"], accepted_on=today, confirmed=True,
        )
        revision = self.portfolio.get_space_status(self.space_id)["revision"]
        key = str(uuid4())
        first = self.service.terminate(
            self.lease["id"], actual_move_out_on=today, end_reason="early_termination", confirmed=True,
            expected_revision=revision, idempotency_key=key,
        )
        replay = self.service.terminate(
            self.lease["id"], actual_move_out_on=today, end_reason="early_termination", confirmed=True,
            expected_revision=revision, idempotency_key=key,
        )
        self.assertEqual(first["inspectionAttention"]["postMoveOut"], "due")
        self.assertEqual(replay, first)

    def test_source_timeline_rolls_back_with_the_lease_transaction(self) -> None:
        before = self.portfolio.get_space_status(self.space_id)["revision"]

        def abort_after_source_write(tx):
            period = next(item for item in tx.occupancy_periods(self.space_id)
                          if item.source_kind == "lease" and item.source_id == self.lease["id"])
            tx.apply_source_timeline(self._source_change(
                replacements=(replace(period, note="must roll back"),), action="rollback",
                expected_revision=before, idempotency_key="lease-source-rollback",
            ))
            raise RuntimeError("abort the enclosing lease transaction")

        with self.assertRaisesRegex(RuntimeError, "abort the enclosing"):
            self.service.unit_of_work.write(abort_after_source_write)
        self.assertEqual(self.portfolio.get_space_status(self.space_id)["revision"], before)

    def test_context_reader_returns_raw_lease_facts_with_bounded_batch_reads(self) -> None:
        reader = SQLiteLeaseContextReader()
        term = self.lease["terms"][0]
        draft = self._new_draft()
        draft_term = draft["terms"][0]
        statements = []
        engine = self.service.unit_of_work.engine
        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with engine.connect() as connection:
                context = reader.term_context(connection, self.lease["id"], term["id"])
                self.assertEqual(context["lease"]["status"], "executed")
                self.assertEqual(context["term"]["agreed_security_deposit_minor"], 200_000)
                self.assertEqual(context["term"]["currency_code"], "USD")
                self.assertEqual(reader.lease_space_id(connection, self.lease["id"]), self.space_id)
                self.assertTrue(reader.participant_active(connection, self.lease["id"], self.tenant_id, date.today().isoformat()))
                self.assertEqual(reader.participant_ids(connection, self.lease["id"]), {self.tenant_id})
                self.assertIsNone(reader.term_context(connection, "missing", term["id"]))
                self.assertEqual(reader.term_context(connection, draft["id"], draft_term["id"])["lease"]["status"], "draft")

                start = len(statements)
                contexts = reader.term_contexts(connection, {
                    (self.lease["id"], term["id"]), (draft["id"], draft_term["id"]), ("missing", "missing"),
                })
                self.assertEqual(set(contexts), {(self.lease["id"], term["id"]), (draft["id"], draft_term["id"])})
                self.assertEqual(len(statements) - start, 3)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    def test_property_participant_context_requires_occupied_eligible_lease_and_uses_end_exclusive_dates(self) -> None:
        reader = SQLiteLeaseContextReader()
        today = date.today()
        tomorrow = today + timedelta(days=1)
        draft = self._new_draft(starts_on=tomorrow)
        engine = self.service.unit_of_work.engine
        with engine.begin() as connection:
            # A participant's end date is exclusive.
            connection.execute(text(
                "UPDATE lease_participants SET ends_on=:end WHERE lease_id=:lease"
            ), {"end": tomorrow.isoformat(), "lease": self.lease["id"]})
            self.assertTrue(reader.participant_active_for_property(
                connection, self.tenant_id, self.property_id, self.space_id, today.isoformat()
            ))
            # This also isolates the draft lease: its occupancy begins
            # tomorrow, after the executed lease's participant has ended.
            self.assertFalse(reader.participant_active_for_property(
                connection, self.tenant_id, self.property_id, self.space_id, tomorrow.isoformat()
            ))
            # A void lease must never establish reporter eligibility.
            connection.execute(text(
                "UPDATE leases SET status='void', executed_on=:executed WHERE id=:lease"
            ), {"executed": today.isoformat(), "lease": draft["id"]})
            self.assertFalse(reader.participant_active_for_property(
                connection, self.tenant_id, self.property_id, self.space_id, tomorrow.isoformat()
            ))

            # Terminated leases remain eligible only before actual move-out.
            yesterday = today - timedelta(days=1)
            connection.execute(text(
                "UPDATE leases SET status='terminated', contract_starts_on=:start, occupancy_starts_on=:start, "
                "actual_move_out_on=:move_out, end_reason='other' WHERE id=:lease"
            ), {"start": yesterday.isoformat(), "move_out": today.isoformat(), "lease": self.lease["id"]})
            connection.execute(text(
                "UPDATE lease_participants SET starts_on=:start, ends_on=NULL WHERE lease_id=:lease"
            ), {"start": yesterday.isoformat(), "lease": self.lease["id"]})
            self.assertTrue(reader.participant_active_for_property(
                connection, self.tenant_id, self.property_id, self.space_id, yesterday.isoformat()
            ))
            self.assertFalse(reader.participant_active_for_property(
                connection, self.tenant_id, self.property_id, self.space_id, today.isoformat()
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
            termination_fee_minor=100_000, currency_code="USD", access_arrangement="24-hour notice",
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
        ended = self.service.end(self.lease["id"], actual_move_out_on=today, confirmed=True,
                                 **self._timeline_kwargs())
        self.assertEqual(ended["status"], "ended")
        successor = self._new_draft(starts_on=today)
        executed = self.service.execute(successor["id"], executed_on=today, confirmed=True,
                                        **self._timeline_kwargs())
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
            case["id"], actual_move_out_on=today, confirmed=True, **self._timeline_kwargs(),
        )
        self.assertEqual(completed["status"], "terminated")
        successor = self._new_draft(starts_on=today)
        self.assertEqual(
            self.service.execute(successor["id"], executed_on=today, confirmed=True,
                                 **self._timeline_kwargs())["status"],
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
            self.service.execute(draft["id"], executed_on=date.today(), confirmed=True,
                                 **self._timeline_kwargs())

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

    def test_term_command_requires_positive_integer_rent_and_ascii_uppercase_currency(self) -> None:
        invalid_rents = (True, 1.0, "100", 0, -1)
        for rent in invalid_rents:
            with self.subTest(rent=rent), self.assertRaises(ValueError):
                TermCommand(rent, "USD", "monthly", 1, 0)
        for currency in ("usd", "US1", "UŠD", "US$"):
            with self.subTest(currency=currency), self.assertRaises(ValueError):
                TermCommand(1, currency, "monthly", 1, 0)

    def test_term_schema_rejects_zero_rent_and_noncanonical_currency(self) -> None:
        for assignment in (
            ("base_rent_minor", 0),
            ("base_rent_minor", 1.5),
            ("currency_code", "usd"),
            ("currency_code", "US1"),
        ):
            column, value = assignment
            with self.subTest(column=column, value=value), self.assertRaises(IntegrityError):
                with self.service.unit_of_work.engine.begin() as connection:
                    connection.execute(
                        text(f"UPDATE lease_term_versions SET {column}=:value WHERE lease_id=:lease"),
                        {"value": value, "lease": self.lease["id"]},
                    )

    def test_lease_api_rejects_noncanonical_term_values_at_request_boundary(self) -> None:
        config = Path(self.temp.name) / "lease-term-api.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}),
            encoding="utf-8",
        )
        payload = {
            "spaceId": self.space_id,
            "leaseKind": "residential",
            "contractStartsOn": date.today().isoformat(),
            "contractEndsOn": (date.today() + timedelta(days=365)).isoformat(),
            "occupancyStartsOn": date.today().isoformat(),
            "participants": [{"tenantPartyId": self.tenant_id, "participantRole": "primary_tenant"}],
            "initialTerm": {
                "baseRentMinor": 0,
                "currencyCode": "USD",
                "paymentFrequency": "monthly",
                "paymentDueDay": 1,
                "agreedSecurityDepositMinor": 0,
            },
        }
        with TestClient(create_app(config)) as client:
            self.assertEqual(client.post("/api/leases", json=payload).status_code, 422)
            payload["initialTerm"]["baseRentMinor"] = 1
            payload["initialTerm"]["currencyCode"] = "usd"
            self.assertEqual(client.post("/api/leases", json=payload).status_code, 422)

    def test_termination_proposal_currency_is_strict_at_every_boundary(self) -> None:
        today = date.today()
        for currency in ("usd", "UŠD", "US1", "US$"):
            with self.subTest(currency=currency), self.assertRaises(ValueError):
                TerminationProposalCommand(today, today, termination_fee_minor=1, currency_code=currency)
        case = self.service.create_termination_case(self.lease["id"], TerminationCaseCommand(
            "job_relocation", today, today + timedelta(days=30), today + timedelta(days=30),
        ))
        proposal = self.service.add_termination_proposal(
            case["id"], TerminationProposalCommand(today + timedelta(days=30), today + timedelta(days=30),
                                                      termination_fee_minor=1, currency_code="USD"),
        )
        proposal_id = proposal["proposals"][0]["id"]
        for currency in ("usd", "UŠD", "US1", "US$"):
            with self.subTest(database_currency=currency), self.assertRaises(IntegrityError):
                with self.service.unit_of_work.engine.begin() as connection:
                    connection.execute(
                        text("UPDATE lease_termination_proposals SET currency_code=:currency WHERE id=:id"),
                        {"currency": currency, "id": proposal_id},
                    )
        config = Path(self.temp.name) / "termination-currency-api.json"
        config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        with TestClient(create_app(config)) as client:
            response = client.post(f"/api/termination-cases/{case['id']}/proposals", json={
                "proposedTerminationOn": (today + timedelta(days=30)).isoformat(),
                "expectedMoveOutOn": (today + timedelta(days=30)).isoformat(),
                "terminationFeeMinor": 1,
                "currencyCode": "usd",
            })
            self.assertEqual(response.status_code, 422)

    def test_schema_normalization_preserves_case_sensitive_glob_literals(self) -> None:
        upper = _normalise("length(currency_code) = 3 AND currency_code GLOB '[A-Z][A-Z][A-Z]'")
        lower = _normalise("length(currency_code) = 3 AND currency_code GLOB '[a-z][a-z][a-z]'")
        self.assertNotEqual(upper, lower)

    def test_schema_validator_rejects_a_lowercase_currency_glob(self) -> None:
        with self.service.unit_of_work.engine.connect() as connection:
            base = inspect(connection)

            class LowercaseGlobInspector:
                def __getattr__(self, name):
                    return getattr(base, name)

                def get_check_constraints(self, table_name, **kwargs):
                    checks = base.get_check_constraints(table_name, **kwargs)
                    if table_name != "lease_term_versions":
                        return checks
                    return [
                        {
                            **check,
                            "sqltext": (check.get("sqltext") or "").replace(
                                "[A-Z][A-Z][A-Z]", "[a-z][a-z][a-z]"
                            ),
                        }
                        for check in checks
                    ]

            with patch(
                "app.modules.leases.infrastructure.schema_validation.inspect",
                return_value=LowercaseGlobInspector(),
            ), self.assertRaises(MigrationSchemaError):
                validate_lease_schema(connection)

    def test_ordinary_end_rejects_early_move_out(self) -> None:
        tomorrow = date.today() + timedelta(days=1)
        self._move_executed_lease_to_yesterday(contract_ends_on=tomorrow)
        with self.assertRaises(LeaseConflictError):
            self.service.end(self.lease["id"], actual_move_out_on=date.today(), confirmed=True,
                             **self._timeline_kwargs())

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
                end_reason="mutual_termination", confirmed=True, **self._timeline_kwargs(),
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

    @fast_backup_encryption()
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
            SQLiteInspectionContextReader(),
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
                json={"executedOn": date.today().isoformat(), "confirmed": True,
                      "expectedRevision": 1, "idempotencyKey": str(uuid4())},
            )
            rule = client.post(
                f"/api/leases/{self.lease['id']}/end",
                json={"actualMoveOutOn": (date.today() + timedelta(days=1)).isoformat(), "confirmed": True,
                      "expectedRevision": 1, "idempotencyKey": str(uuid4())},
            )
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(rule.status_code, 400)


if __name__ == "__main__":
    unittest.main()
