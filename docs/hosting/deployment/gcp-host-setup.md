# GCP host setup and qualification

[Tool source](../../../application/deploy/hosted-mvp/gcp) · [Foundation guides](../foundation/README.md)

These tools prepare an isolated GCP qualification host. They do not enroll an
operator, publish a qualified release or authorize business ingress. Retain raw logs,
failed labs, exact artifacts and source manifests outside Git. The
[completed H02.9 handoff](../qualification/reports/HOSTED_MVP_H02_9_HANDOFF.md)
records the retained stopped target, completed one-time old-host reset, measured
results and separate remaining owners. Do not replay that reset as ordinary setup.

## Cloud and disk setup

Run local Python commands from `application/`. Set `EPM_EVIDENCE` to a new private
directory outside the checkout. Supply `target.json` using `cloud_plan.Target`:
explicit project, region/zone, instance, network/subnet/private CIDR, repository,
service-account name, exact Ubuntu image name and dedicated Tunnel ID. Never use
an implicit gcloud project/zone or a moving image family.

1. Render `startup.sh` with `render_startup.py` and the accepted H02.1 Docker package
   URLs/hashes. Inspect the output; each downloaded package is hash-checked before
   installation. Docker package versions are held. Capture the actual image ID,
   installed kernel bytes and tool versions, not only the requested names.
2. Generate and inspect the cloud plan:

   ```sh
   PYTHONPATH=apps/server .venv/bin/python deploy/hosted-mvp/gcp/cloud_plan.py \
     --target "$EPM_EVIDENCE/target.json" \
     --startup "$EPM_EVIDENCE/startup.sh" > "$EPM_EVIDENCE/cloud-plan.json"
   ```

   Execute the reviewed argument arrays explicitly with gcloud. The plan creates a
   dedicated VPC, IAP-only SSH rule, non-Spot 2-vCPU/8-GiB VM, 20-GiB boot disk and
   retained 50-GiB data disk. It enables OS Login and blocks project SSH keys. It
   contains no old-host deletion, adoption or disk formatting command.
3. Grant the dedicated VM service account Artifact Registry reader on only this
   repository and Secret Manager accessor on only its dedicated Tunnel credential.
   Store that credential in `epm-tunnel-<Tunnel ID>`, version 1. Do not put tokens or
   secret payloads in metadata, commands, logs, unit environments or the checkout.
4. On the new guest, invoke `guest_disk.py` as root with
   `EPM_H02_QUALIFICATION=1`. It accepts only the expected blank whole 50-GiB
   `/dev/disk/by-id/google-epm-h02-data`. Formatting intent is persisted before mkfs;
   interrupted setup rejects rather than guessing whether to adopt/reformat.
   Successful setup mounts ext4/project quotas at `/srv/epm/data` by UUID and makes
   Docker depend on that mount. Existing/changed/partial disks are not candidates
   for rerunning destructive setup.

## Install exact candidates

Prepare fresh offline artifacts with the [packaging procedure](packaging-and-installation.md), using
the accepted Linux dependency lock and wheelhouse. Preserve the generated candidate
manifests and exact registry manifest digests. Tags are convenient upload names,
not identities or qualification results.

On the guest, use `install_runtime.sh` with its explicit root opt-in to extract the
pinned Python runtime. Install a verified offline host-agent bundle into a fresh
canonical destination using its `install_agent.py`. Keep the pinned Caddy and
cloudflared binaries under `/opt/epm/tools`; check their accepted hashes first.

`pull_candidate.py --target <target.json> --reference <owned image@sha256:digest>`
uses only the VM service identity. Its private Docker credential directory is removed
after the pull, including on failure. Pull Admin and Operator by exact manifest
digest and run the standalone installed-candidate `probe.py` without a checkout,
network or writable root, using only a disposable tmpfs and the read-only probe.
Unavailable owning stores must stay unavailable without creating destinations.

