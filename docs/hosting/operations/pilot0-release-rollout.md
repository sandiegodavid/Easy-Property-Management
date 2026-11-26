# Pilot 0 Live Release Rollout (Operator & Admin)

This guide covers building updated Operator and Admin OCI images from a local macOS workstation and rolling them live onto `epm-h02-host` (`epmdemo.xyz`), including workspace reinitialization when the business SQLite schema changes.

See [README.md](README.md) for environment variables (`$PROJECT_ID`, `$ZONE`, `$INSTANCE`) and current live digests, and [host-provisioning-and-packaging.md](host-provisioning-and-packaging.md) for initial host provisioning and dependency resolution.

## Interactive Rollout Wizard (macOS)

You can run the guided interactive wizard from the repository root on macOS instead of executing each section manually:

```bash
bash application/scripts/epm-pilot0-rollout.sh          # interactive menu (defaults to rollout)
bash application/scripts/epm-pilot0-rollout.sh rollout  # full Sections 1–5 rollout + live canary smoke gate
bash application/scripts/epm-pilot0-rollout.sh inspect  # read-only check of services, containers, /health/ready, MANIFEST
bash application/scripts/epm-pilot0-rollout.sh smoke    # standalone SMOKE-01..SMOKE-05 canary run
bash application/scripts/epm-pilot0-rollout.sh rollback # restore Operator containers and/or Admin MANIFEST from snapshot
bash application/scripts/epm-pilot0-rollout.sh cleanup  # Section 5 remote + optional local staging cleanup
```

The wizard persists non-secret defaults and pre-rollout rollback snapshots under `~/Library/Application Support/EPM/pilot0-rollout/`, enforces `/private/tmp/...` paths and AppleDouble-free tarballs, rolls the designated canary (`demo-a`) first, halts rollout if any check in `SMOKE-01`..`SMOKE-05` fails, and never passes `--health-cmd` when recreating Operator containers.

### The 9 Rollout Stages (`rollout` action)

