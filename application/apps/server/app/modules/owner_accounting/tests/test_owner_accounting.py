from __future__ import annotations

from app.modules.owner_accounting.tests.commands import owner_command

from app.modules.finance.tests.commands import rent_command


from app.modules.portfolio.tests.commands import inventory_command

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.ports import FileLink
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.finance.application.ports import RecordedReceipt
from app.modules.finance.application.service import FinanceService
from app.modules.finance.domain.models import (
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    RentReceipt,
    SynchronizeExpectationsCommand,
)
from app.modules.finance.infrastructure.receipt_transaction_operations import (
    SQLiteReceiptTransactionOperations,
)
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.inspections.infrastructure.context_reader import SQLiteInspectionContextReader
from app.modules.leases.tests.commands import lease_command
from app.modules.leases.application.service import (
    LeaseCreateCommand,
    LeaseService,
    ParticipantCommand,
    TermCommand,
)
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.leases.infrastructure.unit_of_work import (
    SQLiteLeaseParticipationGuard,
    SQLiteLeaseUnitOfWork,
)
from app.modules.owner_accounting.api.router import build_router
from app.modules.owner_accounting.application.file_links import OwnerRentReportFileLinkValidator
from app.modules.owner_accounting.application.service import OwnerRentReportService
from app.modules.owner_accounting.domain.audit_policy import OWNER_REPORT_ACTIVITY_POLICY
from app.modules.owner_accounting.domain.models import (
    OwnerRentReport,
    OwnerRentReportCommand,
    OwnerReportConflictError,
    VerifyOwnerRentReportCommand,
)
from app.modules.owner_accounting.infrastructure.file_link_facts import (
    SQLiteOwnerRentReportFileLinkFacts,
)
from app.modules.owner_accounting.infrastructure.schema_validation import (
    validate_owner_accounting_schema,
)
from app.modules.owner_accounting.infrastructure.unit_of_work import SQLiteOwnerRentReportUnitOfWork
from app.modules.parties.application.service import PartyCreateCommand, SharedPartyFactory
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
)
from app.modules.portfolio.application.service import (
    OwnershipInput,
    PortfolioService,
    PropertyCreateCommand,
)
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import (
    SQLitePortfolioLeaseOperations,
    SQLitePortfolioUnitOfWork,
)
from app.modules.tenants.application.service import TenantCreateCommand, TenantService
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantProfileAvailability,
    SQLiteTenantUnitOfWork,
)
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.product_migrations import validate_latest_schema


class _Service:
    def __init__(self):
        self.values = None

    def patch(self, report_id, values, key, *, expected_revision=0):
        self.values = (report_id, values, key)
        return {
            "id": report_id,
            "reportRevision": 1,
            "operationId": str(uuid4()),
            "leaseId": str(uuid4()),
            "propertyId": str(uuid4()),
            "spaceId": str(uuid4()),
            "propertyTimezoneSnapshot": "UTC",
            "ownerPartyId": str(uuid4()),
            "ownerDisplayNameSnapshot": "Owner",
            "receivedOn": "2026-01-02",
            "amountMinor": 1250,
            "currencyCode": "USD",
            "paymentMethodKind": "cash",
            "paymentMethodLabel": None,
            "maskedReference": None,
            "otherPaymentMethodNote": None,
            "reportedAtUtc": "2026-01-02T20:00:00+00:00",
            "sourceNote": None,
            "status": "pending",
            "verifiedReceiptId": None,
            "reviewedAt": None,
            "reviewNote": None,
            "replacesReportId": None,
            "createdAt": "2026-01-02T20:00:00+00:00",
            "updatedAt": "2026-01-02T20:00:00+00:00",
            "receiptLifecycleStatus": None,
            "financiallyEffective": False,
            "evidenceCount": 0,
        }

    def create(self, command, *, expected_revision):
        self.created = command
        return self.patch(str(uuid4()), {}, command.idempotency_key)


