# HOSTED-001 Slice H06.6 Checkpoint — Production Container Images, Healthchecks, 9-Case `image_schema.json` Promotion & Live GCP R2+KMS Recovery Proof

**Date:** 2026-11-23  
**Slice:** `H06.6` (of [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md))  
**Status:** Complete (ready for `H06.7`)  
**Operations Runbook:** [H06_6_IMAGE_AND_LIVE_R2_KMS_RUNBOOK.md](../../runbooks/H06_6_IMAGE_AND_LIVE_R2_KMS_RUNBOOK.md)

---

## 1. Deliverables Completed

### Production Container Images & Loopback Health Probes (D8)
- Created [health_probes.py](../../../application/apps/server/app/modules/hosted_access/infrastructure/health_probes.py):
  - `internal_health_server(...)` bound strictly to loopback (`127.0.0.1`), serving `GET /health/live` (200) and `GET /health/ready` (200 when ready, 503 when not ready). Never exposed on public Caddy routes.
- Updated [Dockerfile.admin](../../../application/deploy/hosted-mvp/Dockerfile.admin) and [Dockerfile.operator](../../../application/deploy/hosted-mvp/Dockerfile.operator):
  - Removed H02 `epm.acceptance="infrastructure_candidate"` labels and `--health-only` stubs.
  - Promoted to production labels (`epm.release_track="pilot0" epm.runtime="production"`), production entrypoints (`app.modules.hosted_access.infrastructure.shared_identity_entry` and `app.modules.hosted_access.infrastructure.operator_entry`, `CMD []`), and loopback `HEALTHCHECK` against `http://127.0.0.1:8081/health/live`.
- Wired `--health-port` (default `8081`) and `internal_health_server` lifecycle into [shared_identity_entry.py](../../../application/apps/server/app/modules/hosted_access/infrastructure/shared_identity_entry.py) and [operator_entry.py](../../../application/apps/server/app/modules/hosted_access/infrastructure/operator_entry.py).
- Fixed keyword-only `BackupProxyHandler` instantiation in [backup_proxy.py](../../../application/apps/server/app/modules/host_agent/infrastructure/backup_proxy.py) `main()`.

### 9-Case `image_schema.json` Qualification
- Created [qualify_h06_image_schema.py](../../../application/deploy/hosted-mvp/gcp/qualify_h06_image_schema.py) and [test_h06_image_schema_qualification.py](../../../application/scripts/tests/test_h06_image_schema_qualification.py).
- Executed all 9 required `image_schema.json` cases across all 6 hosted/business SQLite stores and generated [HOSTED_MVP_H06_6_IMAGE_ALL_STORES.json](HOSTED_MVP_H06_6_IMAGE_ALL_STORES.json) (`status: "passed"`).

### Live GCP R2 + Cloud KMS + `epm-backup-proxy` End-to-End Recovery Proof
- Created [qualify_h06_live_r2_kms.py](../../../application/deploy/hosted-mvp/gcp/qualify_h06_live_r2_kms.py).
- Executed live on `epm-h02-host` (Linux `7.0.0-1017-gcp`, Python 3.14 via `/opt/epm/python/bin/python3`) using GCP Secret Manager secret `epm-h05-r2-credentials` (Cloudflare R2 bucket `epm-hosted-recovery`) and GCP Cloud KMS (`epm-h05-recovery` keyring in `us-west1` with `admin-control-kek` and `operator-workspace-kek`), over real `SO_PEERCRED` Unix sockets (`BackupProxyServer` + `UnixBackupProxyClient` + `ChunkedAeadBackupEngine`):
  - **Admin control recovery**: `create_point` + full readback (`1423 ms`), byte-identical `restore_point` + `PRAGMA integrity_check == ok` (`360 ms`), cross-key KMS wrap (`operator-workspace-kek`) denied (`BackupProxyDenied`), server-side path traversal (`../escape.bin`) denied (`BackupProxyDenied`), live R2 chunk tamper rejected (`RecoveryIntegrityError`/`RecoveryCryptoError`).
  - **Operator workspace recovery**: `InventoryPeerResolver` UID resolution from `host_inventory.sqlite`, `create_point` (SQLite DB + retained attachment) + full readback (`2671 ms`), byte-identical `restore_point` (`907 ms`), cross-key KMS wrap (`admin-control-kek`) denied (`BackupProxyDenied`).
  - **Disposable R2 cleanup**: All `5` disposable R2 objects deleted under `deployments/7606b3e4-995c-41c9-b791-1fa1faa5e961/`, `remaining_objects: 0`.
- Recorded sanitized report at [HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json](HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json).
- Stopped `epm-h02-host` immediately after proof completion.

### Note on Interactive 4-Browser Positive `identity_handoff.json`
- Component-level identity handoff, step-up, and session isolation contracts remain verified; the interactive 4-browser-context live Google/TOTP positive sign-in rehearsal requires human interactive OAuth/TOTP completion and is sequenced with the live Pilot 0 deployment/operations rehearsal in `H06.9` / `H06.10`.

---

## 2. Validation Results

| Check | Result |
| --- | --- |
| `pytest scripts/tests/test_h06_image_schema_qualification.py scripts/tests/test_hosted_packaging.py` | **14 passed** |
| `qualify_h06_image_schema.py` → `HOSTED_MVP_H06_6_IMAGE_ALL_STORES.json` | **9/9 cases passed** |
| Live GCP `qualify_h06_live_r2_kms.py` on `epm-h02-host` → `HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json` | **passed** (`admin_control_recovery`, `operator_workspace_recovery`, `disposable_r2_cleanup`) |
| `ruff check --config pyproject.toml` on all H06.6 Python files | **All checks passed** |
| `ruff format --check --config pyproject.toml` on all H06.6 Python files | **All files already formatted** |
| `epm-h02-host` VM state | **STOPPED** |

---

## 3. Next Slice

Proceed to **H06.7 — GCP Observability, Alert Policies & Billing Budget** (`cloud_plan.py`, `startup.sh`, Ops Agent config, log-based backup/containment alerts, host headroom alerts, VM heartbeat uptime check, and `$250/month` before-credit budget alerts).
