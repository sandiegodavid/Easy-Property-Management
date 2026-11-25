# Pilot 0 Live Release Rollout (Operator & Admin)

This guide covers building updated Operator and Admin OCI images from a local macOS workstation and rolling them live onto `epm-h02-host` (`epmdemo.xyz`), including workspace reinitialization when the business SQLite schema changes.

See [README.md](README.md) for environment variables (`$PROJECT_ID`, `$ZONE`, `$INSTANCE`) and current live digests, and [host-provisioning-and-packaging.md](host-provisioning-and-packaging.md) for initial host provisioning and dependency resolution.

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

The source inspector uses the private Host Agent identity relay to read effective access and logical usage from the bound Operator. Roll out the relay protocol update, the Admin image, and the Operator image together. Verify **Refresh source** on Demo A and confirm that **Source access** and **Free usage** reflect the Operator's current state. Run the [live canary smoke gate](../../active/HOSTED_OPERATOR_POST_DEPLOY_SMOKE_DESIGN.md#5-rollout-integration--passfail-gate) before completing rollout.

See the [source inspection checkpoint](pilot0-source-inspection-checkpoint.md) for current rollout and catalog status.

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