| Stage | Name | Runbook Section | What It Does & Safety Gate |
| --- | --- | --- | --- |
| **1/9** | Select GCP destination, release tag, and review source | Pre-flight | Validates local tools (`git`, `gcloud`, `npm`, `tar`, `uv`, `shasum`), captures `$PROJECT_ID`/`$ZONE`/`$INSTANCE`, validates `pilot0-YYYYMMDD-<label>`, canary slug (`demo-a`), and domain (`epmdemo.xyz`), checks `git status`, and optionally runs the local Docker smoke gate (`http://localhost:18802`). |
| **2/9** | Fetch pinned dependency lockfile & wheelhouse | Section 1.1 | Reuses cached `/private/tmp/epm-agent-bundle` or fetches `/opt/epm/agent-bundle/{dependencies.lock,wheelhouse}` from `epm-h02-host` via IAP into a clean `/private/tmp/...` directory. |
| **3/9** | Build frontend bundles, package OCI contexts & upload | Sections 1.2–1.3 | Runs `npm run build && npm run build:admin && npm run build:central`, packages `operator` and `admin --identity` AMD64 contexts with `scripts/hosted_package.py` into `/private/tmp/epm-build`, archives without macOS AppleDouble files (`COPYFILE_DISABLE=1 tar --no-xattrs --exclude='._*'`), verifies archive integrity locally, and uploads `/private/tmp/epm-contexts.tar.gz` via IAP `scp`. |
| **4/9** | Build immutable AMD64 OCI images on `epm-h02-host` | Section 2 | Extracts `/tmp/epm-contexts.tar.gz` on the VM, builds `epm-pilot0-operator:<RELEASE_TAG>` and `epm-pilot0-admin:<RELEASE_TAG>` offline (`--platform linux/amd64 --network=none --provenance=false --load`), and records both `sha256:...` image IDs. |
| **5/9** | Snapshot live state & optional SQLite schema reinit | Section 3.1 | Captures a `0600` pre-rollout rollback snapshot (every operator's current image ID + Admin's current `MANIFEST`) under `~/Library/Application Support/EPM/pilot0-rollout/snapshots/`. If `0001_initial_schema.py` changed, prompts per operator (`demo` synthetic seed vs `empty`), backs up `active` to `active.bak-<YYYYMMDD>`, reinitializes inside the new image, preserves `workspaceId` in `workspace.json` and `workspace_metadata`, and restores `65532:65532` ownership. |
| **6/9** | Roll canary Operator & run live smoke gate | Section 3.2 + Smoke Gate | Recreates only the canary container (`epm-op-demo-a`) on the new image without `--health-cmd`, waits for Docker `(healthy)` + `GET http://127.0.0.1:8081/health/ready` (`200 {"status":"ready"}`), captures a verified R2 + Cloud KMS recovery point under `HOST_UID` if reinitialized, and runs `SMOKE-01`..`SMOKE-05` against `https://demo-a.epmdemo.xyz` (`EPM_SMOKE_STORAGE_STATE`). **Any failure halts rollout immediately.** |
| **7/9** | Roll remaining Pilot 0 Operator containers | Section 3.2 | Only reached after Stage 6 passes. Recreates all remaining containers in `/etc/epm/pilot0-operators/registry.json` on the new Operator image without `--health-cmd`, verifies `(healthy)` + `/health/ready` on every container, and captures post-reinit R2/KMS recovery points for any reinitialized workspaces. |
| **8/9** | Roll live Pilot 0 Admin (`epm-h03-identity.service`) & verify | Section 4 | Backs up `/opt/epm/h0312/run_identity.py`, atomically updates `MANIFEST` to the new 64-hex Admin image ID, restarts `epm-h03-identity.service`, verifies all 6 host systemd services are `active`, confirms the new Admin container image prefix and `journalctl` (`identitytoolkit bearer refreshed (600s)`, no `verify-shared` failure), and requires manual browser confirmation (**Refresh source** on Demo A in Admin + Operator UI check). |
| **9/9** | Clean up temporary build artifacts | Section 5 | Only reached after live browser verification is confirmed. Removes `/tmp/epm-contexts.tar.gz`, `/tmp/build`, and `/tmp/epm-*` on `epm-h02-host`, optionally removes local `/private/tmp/epm-build` and `/private/tmp/epm-contexts.tar.gz` (retaining `/private/tmp/epm-agent-bundle`), and prints the final release digests and rollback snapshot path. |

The sections below remain the authoritative command-by-command reference.

---

## 1. Package Operator & Admin Contexts Locally (macOS → Linux AMD64 VM)

`epm-h02-host` intentionally does not install `npm` or `uv`. Package the offline Docker build contexts locally on macOS using the VM's pinned `dependencies.lock` and `wheelhouse`, then build the AMD64 OCI images on `epm-h02-host`.

> **Gotcha (macOS `/tmp` Symlink):** On macOS, `/tmp` is a symlink to `/private/tmp`. `hosted_package.py` and `schema_resources.py` reject symlinked parent paths — always pass `/private/tmp/...` paths.

1. **Fetch the pinned lockfile and wheelhouse from `epm-h02-host` (once per dependency lock):**
   ```bash
   mkdir -p /private/tmp/epm-agent-bundle
   gcloud compute ssh "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap \
     --command='sudo tar -C /opt/epm/agent-bundle -cf - dependencies.lock wheelhouse' \
     | tar -C /private/tmp/epm-agent-bundle -xf -
   ```

2. **Build frontend bundles and package both OCI build contexts from `application/`:**
   ```bash
   cd application
   npm run build && npm run build:admin && npm run build:central

   rm -rf /private/tmp/epm-build
   mkdir -p /private/tmp/epm-build

   PYTHONPATH="apps/server:." .venv/bin/python scripts/hosted_package.py \
     --component operator --architecture amd64 \
     --lock /private/tmp/epm-agent-bundle/dependencies.lock \
     --wheelhouse /private/tmp/epm-agent-bundle/wheelhouse \
     --output /private/tmp/epm-build/operator

   PYTHONPATH="apps/server:." .venv/bin/python scripts/hosted_package.py \
     --component admin --identity --architecture amd64 \
     --lock /private/tmp/epm-agent-bundle/dependencies.lock \
     --wheelhouse /private/tmp/epm-agent-bundle/wheelhouse \
     --output /private/tmp/epm-build/admin
   ```

