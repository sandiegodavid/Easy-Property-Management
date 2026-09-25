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
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.files.api.router import build_router as build_files_router
from app.modules.files.domain.audit_policy import (
    FILE_ACTIVITY_SNAPSHOT_POLICY,
    FILE_LINK_ACTIVITY_SNAPSHOT_POLICY,
)
from app.modules.tasks.api.router import build_router as build_tasks_router
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
from app.modules.tasks.domain.audit_policy import TASK_ACTIVITY_POLICY
from app.modules.communications.api.router import build_router as build_communications_router
from app.modules.communications.application.service import CommunicationService
from app.modules.communications.infrastructure.unit_of_work import (
    SQLiteCommunicationUnitOfWork,
)
from app.modules.communications.infrastructure.link_reader import SQLiteCommunicationLinkReader
from app.bootstrap.communication_context import SQLiteCommunicationContextOperations
from app.modules.communications.domain.audit_policy import COMMUNICATION_ACTIVITY_POLICY
from app.modules.maintenance.api.router import build_router as build_maintenance_router
from app.modules.maintenance.application.service import MaintenanceService
from app.modules.maintenance.application.work_journal_service import WorkJournalService
from app.modules.maintenance.application.file_links import MaintenanceFileLinkValidator
from app.modules.maintenance.infrastructure.unit_of_work import SQLiteMaintenanceUnitOfWork
from app.modules.maintenance.infrastructure.file_links import SQLiteMaintenanceFileLinkOperations
from app.modules.maintenance.domain.audit_policy import MAINTENANCE_ACTIVITY_POLICY
from app.modules.owner_accounting.api.router import build_router as build_owner_rent_report_router
from app.modules.owner_accounting.application.service import OwnerRentReportService
from app.modules.owner_accounting.application.file_links import OwnerRentReportFileLinkValidator
from app.modules.owner_accounting.infrastructure.unit_of_work import SQLiteOwnerRentReportUnitOfWork
from app.modules.owner_accounting.infrastructure.file_links import SQLiteOwnerRentReportFileLinkOperations
from app.modules.owner_accounting.domain.audit_policy import OWNER_REPORT_ACTIVITY_POLICY
from app.modules.owner_management.api.router import build_router as build_owner_concern_router
from app.modules.owner_management.application.service import OwnerConcernService
from app.modules.owner_management.infrastructure.unit_of_work import SQLiteOwnerConcernPropertyArchiveGuard, SQLiteOwnerConcernUnitOfWork
from app.modules.owner_management.domain.audit_policy import OWNER_CONCERN_ACTIVITY_POLICY
from app.bootstrap.owner_concern_context import SQLiteOwnerConcernContext
from app.modules.portfolio.api.router import build_router as build_portfolio_router
from app.modules.portfolio.application.service import PortfolioService
from app.modules.portfolio.infrastructure.unit_of_work import (
    SQLitePortfolioLeaseOperations,
    SQLitePortfolioPartyRoleActivityGuard,
    SQLitePortfolioRoleSummaryReader,
    SQLitePortfolioUnitOfWork,
)
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
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
from app.modules.inspections.infrastructure.context_reader import SQLiteInspectionContextReader
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
from app.modules.finance.api.router import build_router as build_finance_router
from app.modules.finance.api.expense_router import build_router as build_expense_router
from app.modules.finance.api.deposit_router import build_router as build_deposit_router
from app.modules.finance.api.prepaid_check_router import build_router as build_prepaid_check_router
from app.modules.finance.application.expense_service import ExpenseService
from app.modules.finance.application.deposit_service import DepositService
from app.modules.finance.application.file_links import ExpenseFileLinkValidator
from app.modules.finance.application.deposit_file_links import DepositFileLinkValidator
from app.modules.finance.application.service import FinanceService
from app.modules.finance.infrastructure.expense_context_reader import SQLiteExpenseContextReader
from app.modules.finance.application.prepaid_check_service import PrepaidCheckService
from app.modules.finance.infrastructure.expense_unit_of_work import SQLiteExpenseUnitOfWork
from app.modules.finance.infrastructure.file_links import SQLiteExpenseFileLinkOperations
from app.modules.finance.infrastructure.deposit_file_links import SQLiteDepositFileLinkOperations
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.finance.infrastructure.receipt_transaction_operations import SQLiteReceiptTransactionOperations
from app.modules.finance.infrastructure.deposit_unit_of_work import SQLiteDepositUnitOfWork
from app.modules.finance.domain.audit_policy import (
    EXPECTATION_ACTIVITY_POLICY, REVIEW_ACTIVITY_POLICY,
    RECEIPT_ACTIVITY_POLICY, ALLOCATION_ACTIVITY_POLICY,
    PREPAID_CHECK_ACTIVITY_POLICY,
    EXPENSE_ACTIVITY_POLICY, EXPENSE_CATEGORY_ACTIVITY_POLICY,
    EXPENSE_REFUND_ACTIVITY_POLICY,
    DEPOSIT_ACTIVITY_POLICY,
)
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.vendors.infrastructure.context_reader import SQLiteProviderContextReader
from app.modules.ai_governance.api.router import build_router as build_ai_governance_router
from app.modules.ai_governance.application.service import AiGovernanceService
from app.modules.ai_governance.application.registry import ACTION_REGISTRY, REDACTION_PROFILE_REGISTRY, ADAPTER_REGISTRY
from app.modules.ai_governance.domain.audit_policy import AI_ACTIVITY_POLICY
from app.modules.ai_governance.infrastructure.credentials import KeyringAiTransportCredentialStore
from app.modules.ai_governance.infrastructure.unit_of_work import SQLiteAiGovernanceUnitOfWork
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
    file_link_reader = SQLiteFileLinkReader()
    task_transaction_operations = SQLiteTaskTransactionOperations()
    portfolio_context_reader = SQLitePortfolioContextReader()
    inspection_context_reader = SQLiteInspectionContextReader()
    ai_governance = AiGovernanceService(
        SQLiteAiGovernanceUnitOfWork(service.paths.database, recorder),
        # This stable local identity is used only as the keyring namespace.  It
        # is never persisted or exported as a credential.
        workspace_id=str(service.paths.database.resolve()),
        actions=ACTION_REGISTRY, profiles=REDACTION_PROFILE_REGISTRY,
        adapters=ADAPTER_REGISTRY, credentials=KeyringAiTransportCredentialStore(),
    )
    lease_context_reader = SQLiteLeaseContextReader()
    party_reads = SQLitePartyReadOperations(party_operations)
    portfolio_lease_operations = SQLitePortfolioLeaseOperations(service.paths.database)
    lease_unit_of_work = SQLiteLeaseUnitOfWork(
        service.paths.database, recorder, SQLiteTenantProfileAvailability(),
        portfolio_lease_operations, inspection_context_reader,
    )
    inspection_unit_of_work = SQLiteInspectionUnitOfWork(service.paths.database, recorder)
    maintenance_unit_of_work = SQLiteMaintenanceUnitOfWork(
        service.paths.database, recorder, portfolio_context_reader,
        SQLiteExpenseContextReader(), SQLiteTaskContextReader(), task_transaction_operations, file_link_reader,
        party_operations, lease_context_reader, SQLiteCommunicationLinkReader(), SQLiteProviderContextReader(),
    )
    files = FileService(
        service,
        primary_store,
        SQLiteFileUnitOfWork(service.paths.database, recorder),
        additional_stores,
        # Inspection evidence is intentionally not a generic FILE-001 upload.
        # Its dedicated endpoint owns the report audit event and correlation ID.
        (
            LeaseFileLinkValidator(lease_unit_of_work),
            ExpenseFileLinkValidator(SQLiteExpenseFileLinkOperations(file_link_reader)),
            DepositFileLinkValidator(SQLiteDepositFileLinkOperations(file_link_reader)),
            MaintenanceFileLinkValidator(SQLiteMaintenanceFileLinkOperations(file_link_reader)),
            OwnerRentReportFileLinkValidator(SQLiteOwnerRentReportFileLinkOperations(file_link_reader)),
        ),
    )
    remote_materializer = s3_store.materialize if s3_store is not None else None
    backups = BackupService(service, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database)), remote_materializer=remote_materializer)
    tasks = TaskService(SQLiteTaskUnitOfWork(service.paths.database, recorder))
    communications = CommunicationService(SQLiteCommunicationUnitOfWork(
        service.paths.database, recorder, SQLiteCommunicationContextOperations(task_transaction_operations),
    ))
    owner_concern_guard = SQLiteOwnerConcernPropertyArchiveGuard()
    portfolio = PortfolioService(SQLitePortfolioUnitOfWork(
        service.paths.database, recorder, (SQLiteTenantRoleActivityGuard(),), (owner_concern_guard,)
    ), party_reads=party_reads, time_zone_resolver=BundledAddressTimeZoneResolver())
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
    finance = FinanceService(SQLiteFinanceUnitOfWork(
        service.paths.database, recorder, lease_context_reader, portfolio_context_reader, party_operations, task_transaction_operations,
    ))
    prepaid_checks = PrepaidCheckService(finance.unit_of_work)
    expenses = ExpenseService(SQLiteExpenseUnitOfWork(
        service.paths.database,
        recorder,
        portfolio_context_reader,
        SQLiteProviderContextReader(),
        party_operations,
        file_link_reader,
    ))
    deposits = DepositService(SQLiteDepositUnitOfWork(
        service.paths.database, recorder,
        lease_context_reader, portfolio_context_reader, party_operations,
        inspection_context_reader, file_link_reader,
    ))
    owner_rent_reports = OwnerRentReportService(SQLiteOwnerRentReportUnitOfWork(
        service.paths.database, recorder, lease_context_reader, portfolio_context_reader,
        party_operations, file_link_reader, SQLiteReceiptTransactionOperations(
            recorder, lease_context_reader, portfolio_context_reader, party_operations,
        ),
    ))
    owner_concerns = OwnerConcernService(SQLiteOwnerConcernUnitOfWork(
        service.paths.database, recorder, SQLiteOwnerConcernContext(task_transaction_operations),
    ))
    inspections = InspectionService(inspection_unit_of_work, files)
    maintenance = MaintenanceService(maintenance_unit_of_work)
    work_journal = WorkJournalService(maintenance_unit_of_work)
    leases = LeaseService(lease_unit_of_work, inspections.attention_for_lease)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        scheduler: asyncio.Task[None] | None = None
        try:
            if runtime.ready:
                ai_governance.recover_interrupted()
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
    app.state.communication_service = communications
    app.state.portfolio_service = portfolio
    app.state.tenant_service = tenants
    app.state.party_contact_service = party_contacts
    app.state.party_identity_service = party_identities
    app.state.provider_service = providers
    app.state.lease_service = leases
    app.state.inspection_service = inspections
    app.state.finance_service = finance
    app.state.prepaid_check_service = prepaid_checks
    app.state.expense_service = expenses
    app.state.deposit_service = deposits
    app.state.maintenance_service = maintenance
    app.state.work_journal_service = work_journal
    app.state.owner_rent_report_service = owner_rent_reports
    app.state.owner_concern_service = owner_concerns
    app.state.ai_governance_service = ai_governance
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
        ("rent_expectation", 1): DEFAULT_SNAPSHOT_POLICY,
        ("rent_expectation_timeliness_review", 1): DEFAULT_SNAPSHOT_POLICY,
        ("rent_receipt", 1): DEFAULT_SNAPSHOT_POLICY,
        ("rent_receipt_allocation", 1): DEFAULT_SNAPSHOT_POLICY,
        ("prepaid_check", 1): DEFAULT_SNAPSHOT_POLICY,
        ("expense_category", 1): DEFAULT_SNAPSHOT_POLICY,
        ("expense", 1): DEFAULT_SNAPSHOT_POLICY,
        ("expense_refund", 1): DEFAULT_SNAPSHOT_POLICY,
        ("security_deposit_account", 1): DEFAULT_SNAPSHOT_POLICY,
        ("security_deposit_receipt", 1): DEFAULT_SNAPSHOT_POLICY,
        ("security_deposit_settlement", 1): DEFAULT_SNAPSHOT_POLICY,
        ("security_deposit_deduction", 1): DEFAULT_SNAPSHOT_POLICY,
        ("security_deposit_deduction_source", 1): DEFAULT_SNAPSHOT_POLICY,
        ("security_deposit_credit", 1): DEFAULT_SNAPSHOT_POLICY,
        ("security_deposit_refund", 1): DEFAULT_SNAPSHOT_POLICY,
        ("communication", 1): DEFAULT_SNAPSHOT_POLICY,
        ("communication_participant", 1): DEFAULT_SNAPSHOT_POLICY,
        ("communication_link", 1): DEFAULT_SNAPSHOT_POLICY,
        ("maintenance_issue", 1): DEFAULT_SNAPSHOT_POLICY,
        ("maintenance_appointment", 1): DEFAULT_SNAPSHOT_POLICY,
        ("maintenance_cost_context", 1): DEFAULT_SNAPSHOT_POLICY,
        ("maintenance_expense_link", 1): DEFAULT_SNAPSHOT_POLICY,
        ("maintenance_quote", 1): DEFAULT_SNAPSHOT_POLICY,
        ("maintenance_assignment", 1): DEFAULT_SNAPSHOT_POLICY,
        ("maintenance_work_journal_entry", 1): DEFAULT_SNAPSHOT_POLICY,
        ("owner_rent_report", 1): DEFAULT_SNAPSHOT_POLICY,
        ("owner_rent_report_operation", 1): DEFAULT_SNAPSHOT_POLICY,
        ("owner_concern", 1): DEFAULT_SNAPSHOT_POLICY,
        ("owner_concern_follow_up_operation", 1): DEFAULT_SNAPSHOT_POLICY,
        ("ai_run", 1): DEFAULT_SNAPSHOT_POLICY,
        ("ai_draft", 1): DEFAULT_SNAPSHOT_POLICY,
        ("ai_review_decision", 1): DEFAULT_SNAPSHOT_POLICY,
        ("ai_settings", 1): DEFAULT_SNAPSHOT_POLICY,
        ("ai_action_limit", 1): DEFAULT_SNAPSHOT_POLICY,
        ("ai_model_connection", 1): DEFAULT_SNAPSHOT_POLICY,
    }, activity_policies={
        ("task", 1): TASK_ACTIVITY_POLICY,
        ("file", 1): FILE_ACTIVITY_SNAPSHOT_POLICY,
        ("file_link", 1): FILE_LINK_ACTIVITY_SNAPSHOT_POLICY,
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
        ("rent_expectation", 1): EXPECTATION_ACTIVITY_POLICY,
        ("rent_expectation_timeliness_review", 1): REVIEW_ACTIVITY_POLICY,
        ("rent_receipt", 1): RECEIPT_ACTIVITY_POLICY,
        ("rent_receipt_allocation", 1): ALLOCATION_ACTIVITY_POLICY,
        ("prepaid_check", 1): PREPAID_CHECK_ACTIVITY_POLICY,
        ("expense_category", 1): EXPENSE_CATEGORY_ACTIVITY_POLICY,
        ("expense", 1): EXPENSE_ACTIVITY_POLICY,
        ("expense_refund", 1): EXPENSE_REFUND_ACTIVITY_POLICY,
        ("security_deposit_account", 1): DEPOSIT_ACTIVITY_POLICY,
        ("security_deposit_receipt", 1): DEPOSIT_ACTIVITY_POLICY,
        ("security_deposit_settlement", 1): DEPOSIT_ACTIVITY_POLICY,
        ("security_deposit_deduction", 1): DEPOSIT_ACTIVITY_POLICY,
        ("security_deposit_deduction_source", 1): DEPOSIT_ACTIVITY_POLICY,
        ("security_deposit_credit", 1): DEPOSIT_ACTIVITY_POLICY,
        ("security_deposit_refund", 1): DEPOSIT_ACTIVITY_POLICY,
        ("communication", 1): COMMUNICATION_ACTIVITY_POLICY,
        ("communication_participant", 1): COMMUNICATION_ACTIVITY_POLICY,
        ("communication_link", 1): COMMUNICATION_ACTIVITY_POLICY,
        ("maintenance_issue", 1): MAINTENANCE_ACTIVITY_POLICY,
        ("maintenance_appointment", 1): MAINTENANCE_ACTIVITY_POLICY,
        ("maintenance_cost_context", 1): MAINTENANCE_ACTIVITY_POLICY,
        ("maintenance_expense_link", 1): MAINTENANCE_ACTIVITY_POLICY,
        ("maintenance_quote", 1): MAINTENANCE_ACTIVITY_POLICY,
        ("maintenance_assignment", 1): MAINTENANCE_ACTIVITY_POLICY,
        ("maintenance_work_journal_entry", 1): MAINTENANCE_ACTIVITY_POLICY,
        ("owner_rent_report", 1): OWNER_REPORT_ACTIVITY_POLICY,
        ("owner_rent_report_operation", 1): OWNER_REPORT_ACTIVITY_POLICY,
        ("owner_concern", 1): OWNER_CONCERN_ACTIVITY_POLICY,
        ("owner_concern_follow_up_operation", 1): OWNER_CONCERN_ACTIVITY_POLICY,
        ("ai_run", 1): AI_ACTIVITY_POLICY,
        ("ai_draft", 1): AI_ACTIVITY_POLICY,
        ("ai_review_decision", 1): AI_ACTIVITY_POLICY,
        ("ai_settings", 1): AI_ACTIVITY_POLICY,
        ("ai_action_limit", 1): AI_ACTIVITY_POLICY,
        ("ai_model_connection", 1): AI_ACTIVITY_POLICY,
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
    app.include_router(build_finance_router(finance, runtime))
    app.include_router(build_prepaid_check_router(prepaid_checks, runtime))
    app.include_router(build_expense_router(expenses, runtime))
    app.include_router(build_deposit_router(deposits, runtime))
    app.include_router(build_communications_router(communications, runtime))
    app.include_router(build_maintenance_router(maintenance, work_journal, runtime))
    app.include_router(build_owner_rent_report_router(owner_rent_reports, runtime))
    app.include_router(build_owner_concern_router(owner_concerns, runtime))
    app.include_router(build_ai_governance_router(ai_governance, runtime))
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
