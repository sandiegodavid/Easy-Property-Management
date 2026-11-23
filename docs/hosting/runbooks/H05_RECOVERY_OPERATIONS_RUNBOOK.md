# H05 Off-Host Recovery Operations & Live GCP Qualification Runbook

**Applies to:** HOSTED-001 Slice H05 (Nightly Verified Off-Host Recovery, Clean-Runtime Repair, Admin Control Recovery & Positive Workspace Ingress)  
**Owning Design:** [HOSTED_MVP_H05_DESIGN.md](../design/HOSTED_MVP_H05_DESIGN.md)  
**Exit Review:** [HOSTED_MVP_H05_11_EXIT_REVIEW.md](../qualification/reports/HOSTED_MVP_H05_11_EXIT_REVIEW.md)

---

## 1. Prerequisites & Environment Variables

Before executing live GCP qualification or enabling production off-host recovery on `epm-h02-host`:

- **GCP Project & VM:** `epm-h02-host` (`e2-standard-2`, Ubuntu 24.04, ext4 `prjquota,nodev,nosuid,noexec` data disk `/var/lib/epm`).
- **Cloudflare R2 Bucket:** Private bucket (e.g., `epm-hosted-recovery`) with versioning disabled on mutable paths and S3-compatible scoped API token stored in GCP Secret Manager (never placed inside Operator containers).
- **GCP Cloud KMS:** Keyring `epm-h05-recovery` with two separate asymmetric/symmetric KEKs:
  - `operator-workspace-kek` (wrapping per-workspace DEKs via `epm-backup-proxy`)
  - `admin-control-kek` (wrapping Admin control-plane DEKs via `epm-backup-proxy`)
- **Protected Bootstrap Authority File (D5):** `/run/epm/admin-recovery-authority.json` (`0600`, owned by the Admin service user) containing the approved Admin Firebase UID, email, issuer, and TOTP MFA enforcement flag — independent of `admin.sqlite`.

---

## 2. Step-by-Step GCP Provisioning (Cloud KMS + R2 + `epm-backup-proxy`)

### 2.1 Start `epm-h02-host` (when stopped)
```bash
gcloud compute instances start epm-h02-host \
  --project=<GCP_PROJECT> \
  --zone=<GCP_ZONE>
```

### 2.2 Generate & Execute Reviewed Cloud KMS Provisioning Commands
Use `application/deploy/hosted-mvp/gcp/cloud_plan.py` (`kms_plan`) to emit the exact reviewed `gcloud` commands (never hand-craft unreviewed IAM bindings):

```bash
cd application
PYTHONPATH=apps/server .venv/bin/python -c '
from pathlib import Path; import json, runpy
mod = runpy.run_path("deploy/hosted-mvp/gcp/cloud_plan.py")
target = mod["Target"].model_validate_json(Path("/private/gcp-target.json").read_text())
for cmd in mod["kms_plan"](target):
    print("gcloud " + " ".join(cmd))
'
```

Execute each printed `gcloud` command to:
1. Enable `cloudkms.googleapis.com`.
2. Create keyring `epm-h05-recovery` in `<GCP_REGION>`.
3. Create `operator-workspace-kek` and `admin-control-kek` (90-day rotation).
4. Grant `roles/cloudkms.cryptoKeyEncrypterDecrypter` solely to the host service account (`epm-h02-host@<GCP_PROJECT>.iam.gserviceaccount.com`).

### 2.3 Store Cloudflare R2 Credentials & Start `epm-backup-proxy`
1. Create a Cloudflare R2 API token scoped **only** to the dedicated recovery bucket (`Object Read & Write`).
2. Store R2 endpoint URL, bucket name, access key ID, and secret access key in GCP Secret Manager and mount them **only** to the host-side `epm-backup-proxy` systemd unit (mode `0600`, root/proxy-owned; never mounted into Operator or Admin containers).
3. Verify `epm-backup-proxy` listens on its private `AF_UNIX` socket (`/run/epm/backup-proxy.sock`) and resolves caller prefixes strictly via kernel `SO_PEERCRED` UID → `host_inventory.sqlite` (`deployments/<deployment_id>/operators/<operator_id>/` or `deployments/<deployment_id>/control/`).

