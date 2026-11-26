# Host Provisioning, Recovery Secrets & Offline Packaging

This guide covers GCP host/disk creation, Cloud KMS & Cloudflare R2 recovery provisioning, D5 bootstrap authority setup, offline OCI image/agent packaging, and live Pilot 0 host bring-up on `epm-h02-host`.

See [README.md](README.md) for environment variables (`$PROJECT_ID`, `$ZONE`, `$INSTANCE`) and pinned artifact digests.

---

## 1. GCP VM, VPC & Ext4 `prjquota` Disk Setup

Tool source: [`application/deploy/hosted-mvp/gcp`](../../../application/deploy/hosted-mvp/gcp). Run local Python commands from `application/` using a fresh private `$EPM_EVIDENCE` directory outside Git.

1. **Render startup script & generate reviewed GCP plan:**
   - Render `startup.sh` via `render_startup.py` with pinned Docker package URLs/hashes (Docker versions held).
   - Generate the cloud plan from an explicit `cloud_plan.Target` JSON (explicit project, zone, instance, VPC/subnet CIDR, Artifact Registry repo, service account, exact Ubuntu image name, Tunnel ID — never moving image families):
     ```bash
     PYTHONPATH=apps/server .venv/bin/python deploy/hosted-mvp/gcp/cloud_plan.py \
       --target "$EPM_EVIDENCE/target.json" \
       --startup "$EPM_EVIDENCE/startup.sh" > "$EPM_EVIDENCE/cloud-plan.json"
     ```
   - Execute the reviewed `gcloud` command arrays to create the dedicated VPC, IAP-only SSH rule (`35.235.240.0/20` → `tcp:22`), non-Spot `e2-standard-2` VM (OS Login enabled, project SSH keys blocked), 20 GiB boot disk, and retained 50 GiB data disk (`auto-delete=false`).
2. **Grant resource-scoped VM service account IAM:**
   - Artifact Registry reader on the owning repository only.
   - Secret Manager accessor on `epm-tunnel-<Tunnel ID>` (version 1) and `epm-h05-r2-credentials`.
   - Cloud KMS `roles/cloudkms.cryptoKeyEncrypterDecrypter` on `operator-workspace-kek` and `admin-control-kek` only.
   - Cloud Logging/Monitoring `roles/logging.logWriter` and `roles/monitoring.metricWriter` (see [observability-and-budgets.md](observability-and-budgets.md)).
3. **Format & mount the 50 GiB data disk on the guest:**
   - Run `guest_disk.py` as `root` with `EPM_H02_QUALIFICATION=1` against the blank whole `/dev/disk/by-id/google-epm-h02-data`.
   - It persists formatting intent before `mkfs`, mounts `ext4` with `rw,prjquota,nodev,nosuid,noexec` at `/srv/epm/data` by UUID, and makes Docker depend on that mount. Never rerun against an existing or partial disk.
4. **Install host runtime & tools:**
   - Extract the pinned Python 3.14 runtime to `/opt/epm/python` via `install_runtime.sh`.
   - Install verified Caddy `v2.11.9` and `cloudflared` `2026.10.7` binaries under `/opt/epm/tools` after hash verification.
   - Install the offline `host-agent.tar.gz` bundle via `install_agent.py` into `/opt/epm/host-agent`.
   - Pull OCI images by exact manifest digest via `pull_candidate.py --target <target.json> --reference <image@sha256:digest>` (removes temporary Docker credentials immediately after pull).

---

## 2. Cloud KMS, Cloudflare R2 & D5 Bootstrap Authority

### 2.1 Provision Cloud KMS Keyring & KEKs

> **Gotcha:** GCP Cloud KMS requires `--next-rotation-time` whenever `--rotation-period` is set (emitted by `cloud_plan.kms_plan()`).

```bash
gcloud services enable cloudkms.googleapis.com --project="$PROJECT_ID"

gcloud kms keyrings create epm-h05-recovery \
  --location=us-west1 --project="$PROJECT_ID"

for KEY in operator-workspace-kek admin-control-kek; do
  gcloud kms keys create "$KEY" \
    --location=us-west1 --keyring=epm-h05-recovery \
    --purpose=encryption --protection-level=software \
    --rotation-period=90d --next-rotation-time=2027-02-21T00:00:00Z \
    --project="$PROJECT_ID"

  gcloud kms keys add-iam-policy-binding "$KEY" \
    --location=us-west1 --keyring=epm-h05-recovery \
    --member="serviceAccount:epm-h02-host@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/cloudkms.cryptoKeyEncrypterDecrypter \
    --project="$PROJECT_ID"
done
```

Smoke-test live `CloudKmsEnvelopeProvider` wrap/unwrap with AAD on `epm-h02-host` using `/opt/epm/host-agent/bin/python`:

