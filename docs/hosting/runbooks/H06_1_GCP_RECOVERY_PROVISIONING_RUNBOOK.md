# H06.1 Operations Runbook — GCP Provider Re-Pin, Cloud KMS, R2 Secret Manager & Native H05.9 Sizing

**Applies to:** HOSTED-001 Slice H06.1 (`epm-h02-host`, GCP project `project-47b72bb7-ba90-42c9-910`, zone `us-west1-b`)  
**Checkpoint:** [HOSTED_MVP_H06_1_CHECKPOINT_2026-11-23.md](../qualification/reports/HOSTED_MVP_H06_1_CHECKPOINT_2026-11-23.md)  
**Related Runbook:** [H05_RECOVERY_OPERATIONS_RUNBOOK.md](H05_RECOVERY_OPERATIONS_RUNBOOK.md)

---

## 1. Start & Stop `epm-h02-host` (Cost Hygiene)

Always start `epm-h02-host` only when executing live operations, and stop it afterward while idle:

```bash
# Start VM
gcloud compute instances start epm-h02-host \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b

# Check status
gcloud compute instances describe epm-h02-host \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --format="value(status)"

# Stop VM when finished
gcloud compute instances stop epm-h02-host \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b
```

All SSH/SCP operations use IAP tunneling (`--tunnel-through-iap`), matching the host's private firewall rule (`35.235.240.0/20` → `tcp:22`).

---

## 2. Re-Pin Protected Host Identity Provider Config (`provider_email_sends_per_day: 100`)

When Google's Firebase/Identity Platform daily email-link quota changes (confirmed `100/day`, app ceiling `90/day`):

1. **Update `/etc/epm/h0312/provider.json` on `epm-h02-host` atomically (preserving permissions/ownership) and compute its SHA-256:**
   ```bash
   gcloud compute ssh epm-h02-host \
     --project=project-47b72bb7-ba90-42c9-910 \
     --zone=us-west1-b \
     --tunnel-through-iap \
     --command="sudo python3 -c '
   import json, os, hashlib
   p = \"/etc/epm/h0312/provider.json\"
   st = os.stat(p)
   d = json.loads(open(p, \"rb\").read())
   d[\"provider_email_sends_per_day\"] = 100
   new_raw = (json.dumps(d, indent=2) + \"\n\").encode(\"utf-8\")
   tmp = p + \".tmp\"
   with open(tmp, \"wb\") as f:
       f.write(new_raw)
   os.chmod(tmp, st.st_mode & 0o7777)
   os.chown(tmp, st.st_uid, st.st_gid)
   os.replace(tmp, p)
   print(\"NEW_SHA256=\" + hashlib.sha256(new_raw).hexdigest())
   '"
   ```
2. **Pin the printed digest** in `application/deploy/hosted-mvp/identity/selection.json` (`provider_config_sha256`), and sync `/etc/epm/h0312/setup.json` on `epm-h02-host` (`revision: 5`, `deployment_sends_per_day: 90`, `provider_sends_per_day: 100`, `provider_config_sha256`).
3. **Verify contract tests locally:**
   ```bash
   cd application
   PYTHONPATH=apps/server .venv/bin/pytest \
     apps/server/app/modules/hosted_access/tests/test_identity_contracts.py \
     apps/server/app/modules/hosted_access/tests/test_provider_boundaries.py
   ```

---

## 3. Provision GCP Cloud KMS Keys & Verify Live Wrap/Unwrap

> **Note:** GCP Cloud KMS requires `--next-rotation-time` whenever `--rotation-period` is specified (now emitted by `cloud_plan.kms_plan()`).

1. **Enable API, create keyring and KEKs, and bind host service account IAM:**
   ```bash
   gcloud services enable cloudkms.googleapis.com \
     --project=project-47b72bb7-ba90-42c9-910

   gcloud kms keyrings create epm-h05-recovery \
     --location=us-west1 \
     --project=project-47b72bb7-ba90-42c9-910

   gcloud kms keys create operator-workspace-kek \
     --location=us-west1 \
     --keyring=epm-h05-recovery \
     --purpose=encryption \
     --protection-level=software \
     --rotation-period=90d \
     --next-rotation-time=2027-02-21T00:00:00Z \
     --project=project-47b72bb7-ba90-42c9-910

   gcloud kms keys create admin-control-kek \
     --location=us-west1 \
     --keyring=epm-h05-recovery \
     --purpose=encryption \
     --protection-level=software \
     --rotation-period=90d \
     --next-rotation-time=2027-02-21T00:00:00Z \
     --project=project-47b72bb7-ba90-42c9-910

   for KEY in operator-workspace-kek admin-control-kek; do
     gcloud kms keys add-iam-policy-binding "$KEY" \
       --location=us-west1 \
       --keyring=epm-h05-recovery \
       --member=serviceAccount:epm-h02-host@project-47b72bb7-ba90-42c9-910.iam.gserviceaccount.com \
       --role=roles/cloudkms.cryptoKeyEncrypterDecrypter \
       --project=project-47b72bb7-ba90-42c9-910
   done
   ```

2. **Smoke-test live `CloudKmsEnvelopeProvider` wrap/unwrap with AAD from `epm-h02-host`:**
   ```bash
   gcloud compute ssh epm-h02-host \
     --project=project-47b72bb7-ba90-42c9-910 \
     --zone=us-west1-b \
     --tunnel-through-iap \
     --command="sudo PYTHONPATH=/opt/epm/h061-source/application/apps/server /opt/epm/h0312-agent/bin/python -c '
   import os
   from app.modules.hosted_recovery.infrastructure.kms_provider import CloudKmsEnvelopeProvider
   prov = CloudKmsEnvelopeProvider()
   for key in (
       \"projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/operator-workspace-kek\",
       \"projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/admin-control-kek\",
   ):
       dek = os.urandom(32)
       aad = b\"h061-live-kms-smoke\"
       wrapped = prov.wrap_dek(key, dek, aad=aad)
       assert prov.unwrap_dek(key, wrapped, aad=aad) == dek
       print(\"KMS_LIVE_OK:\", key.split(\"/\")[-1], len(wrapped))
   '"
   ```

