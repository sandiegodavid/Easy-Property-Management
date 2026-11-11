# Development and host operations

[Foundation guides](README.md) · [Build/install runbook](../deployment/packaging-and-installation.md) · [Linux lab runbook](../deployment/linux-development-and-qualification.md) · [GCP runbook](../deployment/gcp-host-setup.md)

Use the linked runbooks for executable commands. They own exact tool arguments,
protected-input requirements and fresh-output rules. This guide explains which
workflow to choose and the limitations of the retained environments. Recorded host
state below is a qualification observation, not a live inventory query.

## Local development and native labs

Routine development uses Docker Desktop with explicit synthetic composition and no
production credentials, business data or permissive admission adapter. On this Mac,
Docker tools are inside `/Applications/Docker.app/Contents/Resources/bin`; installation
did not create system CLI links. AMD64 execution on the ARM64 Desktop engine is
emulation, not native Ubuntu/GCP qualification.

Development Compose exposes only `127.0.0.1:18801` and `:18802`, uses fixed health-only
modes, non-root/read-only containers, bounded memory/PIDs/logs and no data/credential
volumes or automatic restart. Both return the unavailable page. Its loopback-published
development bridge is not production outbound isolation.

Preserve the stopped Lima baselines `epm-quota-test` and `epm-h02-runtime`. The retained
`epm-h02-8` clone provides isolated native ARM64 Docker/ext4/AppArmor/reboot tests
without host-folder mounts. It recorded kernel `6.8.0-149-generic` and Docker `29.1.3`;
earlier native runs used different exact pins. Clone before kernel/Docker changes,
retain failed laboratories and stop when unused. Do not substitute these platform
results for the AMD64 target.

Create a deterministic source-only snapshot for each proof. It rejects links and
existing output and excludes tests, caches, environment/data files and compiled
assets. Extract into a new root-owned source directory; verify every manifest file
before effects. Do not patch a tested tree in place. Image IDs, source/kernel bytes,
Docker version and quota/bridge prerequisites must match the proof.

Actual reboot qualification records boot/mount/source identities, stopped no-restart
containers, all project observations and stable lock inodes before a real guest reboot.
The continuation requires a changed boot ID and unchanged pins, remounts only its
owned disposable lab if necessary, and repeats enforcement/escape/data checks. Repeating
a completed continuation verifies its retained result without replaying actors. A
container/service restart is not a host-reboot proof.

## Fresh GCP setup

The protected setup selects project/region/zone/domain/account and exact artifacts.
Use a standard non-Spot Ubuntu 24.04 AMD64 VM, Docker/cgroup v2 and supported startup
scripts/cloud-init. Never an implicit project/zone, moving image family or deprecated
container-declaration agent. Scoped Artifact Registry/Tunnel-secret permissions are
separate from operator identity or recovery credentials.

Only an explicitly identified, verified blank new whole device can be formatted.
Persist formatting intent before mkfs; reject signatures, partitions, mounts, changed
identity or partial setup. Mount retained ext4/project-quota data by UUID with
nodev/nosuid/noexec; Docker depends on that mount. Ordinary setup/Add operator cannot
adopt, reformat or enable missing filesystem features on an existing volume.

Install pinned tools and the offline agent into fresh canonical destinations. Use
exact-digest candidate pulls and remove temporary registry credential directories,
including on failure. Probe installed artifacts outside the checkout before service
setup. Permanent host services use empty owning inventory, protected identity,
separate accounts, scoped credential delivery and closed regenerated projections.
Do not run fixtures using the same unit names while installing permanent services.

## Retained qualification target

| Observed input/state | Value |
| --- | --- |
| VM | `epm-h02-host`, ID `6955052781247608210`, `us-west1-b`, `e2-standard-2` |
| Project/domain | `project-47b72bb7-ba90-42c9-910` / `epmdemo.xyz` |
| OS/tools | Ubuntu 24.04 AMD64; kernel `7.0.0-1017-gcp`; Docker 29.9.3, containerd 2.4.2, Python 3.14.10, Caddy 2.11.9, cloudflared 2026.10.7 |
| Disks | 20-GiB boot; 50-GiB balanced `epm-h02-host-data`, device `epm-h02-data`, auto-delete false |
| Data mount | `/srv/epm/data`, UUID `8d2fd2e0-274b-4535-90d5-da78aa6bd9b6`, ext4 project quotas |
| Network | Dedicated `epm-h02-network` / `epm-h02-subnet`, `10.80.0.0/24`; IAP-only TCP/22 ingress |
| Service identity | Dedicated `epm-h02-host`; no project-wide grant; one repository reader and one Tunnel-secret accessor |
| Qualification Tunnel | `epm-h02-qualification`, ID `d87e220e-e2a9-48c5-a67b-318255777bce`; secret version 1 |
| Closed public check | `h02-check.epmdemo.xyz` returned HTTP 403 with connector running; a stopped connector is not that check |
| Final recorded state | VM stopped/TERMINATED, same retained data disk attached, no running fixture containers before stop |

[Exact setup/artifact/reboot pins](../qualification/reports/HOSTED_MVP_H02_9_VALIDATION.json)
and [final source/stop receipt](../qualification/reports/HOSTED_MVP_H02_11_VALIDATION.json)
retain immutable identities, kernel/binary hashes and original observations. Resuming
the host requires rechecking actual protected services, mount/enforcement and closed
ingress. Stopped state is not an always-running hosted service or current availability claim.

## Failures, cleanup and one-time reset

Keep original failure evidence, exact lab/container/project identities and cleanup
results. Inspect uncertain effects; do not allocate replacements or delete/reuse
retained ownership blindly. On failure contain recorded containers, verify actual
stop, preserve all failures, then stop and retain the VM/disks. Shared/private reserves
and fresh capacity checks still apply to retained labs and disabled allocations.

The separately approved old `epm-demo` VM ID `8394063058170166658` and sole 30-GiB boot
disk ID `8124117985590132098` were deleted only after replacement qualification and
exact-ID rechecks. The [reset receipt evidence](../qualification/reports/HOSTED_MVP_H02_9_VALIDATION.json)
records absent old IDs and preserved replacement/data disk. Project/domain, provider
settings, unrelated resources, off-host backups and Lima baselines were preserved.
Old demo URLs no longer have that VM behind them. Do not replay this completed reset
as installation or onboarding; no inherited old grants/data/qualification are assumed.

Observed troubleshooting includes missing kernel quota extras/bridge-filter prerequisites,
OS Login metadata stalls in numeric `setpriv` probes, invalid empty provider credential
fields and competing service refreshes. The [qualification guide](qualification-and-handoff.md#failure-evidence)
links the actual controls and corrections; none justified a deadline, firewall or
identity-check relaxation. No live credential payload belongs in a command log/report.
