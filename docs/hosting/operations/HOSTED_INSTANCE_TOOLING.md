# Registered hosted instances and private maintenance

Slice 1 repository tooling. Installation, live A/B adoption and Linux acceptance must be recorded separately. This runbook does not qualify a third operator or authorize invitations. Use the [Admin design](../design/HOSTED_DEMO_ADMIN_DESIGN.md) for the later authority, UI, provisioning and capacity gates.

## Install once through the private administrator path

Requirements: the existing authenticated IAP administrator login, Linux with system Python 3.12 or newer, `systemctl`, `runuser`, `sudo`, and a reviewed release built by the Mac release wizard. There are no new Python dependencies. Keep the current services and tunnel configuration intact. No root provider credentials, passphrases or browser sessions are inputs to this installation.

The release bundle contains `admin-tools/`. During the first build, decline optional fresh-demo archives: their instance list cannot be fetched until adoption is complete. After setup, the Mac wizard obtains that list through the authenticated VM inventory command; it does not assume A/B. This remote read uses `sudo -n`, so the administrator's established private sudo policy must permit it; do not give that permission to operator Unix accounts.

On the VM, compare the archive SHA-256 with the independent value shown on the Mac. Use a new private administrator-owned extraction directory. For bootstrap, before the installed inventory wrapper exists, unpack without root privileges and validate the full release manifest:

```bash
EPM_RELEASE=release-YYYYMMDD-NN
EPM_ADMIN_STAGE="$(mktemp -d)"
/usr/bin/python3 -I - "$HOME/$EPM_RELEASE.tar.gz" "$EPM_ADMIN_STAGE" <<'CHECK'
from pathlib import PurePosixPath
import sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    members, names, total = [], set(), 0
    for member in archive:
        path = PurePosixPath(member.name)
        total += member.size
        if (path.is_absolute() or '..' in path.parts
                or not (member.isfile() or member.isdir())
                or str(path) in names or len(members) >= 5000
                or total > 1024 * 1024 * 1024):
            raise SystemExit('Unsafe or oversized release archive; stop.')
        names.add(str(path))
        members.append(member)
    archive.extractall(sys.argv[2], members=members, filter='data')
CHECK
(cd "$EPM_ADMIN_STAGE" && sha256sum --check SHA256SUMS)
```

Stop on an extraction, checksum or ownership error. Do not use this bootstrap sequence to bypass a populated, mismatched control store. If `/opt/epm/admin` already exists, first check maintenance status and retain the installed tooling; an upgrade is a reviewed private intervention, not a concurrent overwrite.

For the first installation only, after verification:

```bash
sudo test ! -L /opt/epm/admin
sudo install -d -o root -g root -m 0755 /opt/epm/admin
sudo install -o root -g root -m 0644 \
  "$EPM_ADMIN_STAGE/admin-tools/host_admin.py" \
  "$EPM_ADMIN_STAGE/admin-tools/host_inventory.py" \
  "$EPM_ADMIN_STAGE/admin-tools/release_cleanup.py" /opt/epm/admin/
sudo install -o root -g root -m 0755 \
  "$EPM_ADMIN_STAGE/admin-tools/epm-release-vm.sh" \
  "$EPM_ADMIN_STAGE/admin-tools/epm-release-cleanup-vm.sh" /opt/epm/admin/
sudo install -d -o root -g root -m 0700 /var/lib/epm-admin
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py init
```

`init` refuses to replace an existing inventory. Keep the private control store and `baselines/` outside all portable workspaces and workspace volumes. Do not copy access databases, usable sessions or provider credentials into it. The helper requires protected root-owned code and denies unprivileged CLI calls.

## Discover and explicitly adopt existing instances

```bash
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py discover
```

Discovery inspects installed and loaded units, disabled/stopped instances, runtime/vendor/configured drop-ins, retained instance directories, image/fstab references, exact effective commands, mount/backing identities, deployment/workspace/access bindings and release manifests. It also records effective service-file and installed Admin-tool digests, tunnel configuration identity and observed boot policy. It does not contact Cloudflare, certify Access protection, mount a volume, start a service or initialize a workspace.

