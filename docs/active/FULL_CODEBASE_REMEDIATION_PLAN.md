# Full Codebase Review Remediation Plan

**Date:** 2026-11-24
**Branch:** `hosted_mvp`
**Source Review:** [FULL_CODEBASE_3db88c2c_REVIEW_COMMENTS.txt](../pending_code_review_comments/FULL_CODEBASE_3db88c2c_REVIEW_COMMENTS.txt) (18 findings: 0 P0, 3 P1, 10 P2, 5 P3)
**Review Plan:** [FULL_CODEBASE_REVIEW_PLAN.md](FULL_CODEBASE_REVIEW_PLAN.md)
**Response Log Target:** `docs/pending_code_review_comments/FULL_CODEBASE_3db88c2c_REVIEW_RESPONSE.txt`
**Status:** Completed (All 3 batches / 8 slices / 18 findings addressed and validated)

---

## 1. Execution Strategy

Remediate all 18 findings in **3 cohesive batches** ordered by risk (data integrity & correctness first, then reliability & query budgets, then hygiene & architectural cleanup). Each slice is implemented, validated with focused tests + lint/format/typecheck gates per [AGENTS.md](../../AGENTS.md) and [CODE_QUALITY.md](../CODE_QUALITY.md), and logged in `FULL_CODEBASE_3db88c2c_REVIEW_RESPONSE.txt` upon completion.

---

## 2. Batch 1 — P1 Correctness, Data Integrity & Timezone Consistency

### Slice 1.1 — Fix Same-Day Lease Void Deposit Guard (#6) — **Completed**
- **Checkpoint**: Added `SQLiteLeaseFinanceActivityReader` (`finance/infrastructure/lease_activity_reader.py`), wired via `LeaseFinanceActivityReader` port in `bootstrap/api.py`, replaced raw SQL + `except Exception: continue` in `LeaseService._has_settled_same_day_activity()`. Verified with `test_void_same_day_activity.py` (4 passed).
- **Target files**:
  - `application/apps/server/app/modules/leases/application/service.py:1325-1330, 1889-1918`
  - `application/apps/server/app/modules/leases/application/ports.py`
  - `application/apps/server/app/modules/leases/infrastructure/unit_of_work.py`
  - `application/apps/server/app/bootstrap/api.py` (if wiring a Finance/Inspection port)
- **Changes**:
  - Replace the broken `security_deposit_transactions` (`deposit_account_id`) raw SQL query in `_has_settled_same_day_activity()` with a query against `security_deposit_receipts` joined on `account_id = a.id` (preferably through an owning Finance/Inspection port rather than raw SQL in `leases`).
  - Remove the broad `except Exception: continue` so schema/SQL errors fail loudly instead of silently returning `False`.
