# HOSTED-001 Slice H05.3 Checkpoint — Internal Workspace Backup Runner & Stale Alerting

**Date:** 2026-11-23
**Owning Design Doc:** [HOSTED_MVP_H05_DESIGN.md](../../design/HOSTED_MVP_H05_DESIGN.md#9-ordered-implementation-plan)
**Status:** Complete

## Summary of Changes

1. **Deduplicated External Alert Emitter (D10)**:
   - Added `application/apps/server/app/modules/hosted_recovery/infrastructure/alerting.py`: `RecoveryAlert`, `StructuredLogAlertSink`, HTTPS `WebhookAlertSink`, and `DeduplicatingAlertEmitter` deduplicating per `(operator_id, alert_kind)` (`backup_failed`, `backup_overdue`, `backup_unknown`) and emitting explicit `backup_recovered` notices when protection returns to `healthy`/`unchanged`.
2. **Source-Authenticated Async `workspace_recovery_status` Ingest (D12)**:
   - Added `application/apps/server/app/modules/hosted_admin/infrastructure/recovery_status_ingest.py`: Ed25519-signed `WorkspaceProtectionSummary` (`sign_protection_summary` / `verify_protection_summary`) and `RecoveryStatusIngestService` fencing updates in `admin.sqlite` by `(operator_id, workspace_id, source_epoch)` and monotonic `source_revision` while tolerating Admin outages on the Operator side.
3. **Internal Workspace Backup Runner & Retention (`WorkspaceRecoveryPort`)**:
   - Added `application/apps/server/app/modules/workspace/infrastructure/hosted_recovery.py`:
     - `HostedWorkspaceRecoveryService` implementing `Capture`, `ReconcileCheckpoint`, `observe`, `original`, `read_protection_status`, `reconcile_startup`, `evaluate_freshness` (28-hour `OVERDUE_THRESHOLD_MS`), and best-effort signed summary publishing.
     - Backup-invariant SQLite + retained-file fingerprinting (`probe_live_workspace_state`) and consistent staging via `sqlite3.Connection.backup()` (`stage_consistent_snapshot`) in `scratch/` without holding SQLite writer locks during off-host uploads.
     - `healthy` vs. `unchanged` detection (preserving `captured_at`/`verified_at` when unchanged, detecting file-only changes, and marking unreadable/corrupt state `unknown` rather than `unchanged`).
     - Startup crash reconciliation (`reconcile_startup`) resolving interrupted `running`/`pending` operations and flagging post-crash live-vs-protected drift (`source_commit_crash`) as degraded until catch-up verification succeeds.
     - 7-point reference-safe retention (`_enforce_retention`) pruning only unreferenced chunks via `ChunkedAeadBackupEngine.prune_unreferenced_chunks` and never expiring the sole usable point.

## Validation Results

- `pytest` (`apps/server/app/modules/hosted_recovery/tests/test_h05_backup_runner_and_alerting.py`): **5 passed**, covering `consistent_scheduled_capture` + idempotency/conflict, `unchanged_file_only_checkpoints` + unreadable-never-unchanged, `source_commit_crash` startup reconciliation + catch-up recovery, `seven_points_incremental_retention` (9 points → 7 verified + 2 pruned with shared chunks intact and oldest retained point restorable), and overdue alerting + Admin outage independence + Ed25519 signed `workspace_recovery_status` ingest.
- `ruff check --config application/pyproject.toml`: **All checks passed** across all 4 new Python files.
- `ruff format --check --config application/pyproject.toml`: **4 files already formatted**.

## Next Slice

- **H05.4**: Operator-Authorized Restore & Minimal Recovery Mode (`PreviewRestore`, `ConfirmRestore`, `AcceptRestore`, `ReconstructCatalog`, strong step-up integration, crash-safe `active_business_ref` locator switch, forensic prior-tree retention, minimal recovery-mode startup in `operator_entry.py`, `/api/hosted/recovery/*` API).
