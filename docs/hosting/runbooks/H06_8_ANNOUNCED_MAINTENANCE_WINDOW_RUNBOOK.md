# Pilot 0 Announced Shared Maintenance Window & Cohort Release Runbook (H06.8)

**Owner:** Named Pilot 0 Operational Owner (D4)  
**Scope:** Single shared cohort maintenance window for `epm-h02-host` runtime/image updates (no per-operator scheduling or canary automation — deferred to H10).  
**Design Authority:** [HOSTED_MVP_H06_DESIGN.md](../design/HOSTED_MVP_H06_DESIGN.md) (D5, D8) · [releases.md](../design/mvp/releases.md)

---

## 1. Release Prerequisites

Before announcing a maintenance window:
1. Build immutable Admin OCI image, Operator OCI image, and Host Agent archive from pinned source.
2. Pass all 9 `image_schema.json` cases ([H06_6_IMAGE_AND_LIVE_R2_KMS_RUNBOOK.md](H06_6_IMAGE_AND_LIVE_R2_KMS_RUNBOOK.md)) and record the pinned image digests.
3. Verify schema compatibility for all 6 SQLite store families (greenfield forward-only; no destructive downgrade).

---

## 2. Phase 1 — Announce Window (≥ 24 Hours Before Start)

1. **Publish `/run/epm/maintenance-notice.json` (`state: "announced"`):**
   Write atomically (`0644`, root-owned; mounted read-only into all Operator containers):
   ```json
   {
     "active": true,
     "state": "announced",
     "window_start_utc": "2026-12-01T06:00:00Z",
     "window_end_utc": "2026-12-01T06:30:00Z",
     "message": "Scheduled platform maintenance for all Pilot 0 workspaces."
   }
   ```
2. **Send Cohort Notice Email (D2):**
   - Email all active Pilot 0 operators from `EPM_SUPPORT_CONTACT` with the exact UTC/local start and end window.
3. **Verify Banner:**
   - Confirm Operator UI displays the unobtrusive `HostedMaintenanceBanner` in the shell header and Settings without blocking normal work.

---

## 3. Phase 2 — Enter Maintenance, Drain & Capture Pre-Update Points

1. **Switch Notice to `in_progress`:**
   - Update `/run/epm/maintenance-notice.json` atomically with `"state": "in_progress"`.
   - Operator UI displays **`Updating your workspace`** while **preserving unfinished local form drafts** across devices.
2. **Drain Admitted Work & Capture Verified Pre-Update Backups:**
   - Allow in-flight HTTP writes to complete cleanly.
   - Trigger and verify a fresh pre-update recovery point for the Admin control store (`admin.sqlite`) and every active Operator workspace (`business.sqlite` + retained files).
   - Confirm every pre-update `manifest_sha256` is verified in R2 before stopping any container.

---

## 4. Phase 3 — Apply Pinned Release & Verify Readiness

1. Replace/restart Admin and Operator containers using the exact pinned digests (`--no-floating-tags`).
2. Verify loopback health probes (`GET http://127.0.0.1:8081/health/live` and `/health/ready` → `200`) on Admin and every active Operator container.
3. Verify `epm-gateway.service`, `epm-tunnel.service`, `epm-backup-proxy.service`, `epm-host-guardian.service`, and `google-cloud-ops-agent.service` are `active (running)`.
4. **Rollback Rule:**
   - **Before reopening ingress:** If a container fails readiness/schema validation, roll back to the previous pinned image digest while retaining the pre-update verified recovery point.
   - **After reopening ingress:** **Never** perform destructive data rollback; preserve all post-reopen operator writes.

---

## 5. Phase 4 — Clear Notice & Record Metrics

1. Update `/run/epm/maintenance-notice.json` to `{"active": false, "state": "announced", "window_start_utc": null, "window_end_utc": null, "message": ""}` (or remove the file cleanly).
2. Verify Operator UI clears the maintenance state, unfinished drafts remain intact, and a post-update read/write smoke check passes.
3. Record actual outage duration (seconds), pinned release digests, and total Admin minutes in [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md).