---

## 4. Provision Protected Admin Bootstrap Authority File (D5)

1. Read `deployment_id` and approved `admin_principals` (`issuer`, `subject`) from `/srv/epm/data/host/h0312-identity/admin.sqlite` (read-only URI).
2. Write both `/etc/epm/admin-recovery-authority.json` (persistent across reboots) and `/run/epm/admin-recovery-authority.json` (runtime path) with mode `0600`:
   ```json
   {
     "version": 1,
     "deployment_id": "b77f7c7e-c89c-4d44-b337-e8d4f13ee46f",
     "principals": [
       {
         "issuer": "identity-epmdemo-v1",
         "subject": "<ADMIN_FIREBASE_UID>",
         "principal_ref": "admin:bootstrap-primary",
         "mfa_required": true
       }
     ]
   }
   ```

---

## 5. Provision Cloudflare R2 Bucket & Store Scoped Credentials in GCP Secret Manager

1. **Cloudflare Dashboard → R2 Object Storage:**
   - Create private bucket `epm-hosted-recovery` in **Western North America (WNAM)** (public access disabled).
   - Create a scoped API token (`epm-h05-backup-proxy`) with **Object Read & Write** restricted strictly to `epm-hosted-recovery`.
   - Record the S3 endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, `access_key_id`, and `secret_access_key`.
2. **Store in GCP Secret Manager and grant host service account read-only access:**
   ```bash
   gcloud secrets create epm-h05-r2-credentials \
     --project=project-47b72bb7-ba90-42c9-910 \
     --replication-policy=automatic

   cat <<'EOF' | gcloud secrets versions add epm-h05-r2-credentials \
     --project=project-47b72bb7-ba90-42c9-910 \
     --data-file=-
   {
     "endpoint_url": "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
     "bucket": "epm-hosted-recovery",
     "access_key_id": "<R2_ACCESS_KEY_ID>",
     "secret_access_key": "<R2_SECRET_ACCESS_KEY>"
   }
   EOF

   gcloud secrets add-iam-policy-binding epm-h05-r2-credentials \
     --project=project-47b72bb7-ba90-42c9-910 \
     --member="serviceAccount:epm-h02-host@project-47b72bb7-ba90-42c9-910.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```
3. **Rotating or replacing a bad secret version:** Add a new version with `gcloud secrets versions add ...`, verify `latest` without printing the secret key, and destroy the superseded version with `gcloud secrets versions destroy <VERSION> --secret=epm-h05-r2-credentials --project=project-47b72bb7-ba90-42c9-910`.

---

## 6. Run Native GCP H05.9 Backup/Restore Reserve Sizing (`ext4 prjquota`)

> **macOS tarball gotcha:** Always pass `COPYFILE_DISABLE=1` and `--no-xattrs --exclude='._*'` when creating tarballs on macOS. Otherwise AppleDouble `._*.py` files enter `database/*/versions/` and `schema_resources.py` rejects the directory (`SchemaResourcesUnavailable`).

1. **Create a clean source tarball and record its SHA-256:**
   ```bash
   COPYFILE_DISABLE=1 tar --no-xattrs \
     --exclude='__pycache__' --exclude='.pytest_cache' \
     --exclude='.venv' --exclude='._*' \
     -czf /tmp/epm-h061-source.tar.gz \
     application/apps/server \
     application/database \
     application/deploy/hosted-mvp \
     docs/hosting/qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json \
     docs/hosting/qualification/specifications/recovery.json

   shasum -a 256 /tmp/epm-h061-source.tar.gz
   ```

2. **Upload via IAP and run `qualify_h05_sizing.py --gcp` on `epm-h02-host`:**
   ```bash
   gcloud compute scp /tmp/epm-h061-source.tar.gz \
     epm-h02-host:/tmp/epm-h061-source.tar.gz \
     --project=project-47b72bb7-ba90-42c9-910 \
     --zone=us-west1-b \
     --tunnel-through-iap

   gcloud compute ssh epm-h02-host \
     --project=project-47b72bb7-ba90-42c9-910 \
     --zone=us-west1-b \
     --tunnel-through-iap \
     --command="sudo rm -rf /opt/epm/h061-source /tmp/h059-out && \
       sudo mkdir -p /opt/epm/h061-source /tmp/h059-out && \
       sudo tar -xzf /tmp/epm-h061-source.tar.gz -C /opt/epm/h061-source && \
       sudo env EPM_RUN_H05_SIZING_QUALIFICATION=1 \
         PYTHONPATH=/opt/epm/h061-source/application/apps/server \
         /opt/epm/h0312-agent/bin/python \
         /opt/epm/h061-source/application/deploy/hosted-mvp/gcp/qualify_h05_sizing.py \
         --gcp /tmp/h059-out \
         epm-h03-12-operator:qualification \
         <SOURCE_TARBALL_SHA256> \
         /opt/epm/h061-source/docs/hosting/qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json"
   ```

3. **Save & clean up:** Save the validated JSON output to `docs/hosting/qualification/reports/HOSTED_MVP_H05_9_RECOVERY_SIZING.json`, delete `/tmp/h059-out` and `/tmp/epm-h061-source.tar.gz` on `epm-h02-host`, and stop `epm-h02-host`.
