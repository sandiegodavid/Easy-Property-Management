# Slice H06.6 Operations Runbook — Production Image Qualification & Live GCP R2 + Cloud KMS Recovery Proof

**Slice:** `H06.6` ([HOSTED_MVP_H06_DESIGN.md](../design/HOSTED_MVP_H06_DESIGN.md))  
**Checkpoint:** [HOSTED_MVP_H06_6_CHECKPOINT_2026-11-23.md](../qualification/reports/HOSTED_MVP_H06_6_CHECKPOINT_2026-11-23.md)  
**Target Host:** `epm-h02-host` (GCP project `project-47b72bb7-ba90-42c9-910`, zone `us-west1-b`)

This runbook records the exact operator steps to verify the production container image contracts, generate the 9-case `image_schema.json` qualification report, and execute the live Cloudflare R2 + GCP Cloud KMS + `epm-backup-proxy` end-to-end recovery proof on `epm-h02-host`.

---

## 1. Local Image, Health Probe & 9-Case `image_schema.json` Verification

Run from the repository root:

```bash
# 1. Verify production Dockerfile labels, loopback /health/live & /health/ready probes, and packaging contracts
cd application
PYTHONPATH=apps/server .venv/bin/pytest \
  scripts/tests/test_h06_image_schema_qualification.py \
  scripts/tests/test_hosted_packaging.py

# 2. Generate and validate the 9-case image_schema.json report across all 6 stores
PYTHONPATH=apps/server .venv/bin/python \
  deploy/hosted-mvp/gcp/qualify_h06_image_schema.py \
  ../docs/hosting/qualification/reports/HOSTED_MVP_H06_6_IMAGE_ALL_STORES.json

# 3. Verify Python lint and formatting
.venv/bin/ruff check --config pyproject.toml \
  apps/server/app/modules/hosted_access/infrastructure/health_probes.py \
  apps/server/app/modules/hosted_access/infrastructure/shared_identity_entry.py \
  apps/server/app/modules/hosted_access/infrastructure/operator_entry.py \
  apps/server/app/modules/host_agent/infrastructure/backup_proxy.py \
  deploy/hosted-mvp/gcp/qualify_h06_image_schema.py \
  deploy/hosted-mvp/gcp/qualify_h06_live_r2_kms.py \
  scripts/tests/test_h06_image_schema_qualification.py

.venv/bin/ruff format --check --config pyproject.toml \
  apps/server/app/modules/hosted_access/infrastructure/health_probes.py \
  apps/server/app/modules/hosted_access/infrastructure/shared_identity_entry.py \
  apps/server/app/modules/hosted_access/infrastructure/operator_entry.py \
  apps/server/app/modules/host_agent/infrastructure/backup_proxy.py \
  deploy/hosted-mvp/gcp/qualify_h06_image_schema.py \
  deploy/hosted-mvp/gcp/qualify_h06_live_r2_kms.py \
  scripts/tests/test_h06_image_schema_qualification.py
```

---

## 2. Prerequisites for Live GCP R2 + Cloud KMS Proof

Before starting `epm-h02-host`, confirm:
1. **Cloudflare R2 bucket:** `epm-hosted-recovery` exists in account `af47b25f59f829ac1fea7ceee6b2a6e3` (endpoint `https://af47b25f59f829ac1fea7ceee6b2a6e3.r2.cloudflarestorage.com`).
2. **Cloudflare R2 Account API Token (`epm-h05-backup-proxy`):** status `Active`, permission **Object Read & Write**, **Applied to** `epm-hosted-recovery` (mismatched bucket scope returns `403 Forbidden` / `AccessDenied`).
3. **GCP Secret Manager:** `epm-h05-r2-credentials` (`latest` version) contains JSON keys `endpoint_url`, `bucket` (`"epm-hosted-recovery"`), `access_key_id`, `secret_access_key`, with `roles/secretmanager.secretAccessor` granted to `epm-h02-host@project-47b72bb7-ba90-42c9-910.iam.gserviceaccount.com`.
4. **GCP Cloud KMS:** keyring `epm-h05-recovery` in `us-west1` with keys `admin-control-kek` and `operator-workspace-kek`, IAM-bound to the `epm-h02-host` service account.

---

## 3. Execute Live GCP R2 + Cloud KMS + `epm-backup-proxy` Proof

### Step 3.1 — Build Clean Source Tarball (macOS-Safe)

