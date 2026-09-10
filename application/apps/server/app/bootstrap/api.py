"""FastAPI composition for the local application."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.modules.workspace.api.router import build_router
from app.modules.audit.api.router import build_router as build_audit_router
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.domain.models import AuditSnapshotPolicyRegistry, DEFAULT_SNAPSHOT_POLICY
from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.workspace.application.service import WorkspaceService
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore, S3ContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.files.api.router import build_router as build_files_router
from app.modules.files.domain.audit_policy import FILE_ACTIVITY_SNAPSHOT_POLICY
from app.modules.tasks.api.router import build_router as build_tasks_router
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.portfolio.api.router import build_router as build_portfolio_router
from app.modules.portfolio.application.service import PortfolioService
from app.modules.portfolio.infrastructure.unit_of_work import (
    SQLitePortfolioLeaseOperations,
    SQLitePortfolioPartyRoleActivityGuard,
    SQLitePortfolioRoleSummaryReader,
    SQLitePortfolioUnitOfWork,
)
from app.modules.parties.api.router import build_router as build_party_router
from app.modules.parties.application.service import PartyContactService, PartyIdentityService
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
    SQLitePartyUnitOfWork,
)
from app.modules.tenants.api.router import build_router as build_tenant_router
from app.modules.tenants.application.service import TenantService
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantContactReferenceGuard,
    SQLiteTenantProfileAvailability,
    SQLiteTenantRoleActivityGuard,
    SQLiteTenantRoleSummaryReader,
    SQLiteTenantUnitOfWork,
)
from app.modules.leases.api.router import build_router as build_lease_router
from app.modules.leases.application.service import LeaseService
from app.modules.leases.application.file_links import LeaseFileLinkValidator
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard, SQLiteLeaseUnitOfWork
from app.modules.inspections.api.router import build_router as build_inspection_router
from app.modules.inspections.application.service import InspectionService
from app.modules.inspections.infrastructure.unit_of_work import SQLiteInspectionUnitOfWork
from app.modules.inspections.domain.audit_policy import INSPECTION_ACTIVITY_POLICY
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.parties.domain.audit_policy import PARTY_CONTACT_SNAPSHOT_POLICY
from app.modules.vendors.api.router import build_router as build_provider_router
from app.modules.vendors.application.service import ProviderService
from app.modules.vendors.infrastructure.unit_of_work import (
    SQLiteProviderRoleActivityGuard, SQLiteProviderRoleSummaryReader, SQLiteProviderUnitOfWork,
)
from app.modules.vendors.domain.audit_policy import (
    PROVIDER_ACTIVITY_SNAPSHOT_POLICY, PROVIDER_REPUTATION_LINK_ACTIVITY_POLICY,
)
from app.platform.version import application_version

logger = logging.getLogger(__name__)


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create the local API without implicitly initializing a workspace."""
    service = WorkspaceService.from_local_config(config_path)
    audit_repository = SQLiteAuditRepository(service.paths.database)
    recorder = AuditRecorder(audit_repository)
    runtime = WorkspaceRuntime(service)
    local_store = FilesystemContentStore(service.paths.files)
    additional_stores = {}
    primary_store = local_store
    s3_store = None
    # Existing file records own their bucket/key. Keep this adapter available
    # whenever an S3 bucket is configured, even if new uploads default local.
    if service.config.s3_bucket:
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("S3 file storage requires the boto3 package.") from error
        s3_store = S3ContentStore(boto3.client("s3"), service.config.s3_bucket, service.config.s3_prefix, service.paths.root / ".file-content-locks")
        additional_stores["s3"] = s3_store
    if service.config.file_storage_provider == "s3":
        if s3_store is None:
            raise RuntimeError("S3 file storage requires an available S3 adapter.")
        primary_store = s3_store
        additional_stores["local"] = local_store
    party_operations = SQLitePartyOperations(service.paths.database)
    party_reads = SQLitePartyReadOperations(party_operations)
    portfolio_lease_operations = SQLitePortfolioLeaseOperations(service.paths.database)
    lease_unit_of_work = SQLiteLeaseUnitOfWork(
        service.paths.database, recorder, SQLiteTenantProfileAvailability(),
        portfolio_lease_operations,
    )
    inspection_unit_of_work = SQLiteInspectionUnitOfWork(service.paths.database, recorder)
    files = FileService(
        service,
        primary_store,
        SQLiteFileUnitOfWork(service.paths.database, recorder),
        additional_stores,
        # Inspection evidence is intentionally not a generic FILE-001 upload.
        # Its dedicated endpoint owns the report audit event and correlation ID.
        (LeaseFileLinkValidator(lease_unit_of_work),),
    )
    remote_materializer = s3_store.materialize if s3_store is not None else None
    backups = BackupService(service, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database)), remote_materializer=remote_materializer)
    tasks = TaskService(SQLiteTaskUnitOfWork(service.paths.database, recorder))
    portfolio = PortfolioService(SQLitePortfolioUnitOfWork(
        service.paths.database, recorder, (SQLiteTenantRoleActivityGuard(),)
    ), party_reads=party_reads)
    tenants = TenantService(SQLiteTenantUnitOfWork(
        service.paths.database, recorder, SQLiteLeaseParticipationGuard(),
        party_operations, party_reads,
    ), SharedPartyFactory())
    party_contacts = PartyContactService(SQLitePartyUnitOfWork(
        service.paths.database, recorder, (SQLiteTenantContactReferenceGuard(recorder),),
        (SQLiteTenantRoleActivityGuard(), SQLitePortfolioPartyRoleActivityGuard(), SQLiteProviderRoleActivityGuard()),
    ))
    party_identities = PartyIdentityService(
        SQLitePartyUnitOfWork(
            service.paths.database, recorder, (),
            (SQLiteTenantRoleActivityGuard(), SQLitePortfolioPartyRoleActivityGuard(), SQLiteProviderRoleActivityGuard()),
        ),
        party_reads,
        role_summary_readers=(
            SQLiteTenantRoleSummaryReader(service.paths.database),
            SQLitePortfolioRoleSummaryReader(service.paths.database),
            SQLiteProviderRoleSummaryReader(service.paths.database),
        ),
    )
    providers = ProviderService(SQLiteProviderUnitOfWork(
        service.paths.database, recorder, party_operations, portfolio_lease_operations,
    ))
    inspections = InspectionService(inspection_unit_of_work, files)
    leases = LeaseService(lease_unit_of_work, inspections.attention_for_lease)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        scheduler: asyncio.Task[None] | None = None
        try:
            if runtime.writer_lock_acquired:
                scheduler = asyncio.create_task(_automatic_backup_scheduler(backups, runtime))
            elif runtime.error:
                logger.warning("Workspace is not ready: %s", runtime.error)
            yield
        finally:
            try:
                if scheduler is not None:
                    scheduler.cancel()
                    try:
                        await scheduler
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception("Automatic backup scheduler stopped unexpectedly during shutdown.")
            finally:
                runtime.stop()

    app = FastAPI(title="Easy Property Management", version=application_version(), lifespan=lifespan)
    app.state.backup_service = backups
    app.state.workspace_runtime = runtime
    app.state.file_service = files
    app.state.task_service = tasks
    app.state.portfolio_service = portfolio
    app.state.tenant_service = tenants
    app.state.party_contact_service = party_contacts
    app.state.party_identity_service = party_identities
    app.state.provider_service = providers
    app.state.lease_service = leases
    app.state.inspection_service = inspections
    app.include_router(build_router(service, runtime))
    policies = AuditSnapshotPolicyRegistry({
        ("workspace", 1): DEFAULT_SNAPSHOT_POLICY,
        ("file", 1): DEFAULT_SNAPSHOT_POLICY,
        ("file_link", 1): DEFAULT_SNAPSHOT_POLICY,
        ("task", 1): DEFAULT_SNAPSHOT_POLICY,
        ("task_reminder", 1): DEFAULT_SNAPSHOT_POLICY,
        ("property", 1): DEFAULT_SNAPSHOT_POLICY,
        ("party", 1): DEFAULT_SNAPSHOT_POLICY,
        ("property_ownership", 1): DEFAULT_SNAPSHOT_POLICY,
        ("space", 1): DEFAULT_SNAPSHOT_POLICY,
        ("space_occupancy", 1): DEFAULT_SNAPSHOT_POLICY,
        ("space_availability", 1): DEFAULT_SNAPSHOT_POLICY,
        ("tenant_profile", 1): DEFAULT_SNAPSHOT_POLICY,
        ("party_contact_method", 1): DEFAULT_SNAPSHOT_POLICY,
        ("lease", 1): DEFAULT_SNAPSHOT_POLICY,
        ("lease_term", 1): DEFAULT_SNAPSHOT_POLICY,
        ("lease_participant", 1): DEFAULT_SNAPSHOT_POLICY,
        ("lease_renewal_option", 1): DEFAULT_SNAPSHOT_POLICY,
        ("lease_termination_case", 1): DEFAULT_SNAPSHOT_POLICY,
        ("lease_termination_proposal", 1): DEFAULT_SNAPSHOT_POLICY,
        ("backup_operation", 1): DEFAULT_SNAPSHOT_POLICY,
        ("backup_retention", 1): DEFAULT_SNAPSHOT_POLICY,
        ("workspace_restore", 1): DEFAULT_SNAPSHOT_POLICY,
        ("condition_report", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_area", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_observation", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_report_acknowledgment", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_checklist_template", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_checklist_template_item", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_comparison", 1): INSPECTION_ACTIVITY_POLICY,
        ("provider_profile", 1): DEFAULT_SNAPSHOT_POLICY,
        ("provider_service", 1): DEFAULT_SNAPSHOT_POLICY,
        ("provider_service_area", 1): DEFAULT_SNAPSHOT_POLICY,
        ("provider_work_history", 1): DEFAULT_SNAPSHOT_POLICY,
        ("provider_reference", 1): DEFAULT_SNAPSHOT_POLICY,
        ("provider_reputation_link", 1): DEFAULT_SNAPSHOT_POLICY,
    }, activity_policies={
        ("file", 1): FILE_ACTIVITY_SNAPSHOT_POLICY,
        ("party_contact_method", 1): PARTY_CONTACT_SNAPSHOT_POLICY,
        ("condition_report", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_area", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_observation", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_report_acknowledgment", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_checklist_template", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_checklist_template_item", 1): INSPECTION_ACTIVITY_POLICY,
        ("condition_comparison", 1): INSPECTION_ACTIVITY_POLICY,
        ("provider_profile", 1): PROVIDER_ACTIVITY_SNAPSHOT_POLICY,
        ("provider_service", 1): PROVIDER_ACTIVITY_SNAPSHOT_POLICY,
        ("provider_service_area", 1): PROVIDER_ACTIVITY_SNAPSHOT_POLICY,
        ("provider_work_history", 1): PROVIDER_ACTIVITY_SNAPSHOT_POLICY,
        ("provider_reference", 1): PROVIDER_ACTIVITY_SNAPSHOT_POLICY,
        ("provider_reputation_link", 1): PROVIDER_REPUTATION_LINK_ACTIVITY_POLICY,
    })
    app.include_router(build_audit_router(runtime, audit_repository, policies))
    app.include_router(build_files_router(files, runtime))
    app.include_router(build_tasks_router(tasks, runtime))
    app.include_router(build_portfolio_router(portfolio, runtime))
    app.include_router(build_party_router(party_identities, party_contacts, runtime))
    app.include_router(build_provider_router(providers, runtime))
    app.include_router(build_tenant_router(tenants, runtime))
    app.include_router(build_lease_router(leases, runtime))
    app.include_router(build_inspection_router(inspections, runtime))
    return app


async def _automatic_backup_scheduler(backups: BackupService, runtime: WorkspaceRuntime) -> None:
    """Recheck the local backup schedule while this server owns the workspace."""
    while runtime.writer_lock_acquired:
        if not runtime.ready:
            await asyncio.sleep(1)
            continue
        worker = asyncio.create_task(asyncio.to_thread(backups.run_due_automatic_backup))
        try:
            # Shielding lets cancellation stop the scheduler without abandoning its synchronous worker.
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            try:
                await worker
            except BackupError as error:
                logger.warning("Automatic backup stopped with an error during shutdown: %s", error)
            except Exception:
                logger.exception("Automatic backup worker crashed during shutdown.")
            raise
        except BackupError as error:
            logger.warning("Automatic backup was not run: %s", error)
        except Exception as error:
            logger.exception("Automatic backup worker crashed; recording failure before retrying.")
            backups.record_scheduler_failure(error)
        await asyncio.sleep(60)