The output contains private deployment facts; keep it in administrator records. For A, inspect `observed.a`, its configuration, workspace/operator identities, allocated port, resource profile and its **per-instance** `digest`. Review discrepancies instead of repairing populated paths automatically. Then use that digest:

```bash
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py adopt \
  --key a --observed-digest PER_INSTANCE_DIGEST --confirm
```

Repeat separately for B using B's facts and digest. The helper reads the facts again; a changed observation conflicts. Matching retries return the same instance/allocation IDs. Duplicate identities, email, hostname, port, user, paths or workspace allocations fail. Unknown/unreadable resources remain visible and block checked exports and ordinary maintenance. A stopped instance is not absent.

Adoption stores immutable, digest-addressed configuration observations and protects their selected releases. `checked_at` identifies when facts were read; the semantic digest excludes observation time so a reviewed unchanged observation can be submitted again. Historical acceptance and off-host recovery remain explicitly unverified. A configuration baseline can reconstruct recorded settings; it cannot restore business bytes or approved access by itself. Use verified encrypted business archives and separate binding references from the [recovery runbook](HOSTED_DEMO_OPERATIONS.md#daily-manual-recovery-points). Existing wizard checkpoints remain the authority for their recorded rollback procedure; missing checkpoints are not manufactured by adoption.

Read the registered, currently checked keys:

```bash
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py keys
```

No command provisions a fresh C, promotes capacity, publishes ingress or sends invitations. C coverage in this slice uses temporary test roots only.

## Run one admitted private operation

As the administrator login user, run the installed wizard without `sudo bash`:

```bash
bash /opt/epm/admin/epm-release-vm.sh
# Or, for installed-release cleanup:
bash /opt/epm/admin/epm-release-cleanup-vm.sh
```

The VM wizard supports inspection, install, deploy/resume/rollback, fresh-demo reset/resume/rollback, and `backup`. It lists registered keys and resolves their actual ports and configuration paths. It never derives a port from an instance letter. Select one instance and retain its printed maintenance ID and private checkpoint path.

Every mutating wizard runs beneath the same root-held host lock. The fixed child wizard inherits the lock descriptor so a disconnected wrapper cannot admit another operation while the child still holds it. Shell injection hooks and arbitrary caller environment are not forwarded. Operator processes do not receive an Admin listener or control-store authority. One host operation runs at a time; existing business writers continue unless their selected workflow explicitly fences/stops them. A failed command leaves a durable pending-reconciliation record, and failure recording does not replace the original execution exception.

`backup` first checks that the installed source supports external archive revalidation; an unsupported runtime is rejected before fencing. It then selects the registered instance, confirms its maintenance window, fences access, stops its writer, and creates one operation-specific encrypted archive plus an encrypted binding reference. Existing archive output is revalidated with external staging on retry. Staging is derived from the registered allocation; unsafe existing directory ownership/permissions and symlinks are rejected rather than silently changed. If recovery publication is configured, the existing publisher performs full read-back verification. Missing publication configuration is reported as unverified recovery. The encrypted reference still needs independent off-host verification under the recovery runbook. Restart, eligible identity approval and browser acceptance are explicit steps; backup/publication failures do not start or activate the instance.

Cleanup rechecks observed inventory and all release protections immediately before removal. Current and baseline releases, stopped-instance releases, recorded rollback/checkpoint references, running processes and standard configuration/job references remain protected. Keep an explicitly selected known-good rollback release for **each** registered instance. It never deletes workspaces, reservations, access stores, backups or baseline history.

## Resume or reconcile explicitly

Inspect the bounded recent maintenance records after a lost connection or lost result:

```bash
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py maintenance-status
```

To resume a recorded release operation, use its original ID and the appropriate supported action:

```bash
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py maintenance \
  --kind release --action resume --resume ORIGINAL_MAINTENANCE_ID
# Fresh-demo cutover: --action resume-reset
# Recovery archive retry: --action backup
# Cleanup retry: --kind cleanup --action cleanup
```

The expected action, kind, registered allocation and saved source checkpoints still apply. An unknown resource cannot be ignored during resume. Do not repeat a fresh reset or upload with a new identity to work around an unresolved outcome.

After the operation exits, inspect its source result/checkpoints, read `discover` again, and review the **top-level report** `digest` plus all observed changes. Explicitly reconcile that observed result:

```bash
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py reconcile \
  --maintenance-id ORIGINAL_MAINTENANCE_ID \
  --observed-digest REVIEWED_REPORT_DIGEST --confirm
```

This rechecks current facts, preserves allocation IDs, uses expected instance revisions and commits all inventory changes/audit together. Unmanaged, unverifiable, stale or unexpected authority/allocation changes block it. Reconciliation of a crashed holder is allowed only after acquiring its released lock; it observes an unknown exit and does not execute the old command. A reconciled inventory is not evidence of business acceptance or a new capacity qualification, and it does not grant a session.

Private root emergency containment remains available if normal tools cannot run. Record the incident in private operations history. For an out-of-band configuration/release/tooling repair with unchanged allocation and principal identities, review fresh discovery and record the intervention explicitly:

```bash
sudo /usr/bin/python3 -I /opt/epm/admin/host_admin.py record-breakglass \
  --incident PRIVATE_INCIDENT_REFERENCE \
  --observed-digest REVIEWED_REPORT_DIGEST --confirm
```

This records an observed intervention, not a fabricated pre-effect intent or successful job. It executes no repair and grants no authority. If maintenance already exists, reconcile that operation instead. Allocation/principal changes and incomplete observations still fail; restore the protected baseline or use the separately approved source-owned recovery procedure. Ordinary grants must not resume on an unexplained discrepancy. The system does not claim to prevent intentional root bypass.

## Focused validation and remaining host acceptance

| Area | Repository proof |
| --- | --- |
| Happy paths | Explicit temporary-root A/B/C adoption and reopen; C's nonstandard port used by reset, rollback and release protection; generic Mac/VM selections |
| Invalid combinations | Duplicate allocations; malformed/non-secret contract violations; symlinks/permissions; wrong service/mount/binding/release; unknown and unverifiable resources; unsupported CLI commands |
| Idempotency/retry | Stable adoption IDs; durable original maintenance ID; saved reset checkpoints; one backup output and external revalidation; explicit result lookup/reconciliation |
| Transaction rollback | Conflicting multi-instance reconciliation rolls back every row and leaves the operation pending; original execution failure survives journal failure |
| Persistence/schema | Current exact schema and trigger bodies; append-only audit and retained allocations; UTC retained timestamps; missing inventory/baselines fail closed |
| Backup/restore | Existing encrypted archive/reset validators and rollback tests remain in the focused set; private backup flow exercises staging, publication ordering and failure fencing. Actual R2 read-back, reference decryption and restore-drill evidence remain host acceptance, not mock-test claims |
| Bounds/query behavior | Inventory list is one bounded set read; discovery/output, records, manifest artifacts, file hashes, baseline scans and maintenance history have explicit bounds. No ordinary app-startup discovery is added |
| Private interface | Python 3.12 syntax, shell syntax/help, root CLI denial, fixed command selection, shared lock/operation identity, keyboard/terminal prompts; no Admin browser UI in Slice 1 |

Before using the new tooling on the VM, qualify sudo/runuser/descriptor inheritance and interruption behavior on Linux, adopt the effective A/B configuration, verify preserved rollback/recovery points, and record exact tool/release digests and remaining discrepancies. Keep the existing two-operator capacity and tunnel boot policy. Later slices own the Admin session/broker authority, provisioning engine/UI, verified onboarding recovery and three-operator qualification.