### 2.4 Provision Protected Admin Bootstrap Authority File (D5)
Write `/run/epm/admin-recovery-authority.json` (`0600`) with:
```json
{
  "version": 1,
  "deployment_id": "<DEPLOYMENT_UUID>",
  "principals": [
    {
      "issuer": "firebase:<FIREBASE_PROJECT_ID>",
      "subject": "<ADMIN_FIREBASE_UID>",
      "principal_ref": "admin:<ADMIN_EMAIL>",
      "mfa_required": true
    }
  ]
}
```
Verify Admin recovery mode can authenticate against this file even if `admin.sqlite` is renamed or removed.

---

## 3. Running Live H05.9 Native Linux Backup/Restore Reserve Sizing

Run **only** on native Linux (`epm-h02-host`) with ext4 `prjquota,nodev,nosuid,noexec` (never fabricate on macOS):

1. Build the offline H05 sizing actor image on `epm-h02-host` using `qualify_h05_sizing.build_h05_actor_image()`.
2. Execute `h05_sizing_actor.py workload` for all three workload shapes (`database_heavy`, `retained_file_heavy`, `many_small_files_history`) at `--target-bytes 50000000 --captures 7` inside quota-enforced `workspace`, `control`, and `scratch` directories.
3. Execute `h05_sizing_actor.py exhaustion` for all four independent quota-exhaustion proofs:
   - `backup_byte_exhaustion` (tight `scratch` byte quota → Linux `EDQUOT`/`ENOSPC`)
   - `backup_inode_exhaustion` (tight `scratch` inode quota → Linux `ENOSPC`/`EDQUOT`)
   - `restore_byte_exhaustion` (tight `workspace` byte quota → Linux `EDQUOT`/`ENOSPC`)
   - `restore_inode_exhaustion` (tight `workspace` inode quota → Linux `ENOSPC`/`EDQUOT`)
4. Assemble the raw native Linux evidence JSON and derive/validate the closed H05.9 sizing report:
```bash
cd application
PYTHONPATH=apps/server .venv/bin/python deploy/hosted-mvp/gcp/qualify_h05_sizing.py \
  /private/h059-raw-linux-evidence.json \
  ../docs/hosting/qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json \
  ../docs/hosting/qualification/reports/HOSTED_MVP_H05_9_RECOVERY_SIZING.json
```
5. Confirm `HOSTED_MVP_H05_9_RECOVERY_SIZING.json` replaces `"h05_backup_restore_reserve": "deferred_to_H05"` with pinned per-tree ceilings and `"restore_readiness": "qualified"`.

---

## 4. Running H05.11 Qualification (Component & Live GCP / Browser)

### 4.1 Component-Level 17-Case `recovery.json` + Joint H04/H05 Positive Handoff
```bash
cd application
PYTHONPATH=apps/server .venv/bin/python deploy/hosted-mvp/gcp/qualify_h05_recovery.py \
  ../docs/hosting/qualification/reports/HOSTED_MVP_H05_11_COMPONENT_RECOVERY.json
```

### 4.2 Frontend Lint, Typecheck & Playwright Recovery UI Gate
```bash
cd application
npm run lint && npm run format:check && npm run typecheck
npx playwright test --config playwright.components.config.ts \
  hosted-recovery.spec.ts hosted-settings.spec.ts admin-lite.spec.ts
```

### 4.3 Live Deployed GCP & 4-Browser-Context Joint H04/H05 Handoff
On `epm-h02-host` with Cloud KMS + R2 + `epm-backup-proxy` + Caddy (`SharedIdentityManifest` v3 + `WorkspaceRouteManifest`):
1. Provision two disposable Free pilot operators (`pilot-alpha` empty, `pilot-beta` `synthetic-demo-v1`).
2. Verify both operators stay held (`desired_state="held"`) until their first verified nightly capture succeeds in R2.
3. Capture verified backups for both operators; verify `_live_business_readiness` turns `True` and `HostAgent` admits `desired_state="eligible"` via `WorkspaceRouteManifest` (denying WebSocket `Upgrade` and `/admin`, `/__/auth`, `/internal`, `/debug`, `/metrics` with `403`).
4. Run 4 isolated browser contexts covering eligible claim, cross-device pairing, one-use/lost-response handoff, cookie/CSRF/workspace isolation, renewal, disable/rebind/logout, and exact-purpose recovery step-up.
5. Rehearse:
   - Corrupt business DB → Operator Minimal Recovery Mode → Preview → Step-up → Confirm → Fresh Sign-In → AcceptRestore.
   - Admin **Repair runtime** (`POST /api/admin/operators/{id}/repair-runtime`) → fresh container without empty DB init.
   - Corrupt `admin.sqlite` → Admin Control Recovery Mode (`/api/admin/recovery/*`) using `/run/epm/admin-recovery-authority.json`.
   - Whole-host control loss reconstruction on a clean disposable host.