3. **Archive without macOS AppleDouble files and upload to `epm-h02-host`:**
   ```bash
   COPYFILE_DISABLE=1 tar --no-xattrs --exclude='._*' \
     -C /private/tmp/epm-build -czf /private/tmp/epm-contexts.tar.gz operator admin

   gcloud compute scp /private/tmp/epm-contexts.tar.gz "$INSTANCE":/tmp/epm-contexts.tar.gz \
     --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap
   ```

---

## 2. Build Immutable AMD64 OCI Images on `epm-h02-host`

Pick a release tag (for example, `pilot0-20261124-ui`) and build offline (`--network=none --provenance=false`):

```bash
export RELEASE_TAG="pilot0-<YYYYMMDD>-<label>"

gcloud compute ssh "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap --command="
set -e
rm -rf /tmp/build && mkdir -p /tmp/build
tar -C /tmp/build -xzf /tmp/epm-contexts.tar.gz

sudo docker buildx build --platform linux/amd64 --network=none --provenance=false \
  --load -t epm-pilot0-operator:$RELEASE_TAG /tmp/build/operator

sudo docker buildx build --platform linux/amd64 --network=none --provenance=false \
  --load -t epm-pilot0-admin:$RELEASE_TAG /tmp/build/admin

sudo docker image inspect --format '{{.RepoTags}} {{.Id}}' \
  epm-pilot0-operator:$RELEASE_TAG epm-pilot0-admin:$RELEASE_TAG
"
```

Record the exact `sha256:...` image IDs printed at the end.

---

## 3. Roll Live Pilot 0 Operator Containers (`epm-op-<slug>`)

### 3.1 When the Business SQLite Schema Changed (MVP Greenfield Reinit)

`validate_latest_schema` enforces exact DDL / `CHECK` constraint equality on startup. If the release modifies `application/database/sqlite-migrations/versions/0001_initial_schema.py`, existing Pilot 0 workspaces must be backed up and reinitialized (demo workspaces re-seeded with `synthetic-demo-v1`; other workspaces reinitialized empty if confirmed with the operator):

1. Stop the operator container (`sudo docker stop epm-op-<slug>`).
2. Move `/srv/epm/data/workspace/<operator_id>/active` to `active.bak-<YYYYMMDD>`.
3. Create a fresh `active` directory (`0700 65532:65532`) and initialize it inside `epm-pilot0-operator:$RELEASE_TAG` (either empty via `initialize_store` / workspace init, or seeded via `application/demo/seed.py` + `dataset.json`).
4. Preserve the operator's existing `workspaceId` in both:
   - `/srv/epm/data/workspace/<operator_id>/active/workspace.json` (`"workspaceId"`)
   - `/srv/epm/data/workspace/<operator_id>/active/database/property-management.sqlite` (`workspace_metadata.workspace_id`)
5. Restore ownership `65532:65532` across `/srv/epm/data/workspace/<operator_id>`.

### 3.2 Recreate Operator Containers on the New Image

Recreate each container using `/etc/epm/pilot0-operators/registry.json` and the exact flags from `/opt/epm/pilot0/launch_operator.py`:

> **Gotcha (Do Not Pass `--health-cmd`):** `Dockerfile.operator` already embeds an exec-form `HEALTHCHECK` against `127.0.0.1:8081/health/live`. Do **not** pass `--health-cmd` to `docker run` when recreating containers — overriding it with shell-escaped quotes causes Docker to mark healthy containers `(unhealthy)`.

