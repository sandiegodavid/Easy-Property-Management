# Pilot 0 Incident Response, Support Triage, Break-Glass & Retirement Runbook (H06.8)

**Owner:** Named Pilot 0 Operational Owner (D4)  
**Scope:** Backup/containment/host-loss incident triage, runtime repair, audited support break-glass, and deliberate workspace retirement with 7-day hold.  
**Design Authority:** [HOSTED_MVP_H06_DESIGN.md](../design/HOSTED_MVP_H06_DESIGN.md) (D3, D4, D10) · [H05_RECOVERY_OPERATIONS_RUNBOOK.md](H05_RECOVERY_OPERATIONS_RUNBOOK.md)

---

## 1. Alert Triage Matrix

| Alert Source | Signal | First-Response Action |
| --- | --- | --- |
| **Backup Overdue / Failure** (`epm_hosted_recovery_alerts` / webhook) | `backup_overdue`, `backup_failed`, `backup_unknown` | Inspect Cloud Logging for `hosted_recovery_alert` (operator ID, error code, consecutive failures). Check `epm-backup-proxy.service`, R2 reachability, and Cloud KMS IAM. **Do not clear alert** until a new verified recovery point succeeds and `backup_recovered` emits. |
| **Host Guardian Containment** (`epm_host_guardian_containment`) | `runtime_containment_attention` | Inspect `journalctl -u epm-host-guardian.service` for the contained container and reason. Verify no cross-operator boundary breach; repair runtime before re-enabling ingress. |
| **Host Disk / RAM / CPU Headroom** | Disk > 80%, RAM > 85%, CPU > 85% (10m) | Pause new Pilot 0 admissions immediately. Inspect per-tree `repquota -P /srv/epm/data`, Docker logs, and container RSS. Clear only after headroom returns below thresholds. |
| **External Host-Loss Heartbeat** (`epm-pilot0-host-heartbeat`) | Uptime check failed > 5m | Check GCP VM status (`epm-h02-host`) and `epm-tunnel.service` / `epm-gateway.service`. If host is lost, execute whole-host recovery from [H05_RECOVERY_OPERATIONS_RUNBOOK.md](H05_RECOVERY_OPERATIONS_RUNBOOK.md) (4h RTO engineering objective). |

Record every incident, root cause, resolution, and Admin/support minutes in [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md).

---

## 2. Failed Runtime Repair (`runtime_repair_support`)

When an operator container fails healthchecks or reports a corrupt business database:
1. Keep ingress **held/closed** (or recovery-mode only).
2. Run the supported `repair_runtime` host-agent action:
   - Preserves original `operator_id`, `workspace_id`, UID/GID, and private SQLite/files volumes.
   - **Never** silently reinitializes an empty business database over a damaged store.
3. If data restore is required:
   - Guide the operator to sign in via **authenticated recovery mode** with strong step-up authentication.
   - The operator selects and authorizes the verified recovery point; the internal engine stages, validates, fences the old writer, and switches atomically.
   - **Hard Rule (H05 D1 / D10):** There is **no** Admin offline decrypt or customer restore bypass command.

---

## 3. Audited Support Break-Glass Policy (D10)

1. **Metadata-Only Default:** Operational support views only non-content operational metadata (status, backup freshness, error codes, quota usage, redacted logs).
2. **Consented Troubleshooting:** Any temporary access beyond operational metadata requires:
   - Explicit written consent from the operator (retained in support ticket).
   - Recorded reason, actor identity, and strict expiry timestamp in `admin_audit`.
   - Zero offline decrypt or backup-key export.
3. **Post-Incident Audit:** Verify all temporary access is revoked upon expiry and log elapsed support time.

---

## 4. Deliberate Workspace Retirement (7-Day Recovery Window — D10)

Never hard-delete an active or newly retired operator workspace immediately:
1. **Disable & Fence (`Day 0`):**
   - Disable the operator in Admin-lite (revokes active sessions and fences business ingress).
   - Capture one final verified recovery point via `epm-backup-proxy` and confirm `manifest_sha256` is recorded.
2. **7-Day Hold Window (`Days 0–7`):**
   - Retain the disabled workspace data and encrypted R2 recovery points for **7 full days**.
   - During this window, retirement remains reversible via operator-authenticated re-enable / restore.
3. **Final Retirement & Verified Cleanup (`Day 7+`):**
   - After 7 days with no operator reversal request, run explicit `retire_resources` through host-agent.
   - Verify container removal, ext4 project-quota tree cleanup (`cleanup_verified_at` recorded in `host_inventory.sqlite`), R2 prefix cleanup, and Google OAuth Testing allowlist removal.
   - Record completion in `admin_audit` and the Pilot 0 worksheet.
