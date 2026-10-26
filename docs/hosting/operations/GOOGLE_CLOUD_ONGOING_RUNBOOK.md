# Google Cloud: operate and update the existing host

Use this after setup. It covers the recorded `epm-demo` VM in `us-west1-b`, project
`project-47b72bb7-ba90-42c9-910`, with hosted instances A and B. Confirm the actual
inventory in the [deployment record](CLOUDFLARE_OPERATIONS.md) before proceeding.
These instructions were checked against repository commands; this document does
not claim a new release has been deployed or tested on the VM.

For ordinary inspection, backups and recovery, use the shortcuts below. For a
code update, follow steps 1–6. Do not repeat VM, Cloudflare, enrollment or workspace
initialization. The wheel **and matching schema resources** form the release.

## Interactive wizards (recommended)

On the **Mac**, from the repository root:

```bash
bash application/scripts/epm-release-mac.sh
```

The [Mac wizard](../../../application/scripts/epm-release-mac.sh) asks for a new
release ID, Google destination and test evidence, builds the wheel/SPA, bundles
matching schema resources without macOS metadata, and uploads through IAP. It prints
the exact SSH and VM-wizard commands. Keep the SHA-256 it displays for independent
comparison on the VM. It never changes VM services or workspace data.
Its optional fresh-demo stage creates separate verified synthetic workspaces for
A and B on the Mac, exports encrypted archives, and uploads them with descriptors
bound to the source commit, release, schema and workspace UUID. These artifacts
are separate from the application wheel. The helper is bundled as
`release_demo.py`; it is installer tooling, not a public API.

**Before answering Stage 2, “Review source and tests”:**

- Commit all intended release changes and keep the working tree clean. Confirm
  the displayed source commit is the one you intend to deploy.
- Run tests relevant to those changes against that source. The wizard asks for
  confirmation and evidence; it does not select tests, run them, or verify that
  you ran them. The release maintainer chooses tests based on the changed modules
  and boundaries.

For a hosted sign-in or redirect change, run from `application/`:

```bash
node scripts/python.mjs -m pytest \
  apps/server/app/modules/hosted_access/tests/test_transport.py -q
npm run test:hosted
```

When both pass and the displayed commit is correct, answer `y`. At the next
test-evidence prompt, enter the actual results or a reference to saved results,
for example: `Hosted transport tests and hosted Playwright suite passed locally.`
For other releases, select focused tests for the affected modules and boundaries.
Stage 3 separately runs the build's lint, formatting, type, contract and packaging
checks; a successful build does not substitute for the Stage 2 test prerequisite.

On the **VM**, run the exact command printed by the Mac wizard. Its filename uses
the release ID you selected; it changes for each release. Alternatively, enter
that same ID when prompted:

```bash
read -r -p "Release ID used in the Mac wizard: " release
bash "$HOME/${release:?Release ID is required}-vm.sh"
```

The uploaded [VM wizard](../../../application/scripts/epm-release-vm.sh) offers:

| Action | Use it for |
| --- | --- |
| `inspect` | Read-only service, mount, disk, memory and recent-log inspection |
| `install` | Verify the archive against the Mac hash; install beside current releases using an effective hosted runtime's Python/dependencies; verify resources |
| `deploy` | Update one instance: record rollback state, disable/stop, back up, validate, generate its exact override, wait for readiness, reactivate its verified subject, and confirm browser acceptance |
| `resume` | Complete an interrupted deployment after its backup and override switch; select its saved record, check/start the selected release, reactivate and finish acceptance |
| `rollback` | Explicitly fence/stop an instance, check old-release compatibility, restore only the saved release override, then reactivate and verify |
| `reset-demo` | Replace one active demo with fresh current-format synthetic data, preserving the old dataset, backup, access store and configuration |
| `resume-reset` | Resume the printed reset checkpoint after interruption without recreating completed backups, restoring over existing data or reinitializing access |
| `rollback-reset` | Stop the new writer, restore the preserved old configuration/runtime/recovery binding, then validate and reactivate the old demo |

Choose **install → deploy A → deploy B**, running the wizard again for each action.
Install runs once per release; its A/B prompt selects the current hosted Python
and dependency set to copy, not which instance to deploy. Accept A before B.
For an incompatible demo schema, use **install → reset-demo A → reset-demo B**
instead, following the fresh-demo steps below. Installation uses constraints **and requirements** from the
selected hosted environment so optional installed dependencies such as boto3 remain
available. Dependency/Python changes still need separate review. Stop on failures;
do not remove constraints to bypass them.

