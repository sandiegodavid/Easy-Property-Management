from __future__ import annotations
import tempfile
import unittest
from datetime import UTC, datetime, date
from pathlib import Path
from sqlalchemy import select, text
from app.bootstrap.owner_concern_context import SQLiteOwnerConcernContext
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.owner_management.application.service import OwnerConcernService
from app.modules.owner_management.domain.models import ConcernCreateCommand, FollowUpInput, OwnerConcernConflictError
from app.modules.owner_management.infrastructure.unit_of_work import SQLiteOwnerConcernPropertyArchiveGuard, SQLiteOwnerConcernUnitOfWork
from app.modules.owner_management.infrastructure.sqlalchemy_models import OwnerConcernModel
from app.modules.portfolio.application.service import OwnershipInput, PartyCreateCommand, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig

class OwnerConcernTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        self.workspace=WorkspaceService(LocalConfig(root/"config.json",root/"workspace"));self.workspace.initialize();audit=AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database))
        self.portfolio=PortfolioService(SQLitePortfolioUnitOfWork(self.workspace.paths.database,audit,(),(SQLiteOwnerConcernPropertyArchiveGuard(),)),time_zone_resolver=BundledAddressTimeZoneResolver())
        self.owner=self.portfolio.create_party(PartyCreateCommand("individual","Morgan Owner"))
        self.property=self.portfolio.create_property(PropertyCreateCommand("Maple","10 Maple Street","Portland","US","single_family_home",(OwnershipInput("client_owner",self.owner.id),),region="OR",postal_code="97201"))
        self.service=OwnerConcernService(SQLiteOwnerConcernUnitOfWork(self.workspace.paths.database,audit,SQLiteOwnerConcernContext(SQLiteTaskTransactionOperations())),now=lambda:datetime(2026,9,21,23,tzinfo=UTC)); self.raised_at=f"{date.today().isoformat()}T00:00:00+00:00"
    def _command(self, **overrides):
        values=dict(owner_party_id=self.owner.id,property_id=self.property.id,concern_type="general_rental",summary="Concern",description="Details",raised_at_utc=f"{date.today().isoformat()}T20:00:00+00:00",idempotency_key="00000000-0000-4000-8000-000000009001")
        values.update(overrides);return ConcernCreateCommand(**values)
    def _delete_audit(self, where, values):
        with self.service.unit_of_work.engine.begin() as connection:
            connection.execute(text("DROP TRIGGER audit_events_no_delete"))
            connection.execute(text(f"DELETE FROM audit_events WHERE {where}"), values)
            connection.execute(text("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"))
    def test_create_follow_up_lifecycle_and_archive_guard(self):
        item=self.service.create(self._command(follow_up=FollowUpInput("Call owner")))
        self.assertEqual(item["status"],"open");self.assertEqual(len(item["followUpTasks"]),1)
        self.workspace.open()
        with self.assertRaises(Exception): self.portfolio.archive_property(self.property.id,confirmed=True)
        resolved=self.service.transition(item["id"],"resolved",confirmed=True,narrative="Handled")
        self.assertEqual(resolved["status"],"resolved")
        self.workspace.open()
        self.portfolio.archive_property(self.property.id,confirmed=True)
    def test_duplicate_requires_confirmation_and_idempotency_is_stable(self):
        first=self.service.create(self._command())
        repeated=self.service.create(self._command())
        self.assertEqual(first["id"],repeated["id"])
        with self.assertRaises(OwnerConcernConflictError):
            self.service.create(self._command(idempotency_key="00000000-0000-4000-8000-000000009002"))
        second=self.service.create(self._command(idempotency_key="00000000-0000-4000-8000-000000009003",duplicate_confirmed=True,duplicate_reason="Separate call"))
        self.assertNotEqual(first["id"],second["id"])
    def test_cursor_uses_priority_time_and_id_ordering(self):
        created=[]
        for number, priority in enumerate(("low","urgent","normal","high"), start=10):
            created.append(self.service.create(self._command(
                idempotency_key=f"00000000-0000-4000-8000-0000000090{number}", priority=priority,
                duplicate_confirmed=bool(number > 10), duplicate_reason="Independent" if number > 10 else None,
            )))
        first, cursor = self.service.list(page_size=2)
        second, final = self.service.list(page_size=2, cursor=cursor)
        self.assertIsNone(final)
        self.assertEqual({item["id"] for item in first + second}, {item["id"] for item in created})
    def test_space_context_only_snapshots_vacancy_state(self):
        space_id=self.portfolio.get_property(self.property.id)["spaces"][0]["id"]
        general=self.service.create(self._command(space_id=space_id))
        self.assertIsNone(general["observedOccupancyStatus"])
        vacancy=self.service.create(self._command(idempotency_key="00000000-0000-4000-8000-000000009099",concern_type="vacancy",space_id=space_id,duplicate_confirmed=True,duplicate_reason="Different concern"))
        self.assertIsNotNone(vacancy["observedOccupancyStatus"])
    def test_reopen_does_not_revalidate_archived_historical_sources(self):
        space_id=self.portfolio.get_property(self.property.id)["spaces"][0]["id"]
        item=self.service.create(self._command(space_id=space_id))
        self.service.transition(item["id"],"resolved",confirmed=True,narrative="Closed")
        with self.service.unit_of_work.engine.begin() as connection:
            connection.execute(text("UPDATE parties SET archived_at='2026-09-21T00:00:00+00:00' WHERE id=:id"),{"id":self.owner.id})
            connection.execute(text("UPDATE spaces SET status='archived' WHERE id=:id"),{"id":space_id})
        reopened=self.service.transition(item["id"],"open",confirmed=True,narrative="New information")
        self.assertEqual(reopened["status"],"open")

    def test_restore_rejects_missing_lifecycle_and_patch_audits(self):
        item = self.service.create(self._command())
        self.service.patch(item["id"], {"summary": "Updated concern"})
        self._delete_audit("entity_type='owner_concern' AND entity_id=:id AND action='updated'", {"id": item["id"]})
        with self.assertRaises(Exception):
            self.workspace.open()

    def test_restore_rejects_missing_terminal_and_replacement_audits(self):
        source = self.service.create(self._command())
        self.service.transition(source["id"], "dismissed", confirmed=True, narrative="Wrong property")
        replacement = self.service.create(self._command(
            idempotency_key="00000000-0000-4000-8000-000000009088",
            replaces_concern_id=source["id"],
            duplicate_confirmed=True,
            duplicate_reason="Replacement",
        ))
        self._delete_audit("entity_type='owner_concern' AND entity_id=:id AND action='status_changed'", {"id": source["id"]})
        with self.assertRaises(Exception):
            self.workspace.open()
        self.assertIsNotNone(replacement["id"])

    def test_restore_rejects_active_status_rewrite_without_audit(self):
        item=self.service.create(self._command())
        with self.service.unit_of_work.engine.begin() as connection:
            connection.execute(text("UPDATE owner_concerns SET status='in_progress' WHERE id=:id"),{"id":item["id"]})
        with self.assertRaises(Exception): self.workspace.open()

    def test_restore_rejects_reverting_audited_active_status_without_event(self):
        item=self.service.create(self._command())
        self.service.transition(item["id"],"in_progress",confirmed=True)
        with self.service.unit_of_work.engine.begin() as connection:
            connection.execute(text("UPDATE owner_concerns SET status='open' WHERE id=:id"),{"id":item["id"]})
        with self.assertRaises(Exception): self.workspace.open()

    def test_restore_rejects_deleted_intermediate_lifecycle_event(self):
        item = self.service.create(self._command())
        self.service.transition(item["id"], "in_progress", confirmed=True)
        self.service.transition(item["id"], "open", confirmed=True)
        self._delete_audit(
            "entity_type='owner_concern' AND entity_id=:id AND action='status_changed' "
            "AND json_extract(after_snapshot, '$.status')='in_progress'",
            {"id": item["id"]},
        )
        with self.assertRaises(Exception):
            self.workspace.open()

    def test_restore_rejects_deleted_intermediate_patch_event(self):
        item = self.service.create(self._command())
        self.service.patch(item["id"], {"summary": "First revision"})
        self.service.patch(item["id"], {"description": "Second revision"})
        self._delete_audit(
            "entity_type='owner_concern' AND entity_id=:id AND action='updated' "
            "AND json_extract(after_snapshot, '$.summary')='First revision'",
            {"id": item["id"]},
        )
        with self.assertRaises(Exception):
            self.workspace.open()

    def test_detail_follow_ups_are_bounded_and_projected(self):
        item=self.service.create(self._command())
        for number in range(25):
            self.service.follow_up(item["id"],FollowUpInput(f"Follow-up {number}"),f"00000000-0000-4000-8000-{number + 9100:012d}")
        detail=self.service.get(item["id"])
        self.assertEqual(len(detail["followUpTasks"]),20)
        self.assertEqual(set(detail["followUpTasks"][0]),{"id","status","title","dueAtUtc"})