After disposable fixture checks have finished, run `install_services.py` as root
with `EPM_H02_QUALIFICATION=1` and explicit project/domain/Tunnel arguments. It
checks the live data mount before its first directory/metadata/inventory mutation:
exact mount target and recorded UUID, ext4 on the matching block device, required
`rw,prjquota,nodev,nosuid,noexec` options, filesystem quota features, and kernel project
quota accounting **and enforcement**. Retained `phase=ready` metadata alone is not
readiness. Missing/replaced/unenforced mounts reject without creating authority.
It then initializes an empty owning inventory, preserves the host/filesystem binding,
fetches only the scoped credential, validates it in private staging before publication,
installs hardened units and regenerates closed
projections. Only an empty provider-generated `Endpoint` field is removed; alternate
endpoints/unknown fields reject and the runtime still requires its exact three-field
credential. Service refreshes are ordered gateway → egress → Tunnel during setup
and boot to avoid contention on the exclusive inventory lock. The guardian is containment-only. No operator is admitted or started.
Do not install these permanent units while fixtures using the same unit names are
running. A subsequent credential rotation/configuration change requires its owning
reviewed workflow, not overwriting protected inputs.

## Focused native proofs

Create a fresh immutable archive with `lab/snapshot.py`, copy it to the guest and
extract it into a new root-owned source directory. Do not patch an already tested
tree in place. Set `PYTHONPATH` to that snapshot's `apps/server` and use the pinned
host-agent Python. Every proof requires its explicit disposable-root opt-in.

| Proof | Driver and opt-in | Required observation |
| --- | --- | --- |
| Numeric lab identities | `gcp/qualify_principals.py`, `EPM_H02_QUALIFICATION=1` | In a private network namespace, stalled OS Login metadata makes the old numeric `setpriv` path exceed five seconds; direct numeric subprocess credentials start with the exact UID/GID and no supplementary groups. No host firewall/NSS change. |
| Dual-stack network and stream containment | `gateway/qualify_network.py --image <native config digest> --caddy /opt/epm/tools/caddy`, `EPM_RUN_GATEWAY_QUALIFICATION=1` | Exact bridges, gateway access, sibling/root/tunnel/metadata/public-egress denial, actual forwarding counters and existing-stream closure on containment. Keep the five-second process deadline. |
| Connected sandbox | `gateway/qualify_connected.py --run`, `EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1` | Real AppArmor/seccomp/quotas/WAL/cross-UID isolation with the current bridge/firewall; firewall loss stops runtime. |
| TLS/DNS/redirect egress | `gateway/qualify_egress.py`, `EPM_RUN_GATEWAY_QUALIFICATION=1` | Private mount/network namespaces only; no public upstream or real credential. Retain positive TLS and negative redirect/SNI/rebinding/stalled-DNS results. |
| Hardened services | `gateway/qualify_services.py --caddy /opt/epm/tools/caddy`, `EPM_RUN_GATEWAY_QUALIFICATION=1` | Separate service accounts, restart/closed projection behavior and credential isolation. Run before permanent service installation. |
| Real retained filesystem | `gcp/qualify_host.py before`, `EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1` | Two synthetic owners/six uniquely reserved projects on the retained data disk, runtime faults and native/32-bit controls. Record the printed lab root. |
| Reboot and retained containers | `lab/qualify_reboot.py before`, same quota opt-in | Two no-restart containers holding stable writer locks; exact source/kernel/Docker pins and pre-reboot observations. Record its separate lab root. |

The quota fixtures reserve only synthetic paths/projects. Do not substitute an
operator's business workspace. These are correctness/isolation proofs, not capacity
or entitlement measurements.

Perform an actual guest reboot with `systemctl reboot`. Then run
`gcp/qualify_host.py after --root <direct-disk lab>` and
`lab/qualify_reboot.py after --root <container reboot lab>` from the same snapshot.
Require a changed Linux boot ID with unchanged **running** kernel release/architecture
and source pins. Hash the image corresponding to that running release; an unchanged
older image remaining in `/boot` cannot qualify a different running kernel. Verify filesystem UUID,
all six quota observations and writer-lock inodes. Inspect retained Docker identities
before restarting any fixture: both containers must be stopped with restart disabled.
Recheck the permanent units, closed projections and private credential isolation after
boot. A successful service/container restart alone does not qualify guest reboot.

<a id="h0210-capacity-trial"></a>

## Capacity measurement

