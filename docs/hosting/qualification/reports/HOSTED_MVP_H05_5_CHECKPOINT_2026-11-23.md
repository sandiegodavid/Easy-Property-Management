# HOSTED-001 Slice H05.5 Checkpoint — Clean-Runtime Repair (`repair_runtime`)

**Date:** 2026-11-23
**Owning Design Doc:** [HOSTED_MVP_H05_DESIGN.md](../../design/HOSTED_MVP_H05_DESIGN.md#9-ordered-implementation-plan)
**Status:** Complete

## Summary of Changes

1. **Admin `repair_runtime` Admission & Operation Lookup**:
   - Updated `application/apps/server/app/modules/hosted_admin/infrastructure/admin_control.py`:
     - Wired `RepairRuntime` in `AdminControlService.execute` → `_repair_runtime()` enforcing sensitive Admin MFA auth, idempotent replay + `SemanticConflict` on changed semantics, active operator revision/epoch fencing, `qualified_releases(component='operator', state='qualified')` verification, concurrent lifecycle operation conflict rejection, and `operations`/`operation_events`/`admin_audit` persistence without altering operator IDs, workspace IDs, policy, or access intent.
     - Added `get_operation_outcome()` for original-operation status lookup (`CHECK_OPERATION`).
   - Updated `application/apps/server/app/modules/hosted_admin/api/router.py`:
     - Added `POST /api/admin/operators/{operator_id}/repair-runtime` (returns `202` with `OperationOutcome`) and `GET /api/admin/operations/{operation_id}` while exposing zero customer-workspace restore/decrypt endpoints.
2. **Host Agent Clean-Runtime Repair Orchestrator**:
   - Added `application/apps/server/app/modules/host_agent/infrastructure/repair_runtime.py` (`CleanRuntimeRepairer`):
     - Loads and verifies `operations(kind='repair_runtime')` against `qualified_releases(state='qualified')`, with idempotent return if already `succeeded`.
     - Stops/fences the former container before touching any state.
     - Validates retained `access.sqlite` (`HostedStore.HOSTED_ACCESS`, matching `deployment_id`/`operator_id`/`workspace_id`) and `recovery.sqlite` (`HostedStore.RECOVERY`, matching `workspace_id`, preserving `encryption_key_ref` and `active_business_ref`); fails closed to `needs_attention` if either store is missing/invalid without recreating or wiping stores.
     - Revokes all prior sessions in `access.sqlite` (`revoked_at = now`, `session_generation += 1`, `not_before = max(not_before, now + 1)`) so zero sessions carry over.
     - Inspects the active business DB read-only (never initializing an empty DB or running synthetic seeding) and replaces only the container in minimal recovery mode (`recovery_mode_required=True`).

## Validation Results

- `pytest` (`test_h05_clean_runtime_repair.py` + `test_admin_control.py`): **9 passed** (3 H05.5 + 6 AdminControl regression tests), proving `clean_runtime_repair` preserves IDs/data/stores/key refs, revokes prior sessions, never runs empty init, boots into minimal recovery mode, fails closed on missing stores, and supports idempotent retry and HTTP operation lookup.
- `ruff check --config application/pyproject.toml`: **All checks passed** across all 4 changed/new Python files.
- `ruff format --check --config application/pyproject.toml`: **4 files already formatted**.

## Next Slice

- **H05.6**: Admin Control-Plane Backup & Independent Recovery Mode (`AdminRecoveryPort`, `CaptureControl`, `PreviewControlRestore`, `ConfirmControlRestore`, protected bootstrap authority file (D5), Admin recovery mode without opening `admin.sqlite`, platform host-loss recovery CLI).