The scripts pause before upload, service interruption, switching and activation.
Backups use the application's own passphrase prompt; the wizard does not capture
or save secrets. Only selections are remembered in the Mac's
`~/Library/Application Support/EPM/release-wizard/mac.env` and the VM's
`~/.local/state/epm-release-wizard/vm.env`; these files are read as values, never
executed. Subject approval is explicit and is not saved as a wizard default.
Root-private deployment/rollback records live under the new release's
`wizard-state/` directory; failed commands never trigger automatic rollback,
repeated uploads or automatic reactivation. Rejected browser acceptance explicitly
disables and stops the instance. Repeating `install` can continue an interrupted
extraction only when every file exactly matches the independently verified archive,
no virtual environment exists, and neither hosted service selects that release.
Otherwise use a new release ID; `resume` applies only after a successful deployment
backup and override switch.

If an older uploaded wizard fails at `cd: /opt/epm/releases/...: Permission denied`,
the archive may have restored the Mac bundle directory's private `0700` mode.
The corrected wizard performs the checksum-directory change as root, then sets
the new release's service-readable permissions. Transfer the corrected standalone
VM script under the same release-specific filename and choose `install` again;
the narrow retry checks above apply. Do not loosen permissions on workspace data
or run the entire wizard as root. The release archive itself remains unchanged.

Ordinary Deploy never initializes or replaces workspace data. Only the explicit
fresh-demo actions restore new synthetic data and create new access administration.
No action migrates existing records, deletes old releases/workspaces, publishes
backups to R2 or extends expiry dates. Use the recovery procedures below for
off-host publication. Record final acceptance and release details in the deployment
record. Run only one VM wizard for an instance at a time. Manual equivalents follow.

### Fresh demo after an incompatible schema change

1. On the Mac, choose a new release ID and answer **yes** to preparing fresh-demo
   archives. Each instance is seeded and verified independently using that source.
   Enter an archive passphrase in the application's own prompt for each export;
   retain it privately for restore. Archives and matching descriptors stay in the
   printed external temporary preparation directories and upload from there;
   they must not be exported into the repository's `application/dist/` directory.
   Preparation directories are left intact. Live local workspace/configuration is unchanged.
2. Save the release checksum and both demo checksums printed at handoff, then run
   the uploaded VM wizard and choose **install** once. A release built before this
   helper existed cannot gain reset support merely by replacing its VM script;
   build a new complete release bundle.
3. Run **reset-demo**, select **A**, and supply A's independent Mac demo checksum.
   Confirm that A's existing edits will stay in the preserved old workspace and
   backup; they will not transfer to the fresh synthetic demo.
4. The wizard records a root-private checkpoint, disables access, stops the old
   writer, and creates/validates its backup with the old compatible release. Enter
   the **old demo backup passphrase** at this prompt. A completed backup found on
   retry is validated rather than recreated.
5. It checks the existing qualified storage volume and free space, then restores
   the new archive into a separate directory on that volume. Enter **A's fresh
   archive passphrase from the Mac**. Restore performs current-schema and retained
   data validation. A UUID mismatch, insufficient capacity, malformed archive or
   failed validation stops the reset with old data intact. No volume is resized.
6. A separate access database is initialized and fenced with a fresh-proof cutoff.
   While stopped, the wizard replaces the locator, hosted binding and release
   override using complete-file atomic writes and a resumable journal. Hostname,
   email, capabilities and expiry stay unchanged. Existing recovery configuration,
   when present, is rebound to a separate new-workspace ledger; credentials and
   old recovery points remain unchanged, and no point is uploaded or pruned.
7. On the Mac, open A's assigned `/sign-in`, renew Cloudflare sign-in, and click
   **Continue to workspace** to request enrollment. In the VM wizard, review the
   enrollment and approve the intended subject. Old sessions are not restored.
   Complete the browser record, attachment and save/refresh checks and record any
   NOT TESTED limitations before accepting A. Then repeat **reset-demo B**.

If interrupted, select **resume-reset** with the same release, instance and printed
checkpoint directory. Invalid/unreadable checkpoint metadata stops the workflow;
it is never interpreted as permission to repeat a step. No automatic activation,
rollback or old-data deletion occurs. Rejecting browser acceptance explicitly
disables and stops the instance. Use **rollback-reset** to restore the preserved
old binding/runtime and complete fresh sign-in and browser acceptance; both
datasets, access stores, recovery ledgers and backups remain retained.
Changes made in the new demo remain there after rollback; nothing merges them.

