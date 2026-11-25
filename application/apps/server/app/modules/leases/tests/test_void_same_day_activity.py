"""Regression tests for same-day lease voiding settled-activity guards (Finding 6)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.infrastructure.lease_activity_reader import (
    SQLiteLeaseFinanceActivityReader,
)
from app.modules.inspections.infrastructure.context_reader import SQLiteInspectionContextReader
from app.modules.leases.application.ports import LeaseConflictError
from app.modules.leases.application.service import (
    LeaseCreateCommand,
    LeaseService,
    ParticipantCommand,
    TermCommand,
)
from app.modules.leases.infrastructure.unit_of_work import (
    SQLiteLeaseParticipationGuard,
    SQLiteLeaseUnitOfWork,
)
from app.modules.leases.tests.commands import lease_command
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
)
from app.modules.portfolio.application.service import (
    OwnershipInput,
    PortfolioService,
    PropertyCreateCommand,
)
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import (
    SQLitePortfolioLeaseOperations,
    SQLitePortfolioUnitOfWork,
)
from app.modules.portfolio.tests.commands import inventory_command
from app.modules.tenants.application.service import TenantCreateCommand, TenantService
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantProfileAvailability,
    SQLiteTenantUnitOfWork,
)
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.sqlite_engine import create_sqlite_engine


def _setup_same_day_executed_lease(tmp_path: Path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    workspace.initialize()
    db = workspace.paths.database
    recorder = AuditRecorder(SQLiteAuditRepository(db))
    portfolio = PortfolioService(
        SQLitePortfolioUnitOfWork(db, recorder),
        time_zone_resolver=BundledAddressTimeZoneResolver(),
    )
    prop = inventory_command(
        portfolio,
        "create_property",
        PropertyCreateCommand(
            "Deposit Guard Home",
            "100 Main St",
            "Portland",
            "US",
            "single_family_home",
            (OwnershipInput("local_operator"),),
            region="OR",
        ),
    )
    space_id = portfolio.get_property(prop.id)["spaces"][0]["id"]
    party_ops = SQLitePartyOperations(db)
    tenants = TenantService(
        SQLiteTenantUnitOfWork(
            db,
            recorder,
            SQLiteLeaseParticipationGuard(),
            party_ops,
            SQLitePartyReadOperations(party_ops),
        ),
        SharedPartyFactory(),
    )
    tenant = tenants.create(
        TenantCreateCommand(
            "individual",
            "Guard Tenant",
            official_ids=(
                {"document_type": "passport", "issuing_country": "US", "last_four": "1234"},
            ),
        ),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    leases = LeaseService(
        SQLiteLeaseUnitOfWork(
            db,
            recorder,
            SQLiteTenantProfileAvailability(),
            SQLitePortfolioLeaseOperations(db),
            SQLiteInspectionContextReader(),
            SQLiteLeaseFinanceActivityReader(),
        )
    )
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    draft = lease_command(
        leases,
        "create",
        LeaseCreateCommand(
            space_id,
            "residential",
            today,
            today + timedelta(days=365),
            today,
            TermCommand(200_000, "USD", "monthly", 1, 200_000),
            (ParticipantCommand(tenant["id"], "primary_tenant"),),
        ),
    )
    executed = lease_command(
        leases,
        "execute",
        draft["id"],
        executed_on=today.isoformat(),
        confirmed=True,
        expected_revision=portfolio.get_space_status(space_id)["revision"],
        idempotency_key=str(uuid4()),
    )
    return db, portfolio, leases, prop.id, space_id, executed, today.isoformat()


def _void_same_day(portfolio: PortfolioService, leases: LeaseService, space_id: str, lease: dict):
    return lease_command(
        leases,
        "void",
        lease["id"],
        confirmed=True,
        expected_revision=portfolio.get_space_status(space_id)["revision"],
        expected_lease_revision=lease["leaseRevision"],
        idempotency_key=str(uuid4()),
    )


def test_same_day_void_succeeds_without_settled_activity(tmp_path: Path):
    _, portfolio, leases, _, space_id, lease, _ = _setup_same_day_executed_lease(tmp_path)
    voided = _void_same_day(portfolio, leases, space_id, lease)
    assert voided["status"] == "void"


def test_same_day_void_rejected_with_active_security_deposit_receipt(tmp_path: Path):
    db, portfolio, leases, prop_id, space_id, lease, today = _setup_same_day_executed_lease(
        tmp_path
    )
    term_id = lease["terms"][0]["id"]
    account_id = str(uuid4())
    receipt_id = str(uuid4())
    engine = create_sqlite_engine(db)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO security_deposit_accounts "
                "(id, lease_id, lease_term_id, property_id, space_id, agreed_amount_minor, "
                "currency_code, created_at, updated_at) "
                "VALUES (:id, :lease_id, :term_id, :prop_id, :space_id, 200000, 'USD', :now, :now)"
            ),
            {
                "id": account_id,
                "lease_id": lease["id"],
                "term_id": term_id,
                "prop_id": prop_id,
                "space_id": space_id,
                "now": f"{today}T12:00:00Z",
            },
        )
        conn.execute(
            text(
                "INSERT INTO security_deposit_receipts "
                "(id, account_id, idempotency_key, request_fingerprint, received_on, "
                "amount_minor, currency_code, received_by_kind, created_at) "
                "VALUES (:id, :account_id, :idem, :fp, :today, 200000, 'USD', 'local_operator', :now)"
            ),
            {
                "id": receipt_id,
                "account_id": account_id,
                "idem": str(uuid4()),
                "fp": "a" * 64,
                "today": today,
                "now": f"{today}T12:05:00Z",
            },
        )

    with pytest.raises(LeaseConflictError, match="payments or finalized inspections"):
        _void_same_day(portfolio, leases, space_id, lease)

    # Once voided, same-day lease voiding is allowed again.
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE security_deposit_receipts "
                "SET voided_at = :now, void_reason = 'entered_in_error' WHERE id = :id"
            ),
            {"id": receipt_id, "now": f"{today}T12:10:00Z"},
        )
    voided = _void_same_day(portfolio, leases, space_id, lease)
    assert voided["status"] == "void"


def test_same_day_void_rejected_with_active_rent_receipt(tmp_path: Path):
    db, portfolio, leases, _, space_id, lease, today = _setup_same_day_executed_lease(tmp_path)
    engine = create_sqlite_engine(db)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO rent_receipts "
                "(id, lease_id, idempotency_key, received_on, amount_minor, currency_code, "
                "payment_method_kind, created_at) "
                "VALUES (:id, :lease_id, :idem, :today, 200000, 'USD', 'bank_transfer', :now)"
            ),
            {
                "id": str(uuid4()),
                "lease_id": lease["id"],
                "idem": str(uuid4()),
                "today": today,
                "now": f"{today}T12:00:00Z",
            },
        )

    with pytest.raises(LeaseConflictError, match="payments or finalized inspections"):
        _void_same_day(portfolio, leases, space_id, lease)


def test_same_day_void_rejected_with_finalized_condition_report(tmp_path: Path):
    db, portfolio, leases, _, space_id, lease, today = _setup_same_day_executed_lease(tmp_path)
    engine = create_sqlite_engine(db)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO condition_reports "
                "(id, lease_id, space_id, report_kind, status, walkthrough_on, conducted_by, "
                "tenant_presence, finalized_at, created_at, updated_at) "
                "VALUES (:id, :lease_id, :space_id, 'pre_move_in', 'finalized', :today, "
                "'Operator', 'present', :now, :now, :now)"
            ),
            {
                "id": str(uuid4()),
                "lease_id": lease["id"],
                "space_id": space_id,
                "today": today,
                "now": f"{today}T12:00:00Z",
            },
        )

    with pytest.raises(LeaseConflictError, match="payments or finalized inspections"):
        _void_same_day(portfolio, leases, space_id, lease)
