"""Regression tests for property-timezone business-date evaluation across UTC midnight (Findings 7, 13, 18)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.infrastructure.lease_activity_reader import (
    SQLiteLeaseFinanceActivityReader,
)
from app.modules.inspections.application import service as inspection_service_module
from app.modules.inspections.application.service import InspectionService
from app.modules.inspections.infrastructure.context_reader import SQLiteInspectionContextReader
from app.modules.inspections.infrastructure.unit_of_work import SQLiteInspectionUnitOfWork
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.leases.application import service as lease_service_module
from app.modules.leases.application.service import (
    LeaseCreateCommand,
    LeaseError,
    LeaseService,
    ParticipantCommand,
    TermCommand,
)
from app.modules.leases.infrastructure import unit_of_work as lease_uow_module
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
from app.modules.tenants.application.service import (
    TenantConflictError,
    TenantCreateCommand,
    TenantService,
)
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantProfileAvailability,
    SQLiteTenantUnitOfWork,
)
from app.modules.vendors.application import service as vendor_service_module
from app.modules.vendors.application.service import ProviderError, _reputation_date
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig


class _FrozenDateTime(datetime):
    """Frozen UTC instant: 2026-11-25T02:00:00Z (still 2026-11-24 in America/Los_Angeles)."""

    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 11, 25, 2, 0, 0, tzinfo=UTC)
        return base.astimezone(tz) if tz is not None else base.replace(tzinfo=None)


def test_lease_execute_void_and_move_out_use_property_timezone_across_utc_midnight(tmp_path: Path):
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
            "Pacific Home",
            "100 Main St",
            "Portland",
            "US",
            "single_family_home",
            (OwnershipInput("local_operator"),),
            region="OR",
        ),
    )
    assert prop.time_zone == "America/Los_Angeles"
    space_id = portfolio.get_property(prop.id)["spaces"][0]["id"]
    portfolio_ops = SQLitePortfolioLeaseOperations(db)
    party_ops = SQLitePartyOperations(db)
    tenants = TenantService(
        SQLiteTenantUnitOfWork(
            db,
            recorder,
            SQLiteLeaseParticipationGuard(portfolio_ops.space_time_zones),
            party_ops,
            SQLitePartyReadOperations(party_ops),
        ),
        SharedPartyFactory(),
    )
    tenant = tenants.create(
        TenantCreateCommand(
            "individual",
            "Pacific Tenant",
            official_ids=(
                {"document_type": "passport", "issuing_country": "US", "last_four": "4321"},
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
            portfolio_ops,
            SQLiteInspectionContextReader(),
            SQLiteLeaseFinanceActivityReader(),
        )
    )
    inspections = InspectionService(
        SQLiteInspectionUnitOfWork(
            db,
            recorder,
            space_time_zones=portfolio_ops.space_time_zones,
            lease_context_reader=SQLiteLeaseContextReader(),
        ),
        None,
    )

    pacific_today = date(2026, 11, 24)
    utc_tomorrow = date(2026, 11, 25)

    with (
        patch.object(lease_service_module, "datetime", _FrozenDateTime),
        patch.object(lease_uow_module, "datetime", _FrozenDateTime),
        patch.object(inspection_service_module, "datetime", _FrozenDateTime),
    ):
        draft = lease_command(
            leases,
            "create",
            LeaseCreateCommand(
                space_id,
                "residential",
                pacific_today,
                pacific_today + timedelta(days=365),
                pacific_today,
                TermCommand(200_000, "USD", "monthly", 1, 200_000),
                (ParticipantCommand(tenant["id"], "primary_tenant"),),
            ),
        )
        # At 2026-11-25T02:00:00Z, Pacific local date is still 2026-11-24:
        # executing a lease starting 2026-11-24 must succeed (not fail as historical occupancy).
        executed = lease_command(
            leases,
            "execute",
            draft["id"],
            executed_on=pacific_today.isoformat(),
            confirmed=True,
            expected_revision=portfolio.get_space_status(space_id)["revision"],
            idempotency_key=str(uuid4()),
        )
        assert executed["status"] == "executed"
        assert executed["occupancyState"] == "current"

        # Recording move-out on 2026-11-25 (UTC date, future in Pacific) must be rejected.
        with pytest.raises(LeaseError, match="future"):
            lease_command(
                leases,
                "end",
                executed["id"],
                actual_move_out_on=utc_tomorrow.isoformat(),
                confirmed=True,
                expected_revision=portfolio.get_space_status(space_id)["revision"],
                expected_lease_revision=executed["leaseRevision"],
                idempotency_key=str(uuid4()),
            )

        # Tenant with open lease participation cannot be archived.
        with pytest.raises(TenantConflictError):
            tenants.archive(
                tenant["id"],
                confirmed=True,
                expected_revision=tenant["revision"],
                idempotency_key=str(uuid4()),
            )

        # Inspection attention uses Pacific local date (2026-11-24 => 'due', not UTC 'missing').
        listed = inspections.list_for_lease(executed["id"])
        assert listed["attention"]["preMoveIn"] == "due"

        # Same-day voiding on 2026-11-24 must succeed even though UTC is already 2026-11-25.
        voided = lease_command(
            leases,
            "void",
            executed["id"],
            confirmed=True,
            expected_revision=portfolio.get_space_status(space_id)["revision"],
            expected_lease_revision=executed["leaseRevision"],
            idempotency_key=str(uuid4()),
        )
        assert voided["status"] == "void"


def test_provider_reputation_date_allows_utc_plus_14_and_rejects_beyond():
    with patch.object(vendor_service_module, "datetime", _FrozenDateTime):
        # At 2026-11-25T02:00:00Z, UTC+14 is 2026-11-25T16:00:00+14:00 -> 2026-11-25 is valid.
        assert _reputation_date("2026-11-25") == "2026-11-25"
        with pytest.raises(ProviderError, match="future"):
            _reputation_date("2026-11-26")