Use only the retained qualification host, with normal operator admission and business
routes held. The trial creates six private synthetic principals, unique project quotas
and no-network containers; it does not use business workspaces. Keep shared gateway,
egress, Tunnel and guardian services healthy throughout the trial. Do not overlap this
with other workloads. Unknown running containers or incomplete kernel project accounting
make capacity unavailable.

Create/copy/extract a fresh immutable `lab/snapshot.py` archive as above. From that
root-owned snapshot on the guest, run with the pinned host-agent Python:

```sh
sudo env EPM_RUN_CAPACITY_QUALIFICATION=1 \
  PYTHONPATH="$EPM_CAPACITY_SOURCE/apps/server" \
  /opt/epm/host-agent/bin/python -B \
  "$EPM_CAPACITY_SOURCE/deploy/hosted-mvp/gcp/measure_capacity.py"
```

Set `EPM_CAPACITY_SOURCE` explicitly to the freshly extracted snapshot. The driver
verifies every manifest file, the protected mounted filesystem identity and quota
option before effects. Record the printed `/srv/epm/data/qualification/h02-capacity-*`
root. `progress.json` is a private atomic/fsynced record of allocation identities,
completed phases, actual observations, decisions and containment failures. Do not
change a tested snapshot or rerun its existing allocation paths.

The driver measures two empty-business-workspace application runtimes, then loaded
SQLite/WAL/consistent scratch backup work. Fresh observations and full reservations
must permit each additional runtime before growing to five and six. Six is the bounded
measurement population, **not a product cohort limit**. It then exercises workspace,
control, scratch and inode saturation; deleted-open files; SQLite rollback/reopen;
PID/FD/memory bounds; read-only shared memory; and rotating logs. Independent host
and runtime samples retain memory, CPU, IO, pressure, quota and service observations.
The one-GiB available-RAM/two-GiB free-filesystem abort checks are emergency margins,
not replacement admission policy.

Only completed workloads with verified stopped containers can produce
`candidate-profile.json`. Its evidence hash, source/policy pins, measured limits and
required faults are checked by `capacity_profile.validate_document`; preserve the exact
`progress.json` bytes alongside it. Partial/failed evidence produces no profile. The
candidate distinguishes per-runtime physical ceilings and shared/future-recovery
reserves from the 50,000,000-byte Free logical allowance. These observations do not
qualify H05 restore or authorize H04 admissions.

On failure inspect recorded container IDs and bounded logs, preserve original failure
and cleanup errors, and verify containment before retrying with a new snapshot/lab.
Retained project **hard limits**, including failed labs, remain charged; do not count
only current file sizes or blindly delete/reuse UIDs/projects. Stop and retain the VM
and disks after capturing the result. Publish only a sanitized report and evidence
hashes in Git, with private raw data retained outside the checkout.

## Cloud boundary and handoff

Verify effective GCP firewall rules, resource-local IAM and data-disk auto-delete
settings. Add only an explicitly chosen qualification hostname to the dedicated
Tunnel; verify closed public responses and direct-origin denial. Keep business
ingress held. Preserve the old demo until the replacement qualifies. Any separately
authorized old-host reset must recheck exact VM/disk IDs and leave unrelated
resources and off-host backups intact.

Record measured results and failures in a sanitized handoff, with private raw-log
locations, exact source/artifact/kernel hashes and unresolved gates. The
[H02.11 scoped handoff](../qualification/reports/HOSTED_MVP_H02_11_HANDOFF.md)
consolidates completed infrastructure proofs and measured H02.10 capacity; H03–H05
admission/access/recovery and final artifact promotion remain separate. Stop and retain the
qualification VM/disks when pausing; retain local Lima baselines unchanged.

## Consolidated acceptance and later owners

Use the [acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md#h02-consolidated-infrastructure-acceptance)
and H02.11 validation manifest for exact focused commands, native source hashes and
retained evidence. Never infer a qualified release from a candidate build or historical
proof. H02.11's native-subset and final image/all-store v1 reports validate but return
CLI exit 2 (`unavailable`); missing H03–H05 prerequisites are not passing gates.
Rebuild/requalify final owning artifacts and complete Pilot 0 gates before invitations.
