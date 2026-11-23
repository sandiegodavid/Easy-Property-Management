# HOSTED-001 Slice H06.2 Checkpoint — Production Runtime & Host-Service Wiring

**Date:** 2026-11-23  
**Slice:** H06.2  
**Owning Design:** [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md)  
**Owning Delivery Plan:** [delivery-plan.md](../../design/mvp/delivery-plan.md#implementation-slices)  
**Operations Runbook:** [H06_2_HOST_SERVICES_OPERATIONS_RUNBOOK.md](../../runbooks/H06_2_HOST_SERVICES_OPERATIONS_RUNBOOK.md)  
**Branch:** `hosted_mvp`

---

## 1. Completed Deliverables

1. **Live Workspace Readiness, `AdminControlService`, `AdminControlRecoveryService` & D5 Recovery Fallback (`admin_entry.py`, `shared_identity_entry.py`):**
   - Replaced the `AwaitingWorkspaceReadiness` stub in [shared_identity_entry.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/shared_identity_entry.py) with `AdminWorkspaceReadiness`, querying `main.operators` (`desired_access = 'enabled'`, `setup_state IN ('ready_for_claim', 'active')`, exact `access_epoch`) joined with `main.workspace_recovery_status` (`protection_state IN ('healthy', 'unchanged')`).
   - Added `build_admin_recovery_runtime()` and `build_admin_runtime()` in [admin_entry.py](../../../../application/apps/server/app/modules/hosted_access/infrastructure/admin_entry.py) wiring `AdminControlService`, `AdminControlRecoveryService`, and D5 `build_bootstrap_recovery_authenticator()` (verifying Google + TOTP MFA + live Firebase revocation independently of `admin.sqlite`) into both `admin_entry.py` and `shared_identity_entry.py`.
   - Wired automatic D5 recovery-mode fallback (`create_admin_recovery_app()`) when `admin.sqlite` is missing or corrupted and recovery configuration is present, keeping Admin recovery live on the admin host while failing closed (`503 admin_recovery_mode_active`) on the central login host.

2. **`epm-backup-proxy` CLI & Hardened Systemd Unit (`backup_proxy.py`, `service_config.py`, `host_services.py`, `install_services.py`):**
   - Added `load_r2_credentials()`, `build_cli_parser()`, `_resolve_cli_settings()` (supporting `--config` and systemd `$CREDENTIALS_DIRECTORY/r2.json`), `main()`, and `if __name__ == "__main__":` to [backup_proxy.py](../../../../application/apps/server/app/modules/host_agent/infrastructure/backup_proxy.py), wiring `R2ObjectStore`, `CloudKmsEnvelopeProvider`, `InventoryPeerResolver`, and `BackupProxyServer` with graceful `SIGTERM`/`SIGINT` shutdown.
   - Added `backup_proxy_runtime`, `backup_proxy_secret`, and `backup_proxy_config` to `ServiceLayout` in [service_config.py](../../../../application/apps/server/app/modules/host_agent/infrastructure/service_config.py).
   - Added hardened `service_unit("backup_proxy")` in [host_services.py](../../../../application/apps/server/app/modules/host_agent/infrastructure/host_services.py) (`User=epm-backup-proxy`, `LoadCredential=r2.json:...`, `ReadOnlyPaths` for inventory dir, `InaccessiblePaths` hiding `/run/docker.sock`, `layout.data`, `layout.stops`, and tunnel secrets; zero dependency on `epm-ingress-projection.service` or Admin).
   - Wired `r2_credential()` (Secret Manager `epm-h05-r2-credentials`), `epm-backup-proxy` system user, tmpfiles dir, and `epm-backup-proxy.service` installation into [install_services.py](../../../../application/deploy/hosted-mvp/gcp/install_services.py).

3. **Production `HostAgent` Wiring in Standalone `supervisor.py`:**
   - Added `build_supervision_agent()` and `--config` / `--profile` CLI flags in [supervisor.py](../../../../application/apps/server/app/modules/host_agent/infrastructure/supervisor.py), composing `ServiceRuntime.inventory()`, `Gateway`, `PrivateStorage`, `RuntimeAuthority`, `NativeEffects`, and `HostAgent` for live supervision (preserving fail-closed stop-only mode when `--config` is omitted).
   - Replaced bare `print("Runtime needs attention.")` with structured JSON containment alerts (`_emit_containment_alert()`) and updated `epm-host-guardian.service` in [install_services.py](../../../../application/deploy/hosted-mvp/gcp/install_services.py) to pass `--config {layout.config}`.

---

## 2. Validation Results

- **Focused tests:** [test_h06_runtime_wiring.py](../../../../application/apps/server/app/modules/hosted_access/tests/test_h06_runtime_wiring.py), `test_admin_entry.py`, `test_host_services.py`, `test_supervisor.py`, and `test_backup_engine_and_proxy.py` — **46/46 passed** (`44` sandboxed + `2` localhost TLS / `AF_UNIX` proxy tests).
- **Lint & formatting:** `ruff check` and `ruff format --check` (`application/pyproject.toml`) on all 9 changed Python files — **All checks passed / 9 files already formatted**.
