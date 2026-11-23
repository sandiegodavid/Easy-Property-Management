# HOSTED-001 Slice H06.1 Checkpoint — H05 Re-Review Closure, Provider Config Re-Pin, Cloud KMS & Native GCP H05.9 Sizing

**Date:** 2026-11-23  
**Slice:** H06.1  
**Owning Design:** [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md)  
**Owning Delivery Plan:** [delivery-plan.md](../../design/mvp/delivery-plan.md#implementation-slices)  
**Operations Runbook:** [H06_1_GCP_RECOVERY_PROVISIONING_RUNBOOK.md](../../runbooks/H06_1_GCP_RECOVERY_PROVISIONING_RUNBOOK.md)  
**Branch:** `hosted_mvp`

---

## 1. Completed Deliverables

1. **H05 Follow-Up Code Re-Review Closed (41/41 Resolved):**
   - Verified all 41 findings from commit `745be9a0` against fix commit `9b3404bf` and updated [HOSTED_MVP_H05_745be9a0_REVIEW_COMMENTS.txt](../../../pending_code_review_comments/HOSTED_MVP_H05_745be9a0_REVIEW_COMMENTS.txt) (0 open, 0 regressed, 41 resolved, review date `2026-11-23`).

2. **Protected Host Provider Config Re-Pinned (`90/100` Email-Link Quota):**
   - Updated `/etc/epm/h0312/provider.json` on `epm-h02-host` to `provider_email_sends_per_day: 100` (matching Google's confirmed 100 emails/day Firebase sign-in link quota) and synced `/etc/epm/h0312/setup.json`.
   - Re-pinned `provider_config_sha256` to `5d93ef82356ea1670aacec0e7f51f35b43912e2cee57ba2f10271f962220debe` in [selection.json](../../../../application/deploy/hosted-mvp/identity/selection.json).
   - Updated [test_identity_contracts.py](../../../../application/apps/server/app/modules/hosted_access/tests/test_identity_contracts.py) for `(90, 100)` bounds (`70/70` passed across `test_identity_contracts.py` and `test_provider_boundaries.py`).

3. **GCP Cloud KMS & Protected Admin Bootstrap Authority Provisioned (`epm-h02-host`):**
   - Enabled `cloudkms.googleapis.com` in `project-47b72bb7-ba90-42c9-910`.
   - Created keyring `epm-h05-recovery` (`us-west1`) with `operator-workspace-kek` and `admin-control-kek` (`software`, `90d` rotation, `--next-rotation-time=2027-02-21T00:00:00Z`; updated `cloud_plan.kms_plan()` in [cloud_plan.py](../../../../application/deploy/hosted-mvp/gcp/cloud_plan.py) to emit `--next-rotation-time`).
   - Bound `roles/cloudkms.cryptoKeyEncrypterDecrypter` to `serviceAccount:epm-h02-host@project-47b72bb7-ba90-42c9-910.iam.gserviceaccount.com` on both keys.
   - Verified live `CloudKmsEnvelopeProvider` `wrap_dek`/`unwrap_dek` with AAD on both keys directly from `epm-h02-host`.
   - Provisioned `/etc/epm/admin-recovery-authority.json` and `/run/epm/admin-recovery-authority.json` (`0600`) for deployment `b77f7c7e-c89c-4d44-b337-e8d4f13ee46f`.

4. **Native GCP H05.9 Backup/Restore Reserve Sizing Qualified:**
   - Added native Linux/Docker/GCP `run_gcp_qualification()` (`--gcp`) to [qualify_h05_sizing.py](../../../../application/deploy/hosted-mvp/gcp/qualify_h05_sizing.py) and tightened peak-sampling throttling + sub-1 MiB byte-quota draining in [h05_sizing_actor.py](../../../../application/deploy/hosted-mvp/gcp/h05_sizing_actor.py).
   - Executed on `epm-h02-host` (`Linux 7.0.0-1017-gcp`, `x86_64`, `/srv/epm/data` ext4 `rw,nosuid,nodev,noexec,relatime,prjquota`, UUID `8d2fd2e0-274b-4535-90d5-da78aa6bd9b6`) across all 3 × 50 MB workload shapes (`database_heavy`, `retained_file_heavy`, `many_small_files_history`, 7 captures + concurrent restore each) and all 4 real Linux `EDQUOT` (errno `122`) exhaustion proofs.
   - Saved validated report [HOSTED_MVP_H05_9_RECOVERY_SIZING.json](HOSTED_MVP_H05_9_RECOVERY_SIZING.json) (`restore_readiness: "qualified"`, `admission_enabled: true`, `measurement_sha256: 95202a150d7c5ffec3ec7daabd4f45fc1b1ca134ed2f26300a99397be28d1637`):
     - `workspace`: peak `93,810,688` B / `3,037` inodes → ceiling `193,986,560` B (`185 MiB`, `+23 MiB` over H04.9) / `6,400` inodes (`+1,024`)
     - `scratch`: peak `46,907,392` B / `1,520` inodes → ceiling `114,294,784` B (`109 MiB`, `+76 MiB` over H04.9) / `3,328` inodes (`+2,560`)
     - `control`: peak `368,640` B / `5` inodes → ceiling `17,825,792` B (`17 MiB`) / `768` inodes

5. **Cloudflare R2 Credentials Provisioned in GCP Secret Manager:**
   - Scoped Cloudflare R2 bucket credentials (`epm-hosted-recovery`) stored in GCP Secret Manager (`epm-h05-r2-credentials`, active version verified, placeholder version 1 destroyed) with `roles/secretmanager.secretAccessor` granted to `epm-h02-host@project-47b72bb7-ba90-42c9-910.iam.gserviceaccount.com`.

6. **VM Cost Hygiene:**
   - Cleaned temporary qualification files on `epm-h02-host` and stopped `epm-h02-host` to avoid idle GCP VM charges.

---

## 2. Sequenced Live GCP Follow-Up (Post-H06.6)

Per explicit decision on 2026-11-23, the two remaining live GCP proofs that depend on production container images (`shared_identity_entry`, `operator_entry`, `epm-backup-proxy.service`) are sequenced to execute immediately after **H06.6** (Production Container Images & `image_schema.json` promotion):
- Start `epm-backup-proxy.service` backed by `epm-h05-r2-credentials` in GCP Secret Manager.
- Execute live GCP 17-case `recovery.json` (real Cloud KMS + real Cloudflare R2) and deployed 4-browser-context positive `identity_handoff.json`.

---

## 3. Validation Summary

- `ruff check` & `ruff format --check` (`application/pyproject.toml`) on all 4 modified Python files: **Passed** (0 warnings, 4 files formatted).
- `pytest apps/server/app/modules/hosted_access/tests/test_identity_contracts.py apps/server/app/modules/hosted_access/tests/test_provider_boundaries.py`: **70 passed**.
- `pytest scripts/tests/test_h05_sizing_qualification.py scripts/tests/test_h05_recovery_qualification.py`: **10 passed**.
- Native GCP `qualify_h05_sizing.py --gcp` on `epm-h02-host`: **Passed** (`exit 0`, validated `HOSTED_MVP_H05_9_RECOVERY_SIZING.json`).