6. Remove all disposable operator assignments, containers, directories, and `prjquota` projects.

---

## 5. Day-2 Operational Procedures

### 5.1 Operator Workspace Restore (Normal or Minimal Recovery Mode)
- **Normal Mode:** Operator opens **Settings → Data and backup**, selects a verified point (latest selected by default), clicks **Preview restore**, completes fresh Google/email-link strong step-up, confirms rollback, signs in fresh after session revocation, inspects data, and clicks **Accept restored workspace**.
- **Corrupt Business DB (Minimal Recovery Mode):** Operator container automatically boots into Minimal Recovery Mode (`503 recovery_mode_active` on business routes; never initializes an empty DB). Operator signs in and completes the same Preview → Step-Up → Confirm → Fresh Sign-In → Accept flow.
- **Lost Browser Response:** Use **Check restore status** (`GET /api/hosted/recovery/operations/{operationId}`) to inspect the original restore phase before retrying.

### 5.2 Admin Clean-Runtime Repair (`repair_runtime`)
1. Open Admin-lite → select Operator → **Runtime repair** card.
2. Check the explicit confirmation box and click **Repair runtime** (`POST /api/admin/operators/{operatorId}/repair-runtime`).
3. Use **Check operation status** (`GET /api/admin/operations/{operationId}`) to verify completion.
4. **Boundary:** Admin cannot approve, trigger, or decrypt customer workspace restores. If the workspace DB is damaged, the repaired container boots into Minimal Recovery Mode (`EPM_RECOVERY_MODE_REQUIRED=1`) for the Operator to restore.

### 5.3 Admin Control-Plane Recovery (Damaged `admin.sqlite`)
1. Admin boots into Admin Recovery Mode automatically when `admin.sqlite` is unreadable, authenticating via Google + TOTP MFA against `/run/epm/admin-recovery-authority.json`.
2. Open **Control recovery** in Admin-lite, click **Reconstruct catalog** if `admin-recovery.sqlite` was also rebuilt, select a verified control point, click **Preview control restore**, confirm bootstrap MFA step-up, click **Confirm control restore**, verify restored registry, and click **Accept control restore**.

### 5.4 Whole-Host Control Loss Reconstruction CLI
On a clean replacement host with `epm-backup-proxy` connected to R2 + Cloud KMS and `/run/epm/admin-recovery-authority.json` mounted:
```bash
cd application
PYTHONPATH=apps/server .venv/bin/python -m app.modules.hosted_admin.infrastructure.admin_recovery \
  --admin-recovery-db /var/lib/epm/admin-recovery/admin-recovery.sqlite \
  --bootstrap-authority /run/epm/admin-recovery-authority.json \
  --control-root /var/lib/epm/admin \
  --scratch-root /var/lib/epm/admin-scratch \
  --backup-proxy-socket /run/epm/backup-proxy.sock \
  --backup-proxy-uid <PROXY_UID> \
  --kms-key-ref <ADMIN_CONTROL_KMS_KEY_REF>
```
This reconstructs the control catalog from immutable R2 manifests, restores `admin.sqlite` + `host_inventory.sqlite` into a fresh `incarnation_id` (leaving prior in-flight operations inert and revoking prior sessions), and requires explicit reconciliation of host bindings before reopening ingress.

---

## 6. Post-Qualification Shutdown (Cost Hygiene)
After completing live GCP qualification runs, stop `epm-h02-host` until Pilot 0 launch:
```bash
gcloud compute instances stop epm-h02-host \
  --project=<GCP_PROJECT> \
  --zone=<GCP_ZONE>
```
