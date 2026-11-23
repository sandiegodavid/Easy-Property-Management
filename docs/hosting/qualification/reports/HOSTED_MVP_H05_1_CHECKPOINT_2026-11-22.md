# HOSTED-001 Slice H05.1 Checkpoint — Greenfield Recovery Schemas & `SourceLifecycle` Fences

**Date:** 2026-11-22
**Owning Design Doc:** [HOSTED_MVP_H05_DESIGN.md](../../design/HOSTED_MVP_H05_DESIGN.md#9-ordered-implementation-plan)
**Status:** Complete

## Summary of Changes

1. **Greenfield Operator Recovery Store (`HostedStore.RECOVERY`)**:
   - Replaced scaffold in `application/database/recovery-migrations/alembic.ini` (`resource_state = implemented`) and `env.py` (`run_resource_environment(HostedStore.RECOVERY)`).
   - Added executable baseline `application/database/recovery-migrations/versions/recovery_0001_initial.py` (`recovery_meta`, `recovery_operations`, `recovery_points`, `backup_state`, `restore_operations`, `recovery_audit`) with singleton checks, safe `namespace_prefix` validation, operator-only restore authorization constraint, append-only audit triggers, and terminal/immutability/monotonicity guards.
2. **Greenfield Admin Control Recovery Store (`HostedStore.ADMIN_RECOVERY`)**:
   - Replaced scaffold in `application/database/admin-recovery-migrations/alembic.ini` and `env.py`.
   - Added executable baseline `application/database/admin-recovery-migrations/versions/admin_recovery_0001_initial.py` (`admin_recovery_meta`, `control_recovery_operations`, `control_recovery_points`, `control_restore_operations`, `control_backup_state`, `control_recovery_audit`) with zero cross-DB FKs to `admin.sqlite`, Admin restore authorization checks, and append-only/immutability guards.
3. **Store Registration & Relationship Validation**:
   - Registered `HostedStore.RECOVERY` and `HostedStore.ADMIN_RECOVERY` in `application/apps/server/app/platform/schema_resources.py` (`IMPLEMENTED_REVISIONS`).
   - Added constant-query cross-table relationship and duplicate-key-free JSON validators in `application/apps/server/app/modules/hosted_access/infrastructure/schema_validation.py`.
   - Updated `application/apps/server/app/platform/tests/test_hosted_artifacts.py` (`unavailableSchemas` now empty for all components).
4. **D7 (`SourceLifecycle` Fences & `'drain'` Receipt) & D8 (`unchanged` Protection Mapping)**:
   - Added `'drain'` to `access_receipts.kind` CHECK constraint in `application/database/hosted-access-migrations/versions/access_0001_initial.py`.
   - Implemented `maintenance_fence`, `drain`, and `verify_restore_binding` (mapped to `'restore_binding'`) in `application/apps/server/app/modules/hosted_access/infrastructure/source_lifecycle.py`, supporting Admin-outage-independent `access_epoch` + `restore_generation` advancement and live session revocation.
   - Fixed `application/apps/server/app/modules/hosted_admin/infrastructure/admin_control.py` so both `healthy` and `unchanged` project to `Protection.status = "protected"` and readiness `protection` gate `"passed"`, while `overdue` projects to `"degraded"` and `unknown`/`unavailable` project to `Section[Protection](state="unavailable")`.

## Validation Results

- `pytest`: **52 passed** (`test_recovery_schema.py`, `test_h05_source_lifecycle_fences.py`, `test_hosted_artifacts.py`, `test_admin_control.py`, `test_sessions.py`).
- `ruff check --config application/pyproject.toml`: **All checks passed** across all 12 changed/added Python files.
- `ruff format --check --config application/pyproject.toml`: **12 files already formatted**.

## Adjacent Issues Noted (Not Modified)

- Pre-existing `application/apps/server/app/platform/tests/test_access_schema.py::test_usage_and_draft_constraints` omits `restore_generation` when inserting into `draft_leases`.

## Next Slice

- **H05.2**: Backup Engine, Envelope Encryption & `epm-backup-proxy` (D2, D3, D11).
