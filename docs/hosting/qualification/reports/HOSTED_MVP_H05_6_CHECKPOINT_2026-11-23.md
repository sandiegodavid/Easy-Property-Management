# HOSTED-001 Slice H05.6 Checkpoint — Admin Control-Plane Backup & Independent Recovery Mode

**Date:** 2026-11-23
**Owning Design Doc:** [HOSTED_MVP_H05_DESIGN.md](../../design/HOSTED_MVP_H05_DESIGN.md#9-ordered-implementation-plan)
**Status:** Complete

## Summary of Changes

1. **Protected Bootstrap Recovery Authority & Admin Control Recovery Service (D5)**:
   - Added `application/apps/server/app/modules/hosted_admin/infrastructure/admin_recovery.py`:
     - `BootstrapRecoveryAuthority` + `load_bootstrap_authority()`: validates private non-symlink `/run/epm/admin-recovery-authority.json` pinned by SHA-256 in `admin_recovery_meta.recovery_authority_ref`, verifying approved Admin recovery principals + TOTP/MFA without ever opening `admin.sqlite` (rejecting Operator identities and un-MFA callers).
     - `AdminControlRecoveryService` implementing `AdminRecoveryPort`:
       - `CaptureControl`: snapshots `admin.sqlite` + `host_inventory.sqlite` via `sqlite3.Connection.backup()` into `scratch/`, encrypts and uploads under `deployments/<id>/control/...` with full readback verification, and records verified `control_recovery_points`, `control_backup_state`, and `control_recovery_audit`.
       - `detect_admin_mode()`: detects damaged/missing `admin.sqlite` and boots Admin recovery mode without requiring `admin.sqlite`.
       - `PreviewControlRestore` & `ConfirmControlRestore`: restores into a separate sibling incarnation (`admin-incarnation-<new_gen>`), preserves `admin-recovery.sqlite` and prior `admin.sqlite` intact, validates schemas (`HostedStore.ADMIN`, `HostedStore.HOST_INVENTORY`) + `PRAGMA integrity_check`, advances `control_meta.registry_generation`, revokes all historical `admin_sessions` and `managed_identity_sessions`, marks historical `pending`/`running` `operations` `unknown` (`historical_after_control_restore`, never replayed), and supports explicit `accept_control_restore()`.
       - `reconstruct_on_clean_host()` + `build_host_loss_cli_parser()`: restricted platform control-plane host-loss recovery initializing a fresh `admin-recovery.sqlite` incarnation and reconstructing verified `control_recovery_points` from off-host manifests + KMS without importing runnable prior operations or exposing any customer-workspace restore/decrypt capability.
2. **Independent Admin Control Recovery HTTP Router**:
   - Added `application/apps/server/app/modules/hosted_admin/api/recovery_router.py` exposing `GET /api/admin/recovery/status`, `GET /api/admin/recovery/points`, `POST /api/admin/recovery/preview`, `POST /api/admin/recovery/confirm`, `POST /api/admin/recovery/accept`, and `POST /api/admin/recovery/reconstruct` independent of `admin.sqlite`.
   - Wired optional `admin_recovery` + `authenticate_recovery` into `build_admin_identity_app()` in `application/apps/server/app/modules/hosted_access/api/admin_identity.py`.

## Validation Results

- `pytest` (`apps/server/app/modules/hosted_recovery/tests/test_h05_admin_control_recovery.py`): **2 passed**, covering `separate_admin_recovery_loss` (damaged main `admin.sqlite`, independent bootstrap MFA auth, `/api/admin/recovery/*` preview/confirm/accept, `registry_generation` advance, historical session revocation, pending operation inerting) and `whole_host_control_loss` (clean-host fresh `admin-recovery.sqlite` incarnation, off-host manifest catalog reconstruction, full control restore, and control-only CLI scope).
- `ruff check --config application/pyproject.toml`: **All checks passed** across all 4 changed/new Python files.
- `ruff format --check --config application/pyproject.toml`: **4 files already formatted**.

## Next Slice

- **H05.7**: Positive Workspace Gateway Routing (`desired_state="eligible"`) — `WorkspaceRouteManifest` (D9), `HostAgentService` + `gateway.py` + `auth_projection.py` eligible projection gated by verified H05 recovery-point proof, `operator_entry.py` live `readiness` + `protection_reader`.
