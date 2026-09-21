from __future__ import annotations
import tempfile
import unittest
from datetime import UTC, datetime, date
from pathlib import Path
from sqlalchemy import select
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
    def test_create_follow_up_lifecycle_and_archive_guard(self):
        item=self.service.create(self._command(follow_up=FollowUpInput("Call owner")))
        self.assertEqual(item["status"],"open");self.assertEqual(len(item["followUpTasks"]),1)
        self.workspace.open()
        with self.assertRaises(Exception): self.portfolio.archive_property(self.property.id,confirmed=True)
        resolved=self.service.transition(item["id"],"resolved",confirmed=True,narrative="Handled")
        self.assertEqual(resolved["status"],"resolved")
        self.portfolio.archive_property(self.property.id,confirmed=True)
    def test_duplicate_requires_confirmation_and_idempotency_is_stable(self):
        first=self.service.create(self._command())
        repeated=self.service.create(self._command())
        self.assertEqual(first["id"],repeated["id"])
        with self.assertRaises(OwnerConcernConflictError):
            self.service.create(self._command(idempotency_key="00000000-0000-4000-8000-000000009002"))
        second=self.service.create(self._command(idempotency_key="00000000-0000-4000-8000-000000009003",duplicate_confirmed=True,duplicate_reason="Separate call"))
        self.assertNotEqual(first["id"],second["id"])