Always strip macOS AppleDouble (`._*`) files and xattrs so `schema_resources.py` does not reject the unpacked tree:

```bash
COPYFILE_DISABLE=1 tar --no-xattrs --exclude='._*' --exclude='__pycache__' --exclude='*.pyc' \
  -czf /tmp/epm-h066-src.tar.gz \
  application/apps/server \
  application/database \
  application/alembic.ini \
  application/deploy/hosted-mvp/gcp/qualify_h06_live_r2_kms.py
```

### Step 3.2 — Start `epm-h02-host` and Upload Tarball

```bash
gcloud compute instances start epm-h02-host \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b

gcloud compute scp --tunnel-through-iap \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  /tmp/epm-h066-src.tar.gz \
  epm-h02-host:/tmp/epm-h066-src.tar.gz
```

### Step 3.3 — Run `qualify_h06_live_r2_kms.py` with Python 3.14

Note: Ubuntu's system `/usr/bin/python3` on `epm-h02-host` is Python 3.12, whereas the hosted codebase targets Python 3.14 (`application/pyproject.toml`). Use `/opt/epm/python/bin/python3` (Python 3.14) installed on the host.

```bash
gcloud compute ssh epm-h02-host --tunnel-through-iap \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --command='set -euo pipefail
WORK=/tmp/epm-h066
rm -rf "$WORK"
mkdir -p "$WORK"
trap "rm -rf $WORK /tmp/epm-h066-src.tar.gz" EXIT
tar -xzf /tmp/epm-h066-src.tar.gz -C "$WORK"
umask 077
gcloud secrets versions access latest \
  --secret=epm-h05-r2-credentials \
  --project=project-47b72bb7-ba90-42c9-910 > "$WORK/r2.json"
chmod 600 "$WORK/r2.json"
/opt/epm/python/bin/python3 -m venv "$WORK/venv"
PY="$WORK/venv/bin/python"
"$PY" -m pip install -q boto3 sqlalchemy alembic pydantic cryptography
PYTHONPATH="$WORK/application/apps/server" "$PY" \
  "$WORK/application/deploy/hosted-mvp/gcp/qualify_h06_live_r2_kms.py" \
  --credentials-file "$WORK/r2.json" \
  --admin-key-ref projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/admin-control-kek \
  --operator-key-ref projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/operator-workspace-kek \
  --output /tmp/h066-live-r2-kms-report.json
cat /tmp/h066-live-r2-kms-report.json
rm -f /tmp/h066-live-r2-kms-report.json'
```

Verify the JSON output reports:
- `status: "passed"`
- `cases.admin_control_recovery`: `status: "passed"`, `cross_key_denied: true`, `path_traversal_denied: true`, `tampered_chunk_rejected: true`
- `cases.operator_workspace_recovery`: `status: "passed"`, `cross_key_denied: true`
- `cases.disposable_r2_cleanup`: `status: "passed"`, `remaining_objects: 0`

Save the sanitized JSON output to `docs/hosting/qualification/reports/HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json` (never include R2 credentials or secret values).

### Step 3.4 — Stop `epm-h02-host` Immediately After Proof

```bash
gcloud compute instances stop epm-h02-host \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b
```

---

## 4. Troubleshooting Notes Observed in H06.6

- **R2 `403 Forbidden` / `AccessDenied` on all operations:** Confirm the Cloudflare R2 API token's **Applied to** bucket matches the `bucket` field in `epm-h05-r2-credentials` (`epm-hosted-recovery`) and has **Object Read & Write** permission. Editing the token's bucket scope in Cloudflare R2 preserves the existing Access Key ID and Secret Access Key.
- **`SyntaxError: multiple exception types must be parenthesized` on VM:** Indicates `/usr/bin/python3` (3.12) was invoked instead of `/opt/epm/python/bin/python3` (3.14).
- **MacOS `HostedSchemaError` in local tests:** `tempfile.TemporaryDirectory` on macOS returns `/var/folders/...`, which symlinks to `/private/var/folders/...`. Resolve temp paths with `Path(td).resolve()` and `chmod(0o700)` before calling `initialize_store()`.
- **Restored retained files path:** `ChunkedAeadBackupEngine.restore_point()` places databases at `<destination_dir>/<db.filename>` and retained attachments under `<destination_dir>/files/<relative_path>`.
