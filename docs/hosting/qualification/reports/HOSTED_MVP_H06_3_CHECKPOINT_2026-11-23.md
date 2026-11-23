# HOSTED-001 Slice H06.3 Checkpoint — Nightly Backup Scheduler, Async Summary Relay (D12), External Alerting & Maintenance Notice

**Date:** 2026-11-23  
**Slice:** H06.3  
**Owning Design:** [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md)  
**Owning Delivery Plan:** [delivery-plan.md](../../design/mvp/delivery-plan.md#implementation-slices)  
**Operations Runbook:** [H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md](../../runbooks/H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md)  
**Branch:** `hosted_mvp`

---

## 1. Completed Deliverables

1. **Nightly Backup Scheduler & Hourly Overdue Watchdog (D6 — `scheduler.py`, `operator_entry.py`, `operator_identity_runtime.py`, `shared_identity_entry.py`):**
   - Created [scheduler.py](../../../../application/apps/server/app/modules/hosted_recovery/infrastructure/scheduler.py) with `deterministic_nightly_jitter_seconds()`, `WorkspaceBackupScheduler` (running hourly `evaluate_freshness()` watchdog + 24h jittered `Capture` with per-day idempotency keys), and `AdminControlBackupScheduler` (running 24h jittered `CaptureControl`).
   - Wired `WorkspaceBackupScheduler` into [operator_entry.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/operator_entry.py) & [operator_identity_runtime.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/operator_identity_runtime.py) lifespan (normal mode only, Admin-outage independent), and `AdminControlBackupScheduler` into [shared_identity_entry.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/shared_identity_entry.py) lifespan.

2. **Private Async Protection Summary Relay (`POST /internal/recovery-status`, D7 / D12 — `recovery_status_ingest.py`, `shared_identity_entry.py`, `operator_entry.py`):**
   - Added `handle_recovery_status_connection()`, `RecoveryStatusRelayServer` (`SO_PEERCRED` UID + Ed25519 signature verification via `RecoveryStatusIngestService`), and bounded-timeout best-effort `UnixSummaryPublisher` (5s timeout, swallowing relay outages so backups are never blocked or invalidated) to [recovery_status_ingest.py](../../../../application/apps/server/app/modules/hosted_admin/infrastructure/recovery_status_ingest.py).
   - Mounted `RecoveryStatusRelayServer` on `socket_directory/recovery-status.sock` in [shared_identity_entry.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/shared_identity_entry.py) resolving Operator Ed25519 keys from `SourceRegistry`, and wired `UnixSummaryPublisher` into [operator_entry.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/operator_entry.py) (`recovery_status_socket`).

3. **External Alerting Wiring (D3 — `alerting.py`, `operator_entry.py`):**
   - Added `build_alert_emitter(webhook_url=...)` to [alerting.py](../../../../application/apps/server/app/modules/hosted_recovery/infrastructure/alerting.py) combining `StructuredLogAlertSink` with optional SSRF-validated `WebhookAlertSink` (HTTPS public host, no redirects), and wired `alert_webhook_url` on `OperatorDeployment` in [operator_entry.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/operator_entry.py).

4. **Read-Only Shared Maintenance Notice Reader (D5 — `maintenance_notice.py`, `operator_identity_runtime.py`, `operator_entry.py`):**
   - Created [maintenance_notice.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/maintenance_notice.py) reading `/run/epm/maintenance-notice.json` (O(1) bounded `<= 8 KiB` read, failing safe to `unavailable` on missing/inactive/malformed files) and wired `maintenance_reader` through `OperatorIdentityInputs` into `OperatorSettingsInputs`.

---

## 2. Validation Results

- **Focused tests:** [test_h06_scheduler_relay_and_maintenance.py](../../../../application/apps/server/app/modules/hosted_recovery/tests/test_h06_scheduler_relay_and_maintenance.py), `test_h05_backup_runner_and_alerting.py`, and `test_h06_runtime_wiring.py` — **13/13 passed**.
- **Lint & formatting:** `ruff check` and `ruff format --check` (`application/pyproject.toml`) on all 9 changed Python files — **All checks passed / 9 files already formatted**.