class OwnerRentReportApiTests(unittest.TestCase):
    def test_patch_translates_contract_fields_to_application_fields(self):
        service = _Service()
        app = FastAPI()
        app.include_router(
            build_router(service, SimpleNamespace(ready=True, error=None, can_write=True))
        )
        report_id, party_id, key = str(uuid4()), str(uuid4()), str(uuid4())
        response = TestClient(app).patch(
            f"/api/owner-rent-reports/{report_id}",
            json={
                "ownerPartyId": party_id,
                "receivedOn": "2026-01-02",
                "amountMinor": 1250,
                "paymentMethodKind": "cash",
                "reportedAtUtc": "2026-01-02T20:00:00+00:00",
                "idempotencyKey": key,
                "expectedRevision": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        _, values, actual_key = service.values
        self.assertEqual(actual_key, key)
        self.assertEqual(values["owner_party_id"], party_id)
        self.assertEqual(values["received_on"], "2026-01-02")
        self.assertEqual(values["amount_minor"], 1250)
        self.assertEqual(values["payment_method_kind"], "cash")
        self.assertEqual(values["reported_at_utc"], "2026-01-02T20:00:00+00:00")

    def test_verify_shape_and_cursor_are_rejected_at_the_api_boundary(self):
        service = _Service()
        app = FastAPI()
        app.include_router(
            build_router(service, SimpleNamespace(ready=True, error=None, can_write=True))
        )
        report_id, key = str(uuid4()), str(uuid4())
        both = TestClient(app).post(
            f"/api/owner-rent-reports/{report_id}/verify",
            json={
                "confirmed": True,
                "reviewNote": "checked",
                "idempotencyKey": key,
                "existingReceiptId": str(uuid4()),
                "receiptIdempotencyKey": str(uuid4()),
            },
        )
        self.assertEqual(both.status_code, 422)
        malformed = TestClient(app).get("/api/owner-rent-reports", params={"cursor": "bad"})
        self.assertEqual(malformed.status_code, 422)

    def test_malformed_dates_and_naive_timestamps_are_rejected_at_the_api_boundary(self):
        service = _Service()
        app = FastAPI()
        app.include_router(
            build_router(service, SimpleNamespace(ready=True, error=None, can_write=True))
        )
        response = TestClient(app).post(
            "/api/owner-rent-reports",
            json={
                "leaseId": str(uuid4()),
                "ownerPartyId": str(uuid4()),
                "receivedOn": "not-a-date",
                "amountMinor": 100,
                "paymentMethodKind": "cash",
                "reportedAtUtc": "2026-01-02T12:00:00",
                "idempotencyKey": str(uuid4()),
                "expectedRevision": 0,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_converts_typed_date_to_the_application_value(self):
        service = _Service()
        app = FastAPI()
        app.include_router(
            build_router(service, SimpleNamespace(ready=True, error=None, can_write=True))
        )
        response = TestClient(app).post(
            "/api/owner-rent-reports",
            json={
                "leaseId": str(uuid4()),
                "ownerPartyId": str(uuid4()),
                "receivedOn": "2026-01-02",
                "amountMinor": 100,
                "paymentMethodKind": "cash",
                "reportedAtUtc": "2026-01-02T12:00:00+00:00",
                "idempotencyKey": str(uuid4()),
                "expectedRevision": 0,
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(service.created.received_on, "2026-01-02")


class OwnerRentReportAuditPolicyTests(unittest.TestCase):
    def test_activity_policy_redacts_report_and_operation_sensitive_fields(self):
        activity = OWNER_REPORT_ACTIVITY_POLICY.redact(
            {
                "status": "verified",
                "amountMinor": 1200,
                "ownerPartyId": "owner",
                "reviewNote": "private",
                "idempotency_key": "key",
                "request_fingerprint": "hash",
            }
        )
        self.assertEqual(activity["status"], "verified")
        for field in (
            "amountMinor",
            "ownerPartyId",
            "reviewNote",
            "idempotency_key",
            "request_fingerprint",
        ):
            self.assertEqual(activity[field], "[redacted]")

    def test_activity_policy_redacts_nested_verification_evidence_identifiers(self):
        activity = OWNER_REPORT_ACTIVITY_POLICY.redact(
            {
                "verificationEvidence": [{"linkId": "link", "fileId": "file", "active": True}],
            }
        )
        evidence = activity["verificationEvidence"][0]
        self.assertEqual(evidence["linkId"], "[redacted]")
        self.assertEqual(evidence["fileId"], "[redacted]")
        self.assertTrue(evidence["active"])


class OwnerRentReportEvidenceTests(unittest.TestCase):
    def test_archiving_unavailable_link_does_not_remove_last_available_evidence(self):
        class Operations:
            def report(self, connection, report_id):
                return SimpleNamespace(status="verified")

            def link_is_active_available(self, connection, link_id):
                return False

            def active_available_link_count(self, connection, entity_type, entity_id):
                return 1

        validator = OwnerRentReportFileLinkValidator(Operations(), Operations())
        validator.validate_archive(
            None,
            FileLink(
                str(uuid4()),
                "owner_rent_report",
                str(uuid4()),
                "supporting_document",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    def test_archiving_last_available_link_is_rejected(self):
        class Operations:
            def report(self, connection, report_id):
                return SimpleNamespace(status="verified")

            def link_is_active_available(self, connection, link_id):
                return True

            def active_available_link_count(self, connection, entity_type, entity_id):
                return 1

        validator = OwnerRentReportFileLinkValidator(Operations(), Operations())
        with self.assertRaises(ValueError):
            validator.validate_archive(
                None,
                FileLink(
                    str(uuid4()),
                    "owner_rent_report",
                    str(uuid4()),
                    "supporting_document",
                    "2026-01-01T00:00:00+00:00",
                ),
            )


class OwnerRentReportVerificationTests(unittest.TestCase):
    def setUp(self):
        self.ids = {
            name: str(uuid4())
            for name in ("report", "lease", "property", "space", "owner", "receipt", "expectation")
        }
        self.report = OwnerRentReport(
            self.ids["report"],
            self.ids["lease"],
            self.ids["property"],
            self.ids["space"],
            "UTC",
            self.ids["owner"],
            "Owner",
            "2026-01-02",
            100,
            "USD",
            "cash",
            None,
            None,
            None,
            "2026-01-02T12:00:00+00:00",
            None,
            "pending",
            None,
            None,
            None,
            None,
            "2026-01-02T12:00:00+00:00",
            "2026-01-02T12:00:00+00:00",
        )
        self.receipt = RentReceipt(
            self.ids["receipt"],
            self.ids["lease"],
            str(uuid4()),
            "2026-01-02",
            100,
            "USD",
            "cash",
            None,
            None,
            None,
            self.ids["owner"],
            None,
            None,
            None,
            None,
            "2026-01-02T12:00:00+00:00",
        )
        self.tx = _VerificationTx(self.report, self.receipt)
        self.service = OwnerRentReportService(
            _OneTxUow(self.tx), now=lambda: datetime(2026, 1, 3, tzinfo=UTC)
        )

    def _command(self):
        return VerifyOwnerRentReportCommand(
            True,
            "Confirmed against statement.",
            None,
            str(uuid4()),
            (ReceiptAllocationCommand(self.ids["expectation"], 100),),
            None,
        )

    def test_creation_mode_rejects_a_reused_finance_idempotency_receipt(self):
        self.tx.recorded = RecordedReceipt(self.receipt, created=False)
        with self.assertRaises(OwnerReportConflictError):
            self.service.verify(
                self.report.id,
                self._command(),
                str(uuid4()),
                expected_revision=0,
                expected_ledger_revision=0,
            )
        self.assertIsNone(self.tx.replaced)

    def test_verification_records_immutable_evidence_snapshot_with_shared_correlation(self):
        self.tx.recorded = RecordedReceipt(self.receipt, created=True)
        self.service.verify(
            self.report.id,
            self._command(),
            str(uuid4()),
            expected_revision=0,
            expected_ledger_revision=0,
        )
        report_event, operation_event = self.tx.changes[-2:]
        self.assertEqual(operation_event["correlation_id"], report_event["correlation_id"])
        self.assertEqual(operation_event["action"], "recorded")
        self.assertEqual(report_event["action"], "verified")
        self.assertEqual(
            report_event["after"]["verificationEvidence"],
            [
                {
                    "linkId": "link",
                    "fileId": "file",
                    "active": True,
                    "available": True,
                }
            ],
        )

    def test_batched_zero_evidence_uses_zero_without_an_individual_count_query(self):
        class BatchTx:
            def evidence_count(self, _):
                raise AssertionError("batch list must not count evidence per report")

        view = self.service._view(
            BatchTx(), self.report, context={"evidence": {}, "receipts": {}, "owners": {}}
        )
        self.assertEqual(view["evidenceCount"], 0)


class OwnerRentReportCommandTests(unittest.TestCase):
    def test_reported_timestamp_is_normalized_to_utc_before_fingerprinting_or_persistence(self):
        command = OwnerRentReportCommand(
            str(uuid4()),
            str(uuid4()),
            "2026-01-02",
            100,
            "cash",
            str(uuid4()),
            "2026-01-02T12:00:00-05:00",
        )
        self.assertEqual(command.reported_at_utc, "2026-01-02T17:00:00+00:00")


class OwnerRentReportSQLiteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        config = root / "config.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8"
        )
        workspace = WorkspaceService(LocalConfig(config, root / "workspace"))
        workspace.initialize()
        self.workspace = workspace
        database = workspace.paths.database
        recorder = AuditRecorder(SQLiteAuditRepository(database))
        parties = SQLitePartyOperations(database)
        portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(database, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        owner = portfolio.create_party(PartyCreateCommand("individual", "Client owner"))
        self.owner_id = owner.id
        property_record = inventory_command(
            portfolio,
            "create_property",
            PropertyCreateCommand(
                "Owner home",
                "1 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (OwnershipInput("client_owner", party_id=owner.id),),
                region="OR",
            ),
        )
        space_id = portfolio.get_property(property_record.id)["spaces"][0]["id"]
        tenant = TenantService(
            SQLiteTenantUnitOfWork(
                database,
                recorder,
                SQLiteLeaseParticipationGuard(),
                parties,
                SQLitePartyReadOperations(parties),
            ),
            SharedPartyFactory(),
        ).create(
            TenantCreateCommand("individual", "Tenant"),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        # Capture one injected instant and derive all business dates from the
        # property's timezone.  This remains correct during UTC/local-date
        # boundaries and prevents a test from crossing midnight mid-run.
        self.now = datetime.now(UTC).replace(microsecond=0)
        today = self.now.astimezone(ZoneInfo("America/Los_Angeles")).date()
        # Start the monthly fixture on its due date. A one-day initial stub is
        # deliberately invalid in FIN-001 and is covered by finance tests.
        if today.day != 1:
            today = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        self.now = datetime.combine(today, datetime.min.time(), UTC) + timedelta(hours=12)
        leases = LeaseService(
            SQLiteLeaseUnitOfWork(
                database,
                recorder,
                SQLiteTenantProfileAvailability(),
                SQLitePortfolioLeaseOperations(database),
                SQLiteInspectionContextReader(),
            )
        )
        lease = lease_command(
            leases,
            "create",
            LeaseCreateCommand(
                space_id,
                "residential",
                today,
                today + timedelta(days=365),
                today,
                TermCommand(100_000, "USD", "monthly", 1, 0),
                (ParticipantCommand(tenant["id"], "primary_tenant"),),
            ),
        )
        self.lease = lease_command(
            leases,
            "execute",
            lease["id"],
            executed_on=today,
            confirmed=True,
            expected_revision=portfolio.get_space_status(space_id)["revision"],
            idempotency_key=str(uuid4()),
        )
        self.recorder, self.database, self.parties = recorder, database, parties
        self.files_reader = SQLiteFileLinkReader()
        self.receipt_operations = SQLiteReceiptTransactionOperations(
            recorder, SQLiteLeaseContextReader(), SQLitePortfolioContextReader(), parties
        )
        self.finance = FinanceService(
            SQLiteFinanceUnitOfWork(
                database,
                recorder,
                SQLiteLeaseContextReader(),
                SQLitePortfolioContextReader(),
                parties,
            ),
            now=lambda: self.now,
        )
        self.service = OwnerRentReportService(
            SQLiteOwnerRentReportUnitOfWork(
                database,
                recorder,
                SQLiteLeaseContextReader(),
                SQLitePortfolioContextReader(),
                parties,
                self.files_reader,
                self.receipt_operations,
            ),
            now=lambda: self.now,
        )
        self.files = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(database, recorder),
            link_validators=(
                OwnerRentReportFileLinkValidator(
                    SQLiteOwnerRentReportFileLinkFacts(), self.files_reader
                ),
            ),
        )

    def _expectation(self):
        term = self.lease["terms"][0]
        rows = rent_command(
            self.finance,
            "synchronize",
            self.lease["id"],
            SynchronizeExpectationsCommand(
                term["id"],
                (
                    self.now.astimezone(ZoneInfo("America/Los_Angeles")).date() + timedelta(days=60)
                ).isoformat(),
                self.now.astimezone(ZoneInfo("America/Los_Angeles"))
                .date()
                .replace(day=1)
                .isoformat(),
            ),
        )
        return rows[0]

    def _report_with_evidence(self, amount, key=None):
        item = owner_command(
            self.service,
            "create",
            OwnerRentReportCommand(
                self.lease["id"],
                self.owner_id,
                self.now.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat(),
                amount,
                "cash",
                key or str(uuid4()),
                self.now.isoformat(),
            ),
        )
        source = Path(self.temp.name) / f"{item['id']}.txt"
        source.write_text("statement", encoding="utf-8")
        self.files.add(
            source,
            "statement.txt",
            "text/plain",
            entity_type="owner_rent_report",
            entity_id=item["id"],
            purpose="owner_statement",
        )
        return item

    def test_create_and_zero_evidence_list_are_transactional_and_batched(self):
        for amount in (100, 101, 102):
            owner_command(
                self.service,
                "create",
                OwnerRentReportCommand(
                    self.lease["id"],
                    self.owner_id,
                    self.now.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat(),
                    amount,
                    "cash",
                    str(uuid4()),
                    self.now.isoformat(),
                ),
            )
        statements = []

        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2].upper())

        engine = self.service.unit_of_work.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            page = self.service.list(page_size=3)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual([item["evidenceCount"] for item in page["items"]], [0, 0, 0])
        self.assertEqual(
            sum("COUNT(" in statement and "FILE_LINKS" in statement for statement in statements), 1
        )

    def test_verification_adopts_existing_receipt_and_retries_idempotently(self):
        expectation = self._expectation()
        receipt = rent_command(
            self.finance,
            "record_receipt",
            RecordReceiptCommand(
                self.lease["id"],
                str(uuid4()),
                self.now.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat(),
                expectation["expectedAmountMinor"],
                "USD",
                (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
                "cash",
                received_by_party_id=self.owner_id,
            ),
        )
        report = self._report_with_evidence(expectation["expectedAmountMinor"])
        key = str(uuid4())
        command = VerifyOwnerRentReportCommand(True, "Matched receipt.", receipt["id"])
        ledger_revision = self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"]
        verified = owner_command(self.service, "verify", report["id"], command, key)
        retried = owner_command(self.service, "verify", report["id"], command, key)
        self.assertEqual(verified["rentLedgerRevision"], ledger_revision)
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"],
            ledger_revision,
        )
        self.assertEqual(verified["reportRevision"], report["reportRevision"] + 1)
        self.assertEqual(retried, verified)
        self.assertEqual(retried["id"], verified["id"])
        with self.service.unit_of_work.engine.connect() as connection:
            operation = (
                connection.execute(
                    text(
                        "SELECT receipt_created, correlation_id FROM owner_rent_report_operations WHERE idempotency_key=:key"
                    ),
                    {"key": key},
                )
                .mappings()
                .one()
            )
            self.assertEqual(operation["receipt_created"], 0)
            self.assertEqual(
                connection.execute(
                    text(
                        "SELECT count(*) FROM audit_events WHERE correlation_id=:id AND entity_type='rent_receipt'"
                    ),
                    {"id": operation["correlation_id"]},
                ).scalar_one(),
                0,
            )

    def test_verification_creates_receipt_allocations_and_correlated_audits(self):
        expectation = self._expectation()
        report = self._report_with_evidence(expectation["expectedAmountMinor"])
        key = str(uuid4())
        verified = owner_command(
            self.service,
            "verify",
            report["id"],
            VerifyOwnerRentReportCommand(
                True,
                "Matched statement.",
                None,
                str(uuid4()),
                (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            ),
            key,
        )
        with self.service.unit_of_work.engine.connect() as connection:
            operation = (
                connection.execute(
                    text(
                        "SELECT receipt_created, result_receipt_id, correlation_id FROM owner_rent_report_operations WHERE idempotency_key=:key"
                    ),
                    {"key": key},
                )
                .mappings()
                .one()
            )
            self.assertEqual(operation["receipt_created"], 1)
            self.assertEqual(operation["result_receipt_id"], verified["verifiedReceiptId"])
            self.assertEqual(
                connection.execute(
                    text(
                        "SELECT count(*) FROM audit_events WHERE correlation_id=:id AND entity_type IN ('rent_receipt','rent_receipt_allocation')"
                    ),
                    {"id": operation["correlation_id"]},
                ).scalar_one(),
                2,
            )
            validate_owner_accounting_schema(connection)

    def test_schema_validation_rejects_tampered_creation_history(self):
        expectation = self._expectation()
        report = self._report_with_evidence(expectation["expectedAmountMinor"])
        owner_command(
            self.service,
            "verify",
            report["id"],
            VerifyOwnerRentReportCommand(
                True,
                "Matched.",
                None,
                str(uuid4()),
                (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            ),
            str(uuid4()),
        )
        with self.service.unit_of_work.engine.begin() as connection:
            correlation = connection.execute(
                text(
                    "SELECT correlation_id FROM owner_rent_report_operations WHERE report_id=:id AND action='verify'"
                ),
                {"id": report["id"]},
            ).scalar_one()
            connection.execute(text("DROP TRIGGER audit_events_no_delete"))
            connection.execute(
                text(
                    "DELETE FROM audit_events WHERE correlation_id=:id AND entity_type='rent_receipt_allocation'"
                ),
                {"id": correlation},
            )
        with self.service.unit_of_work.engine.connect() as connection:
            with self.assertRaisesRegex(Exception, "allocation audit history"):
                validate_owner_accounting_schema(connection)

    def test_finance_creation_rolls_back_when_owner_operation_cannot_be_recorded(self):
        expectation = self._expectation()
        report = self._report_with_evidence(expectation["expectedAmountMinor"])
        with patch.object(
            self.service, "_operation", side_effect=RuntimeError("operation audit unavailable")
        ):
            with self.assertRaisesRegex(RuntimeError, "operation audit unavailable"):
                owner_command(
                    self.service,
                    "verify",
                    report["id"],
                    VerifyOwnerRentReportCommand(
                        True,
                        "Matched.",
                        None,
                        str(uuid4()),
                        (
                            ReceiptAllocationCommand(
                                expectation["id"], expectation["expectedAmountMinor"]
                            ),
                        ),
                    ),
                    str(uuid4()),
                )
        with self.service.unit_of_work.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT count(*) FROM rent_receipts")).scalar_one(), 0
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT status FROM owner_rent_reports WHERE id=:id"), {"id": report["id"]}
                ).scalar_one(),
                "pending",
            )

    @fast_backup_encryption()
    def test_verified_creation_history_survives_backup_and_restore(self):
        expectation = self._expectation()
        report = self._report_with_evidence(expectation["expectedAmountMinor"])
        verification_key = str(uuid4())
        verified = owner_command(
            self.service,
            "verify",
            report["id"],
            VerifyOwnerRentReportCommand(
                True,
                "Matched statement.",
                None,
                str(uuid4()),
                (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            ),
            verification_key,
        )
        backups = BackupService(
            self.workspace,
            self.recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        root = self.workspace.paths.root.parent
        archive = backups.create_backup(
            "a sufficiently long backup passphrase", output_path=root / "owner003.epm-backup"
        )
        restored_root = root / "restored-owner003"
        backups.restore(
            archive.archive_path, "a sufficiently long backup passphrase", restored_root
        )
        restored_database = restored_root / "database" / "property-management.sqlite"
        validate_latest_schema(restored_database)
        restored = OwnerRentReportService(
            SQLiteOwnerRentReportUnitOfWork(
                restored_database,
                AuditRecorder(SQLiteAuditRepository(restored_database)),
                SQLiteLeaseContextReader(),
                SQLitePortfolioContextReader(),
                SQLitePartyOperations(restored_database),
                SQLiteFileLinkReader(),
                SQLiteReceiptTransactionOperations(
                    AuditRecorder(SQLiteAuditRepository(restored_database)),
                    SQLiteLeaseContextReader(),
                    SQLitePortfolioContextReader(),
                    SQLitePartyOperations(restored_database),
                ),
            )
        )
        self.assertEqual(
            restored.detail(report["id"])["verifiedReceiptId"], verified["verifiedReceiptId"]
        )
        self.assertEqual(restored.command_operation(verification_key)["result"], verified)
        with (
            self.service.unit_of_work.engine.connect() as source,
            restored.unit_of_work.engine.connect() as destination,
        ):
            for table in (
                "owner_rent_report_operations",
                "finance_command_operations",
                "finance_command_revisions",
            ):
                self.assertEqual(
                    source.exec_driver_sql(
                        f"SELECT * FROM {table} ORDER BY id"
                        if table != "finance_command_revisions"
                        else f"SELECT * FROM {table} ORDER BY scope_kind, scope_id"
                    ).all(),
                    destination.exec_driver_sql(
                        f"SELECT * FROM {table} ORDER BY id"
                        if table != "finance_command_revisions"
                        else f"SELECT * FROM {table} ORDER BY scope_kind, scope_id"
                    ).all(),
                )

    def test_original_create_patch_and_reject_replay_and_single_read_recovery(self):
        report = self._report_with_evidence(100)
        patch_key, reject_key = str(uuid4()), str(uuid4())
        values = {"source_note": "Statement correction"}
        patched = self.service.patch(report["id"], values, patch_key, expected_revision=1)
        self.assertEqual(patched["reportRevision"], 2)
        from app.modules.owner_accounting.domain.models import RejectOwnerRentReportCommand

        command = RejectOwnerRentReportCommand(True, "Unsupported claim")
        rejected = self.service.reject(report["id"], command, reject_key, expected_revision=2)
        self.assertEqual(rejected["reportRevision"], 3)
        self.assertEqual(
            self.service.patch(report["id"], values, patch_key, expected_revision=1), patched
        )
        self.assertEqual(
            self.service.reject(report["id"], command, reject_key, expected_revision=2), rejected
        )
        statements = []
        engine = self.service.unit_of_work.engine

        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])

        event.listen(engine, "before_cursor_execute", capture)
        try:
            self.assertEqual(self.service.command_operation(patch_key)["result"], patched)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 1)
        with self.assertRaises(OwnerReportConflictError):
            self.service.patch(
                report["id"], {"source_note": "Different"}, patch_key, expected_revision=1
            )
        validate_latest_schema(self.database)

    def test_stale_ledger_verification_and_receipt_write_failure_roll_back_both_scopes(self):
        expectation = self._expectation()
        report = self._report_with_evidence(expectation["expectedAmountMinor"])
        command = VerifyOwnerRentReportCommand(
            True,
            "Verified statement",
            None,
            str(uuid4()),
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
        )
        from app.modules.finance.domain.models import FinanceConflictError

        with self.assertRaises(FinanceConflictError):
            self.service.verify(
                report["id"], command, str(uuid4()), expected_revision=1, expected_ledger_revision=0
            )
        ledger = self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"]
        with (
            patch.object(
                self.service, "_operation", side_effect=RuntimeError("owner audit unavailable")
            ),
            self.assertRaises(RuntimeError),
        ):
            self.service.verify(
                report["id"],
                command,
                str(uuid4()),
                expected_revision=1,
                expected_ledger_revision=ledger,
            )
        self.assertEqual(self.service.detail(report["id"])["reportRevision"], 1)
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"], ledger
        )
        with self.service.unit_of_work.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM rent_receipts")), 0)
            self.assertEqual(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM finance_command_operations WHERE action='record_receipt'"
                    )
                ),
                0,
            )
        key = str(uuid4())
        verified = self.service.verify(
            report["id"], command, key, expected_revision=1, expected_ledger_revision=ledger
        )
        self.assertEqual(verified["reportRevision"], 2)
        self.assertEqual(verified["rentLedgerRevision"], ledger + 1)
        self.assertEqual(
            self.service.verify(
                report["id"], command, key, expected_revision=1, expected_ledger_revision=ledger
            ),
            verified,
        )
        validate_latest_schema(self.database)

    def test_report_noop_and_rewritten_original_result_validation(self):
        report = self._report_with_evidence(100)
        key = str(uuid4())
        noop = self.service.patch(report["id"], {}, key, expected_revision=1)
        self.assertEqual(noop["reportRevision"], 1)
        self.assertEqual(noop["updatedAt"], report["updatedAt"])
        validate_latest_schema(self.database)
        from app.platform.migration_errors import MigrationSchemaError

        with self.service.unit_of_work.engine.begin() as connection:
            connection.execute(text("DROP TRIGGER owner_rent_report_operations_no_update"))
            connection.execute(
                text(
                    "UPDATE owner_rent_report_operations SET response_json=json_set(response_json,'$.sourceNote','rewritten') WHERE idempotency_key=:key"
                ),
                {"key": key},
            )
        with (
            self.service.unit_of_work.engine.connect() as connection,
            self.assertRaises(MigrationSchemaError),
        ):
            validate_owner_accounting_schema(connection)


class _OneTxUow:
    def __init__(self, tx):
        self.tx = tx

    def write(self, operation):
        return operation(self.tx)

    def read(self, operation):
        return operation(self.tx)


class _VerificationTx:
    def __init__(self, report, receipt):
        self.item, self.receipt_item, self.recorded = report, receipt, None
        self.replaced = None
        self.changes = []

    def report_by_operation_key(self, _):
        return None

    def report(self, _):
        return self.item

    def require_ledger_revision(self, *_):
        pass

    def has_evidence(self, _):
        return True

    def owner_eligible(self, *_):
        return True

    def record_receipt(self, *_args, **_kwargs):
        return self.recorded

    def report_for_receipt(self, _):
        return None

    def receipt_allocations(self, _):
        return [{"amount_minor": 100}]

    def replace_report(self, item):
        self.replaced = item
        self.item = item

    def insert_operation(self, _):
        pass

    def record_change(self, **change):
        self.changes.append(change)

    def available_evidence_links(self, _):
        return [SimpleNamespace(id="link", file_id="file")]

    def receipt(self, _):
        return self.receipt_item

    def evidence_count(self, _):
        return 1

    def replacement_receipt(self, _):
        return None