- **Acceptance & Tests (#18)**:
  - Focused `leases` tests on a real migrated SQLite DB verifying same-day `void_lease` is rejected when an active `security_deposit_receipts`, `rent_receipts`, or finalized `condition_reports` row exists, and succeeds when none exist (or only voided receipts exist).

### Slice 1.2 — Switch `SQLiteMaintenanceUnitOfWork` to `create_sqlite_engine()` (#12) — **Completed**
- **Checkpoint**: Switched `SQLiteMaintenanceUnitOfWork` to hold `self.engine = create_sqlite_engine(database)` and updated query-budget tests to listen on `unit_of_work.engine`. Verified with `test_uow_integrity.py`, `test_command_readiness.py`, and `test_workflow.py` (all passing).
- **Target files**:
  - `application/apps/server/app/modules/maintenance/infrastructure/unit_of_work.py:13, 1196-1268`
- **Changes**:
  - Initialize `self.engine = create_sqlite_engine(database)` once in `SQLiteMaintenanceUnitOfWork.__init__()` and reuse it in `write()` and `read()` instead of calling raw `create_engine(f"sqlite:///{self.database}")` per call.
  - Restores `PRAGMA foreign_keys = ON`, `BEGIN IMMEDIATE`, `raise_closed_attempt` (`ClosedCommandError` / `PreparedEditRequired`), `unicode_casefold`, and canonical `engine.url` matching for `workspace_mutation_scope`.
- **Acceptance & Tests (#18)**:
  - Focused `maintenance` tests verifying FK violations are rejected at SQLite level, closed-command attempt fences map to `ClosedCommandError` (HTTP 409 `submission_closed`), and paths with special characters work cleanly.

### Slice 1.3 — Property-Timezone Business Dates Across Backend & Frontend (#7, #13, #15) — **Completed**
- **Checkpoint**: Replaced host `date.today()` with stored Property `ZoneInfo` dates across `leases`, `inspections`, `portfolio`, and `tenants`; updated `vendors` `lastCheckedOn` to UTC+14 calendar-date bound; updated `leasing.tsx` to compute same-day void eligibility via `Intl.DateTimeFormat("en-CA", { timeZone })`. Verified with `test_property_timezone_dates.py` and focused vendor/portfolio/tenant tests.
- **Target files**:
  - `application/apps/server/app/modules/leases/application/service.py:798, 1037, 1219, 1304, 1626, 1986, 2232`
  - `application/apps/server/app/modules/inspections/application/service.py:232`
  - `application/apps/server/app/modules/portfolio/application/service.py:1175`
  - `application/apps/server/app/modules/portfolio/infrastructure/unit_of_work.py:64, 84`
  - `application/apps/server/app/modules/tenants/application/service.py:354`
  - `application/apps/server/app/modules/vendors/api/router.py:184-189`
  - `application/apps/server/app/modules/vendors/application/service.py:1720-1726`
  - `application/apps/web/src/workflows/leasing.tsx:266-276`
- **Changes**:
  - Resolve current business date via `datetime.now(ZoneInfo(property.time_zone)).date()` for property-, space-, lease-, and inspection-scoped operations, and evaluate cross-property party/tenant archive guards per property timezone.
  - For non-property-scoped provider `lastCheckedOn` (#13), validate against a UTC+14 calendar-date bound or explicit `asOf` date so UTC+ operators are not blocked.
  - In `leasing.tsx:270` (#15), derive same-day `lease.void` eligibility from backend-computed eligibility or `Intl.DateTimeFormat("en-CA", { timeZone: propertyTimeZone })` instead of `new Date().toISOString().slice(0, 10)`.
- **Acceptance & Tests (#18)**:
  - Focused tests simulating a UTC host clock at e.g. `2026-11-25T02:00:00Z` with an `America/Los_Angeles` property (`2026-11-24` local) verifying lease execution, same-day voiding, move-out validation, inspection attention, archive guards, and `leasing.tsx` action visibility.

---

## 3. Batch 2 — P2 Reliability, Resource Hygiene & Query Budgets

### Slice 2.1 — Avoid Per-Request Full Schema/Data Scans on `/health` & `/api/workspace` (#1) — **Completed**
- **Checkpoint**: Cached validated `WorkspaceManifest` on `WorkspaceRuntime`, added lightweight `SQLiteWorkspaceStore.ping()`, and served `/health` and `/api/workspace` from ready runtime state without calling `validate_latest_schema()` or `chmod`. Verified with `workspace/tests/test_api.py` (12 passed).
- **Target files**:
  - `application/apps/server/app/modules/workspace/api/router.py:40-73`
  - `application/apps/server/app/modules/workspace/application/runtime.py`
- **Changes**:
  - Cache the validated `WorkspaceManifest` on `WorkspaceRuntime` during `start()`/`refresh()`.
  - Serve `GET /health` and `GET /api/workspace` from validated runtime state (plus lightweight DB/manifest presence check) instead of calling `service.open()` (`validate_latest_schema()` + `chmod`) on every request.
- **Acceptance & Tests**:
  - Focused `workspace` API tests verifying `/health` and `/api/workspace` return 200 without invoking `validate_latest_schema()` on already-ready runtimes, while still returning 503/404 when uninitialized or errored.

### Slice 2.2 — Fix File Verification Continuation, Replay Rollback & Backup Connection Leaks (#2, #3, #4) — **Completed**
- **Checkpoint**: Restricted per-file content verification in `FileStorageVerificationService.verify()` to initial pass (`continuation is None`) with `counts` carried in cursor; isolated `FileService.upload()` replay rollback to prevent double-rollback and record cleanup attention; wrapped all three `sqlite3.connect(...)` calls in `BackupService` with `contextlib.closing(...)`. Verified with `test_verification_and_replay.py` and `test_backup_service.py`.
- **Target files**:
  - `application/apps/server/app/modules/files/application/verification.py:51-156` (#2)
  - `application/apps/server/app/modules/files/application/service.py:249-274` (#3)
  - `application/apps/server/app/modules/workspace/application/backup_service.py:425, 441, 467` (#4)
- **Changes**:
  - (#2) Run per-file content hashing/verification only on the initial verification call (`continuation is None`), carry `counts` in the continuation cursor, and advance only paginated S3 reconciliation on subsequent pages.
  - (#3) Isolate replay-path `content.rollback()` in its own `try/except`, record `PublicationCleanupIncomplete` on failure, and clear `content = None` so the outer `except` never double-rolls back.
  - (#4) Wrap all three `sqlite3.connect(...)` calls in `BackupService` with `contextlib.closing(...)`.
- **Acceptance & Tests**:
  - Focused `files` tests for multi-page S3 verification (asserting `path_for` is called once per file, not once per page) and replay rollback failure handling; focused `workspace` backup/restore tests.

### Slice 2.3 — Eliminate Inspection & Prepaid Check N+1 Queries and Narrow `OperationalError` Mapping (#8, #9, #11) — **Completed**
- **Checkpoint**: Batched `SQLiteInspectionUnitOfWork.report_views()` and `template_views()` with `IN (...)` queries; narrowed `SQLiteInspectionUnitOfWork.write()` `OperationalError` mapping to SQLite lock errors only; added batch expectation/receipt/reminder preload in `PrepaidCheckService.list()`. Verified with `test_batch_and_errors.py`, `inspections/tests/test_workflow.py`, and `finance/tests/test_finance.py`.
- **Target files**:
  - `application/apps/server/app/modules/inspections/infrastructure/unit_of_work.py:53-62, 100-110, 129-147, 424-507` (#8, #9)
  - `application/apps/server/app/modules/finance/application/prepaid_check_service.py:225-256, 749-760` (#11)
  - `application/apps/server/app/modules/finance/infrastructure/unit_of_work.py` (#11 batch projection helpers)
- **Changes**:
  - (#8) Batch-load areas, observations, file attachments, acknowledgments, and template items with `IN (...)` queries in `SQLiteInspectionUnitOfWork`.
  - (#9) Only map `OperationalError` to `InspectionConflictError` when `"locked"` is in `str(error).casefold()`; re-raise all other `OperationalError`s.
  - (#11) Batch-load expectations, lease/term snapshots (with property `time_zone`), and linked receipts per chunk in `PrepaidCheckService.list()`.
- **Acceptance & Tests**:
  - Query-count assertions on `report_views`, `template_views`, and `PrepaidCheckService.list()`; focused test verifying non-lock `OperationalError` is not turned into HTTP 409.

---

## 4. Batch 3 — P3 Hygiene, Boundary Cleanup & Polish

### Slice 3.1 — Small Targeted Fixes (#5, #14, #16, #17) — **Completed**
- **Checkpoint**: Added `"file_too_large"` error code in `FilesystemContentStore.store()`; logged privacy-safe warning in `BackupProxyServer` connection handler; called `await checkHostedResponse(response)` in `hosted-settings.tsx`; broadened PEM private-key regex and resolved `--output` parent path in `hosted_package.py`.
- **Target files**:
  - `application/apps/server/app/modules/files/infrastructure/content_store.py:89-90` (#5: pass `"file_too_large"` error code)
  - `application/apps/server/app/modules/host_agent/infrastructure/backup_proxy.py:520-522` (#14: log privacy-safe warning with exception class + peer UID)
  - `application/apps/web/src/app/hosted-settings.tsx:171-182` (#16: call `await checkHostedResponse(response)`)
  - `application/scripts/hosted_package.py:135-146, 246-248` (#17: match all `-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----` headers and resolve `--output` parent path)
- **Acceptance & Tests**:
  - Focused unit tests for each of the 4 fixes.

### Slice 3.2 — Remove Cross-Module ORM Imports in Wave 2 Infrastructure (#10) — **Completed**
- **Checkpoint**: Removed all 5 cross-module ORM/UoW imports from `inspections/infrastructure/{unit_of_work,recovery_reader}.py`, `leases/infrastructure/{context_reader,unit_of_work}.py`, and `portfolio/infrastructure/unit_of_work.py` by routing reads/writes through `SQLiteFileLinkReader`, `SQLiteLeaseContextReader`, `SQLitePortfolioContextReader`, and `SQLitePartyOperations` wired in `bootstrap/api.py` and `bootstrap/operator_inspection_commands.py`. Cross-module import scan confirmed 0 violations; 66 focused tests in `inspections`, `leases`, and `portfolio` passed.
- **Target files**:
  - `application/apps/server/app/modules/inspections/infrastructure/unit_of_work.py:15-19, 38-42`
  - `application/apps/server/app/modules/inspections/infrastructure/recovery_reader.py:12`
  - `application/apps/server/app/modules/leases/infrastructure/context_reader.py:15`
  - `application/apps/server/app/modules/leases/infrastructure/unit_of_work.py:13-17`
  - `application/apps/server/app/modules/portfolio/infrastructure/unit_of_work.py:15, 18`
  - `application/apps/server/app/bootstrap/api.py`
- **Changes**:
  - Route cross-module reads through small owning-module reader/operation protocols (`SQLiteFileLinkReader`, `SQLiteLeaseContextReader`, `SQLitePortfolioContextReader`, `PartyTransactionOperations`) wired in `app/bootstrap/api.py`.
- **Acceptance & Tests**:
  - Re-run Phase 0 cross-module infrastructure import scan confirming 0 domain-module ORM imports; run focused `inspections`, `leases`, and `portfolio` test suites.

---

## 5. Validation Matrix & Completion Gate

| Validation Area | Coverage |
| --- | --- |
| Happy paths | Same-day lease void (no activity), maintenance CRUD, timezone-aware lease/inspection/vendor ops, `/health` & `/api/workspace`, batched inspection & prepaid-check reads |
| Invalid combinations | Same-day lease void with active deposit/rent receipt/finalized report, Maintenance FK violation, future move-out/lastCheckedOn across UTC midnight |
| Idempotency & retry | `FileService.upload()` replay rollback failure, multi-page S3 verification continuation |
| Transaction rollback | `SQLiteMaintenanceUnitOfWork` rollback on FK/fence error, `FileService` rollback attention |
| Query budgets / N+1 | Constant query count on `report_views`, `template_views`, `PrepaidCheckService.list()`, and `/health` |
| Static & contract gates | `ruff check`, `ruff format --check` on all changed Python; `npm run lint`, `npm run format:check`, `npm run typecheck`, and OpenAPI contract parity check if any API schema changes |

Upon completing all batches, save `docs/pending_code_review_comments/FULL_CODEBASE_3db88c2c_REVIEW_RESPONSE.txt` summarizing every change with exact `file:line` references and validation results.