```bash
gcloud compute ssh "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap --command="
sudo python3 - << 'PY'
import json, subprocess, time
from pathlib import Path

IMAGE = 'epm-pilot0-operator:$RELEASE_TAG'
CENTRAL_UID = 65532
reg = json.loads(Path('/etc/epm/pilot0-operators/registry.json').read_text())

for op_id, op in reg['operators'].items():
    slug = op['workspace_slug']
    ctr_name = f'epm-op-{slug}'
    net_name = f'epm-op-{slug}'
    op_ip = op['ip']
    op_dir = f'/etc/epm/pilot0-operators/{op_id}'
    print(f'Recreating {ctr_name} ({op_id}, {op_ip})...')
    subprocess.run(['docker', 'rm', '-f', ctr_name], check=False, capture_output=True)
    stale = Path(f'/run/epm-operator-sockets/{op_id}/{op_id}.sock')
    if stale.exists():
        stale.unlink()
    subprocess.run([
        'docker', 'run', '-d', '--name', ctr_name, '--restart', 'unless-stopped',
        '--pull', 'never', '--user', f'{CENTRAL_UID}:{CENTRAL_UID}',
        '--network', net_name, '--ip', op_ip,
        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=32m',
        '--mount', f'type=bind,source={op_dir},target=/control,readonly',
        '--mount', f'type=bind,source=/srv/epm/data/workspace/{op_id},target=/data/workspace',
        '--mount', f'type=bind,source=/srv/epm/data/control/{op_id},target=/data/control',
        '--mount', f'type=bind,source=/srv/epm/data/scratch/{op_id},target=/data/scratch',
        '--mount', 'type=bind,source=/run/epm-central-identity,target=/run/epm-central-identity',
        '--mount', f'type=bind,source=/run/epm-operator-sockets/{op_id},target=/run/epm-identity-sockets',
        '--entrypoint', '/bin/sh', IMAGE, '-ec',
        'rm -f /run/epm-identity-sockets/*.sock; mkdir -m 700 /tmp/epm-identity-sockets; exec /opt/epm/venv/bin/python -B -m app.modules.hosted_access.infrastructure.operator_entry --configuration /control/deployment.json --tls-key /control/tls.key --tls-certificate /control/tls.pem',
    ], check=True)

time.sleep(35)
print(subprocess.check_output(['docker', 'ps', '--format', '{{.Names}} {{.Image}} {{.Status}}'], text=True))
PY
"
```

Verify both readiness and Docker health:
- `docker ps` reports `(healthy)` for every `epm-op-<slug>` container.
- Inside each container, `GET http://127.0.0.1:8081/health/ready` returns `200 {"status":"ready"}`.
- If any workspace was reinitialized in Section 3.1, capture a fresh verified R2 + Cloud KMS recovery point under that operator's registered `HOST_UID` (see [pilot0-admission-and-incidents.md](pilot0-admission-and-incidents.md#step-3--launch-container-capture-initial-verified-backup--verify-ingress)) so `protection_state` clears from `Degraded` (`overdue`) to `Protected`.

---

## 4. Roll Live Pilot 0 Admin (`epm-h03-identity.service`)

`epm-h03-identity.service` runs `/opt/epm/h0312/run_identity.py`, which pins the Admin container image via the top-level `MANIFEST` constant (64-hex `sha256` without the `sha256:` prefix).

