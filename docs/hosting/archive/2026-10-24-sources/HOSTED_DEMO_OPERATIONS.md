# Hosted demo operations and qualification — Slice 7

For the dashboard setup, private credential handoff and actual R2 activity, see
the [Cloudflare operations log for October 23](CLOUDFLARE_OPERATIONS.md#october-23-2026).

Latest deployment state: see the [current checkpoint](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md#resume-checkpoint--october-24-2026). A/B hosted services now run on bounded volumes; provisional Access-protected routes are active for acceptance, with operators inactive and the tunnel disabled at boot. The following October 23 deployment narrative is historical; use the checkpoint for what remains.

Source runbook, October 23, 2026. These commands require a newly built, tested
release; they do not upgrade A/B's installed `demo-001`. The approved third-workspace
[Linux quota drill](../../qualification/reports/HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md),
[actual R2 recovery](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md), and
[installed-release/approved boot checks](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md)
have passed within their recorded scratch scope. A/B returned on their unchanged
private configurations after the approved reboot. The original scratch volume is
persistently mounted with its hosted application stopped; the second recovery
image remains detached. Only synthetic encrypted objects were added to R2.

The subsequent [systemd/physical upload drill](../../qualification/reports/HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md)
also passed on scratch after fixing retained body-spool overlap. Its temporary
units are stopped. Final wheel/env-file startup, persistent scratch mount/reboot
and off-host recovery now pass; A/B deployment and remaining failure/reset/rollback
qualification are still release gates.
Keep invitations and tunnel routes blocked meanwhile. See the
[public-access plan](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) for scope and release gates.

## Physical storage and launch contract

Create the root-owned **code** environment with an installation umask such as
`022`, so the service account can traverse directories and execute/read the
runtime. Check interpreter/import access as that account before starting its
unit. Keep workspace data, administrative state and credential files private
with `077`; do not recursively relax those paths. The installed scratch drill
initially caught an inaccessible interpreter caused by applying `077` to code.

Each workspace uses a separate **fully allocated 250 MiB ext4 loop image**. The
kernel bounds the combined database, WAL/journals, evidence, temporary uploads and
staging, rather than relying on a directory-size estimate. The service cannot
resize/read the root-owned backing image. Filesystem metadata and reserved space
reduce usable capacity: 250 MiB is the physical ceiling, not a promise of 250 MiB
of attachments. The existing 50 MiB per-file limit is unchanged.

Provisioning requirements, to be executed by the administrator on Linux:

- Root-owned, non-symlink image directory `/var/lib/epm-volumes`, not writable by
  services. Mode `0711` permits services to stat their pinned image without listing
  other images. Each image is root-owned `0600`, exactly `262144000` bytes and
  fully allocated (not sparse). Check host free disk before allocation.
- Format a **new image only** as ext4, with 10% root-reserved blocks, discard and
  deferred initialization disabled
  (`mkfs.ext4 -m 10 -E nodiscard,lazy_itable_init=0,lazy_journal_init=0`).
  Recheck allocation after formatting **and again after first mount and workspace
  initialization**. The real drill found that `nodiscard` alone did not preserve
  allocation through first mount. Never format
  an existing image or operator data. Mount the complete filesystem at
  `/var/lib/epm-a/volume` using `rw,nodev,nosuid,noexec`; not a bind mount. Root
  owns the underlying unmounted mountpoint and protects its parent chain. Use one loop mapping per image, with
  `losetup --find --show --nooverlap` and serialized administrator provisioning.
  Record the exact device/image mapping and persistent mount configuration.
- After mounting, make the mounted filesystem root service-owned `0700` so the
  owner can create the sibling `.workspace.server.lock`; the root-owned image
  remains inaccessible and non-resizable. Inside it, create service-owned `0700`
  `workspace/` and `tmp/`. Set both the
  environment `TMPDIR` and Python's effective temporary directory to
  `/var/lib/epm-a/volume/tmp`. Do not use shared `/tmp` restore locks.
- Keep `/var/lib/epm-a/access/` service-owned `0700` **outside** the volume for
  bounded administrative session state. Keep encrypted backup outputs/staging
  outside the volume too, private to the account running each operation.
- Repeat independently for B. Check mount persistence through a reboot before
  treating this as qualified storage. An absent mount or changed device/image
  fails application startup; do not bypass validation.

Do not enable mount-time discard or run TRIM against the reserved images. For
persistent mounts, include `X-fstrim.notrim` and verify the host's actual TRIM
job uses an fstab/listed-in mode that honors it; do not assume every invocation
does. Do not disable host-wide TRIM merely to exclude these volumes. See
[mke2fs options](https://man7.org/linux/man-pages/man8/mke2fs.8.html) and
[fstrim exclusions](https://man7.org/linux/man-pages/man8/fstrim.8.html).

If an **explicitly verified new scratch image** has allocation holes after initial
setup, root may re-reserve them with `fallocate --keep-size --length 262144000`
against that exact pinned image, after checking its length/mapping and host free
space. This preserves data and length; it is not permission to resize/reformat an
operator image. Recheck allocation and rerun validation. This correction passed
the recorded physical drill. Corrected fresh formatting and explicit detach/remount
now pass the [new-image qualification](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md);
persistent mounts and reboot stability remain separate gates.

Root provisions these resources; the application performs no mount, allocation or
resize. Validate image allocation, exact block-device size, backing-file identity,
mount flags, same-device workspace/temp directories, and at least 16 MiB of
root-only reserved space. The implementation inspects these properties at startup
and rechecks device/size/free-space facts per protected business request.
Linux distinguishes privileged free blocks from blocks available to an ordinary
user; the adapter uses the latter for admission. See
[statvfs](https://man7.org/linux/man-pages/man3/statvfs.3.html),
[ext4 administration](https://docs.kernel.org/admin-guide/ext4.html) and
[loop-device overlap precautions](https://man7.org/linux/man-pages/man8/losetup.8.html).

Request reservations include 16 MiB write headroom (1 MiB for reads, which can
audit) plus three times admitted body bytes for spooling, owning multipart staging
and immutable publication. In-flight reservations are serialized and already
allocated bytes remain counted conservatively. Unknown unsafe body lengths reserve
the maximum; bytes exceeding the admitted length are rejected. At host disk use
of 80%, requests log a rate-bounded administrator warning; at 89%, new business
writes return typed maintenance `503`. Quota admission returns typed `507`.
These are not guarantees that every admitted write succeeds: actual database
growth is bounded by the filesystem, and the real FULL/rollback drill is required.
Session/logout controls remain available outside business quota accounting.
The complete body spool is closed on its last replay chunk before owning handler
publication; otherwise the parser/handler/publication could overlap four copies.
Raw or explicitly wrapped storage-full errno failures are typed even after cleanup
restores free space. Original-result reads may require an explicit later retry
while an earlier request's conservative reservation is still unwinding; never
resubmit a consequential command under a new key to compensate.

## Prepare a release and switch privately

Current A/B installation (October 24): `qual-c8aab474` is running privately under
`epm-hosted@a.service` / `epm-hosted@b.service`, with original units masked.
The installed template uses `hosted-local.json`; the source template's default
`config.json` argument was changed in the reviewed deployment copy to preserve
the original private locators for fallback. Use the hosted locator in commands
below. See the [switch evidence](../../evidence/HOSTED_DEMO_PRIVATE_SWITCH_2026-10-24.json).
Public routing and operator activation remain pending.

1. Record the source revision, wheel/frontend/schema checksums, Python patch,
   dependency lock, local installation verification and focused test results.
   Build from current source; this latest-format work is not a migration of the
   earlier private VM installation.
2. Stop/fence the old writer. Preserve a complete validated encrypted recovery
   point. Restore a compatible current-schema synthetic archive into a **new,
   empty private** destination on the prepared volume; do not copy live SQLite
   or overwrite a live workspace. Use a separate bootstrap configuration whose
   live-workspace path is not the restore destination, as in the
   [Google Cloud runbook](../../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md).
3. Pin the new workspace path in the local config and use the
   [protected deployment JSON](../../deployment/HOSTED_DEMO_CONFIGURATION.md), including the
   volume, image, exact workspace UUID and external access database. Validate
   workspace/configuration and initialize the administrative store explicitly.
4. Install a reviewed copy of
   `application/deploy/hosted-demo/epm-hosted@.service`. Replace `HOSTED_RELEASE`
   with the exact qualified root-owned release. Set `/etc/epm/hosted-a.env` to
   `EPM_PORT=8001`, B to `8002`; root-owned, service-readable, not writable.
   Validate the unit on Linux with `systemd-analyze verify`. Mask the prior
   `epm@a.service`/`epm@b.service` before switching, one instance at a time.
5. Start only the hosted owner. The template conflicts with the old service,
   requires the mount, preserves resource limits and confines writable paths to
   the volume/access directory. It always binds loopback, disables forwarded
   proxy-header trust and runs one writer. Keep public application ports closed.

The explicit command, with the service account's correct `TMPDIR`, is:

```bash
sudo -u epm-a env TMPDIR=/var/lib/epm-a/volume/tmp \
  /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  serve-hosted --deployment /etc/epm/hosted-a.json --port 8001
```

Use systemd for supervision, not both this foreground command and a service.
There is no public bind override or local-policy fallback. Qualify the unit's
mount/sysfs access under its actual sandbox before deployment. Ordinary local
`serve` remains loopback-only and does not require hosted infrastructure.

## Daily manual recovery points

The project administrator owns execution, passphrase custody, alert checks and
recovery. These are **manual**, not an unattended cron/keyring integration. Stagger
A and B; watch the other workspace during maintenance. Prepare service-private
external archive and staging directories with host disk headroom.

For A, disable access using `hosted-admin ... disable`, drain/stop
`epm-hosted@a.service`, and keep it stopped during the complete backup:

```bash
sudo -u epm-a env TMPDIR=/var/lib/epm-a/volume/tmp \
  /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-backup /etc/epm/hosted-a.json \
  --output /var/backups/epm-a/DAILY.epm-backup \
  --staging-directory /var/backups/epm-a/staging
```

Choose a new dated output. Enter the existing backup passphrase interactively.
The command holds the same lifetime writer lock as the server, creates a complete
application archive, runs owning archive/retained-data validators, checks its UUID
and permits a final backup after demo expiry. It refuses an active writer. External
archive staging does not move live DB/WAL or ordinary upload staging outside quota.
After successful checks, restart the service; explicitly reactivate the intended
subject only if still eligible. Fresh identity proof/session is required after
disablement. A failed backup is not a new recovery point.
If exhausted storage prevents the final backup/audit, leave access fenced and
retain the previous verified point. Use the qualified recovery procedure on a new
volume; do not bypass admission, delete immutable evidence, or mutate SQLite by hand.

The administrator owns a private R2 Standard bucket and a dedicated bucket-scoped
credential with only the required read/write/delete permissions. Never select
R2 as the live File provider, enable public bucket access, or give these credentials
to the application users. Create root-owned `0600` `/etc/epm/recovery-a.json` under
root-protected parents; this example contains placeholders, not credentials:

```json
{
  "deployment_id": "00000000-0000-4000-8000-000000000010",
  "workspace_id": "0efb09a0-5af2-4e6f-904f-154a50ab9445",
  "endpoint": "https://ACCOUNT_ID_32_HEX.r2.cloudflarestorage.com",
  "bucket": "epm-private-recovery",
  "access_key_id": "REPLACE_PRIVATELY",
  "secret_access_key": "REPLACE_PRIVATELY",
  "ledger_path": "/var/lib/epm-recovery/a/ledger.json"
}
```

Use a new deployment UUID and the exact business UUID. The ledger directory and
administrator staging directory must exist, root-owned `0700`, outside the checkout
and all workspaces/volumes, with protected non-symlink root-owned parents.
The endpoint requires the real 32-hex account ID. The qualified release must include
its boto3 dependency. As root, using the appropriate local configuration:

```bash
sudo /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-publish-backup /etc/epm/hosted-a.json /etc/epm/recovery-a.json \
  /var/backups/epm-a/DAILY.epm-backup \
  --staging-directory /var/lib/epm-recovery/a/staging

sudo /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-recovery-status /etc/epm/recovery-a.json
```

Publication makes a bounded administrator-private copy, revalidates the complete
archive and workspace identity, uploads under `epm/<deployment>/<workspace>/`, then
downloads the entire object and verifies SHA-256/size. No ETag shortcut. The durable
verification ledger is saved **before** any pruning. Retention keeps the latest
successful snapshot from each of the latest seven UTC days; same-day retries do not
count as extra days. Failed upload/read-back/ledger persistence never authorizes
pruning the prior point. Prune failure reports `retentionPending`; repair/retry
explicitly. An older seed cannot replace a newer verified point.

Status reports age from the archive's creation time, not upload time; re-uploading
an old archive does not refresh recovery. Status does not contact R2, so it is not
proof of continued remote availability. A missing/stale (>24 hour) point or pending
retention needs administrator attention. Record the actual verified snapshot time;
do not keep promising at most 24 hours of lost edits when the schedule has failed.
Keep failed/new local archives until reviewed. Budget actual stored bytes and full
read-back operations; bucket allowances are shared. See the
[R2 S3 API contract](https://developers.cloudflare.com/r2/api/s3/api/).

## Administrator recovery bundle and host loss

Export a separate encrypted reference bundle as the owning service user into a
private external folder, while the administrative store is available:

```bash
sudo -u epm-a /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-recovery-bundle /etc/epm/hosted-a.json \
  --output /var/backups/epm-a/hosted-reference.enc
```

Use a separate password-manager passphrase. This uses production-strength scrypt
and authenticated encryption. Copy the encrypted bundle off-host separately and
verify recovery; never upload its decrypted contents. It includes protected
deployment configuration and approved/pending subject **references**, not sessions,
token hashes, leases, Access assertions or R2/provider credentials. Preserve the
local workspace configuration/path mapping and release record separately in the
administrator's protected recovery records. Keep R2/Cloudflare credentials in the
administrator's secret store; the bundle is intentionally insufficient to restore
usable authority.

On host loss, retrieve a verified business archive and the bundle through the
administrator account. The following writes a **new private reference JSON only**;
it never initializes or approves a subject:

```bash
/opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /PRIVATE/NEW/restore-bootstrap.json \
  hosted-unpack-recovery-bundle hosted-reference.enc \
  --output /PRIVATE/NEW/hosted-reference.json
```

The CLI loads a local configuration before dispatching these commands. On a new
host, create the private bootstrap locator first, pointing `localWorkspacePath`
at a new unused external path; reference unpacking does not initialize it.

Reprovision the qualified volume/release. Restore the business archive using a
separate bootstrap config into a new private destination and external archive
staging. Validate all retained data, IDs, relationships, history, file bytes and
financial totals. Reconstruct protected configuration with correct new paths;
initialize a **fresh** administrative database, then verify/approve fresh
enrollment. Never restore live session/lease tables. Startup also fences a changed
restore marker. Keep public routes disabled until new sessions and isolation pass.

## Disable, renew, reset and rollback

- `hosted-admin ... disable` and `revoke` remain available after expiry or broken
  business storage. Confirm denial from an existing browser. Permanent removal
  also removes/revokes the provider's Access policy/session; app fencing is immediate.
- Renewal is an administrator change to protected dates (maximum 14-day window),
  followed by stopped-process validation/restart and explicit eligible activation.
  Never silently renew sessions or replay interrupted commands.
- Reset: disable, stop/drain, create/verify the final recovery point, prepare a new
  private synthetic workspace, validate it, then atomically replace protected path/
  identity configuration **while stopped**. A new UUID requires fresh administrative
  binding; a same-UUID restore still requires new runtime/enrollment/session authority.
  Do not overwrite a SQLite file or reuse authority to skip enrollment.
- Failed preparation leaves the old stopped data untouched. Keep explicit maintenance
  until either the new state passes or a compatible previous release/data pair is
  selected. Stop the new writer before rollback; never run both, downgrade an
  incompatible schema, or expose the old local server to bypass hosted checks.

## Required qualification and evidence record

Use a **third disposable Linux workspace**, never A/B, for destructive quota tests.
Provision the exact image/mount/account contract above and a strict synthetic
deployment (`allowed_email` ending `@example.invalid`). Create a private marker
`<volume>/.epm-destructive-qualification` containing exactly
`disposable synthetic quota qualification only`. As its unprivileged owner, with
correct `TMPDIR`, run from the tested release's source checkout:

```bash
EPM_TEST_HOSTED_QUOTA_DEPLOYMENT=/etc/epm/hosted-scratch.json \
EPM_TEST_HOSTED_QUOTA_LOCAL_CONFIG=/var/lib/epm-scratch/config.json \
  .venv/bin/python -m pytest \
  apps/server/app/modules/hosted_access/tests/test_linux_storage_qualification.py -q
```

This must run (not skip), reach real SQLite `FULL` under WAL/FULL durability,
retain the acknowledged row, roll back the attempted transaction, pass integrity
validation and retain root recovery blocks. Also exercise real concurrent uploads,
temporary spooling, typed HTTP failure and an original-result reconciliation after
an interrupted write. Synthetic `StorageFacts` tests do not qualify the kernel or
the systemd sandbox. Do not fill the VM's host filesystem: use a disposable
host/disk for the host-disk failure drill.

| Area | Required evidence before Slice 7 completion |
| --- | --- |
| Happy path | Both private hosted units, mounted volumes, correct identity and daily verified archive |
| Invalid combinations | Wrong image/size/mount/temp/config/UUID rejected; secrets inaccessible to app users |
| Retry/idempotency | Failed upload/read-back preserves old point; same-day retry and retention repair remain bounded |
| Rollback | Real FULL/upload/DB transaction failure retains acknowledged effects only; original key resolves uncertainty |
| Persistence | Reboot remounts exact images; one writer; expired/disabled sessions stay fenced |
| Backup/restore | Download from actual private R2, restore new destination, compare bytes/history/totals, fresh enrollment |
| Bounded work | Concurrent reservations serialize; session query budgets unchanged; no remote R2 work in requests |
| Faults | Auth-key/tunnel outage, full volume, host maintenance, failed reset, lost host and rollback have truthful states |

Record revision/build checksums, Python/dependencies/schema, host and paths,
workspace/operator bindings, actual trial expiry, maintenance owner/contact, disk
allocation/headroom, last archive timestamp/read-back/restore result, durations,
and each fault outcome. Keep secrets out. Current source tests pass only the
automatable local portions. The [real Linux SQLite FULL/rollback drill](../../qualification/reports/HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md)
also passed on the isolated scratch volume. Corrected clean formatting, bounded
restore and detach/remount now pass, alongside actual scratch R2 full read-back,
restore and encrypted reference recovery; see the
[recovery qualification](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md). Its sparse fixture
does not independently cover populated financial totals or multi-day retention
failures. Installed wheel/env-file startup and the authorized scratch boot mount
now also pass; see the [installed-release evidence](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md).
A/B deployment and remaining fault/reset/rollback evidence remain **pending**.
Only then proceed to Slice 8's Cloudflare/real-client,
caching, cost and latency qualification.
Template-equivalent systemd startup and real 50 MiB Intake/File concurrent admission,
receipt recovery and byte-hash checks are recorded in the
[subsequent evidence](../../qualification/reports/HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md); this is not a pass
for every endpoint, host-full case or remote identity flow.
