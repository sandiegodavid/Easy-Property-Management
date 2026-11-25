# Local Development, Lima Native Lab & GCP Qualification

Mac Docker Desktop (emulated AMD64), native ARM64 Lima, and native AMD64 GCP (`epm-h02-host`) are separate evidence scopes. Always use synthetic data only for qualification, retain raw logs outside Git, and never patch a tested snapshot in place.

---

## 1. Local Pre-Release Validation Gates

Run from `application/`:

```bash
# Frontend lint, format, typecheck & Playwright Pilot 0 component suites
npm run lint && npm run format:check && npm run typecheck
npx playwright test --config playwright.components.config.ts \
  admin-identity.spec.ts central-identity.spec.ts managed-security.spec.ts \
  recovery.spec.ts hosted-recovery.spec.ts hosted-settings.spec.ts admin-lite.spec.ts

# Core hosted Python proofs & contracts
PYTHONPATH=apps/server .venv/bin/pytest \
  apps/server/app/platform/tests/test_hosted_artifacts.py \
  apps/server/app/platform/tests/test_hosted_proofs.py \
  apps/server/app/platform/tests/test_hosted_ui_contracts.py \
  apps/server/app/platform/tests/test_schema_resources.py \
  apps/server/app/platform/tests/test_hosted_schema.py \
  scripts/tests/test_hosted_packaging.py \
  scripts/tests/test_h06_image_schema_qualification.py \
  scripts/tests/test_h06_observability_and_budgets.py \
  scripts/tests/test_h06_pilot0_operations_economics.py -q
```

---

## 2. Mac Docker Desktop Development Lab

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
export EPM_LAB="$HOME/Desktop/Property-Management-Data/hosted-mvp-qualification/dev"

# Verify pinned AMD64 candidate images outside checkout (no tags)
.venv/bin/python deploy/hosted-mvp/lab/desktop.py \
  --admin "$(cat "$EPM_LAB/admin-image-id")" \
  --operator "$(cat "$EPM_LAB/operator-image-id")" \
  --output "$EPM_LAB/desktop-check.json"

# Inspect loopback unavailable pages (Admin :18801, Operator :18802)
docker compose -p epm-h02-dev -f deploy/hosted-mvp/lab/compose.yaml up -d
docker compose -p epm-h02-dev -f deploy/hosted-mvp/lab/compose.yaml down
```

### Interactive Local Hosting Test Containers (Admin + Operator Only)

For local browser and API testing of the real compiled Admin-lite and Operator UIs without Caddy, Cloudflare Tunnel, Firebase, `epm-backup-proxy`, `epm-egress-proxy`, or `epm-host-guardian`, see [deploy/hosted-mvp/local-test/README.md](../../../application/deploy/hosted-mvp/local-test/README.md):

```bash
# From application/ (rebuild frontend bundles first if UI changed)
docker compose -f deploy/hosted-mvp/local-test/compose.yaml up -d --build
# Admin UI:    http://localhost:18801
# Operator UI: http://localhost:18802
docker compose -f deploy/hosted-mvp/local-test/compose.yaml down
```

---

## 3. Native Linux Qualification (Lima Clones)

Preserve stopped baseline VMs (`epm-quota-test`, `epm-h02-runtime`, `epm-h02-8`); clone into a fresh VM name with `--mount-none` (verify `findmnt -rn -t virtiofs,9p,fuse.sshfs` prints nothing). Package immutable source snapshots with `deploy/hosted-mvp/lab/snapshot.py`.

Establish kernel prerequisites explicitly after every boot:

```bash
sudo modprobe quota_v2
sudo modprobe br_netfilter
sudo sysctl -w net.bridge.bridge-nf-call-iptables=1 net.bridge.bridge-nf-call-ip6tables=1
```

| Suite | Driver & Opt-In |
| --- | --- |
| **Runtime sandbox & quotas** | `EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1` · `sandbox/qualify_runtime.py --run` |
| **Connected bridge/firewall + sandbox** | `EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1` · `gateway/qualify_connected.py --run` |
| **Two-phase guest reboot** | `EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1` · `lab/qualify_reboot.py before` → `sudo systemctl reboot` → `lab/qualify_reboot.py after --root <lab>` |
| **Gateway / containment / network / services / tunnel / egress** | `EPM_RUN_GATEWAY_QUALIFICATION=1` · `gateway/qualify_{gateway,containment,network,services,tunnel,egress}.py` |
| **Shared identity & identity reboot/drift** | `gateway/qualify_shared_identity.py <image_sha256> /usr/bin/caddy` and `gateway/qualify_identity_reboot.py {before,after}` |

---

## 4. Native GCP Qualification Drivers (`epm-h02-host`)

Always upload clean macOS-safe tarballs (`COPYFILE_DISABLE=1 tar --no-xattrs --exclude='._*'`), run with `/opt/epm/python/bin/python3` (3.14) or `/opt/epm/host-agent/bin/python`, remove `/tmp` staging directories, and stop `epm-h02-host` when idle during qualification.

| Qualification Gate | Driver & Validation |
| --- | --- |
| **Host principals, retained disk & reboot** | `gcp/qualify_principals.py`, `gcp/qualify_host.py {before,after}`, `lab/qualify_reboot.py {before,after}` |
| **Host capacity profile** | `EPM_RUN_CAPACITY_QUALIFICATION=1` · `gcp/measure_capacity.py` |
| **Free + recovery reserve sizing (`ext4 prjquota`)** | `EPM_RUN_H05_SIZING_QUALIFICATION=1` · `gcp/qualify_h05_sizing.py --gcp <out> <operator_image> <tar_sha256> <h04_sizing.json>` |
| **9-case `image_schema.json` (6 stores)** | `gcp/qualify_h06_image_schema.py <output.json>` (paired with zero-checkout `docker run` verification of `epm-pilot0-admin` & `epm-pilot0-operator`) |
| **Live R2 + Cloud KMS + `SO_PEERCRED` proxy** | `gcp/qualify_h06_live_r2_kms.py --credentials-file <r2.json> --admin-key-ref ... --operator-key-ref ... --output <out.json>` (verifies cross-key denial, path-traversal denial, tamper rejection, and 0 remaining disposable R2 objects) |
| **17-case `recovery.json` + joint H04/H05 handoff** | `gcp/qualify_h05_recovery.py <output.json>` |
| **Identity proof & validator** | `identity/qualify_identity_proof.py` + `python -m app.platform.hosted_proofs validate --spec <spec.json> --report <report.json>` |
| **Observability & synthetic alerts** | `gcp/qualify_h06_observability.py <output.json>` |
| **9-case `operations_economics.json`** | `gcp/qualify_h06_pilot0.py <output.json>` |

### Live Deployed Browser Smoke Checklist (After Web Bundle Releases)
1. Open `https://admin.epmdemo.xyz/` and `https://login.epmdemo.xyz/auth/start?flow=operator` — confirm `dctech92130@gmail.com` appears on sign-in and error views.
2. Open Operator **Settings → Workspace plan and storage** — confirm real support contact, Pilot 0 disclosure, and zero billing/upgrade buttons.
3. Sign in to Admin-lite with Google + TOTP MFA — confirm Cohort Health/Headroom/Maintenance overview matches live counts and capacity profile.
4. Rehearse `announced` → `in_progress` → cleared `/run/epm/maintenance-notice.json` and confirm unfinished form drafts remain intact.