1. **Back up `/opt/epm/h0312/run_identity.py`, update `MANIFEST`, and restart `epm-h03-identity.service`:**
   ```bash
   gcloud compute ssh "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap --command="
   set -e
   NEW_ID=\$(sudo docker image inspect --format '{{.Id}}' epm-pilot0-admin:$RELEASE_TAG | sed 's/^sha256://')
   echo \"NEW_ID=\$NEW_ID\"
   sudo cp -p /opt/epm/h0312/run_identity.py /opt/epm/h0312/run_identity.py.bak-\$(date +%Y%m%d)
   sudo python3 -c '
   import re, sys
   from pathlib import Path
   p = Path(\"/opt/epm/h0312/run_identity.py\")
   text, n = re.subn(r\"^MANIFEST = \\\"[0-9a-f]{64}\\\"$\", f\"MANIFEST = \\\"{sys.argv[1]}\\\"\", p.read_text(), count=1, flags=re.M)
   assert n == 1, \"MANIFEST line not found\"
   p.write_text(text)
   ' \"\$NEW_ID\"
   sudo grep -n '^MANIFEST = ' /opt/epm/h0312/run_identity.py
   sudo systemctl restart epm-h03-identity.service
   sleep 20
   sudo systemctl is-active epm-h03-identity.service epm-gateway.service epm-tunnel.service epm-backup-proxy.service epm-host-guardian.service google-cloud-ops-agent.service
   sudo docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
   sudo journalctl -u epm-h03-identity.service --since '2 minutes ago' --no-pager
   "
   ```

2. **Confirm startup succeeded:**
   - All 6 host services report `active`.
   - `docker ps` shows the new Admin container running on the new `NEW_ID` prefix (note: during startup `run_identity.py` briefly runs a temporary inventory container before launching the long-lived Admin container).
   - `journalctl -u epm-h03-identity.service` shows `identitytoolkit bearer refreshed (600s)` with no `verify-shared` failure.

> **Gotcha (`qualified_releases` Immutability):** `admin.sqlite` enforces an `immutable hosted record` trigger on `qualified_releases`. Never `UPDATE` an existing `qualified_releases` row in place; when admitting brand-new Pilot 0 operators on a newer release, `INSERT` a new `release_id` row with the new Operator image digest instead.

### Admin source inspection

The source inspector uses the private Host Agent identity relay to read effective access and logical usage from the bound Operator. Roll out the relay protocol update, the Admin image, and the Operator image together. Verify **Refresh source** on Demo A and confirm that **Source access** and **Free usage** reflect the Operator's current state. Run the [live canary smoke gate](../../active/HOSTED_OPERATOR_POST_DEPLOY_SMOKE_DESIGN.md#5-rollout-integration--passfail-gate) before completing rollout. See [README.md](README.md#live-pilot-0-host-inventory--constants) for current live digests and registered catalog releases.

---

## 5. Clean Up Temporary Build Artifacts

After verifying the live rollout in a browser (hard-refresh with `Cmd+Shift+R`):

```bash
# Clean up temporary build files on epm-h02-host
gcloud compute ssh "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap \
  --command='sudo rm -rf /tmp/epm-contexts.tar.gz /tmp/build /tmp/epm-*'

# Optionally clean up local macOS build staging
rm -rf /private/tmp/epm-build /private/tmp/epm-contexts.tar.gz
```

## 6. Reclaim Disk Space from Old, Unused Releases

When old Pilot 0 OCI images, exited containers, Docker build cache, or legacy qualification directories under `/opt/epm` accumulate on `epm-h02-host`, run the interactive release cleanup wizard from your workstation:

```bash
# Read-only inventory of disk usage and KEEP vs. REMOVABLE items
bash application/scripts/epm-pilot0-release-cleanup.sh inspect

# Interactive 6-stage cleanup wizard (stopped containers, unused images, build cache, /tmp, unreferenced /opt/epm dirs)
bash application/scripts/epm-pilot0-release-cleanup.sh cleanup
```

The wizard streams `application/scripts/pilot0_release_cleanup.py` over IAP SSH (no extra files installed on the VM) and enforces automatic protections before every deletion:
- **Never removes** running containers or their images, the active Admin `MANIFEST` image (`/opt/epm/h0312/run_identity.py`), the latest or operator-referenced `qualified_releases` catalog entries in `admin.sqlite`, the offline-build `python:*` base image, core `/opt/epm` runtime directories or anything referenced by `systemd`, `/etc/epm`, symlinks, or running processes, or any `/srv/epm/data` workspace/control/backup data.
- Supports explicit `--keep` rollback image retention and requires typed `DELETE` confirmation for bulk image or `/opt/epm` directory removal.
