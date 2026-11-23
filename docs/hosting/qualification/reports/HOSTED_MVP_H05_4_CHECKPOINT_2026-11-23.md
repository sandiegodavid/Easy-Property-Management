# HOSTED-001 Slice H05.4 Checkpoint — Operator-Authorized Restore & Minimal Recovery Mode

**Date:** 2026-11-23
**Owning Design Doc:** [HOSTED_MVP_H05_DESIGN.md](../../design/HOSTED_MVP_H05_DESIGN.md#9-ordered-implementation-plan)
**Status:** Complete

## Summary of Changes

1. **Operator-Authorized Restore, Preview, Acceptance & Catalog Reconstruction (`HostedWorkspaceRecoveryService`)**:
   - Extended `application/apps/server/app/modules/workspace/infrastructure/hosted_recovery.py` with:
     - `detect_startup_mode()` inspecting `recovery_meta.active_business_ref`, unfinished `restore_operations`, and `EPM_RECOVERY_MODE_REQUIRED` before business composition (never silently initializing an empty business DB).
     - `protection_section()` building a live `Section[Protection]` directly from `recovery.sqlite` (D12, zero Admin dependency).
     - `preview_restore()` (`PreviewRestore`) issuing short-lived 10-minute previews with deterministic `exact_request_hash` binding `(workspace_id, point_id, source_epoch, preview_id)` (D4) and rejecting foreign, unverified, or schema-incompatible points.
     - `confirm_restore()` (`ConfirmRestore`) enforcing single-use preview consumption, 10-minute step-up freshness, 5-minute execution authorization window, `SourceLifecycle` `maintenance_fence` + `drain`, sibling-directory restore (`incarnation-<new_gen>`), SQLite `PRAGMA integrity_check` + file digest validation, atomic `recovery_meta.active_business_ref` switchover (D6), `SourceLifecycle.verify_restore_binding` (advancing `access_epoch`/`restore_generation` and revoking all existing operator sessions without Admin dependency), forensic prior-tree preservation (`healthy_pre_state` / `forensic_damaged`), and clean staging rollback on failure.
     - `accept_restore()` marking switched restores `accepted` after fresh post-restore operator sign-in.
     - `reconstruct_catalog()` (`ReconstructCatalog`) rebuilding missing verified `recovery_points` rows from own-workspace off-host manifests.
2. **Authenticated Operator Recovery API (`/api/hosted/recovery/*`)**:
   - Added `application/apps/server/app/modules/hosted_access/api/operator_recovery.py` exposing `GET /status`, `GET /points`, `POST /preview` (paired with `SourceSessions.begin_recent`), `POST /confirm` (atomically consuming `RecentAuthGrant` via `SourceSessions.consume_recent`), `GET /operations/{operation_id}`, `POST /accept`, and `POST /reconstruct` with strict origin, operator cookie, CSRF (`x-epm-csrf`), and closed request contracts (rejecting caller-supplied filesystem paths or key/object refs).
3. **Minimal Recovery Mode Runtime & Entry**:
   - Updated `application/apps/server/app/modules/hosted_access/infrastructure/operator_identity_runtime.py` (`DestinationHTTP`, `OperatorIdentityInputs`, `create_minimal_recovery_app`) to route `/api/hosted/recovery/*` and wire `protection_reader` into `/api/hosted/settings`, while returning `503 recovery_mode_active` for business `/api/*` routes in minimal recovery mode without opening or initializing a business DB.
   - Updated `application/apps/server/app/modules/hosted_access/infrastructure/operator_entry.py` (`OperatorDeployment`, `candidate`) to validate `HostedStore.RECOVERY` when configured and automatically boot `create_minimal_recovery_app` when business DB validation fails, an interrupted restore exists, or `EPM_RECOVERY_MODE_REQUIRED=1`.

## Validation Results

- `pytest` (`test_h05_operator_restore_and_recovery_mode.py` + `test_h05_backup_runner_and_alerting.py`): **10 passed** (5 H05.4 + 5 H05.3), covering `corrupt_business_recovery_mode`, `operator_step_up_exact_confirmation`, `cross_workspace_replay_path_key_denial`, `crash_safe_locator_switch`, `forensic_prior_tree` (both `forensic_damaged` and `healthy_pre_state`), `admin_outage_independence` + `reconstruct_catalog`, and `no_offline_workspace_bypass`.
- `ruff check --config application/pyproject.toml`: **All checks passed** across all 5 changed/new Python files.
- `ruff format --check --config application/pyproject.toml`: **5 files already formatted**.

## Next Slice

- **H05.5**: Clean-Runtime Repair (`repair_runtime`) — Admin `repair_runtime` operation + Host Agent container-only replacement preserving IDs, trees, stores, and key refs, booting damaged workspaces into minimal recovery mode.
