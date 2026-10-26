# Google Cloud: operate and update the existing host

Use this after setup. It covers the recorded `epm-demo` VM in `us-west1-b`, project
`project-47b72bb7-ba90-42c9-910`, with hosted instances A and B. Confirm the actual
inventory in the [deployment record](CLOUDFLARE_OPERATIONS.md) before proceeding.
These instructions were checked against repository commands; this document does
not claim a new release has been deployed or tested on the VM.

For ordinary inspection, backups and recovery, use the shortcuts below. For a
code update, follow steps 1–6. Do not repeat VM, Cloudflare, enrollment or workspace
initialization. The wheel **and matching schema resources** form the release.

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
sudo "$next/venv/bin/python" -m pip install --constraint "$next/constraints.txt" \
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