```bash
gcloud compute ssh "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap \
  --command='sudo /opt/epm/host-agent/bin/python -B -c "
import os
from app.modules.hosted_recovery.infrastructure.kms_provider import CloudKmsEnvelopeProvider
prov = CloudKmsEnvelopeProvider()
for key in (
    \"projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/operator-workspace-kek\",
    \"projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/admin-control-kek\",
):
    dek = os.urandom(32); aad = b\"kms-live-smoke\"
    wrapped = prov.wrap_dek(key, dek, aad=aad)
    assert prov.unwrap_dek(key, wrapped, aad=aad) == dek
    print(\"KMS_LIVE_OK:\", key.split(\"/\")[-1], len(wrapped))
"'
```

### 2.2 Provision Cloudflare R2 Bucket & GCP Secret Manager

1. In Cloudflare Dashboard → R2, create private bucket `epm-hosted-recovery` in **Western North America (WNAM)** (public access disabled).
2. Create a scoped R2 API token (`epm-h05-backup-proxy`) with **Object Read & Write** restricted strictly to `epm-hosted-recovery`.
3. Store the credentials JSON in GCP Secret Manager and bind host service account read-only access:
   ```bash
   gcloud secrets create epm-h05-r2-credentials \
     --project="$PROJECT_ID" --replication-policy=automatic

   cat <<'EOF' | gcloud secrets versions add epm-h05-r2-credentials \
     --project="$PROJECT_ID" --data-file=-
   {
     "endpoint_url": "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
     "bucket": "epm-hosted-recovery",
     "access_key_id": "<R2_ACCESS_KEY_ID>",
     "secret_access_key": "<R2_SECRET_ACCESS_KEY>"
   }
   EOF

   gcloud secrets add-iam-policy-binding epm-h05-r2-credentials \
     --project="$PROJECT_ID" \
     --member="serviceAccount:epm-h02-host@${PROJECT_ID}.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```
   To rotate: add a new secret version, verify `latest` without printing the secret, and destroy the superseded version via `gcloud secrets versions destroy <VERSION> --secret=epm-h05-r2-credentials --project="$PROJECT_ID"`.

### 2.3 Provision Admin Recovery Bootstrap Authority File (D5)

Read `deployment_id` and approved `admin_principals` (`issuer`, `subject`) from `/srv/epm/data/host/h0312-identity/admin.sqlite`, then write both `/etc/epm/admin-recovery-authority.json` (persistent across reboots) and `/run/epm/admin-recovery-authority.json` (runtime) with mode `0600`:

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

## 3. Offline Packaging & Immutable OCI Image Builds

Tool source: [`application/deploy/hosted-mvp`](../../../application/deploy/hosted-mvp) and [`application/scripts/hosted_package.py`](../../../application/scripts/hosted_package.py).

### 3.1 Resolve Linux AMD64 Dependencies Once (Pinned Base Image)

Only dependency resolution requires public PyPI access; retain `resolution.json`, `dependencies.lock`, and `wheels/` together in a private directory outside Git:

```bash
export EPM_ARTIFACTS="$HOME/Desktop/Property-Management-Data/hosted-mvp-qualification/build-new"
export EPM_APPLICATION="$PWD"   # run from application/
export EPM_BASE='docker.io/library/python@sha256:1faf2343e747208b2a36e5f2b5ff908ec3b2d0078a6a7bfe73b535698fe83909'
mkdir -m 700 "$EPM_ARTIFACTS"
docker pull --platform linux/amd64 "$EPM_BASE"
docker run --rm --platform linux/amd64 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m --workdir /tmp \
  --mount "type=bind,src=$EPM_APPLICATION/pyproject.toml,dst=/project.toml,readonly" \
  --mount "type=bind,src=$EPM_APPLICATION/deploy/hosted-mvp/resolve_lock.py,dst=/resolve.py,readonly" \
  --mount "type=bind,src=$EPM_ARTIFACTS,dst=/out" \
  "$EPM_BASE" python -B /resolve.py --project /project.toml \
  --output /out/linux-amd64 --architecture amd64
```

### 3.2 Package & Build Production Admin, Operator & Host Agent Artifacts

1. Build frontend bundles locally (`cd application && npm run build && npm run build:admin && npm run build:central`). If transferring from macOS, archive with `COPYFILE_DISABLE=1 tar --no-xattrs --exclude='._*'`.
2. Prime `uv`'s offline wheel-builder cache once on the build host (`setuptools==84.0.0`):
   ```bash
   uv build --wheel --build-constraints deploy/hosted-mvp/build-constraints.txt --out-dir /tmp/prime
   ```