### Wizard verification

From `application/`, run
`node scripts/python.mjs -m pytest scripts/tests/test_release_wizards.py scripts/tests/test_release_demo.py demo/test_demo.py -q`.
Tests use temporary roots and mocked systemd/ownership boundaries. The reset
integration test also generates separate A/B demo fixtures, exports real encrypted
archives, and restores them with production validators. No live workspace or VM
service is used.

| Area | Automated checks / remaining operator proof |
| --- | --- |
| Happy path and inputs | Shell syntax/help, release IDs, A/B paths/ports, effective commands, descriptor/source binding and distinct reset UUIDs |
| Invalid combinations | Wrong-instance configuration/archives, local-only CLI, altered configuration snapshots, corrupt metadata, unsafe archive entries and identity reuse are rejected |
| Retry and failure | Stopped `failed` requires PID zero; transient restarts are rejected; missing versus unreadable checkpoints differ; backup/restore/init retry guards and interrupted configuration switching are tested |
| Rollback | Old configuration and recovery binding are restored exactly without deleting either dataset; rejected acceptance fences/stops; real Linux cutover still needs host acceptance |
| Backup/restore | Real seeded A/B encrypted export/restore preserves domain rows and distinct UUIDs; off-host read-back and recovery of actual hosted backups remain administrator checks |
| Persistence/authority | Current schema validates restored workspaces; fresh access requires enrollment/approval and fresh proof; old sessions are rejected; expiry/capabilities remain unchanged |
| Query budgets | Not applicable to these operational scripts; they add no domain projections |

Script syntax and focused guards are not evidence of a successful VM cutover,
real Cloudflare renewal or physical Linux quota behavior. Local encrypted fixture
round trips are not proof of the VM's current recovery point. Record host results
only after the corresponding operator checks pass.

## Routine operation

Connect from the **Mac**:

```bash
gcloud compute ssh epm-demo \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b --tunnel-through-iap
```

Inside the **VM**, inspect services and recent errors:

```bash
sudo systemctl status epm-hosted@a.service epm-hosted@b.service epm-cloudflared.service --no-pager
sudo journalctl -u epm-hosted@a.service -u epm-hosted@b.service --since '1 hour ago' --no-pager
df -h / /var/lib/epm-a/volume /var/lib/epm-b/volume
free -h
```

| Task | Procedure |
| --- | --- |
| Daily backup | [Daily manual recovery points](HOSTED_DEMO_OPERATIONS.md#daily-manual-recovery-points): fence access, stop the owning service, create/validate an encrypted archive, restart, then publish and verify off-host recovery |
| Restart an unchanged instance | Save/reconcile operator work, then `sudo systemctl restart epm-hosted@a.service`; check status, logs and browser access; repeat separately for B if needed |
| Restart after a VM reboot | First verify both workspace mounts and hosted services using [Routine inspection](HOSTED_DEMO_OPERATIONS.md#routine-inspection); check tunnel status explicitly—it is recorded as disabled at boot |
| Sign-in, expiry, enrollment or access changes | [Configuration contract](../deployment/HOSTED_DEMO_CONFIGURATION.md) and [disable/renew/reset](HOSTED_DEMO_OPERATIONS.md#disable-renew-reset-and-rollback) |
| Missing data, integrity failures or host loss | Keep affected access fenced; follow [recovery](HOSTED_DEMO_OPERATIONS.md#administrator-recovery-bundle-and-host-loss) rather than initializing or editing SQLite |
| Billing and capacity | Review disk headroom, recovery age and actual provider charges; see [funded operation](HOSTED_DEMO_OPERATIONS.md#billing-and-funded-operation) |

## 1. Build and bundle on the Mac

Start from the repository root with the intended changes committed. Use a new
release identifier for every build; the package version alone is not unique.

```bash
git status --short
git rev-parse HEAD
./application/scripts/build_wheel.sh
```

Stop if the checkout contains unintended changes or the build fails. The script
checks frontend quality and packages the compiled SPA; it does not run the whole
test suite. Run the focused tests appropriate to the release and record results.

Still at the repository root, set a **new** identifier and assemble a fresh bundle:

```bash
release=release-YYYYMMDD-NN
bundle="$PWD/application/dist/$release"
mkdir "$bundle"
mkdir -p "$bundle/schema-resources/database"
cp application/dist/easy_property_management-0.1.0-py3-none-any.whl "$bundle/"
cp application/alembic.ini "$bundle/schema-resources/"
cp -R application/database/sqlite-migrations "$bundle/schema-resources/database/"
cp application/scripts/stage_schema_resources.py application/scripts/verify_installation.py "$bundle/"
git rev-parse HEAD > "$bundle/SOURCE_COMMIT.txt"
```

Substitute the actual wheel filename if its version changes. Include only the
matching source resources; exclude Python caches and macOS metadata from the transfer:

```bash
cd "$bundle"
find . -type f ! -path '*/__pycache__/*' ! -name '*.pyc' \
  ! -name '._*' ! -name '.DS_Store' ! -name SHA256SUMS \
  -exec shasum -a 256 {} \; > SHA256SUMS
COPYFILE_DISABLE=1 tar --disable-copyfile --exclude='._*' --exclude='.DS_Store' \
  --exclude='__pycache__' --exclude='*.pyc' -czf "../$release.tar.gz" .
shasum -a 256 "../$release.tar.gz"
```

Keep the archive hash, source commit and test results in your release record.
Never bundle workspace data, configuration, credentials or a Mac virtual environment.
The Mac-specific `--disable-copyfile` prevents tar from generating AppleDouble
`._` sidecars for extended attributes. A sidecar named `._0001_initial_schema.py`
is binary metadata, but Alembic tries to load it as Python and reports
`source code string cannot contain null bytes`.

## 2. Upload from the Mac

From the bundle directory used above:

```bash
gcloud compute scp "../$release.tar.gz" epm-demo: \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b --tunnel-through-iap
```

Connect using the SSH command above. The remaining commands run on the **VM**.

## 3. Install beside the current release

Inspect the effective commands; per-instance overrides can differ from the shared
unit template. Record each instance's current release and full command for rollback.

```bash
sudo systemctl show epm-hosted@a.service epm-hosted@b.service -p ExecStart
sudo systemctl cat epm-hosted@a.service epm-hosted@b.service
```

Set these variables explicitly. `previous` must be an installed, qualified release
with the intended Python patch and dependency set, not a guessed path:

```bash
release=release-YYYYMMDD-NN
previous=/opt/epm/releases/ACTUAL_CURRENT_RELEASE
next="/opt/epm/releases/$release"
sha256sum "$HOME/$release.tar.gz"
```

Check that `previous` matches A's effective `ExecStart`, including any drop-ins;
do not select the retained local-only `demo-001` environment. Confirm its CLI
before using it for backup:

```bash
printf 'Previous release: %s\n' "$previous"
"$previous/venv/bin/python" -m app --help
```

The commands must include `hosted-backup`, `hosted-admin` and
`validate-hosted-config`. If they do not, stop and compare the interpreter with
`systemctl show ... -p ExecStart` above. Check `PYTHONPATH`/`PYTHONHOME` and the
imported `app` location if the interpreter matches but loads the wrong package;
do not substitute the local `backup` command for hosted recovery. If A and B use
different releases, record and use each instance's own previous interpreter.

Compare the archive hash with the Mac's value before extraction. Use an unused
release directory; stop on any failed command:

```bash
sudo mkdir "$next"
sudo tar -xzf "$HOME/$release.tar.gz" -C "$next"
cd "$next"
sudo sha256sum --check SHA256SUMS
sudo chmod -R u=rwX,go=rX "$next"
sudo "$previous/venv/bin/python" -m pip freeze --exclude easy-property-management \
  | sudo tee "$next/constraints.txt" > /dev/null
sudo "$previous/venv/bin/python" -m venv "$next/venv"
sudo "$next/venv/bin/python" -m pip install --requirement "$next/constraints.txt" \
  --constraint "$next/constraints.txt" \
  "$next/easy_property_management-0.1.0-py3-none-any.whl"
sudo "$next/venv/bin/python" -m pip check
sudo "$next/venv/bin/python" "$next/stage_schema_resources.py" "$next/schema-resources"
sudo "$next/venv/bin/python" "$next/verify_installation.py"
```

This reuses the installed Linux Python and pins existing dependencies. If a release
needs different dependencies or Python, qualify those deliberately using the
[installation guide](../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md#2-build-and-install-a-reproducible-release);
do not discard constraints just to get pip to succeed. Keep code root-owned and
service-readable; configuration and data retain their existing private permissions.

### If installation verification reports null bytes

Do not switch services. On the VM, inspect the new release's schema copies for
macOS sidecars (the staging script reports the installed root, currently `venv/lib`):

```bash
sudo find "$next/schema-resources" "$next/venv/lib/database/sqlite-migrations" \
  -type f -name '._*' -print
```

If those are the unwanted metadata files, remove only these sidecars and retry:

```bash
sudo find "$next/schema-resources" "$next/venv/lib/database/sqlite-migrations" \
  -type f -name '._*' -delete
sudo "$next/venv/bin/python" "$next/verify_installation.py"
```

This does not touch the running release, configuration or workspace. Record the
removed paths in the release evidence. Rebuild a clean archive with a new release
identifier using step 1 before treating it as a reproducible distributable; do not
overwrite the original checksum record. If no sidecars exist or verification still
fails, obtain the traceback to identify the damaged source file:

```bash
sudo "$next/venv/bin/python" -c \
  'from app.platform.product_migrations import current_revision; print(current_revision())'
```

Do not strip null bytes from actual source files or bypass installation validation.

## 4. Protect and validate one instance

Deploy **A first**, then repeat for B after acceptance. Ask the operator to save
and reconcile work. Using `previous` from step 3, explicitly disable access and
stop the owning writer:

```bash
sudo -u epm-a env TMPDIR=/var/lib/epm-a/volume/tmp \
  "$previous/venv/bin/python" -m app --config /var/lib/epm-a/hosted-local.json \
  hosted-admin /etc/epm/hosted-a.json disable
sudo systemctl stop epm-hosted@a.service
sudo systemctl is-active epm-hosted@a.service
```

The last command must report `inactive` (its nonzero exit is expected). If it
reports `active` or `deactivating`, do not proceed to backup or validation.

Create the pre-release backup using the existing service-private backup/staging
directories and a new output filename. See the [manual recovery-point procedure](HOSTED_DEMO_OPERATIONS.md#daily-manual-recovery-points)
for directory preparation, passphrase custody and verified off-host publication.

```bash
sudo -u epm-a env TMPDIR=/var/lib/epm-a/volume/tmp \
  "$previous/venv/bin/python" -m app --config /var/lib/epm-a/hosted-local.json \
  hosted-backup /etc/epm/hosted-a.json \
  --output "/var/backups/epm-a/before-$release.epm-backup" \
  --staging-directory /var/backups/epm-a/staging
```

Enter the backup passphrase at the prompt. Stop if backup fails; do not overwrite
an existing archive on retry. Keep A stopped during the following checks and
through switching. Preserve the successful backup and the previous release.

```bash
sudo -u epm-a env TMPDIR=/var/lib/epm-a/volume/tmp \
  "$next/venv/bin/python" -m app --config /var/lib/epm-a/hosted-local.json workspace-status
sudo -u epm-a env TMPDIR=/var/lib/epm-a/volume/tmp \
  "$next/venv/bin/python" -m app --config /var/lib/epm-a/hosted-local.json \
  validate-hosted-config /etc/epm/hosted-a.json
```

If workspace or hosted validation fails, stop. This greenfield project has no compatibility
migration procedure: do not initialize, rewrite or reset existing records to make
a new release fit. Use the separate reviewed restore/reset procedure if needed.

After A passes acceptance, repeat step 4 for B. Set `previous` to the release recorded
for B in step 3; keep the same `$release` and `$next` values:

```bash
sudo -u epm-b env TMPDIR=/var/lib/epm-b/volume/tmp \
  "$previous/venv/bin/python" -m app --config /var/lib/epm-b/hosted-local.json \
  hosted-admin /etc/epm/hosted-b.json disable
sudo systemctl stop epm-hosted@b.service
sudo systemctl is-active epm-hosted@b.service

sudo -u epm-b env TMPDIR=/var/lib/epm-b/volume/tmp \
  "$previous/venv/bin/python" -m app --config /var/lib/epm-b/hosted-local.json \
  hosted-backup /etc/epm/hosted-b.json \
  --output "/var/backups/epm-b/before-$release.epm-backup" \
  --staging-directory /var/backups/epm-b/staging

sudo -u epm-b env TMPDIR=/var/lib/epm-b/volume/tmp \
  "$next/venv/bin/python" -m app --config /var/lib/epm-b/hosted-local.json workspace-status
sudo -u epm-b env TMPDIR=/var/lib/epm-b/volume/tmp \
  "$next/venv/bin/python" -m app --config /var/lib/epm-b/hosted-local.json \
  validate-hosted-config /etc/epm/hosted-b.json
```

The `is-active` command must report `inactive`; its nonzero exit is expected. Enter
the backup passphrase at the prompt. Stop if backup or either validation fails.

## 5. Switch, then verify

Before editing, preserve any existing `90-release.conf` in the new release's
rollback records; record if it was absent. Keep all other drop-ins unchanged.

```bash
sudo mkdir -p /etc/systemd/system/epm-hosted@a.service.d
sudoedit /etc/systemd/system/epm-hosted@a.service.d/90-release.conf
```

Use the **actual new release path** in this override:

```ini
[Service]
ExecStart=
ExecStart=/opt/epm/releases/RELEASE/venv/bin/python -m app --config /var/lib/epm-a/hosted-local.json serve-hosted --deployment /etc/epm/hosted-a.json --port 8001
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemd-analyze verify epm-hosted@a.service
sudo systemctl show epm-hosted@a.service -p ExecStart
sudo systemctl start epm-hosted@a.service
sudo systemctl status epm-hosted@a.service --no-pager
sudo journalctl -u epm-hosted@a.service --since '5 minutes ago' --no-pager
```

Confirm effective `ExecStart` uses the new release and existing hosted configuration.
Run the [private boundary probes](HOSTED_DEMO_OPERATIONS.md#routine-inspection), then
explicitly reactivate only the eligible intended subject using the existing admin
procedure. Sign in afresh at `https://demo-a.epmdemo.xyz` and check:

- Home, Properties, Money and Settings load; existing records and evidence open.
- An approved harmless change saves, survives refresh and appears in History.
- An unavailable read is shown as unavailable, not a zero or empty result.
- B remains usable and cannot access A's records.

Repeat steps 4–5 for B using `epm-b`, `hosted-b.json`, its local configuration,
`epm-hosted@b.service`, port `8002` and `https://demo-b.epmdemo.xyz`. Keep the
per-instance previous command/override so either instance can be rolled back.
Do not change Cloudflare routing, ports, mounts or enrollment bindings for a code-only release.

For B, run these commands on the VM after B passes step 4. Preserve any existing
B release drop-in in its rollback records before editing:

```bash
sudo mkdir -p /etc/systemd/system/epm-hosted@b.service.d
sudoedit /etc/systemd/system/epm-hosted@b.service.d/90-release.conf
```

Enter the actual `$next` release path in the override (replace `RELEASE`):

```ini
[Service]
ExecStart=
ExecStart=/opt/epm/releases/RELEASE/venv/bin/python -m app --config /var/lib/epm-b/hosted-local.json serve-hosted --deployment /etc/epm/hosted-b.json --port 8002
```

Then run:

```bash
sudo systemctl daemon-reload
sudo systemd-analyze verify epm-hosted@b.service
sudo systemctl show epm-hosted@b.service -p ExecStart
sudo systemctl start epm-hosted@b.service
sudo systemctl status epm-hosted@b.service --no-pager
sudo journalctl -u epm-hosted@b.service --since '5 minutes ago' --no-pager
```

If an older release's **Renew Cloudflare sign-in** returns a 403 at
`/?__cf_access_message=logged_out`, navigate directly to the assigned origin's
`/sign-in` and continue explicitly. The corrected hosted middleware redirects that
exact public HTML navigation to `/sign-in`; session creation and business requests
still require their normal origin and identity checks. Include the middleware fix
in the next release and verify renewal through the real Cloudflare flow after deployment.

## 6. Record the result or roll back

Append one dated entry to the [deployment record](CLOUDFLARE_OPERATIONS.md): source
commit, archive/wheel hashes, Python/dependencies, old/new release paths, instance
switches, recovery-point references, checks and remaining limitations. Update its
current-release inventory and the qualification register only to match actual evidence.
Retain previous releases and verified backups until acceptance and retention review.

If acceptance fails, fence the affected instance and stop its new writer. Restore
the saved `90-release.conf`, or remove **only that new drop-in** if it was absent
before. Reload systemd, check the effective command and start the previous release
only if it still accepts the current data. Recheck private and public access before
reactivating an eligible subject. Do not use `systemctl revert`, which would remove
unrelated instance overrides. If data is incompatible, leave access fenced and
[restore the appropriate backup into a separate destination](HOSTED_DEMO_OPERATIONS.md#disable-renew-reset-and-rollback).