3. Package all three components and build immutable AMD64 OCI images (`--network=none --provenance=false`, non-root UID/GID `65532`, no compiler or source checkout):
   ```bash
   PYTHONPATH="apps/server:." /opt/epm/python/bin/python3 scripts/hosted_package.py \
     --component admin --identity --architecture amd64 \
     --lock /opt/epm/agent-bundle/dependencies.lock \
     --wheelhouse /opt/epm/agent-bundle/wheelhouse --output /tmp/build/admin

   PYTHONPATH="apps/server:." /opt/epm/python/bin/python3 scripts/hosted_package.py \
     --component operator --architecture amd64 \
     --lock /opt/epm/agent-bundle/dependencies.lock \
     --wheelhouse /opt/epm/agent-bundle/wheelhouse --output /tmp/build/operator

   PYTHONPATH="apps/server:." /opt/epm/python/bin/python3 scripts/hosted_package.py \
     --component host_agent --architecture amd64 \
     --lock /opt/epm/agent-bundle/dependencies.lock \
     --wheelhouse /opt/epm/agent-bundle/wheelhouse --output /tmp/build/host_agent

   /opt/epm/python/bin/python3 deploy/hosted-mvp/archive_agent.py \
     /tmp/build/host_agent /tmp/build/host-agent.tar.gz

   sudo docker buildx build --platform linux/amd64 --network=none --provenance=false \
     --load -t epm-pilot0-admin:<tag> /tmp/build/admin
   sudo docker buildx build --platform linux/amd64 --network=none --provenance=false \
     --load -t epm-pilot0-operator:<tag> /tmp/build/operator
   ```
4. **Verify zero-checkout, zero-`PYTHONPATH` installed integrity** inside both containers (`sudo docker run --rm --network none --read-only --entrypoint /opt/epm/venv/bin/python ...`) using `deploy/hosted-mvp/probe.py` and `app.hosted_candidates.runtime.inspect(...)` across all 6 stores (`admin`, `admin-recovery`, `business`, `hosted-access`, `recovery`, `host-inventory`), verifying fresh `initialize_store`, idempotent re-init (`already_initialized`), and wrong-store rejection. Record the exact OCI manifest digests (`sha256:...`), not mutable tags.

---

## 4. Production Pilot 0 Host Bring-Up (`epm-h02-host`)

1. **Install/upgrade `/opt/epm/host-agent`:**
   - Install the packaged `host_agent` wheel via `pip --python /opt/epm/host-agent/bin/python install --no-index --no-deps --force-reinstall`, clear stale `/opt/epm/host-agent/lib/{database,hosted-candidate.json}` before re-running `stage_schema_resources.py --component host_agent`, and ensure `boto3` is installed in `/opt/epm/host-agent` (required by `R2ObjectStore`).
2. **Initialize host inventory & services:**
   - Run `install_services.py` as `root` with `EPM_H02_QUALIFICATION=1` (verifies live `/srv/epm/data` mount UUID, `rw,prjquota,nodev,nosuid,noexec`, and kernel quota enforcement before mutating inventory; initializes empty `inventory.sqlite` preserving `/srv/epm/data/host/metadata.json`; installs hardened units ordered `gateway -> egress -> tunnel`).
3. **Provision `epm-backup-proxy.service`:**
   - Create system user `epm-backup-proxy` (`uid=940`), fetch `/etc/epm/secrets/r2.json` (`0600`) via `install_services.r2_credential("project-47b72bb7-ba90-42c9-910")`, write `/etc/epm/backup-proxy.json` (`0640 root:epm-backup-proxy`), add `/run/epm-backup-proxy` (`0711`) to `/etc/tmpfiles.d/epm-host.conf`, and `systemctl enable --now epm-backup-proxy.service`.
4. **Initialize `admin-recovery.sqlite` & seed Pilot 0 metadata in `admin.sqlite`:**
   - Create `/srv/epm/data/host/{admin-recovery,admin-control,admin-scratch}` (`0700 65532:65532`) and run `initialize_store(HostedStore.ADMIN_RECOVERY, ...)` inside the built `epm-pilot0-admin:<tag>` image.
   - Seed `admin.sqlite` with `bootstrap_free_v1_policy` (`05038762-822b-5aa1-8906-99c94decabbc`), an initial `qualified_releases` row pointing to the built `epm-pilot0-operator:<tag>` digest, `capacity_profiles` (`pilot0-free-v1`), and `capacity_snapshots` (`complete=True`).
5. **Wire Admin mounts & `v3` route policy in `/opt/epm/h0312/run_identity.py`:**
   > **Gotcha 1 (Mount Allowlist):** `verify_runtime_mounts` in `shared_identity_registration.py` only allows bind mounts under `/control`, `/run/epm-identity-relay`, and `/run/epm-central-identity`, and `/control` is mounted read-only. Create stub dirs `admin-recovery`, `admin-control`, `admin-scratch`, and `backup-proxy` inside `/run/epm-h0312-identity/control` (`0700 65532:65532`), bind `/run/epm-backup-proxy` at `/control/backup-proxy`, and set `"backup_proxy_socket": "/control/backup-proxy/backup-proxy.sock"` in `admin.json`.
   >
   > **Gotcha 2 (`v3` Route Policy):** `SharedIdentityManifest` defaults to `v1` (auth routes only), causing Caddy to return `403` on `/api/admin/bootstrap` and `/api/admin/operators`. Pass `route_policy="separate_exact_host_method_allowlists_v3"` and `admin_routes=ADMIN_H05_ROUTES`.
6. **Verify all 6 host services are `active`:**
   ```bash
   sudo systemctl is-active \
     epm-backup-proxy.service epm-h03-identity.service \
     epm-gateway.service epm-tunnel.service \
     epm-host-guardian.service google-cloud-ops-agent.service
   ```
