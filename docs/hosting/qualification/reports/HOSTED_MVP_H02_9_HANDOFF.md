# H02.9 native GCP setup and approved old-host reset

Delivered November 13, 2026, within native AMD64/GCP infrastructure scope. Fresh
host setup, installed candidates, isolation, closed ingress, actual guest reboot and
the separately approved old VM/boot-disk reset are complete. The replacement is
**stopped and retained**, with its data disk preserved. No operator was enrolled,
business ingress enabled or candidate promoted to a qualified hosted release.

Use the [executable GCP runbook](../../deployment/gcp-host-setup.md)
for repeatable setup/proof procedures and the
[validation manifest](HOSTED_MVP_H02_9_VALIDATION.json) for exact source, artifact,
platform and raw-evidence hashes. Earlier H02.8 ARM64/Desktop results are separate
evidence; they were not substituted for the native GCP checks below.

## Retained target and reset outcome

| Resource | Observed result |
| --- | --- |
| Project / domain | Retained `project-47b72bb7-ba90-42c9-910` / `epmdemo.xyz` |
| Replacement | `epm-h02-host`, ID `6955052781247608210`, `us-west1-b`, `e2-standard-2`; stopped after qualification |
| OS | Ubuntu 24.04 AMD64 image `ubuntu-2404-noble-amd64-v20261105`, image ID `1892012953239034119` |
| Disks | 20-GiB boot; retained 50-GiB balanced `epm-h02-host-data`, device `epm-h02-data`, auto-delete false |
| Filesystem | ext4 at `/srv/epm/data`, UUID `8d2fd2e0-274b-4535-90d5-da78aa6bd9b6`; project quotas, nodev/nosuid/noexec |
| Network | Dedicated `epm-h02-network` / `epm-h02-subnet`, `10.80.0.0/24`; only IAP TCP/22 ingress |
| Host identity | Dedicated `epm-h02-host` service account; no project-level role, repository-local reader and accessor on only its dedicated Tunnel secret |
| Tunnel | New `epm-h02-qualification`, ID `d87e220e-e2a9-48c5-a67b-318255777bce`; scoped credential version 1, no secret bytes in Git |
| Qualification hostname | Only new `h02-check.epmdemo.xyz`; observed HTTP 403 through the running connector. A stopped connector is not an operational HTTP-403 check. |
| Old VM | Approved `epm-demo`, ID `8394063058170166658`, deleted after new-host qualification |
| Old boot disk | Sole 30-GiB `epm-demo`, ID `8124117985590132098`, deleted with that VM; subsequent inventory confirmed both IDs absent |

The one-time reset rechecked both old IDs, sole boot-disk attachment/ownership and
size, the stopped replacement identity, its retained data disk, and the successful
reboot proofs immediately before deletion. It deleted only the old VM and boot disk;
the replacement/data-disk IDs were rechecked afterward. The private
`old-host-reset-receipt.json` records completion. This explicit user-approved reset
does not grant Add operator or ordinary setup permission to adopt/format existing
volumes or delete older hosts.

Existing demo DNS/Tunnel configuration, unrelated project resources, off-host
backups and local Lima baselines were left unchanged. Old demo URLs no longer have
the deleted host behind them. No legacy Cloudflare grant, data or qualification was
inherited by the replacement. Retargeting legacy URLs or deleting provider resources
was outside this reset's scope.

## Delivered setup and installed artifacts

- Explicit cloud argument planner, with no implicit project/zone, shell command
  strings, moving image family or deletion command. The supported startup script
  installs hash-checked Docker packages, records OS readiness and preserves the
  accepted versions. The GCP kernel already provides quota support; matching generic
  kernel extras are not assumed.
- Explicit blank-device initializer accepts only the expected whole 50-GiB device.
  It persists formatting intent before mkfs, rejects signatures/partitions/mounts
  and partial setup, and uses a UUID-bound systemd mount. Docker requires that mount.
  Existing/changed filesystems are never silently reformatted or adopted.
- Pinned Docker CE 29.9.3, containerd 2.4.2, Caddy 2.11.9, cloudflared 2026.10.7 and
  official pinned AMD64 Python runtime, observed as Python 3.14.10. Actual kernel
  `7.0.0-1017-gcp` SHA-256 is
  `3cf8c2c34cd30720d3f37c8b5327ae7d10f24073e73a34edb1e4aaea4dd39adb`.
- Fresh offline host-agent installation at `/opt/epm/host-agent`, verified without
  a checkout dependency. Its preceding installation remains privately retained at
  `/opt/epm/host-agent-prior-source-3`; successful and failed fixture laboratories
  remain on the retained guest.
- Empty owning inventory, stable host/filesystem binding, separate non-login host
  service accounts, protected projections, scoped secret delivery and one
  containment-only guardian. No simulated production admission authority was added.
- Canonical credential is validated in private staging before non-overwriting
  publication. Only the provider's empty `Endpoint` field is removed; nonempty
  endpoints/unknown fields reject. Runtime three-field validation remains exact.
  Two real setup retries preserved host metadata, inventory and credential bytes.
- Gateway → egress → Tunnel startup ordering avoids concurrent exclusive inventory
  refreshes. All six real units were active after reboot, with zero gateway, egress,
  Tunnel or guardian restarts and no failed refresh. Live firewall/Caddy closed
  projection verification passed.
- Fresh Admin and Operator images were built offline, pushed to the dedicated
  repository, pulled by exact digest using only the host service identity, and
  probed on native AMD64. Temporary registry credentials were removed. Available
  schemas validate; unavailable owning stores create no destination. Compiler is
  absent, normal startup remains blocked, liveness is 200 and readiness is 503.

Exact image manifest digests in
`us-west1-docker.pkg.dev/project-47b72bb7-ba90-42c9-910/epm-h02-candidates/`:

| Artifact | Identity |
| --- | --- |
| Admin | `admin@sha256:a8c17495ce5618856df13b37e384b0671c2a49190e586cb4e8c3bbc93fb6ee37` |
| Operator | `operator@sha256:6c264a90ff2f9a64e1d66b8e5b1405680d517210b4e3d1c586816603c486c995` |
| Host-agent archive | SHA-256 `d16ce4b2ec9e43cc194f3e1219f02917683331c13a663c7ed4073fcd62d8c36c` |

Convenience tag `h02-9-8c46a24c-source5` is not a qualification identity. The manifest
records dependency-lock, candidate-source, installed-resource and binary hashes.
No qualified-release row was created.

## Native proof and source custody

Two synthetic owners/six independently bounded projects exercised bytes, inodes,
deleted-open files, WAL exhaustion/rollback, cross-UID and namespace/mount/ioctl
denials, cgroup/log bounds, replacement, missing inventory and guardian death.
The direct proof used synthetic paths on the actual retained data disk. Native
control exited 42; a static 32-bit control exited 159 under the same Docker policy.

The connected proof repeated the quota/sandbox faults with exact bridge/firewall
inspection and stopped runtime on firewall loss. The dedicated network proof
verified unpublished dual-stack gateway access, sibling/root/tunnel denial,
metadata and direct-public-egress denial, controlled proxy behavior, four actual
forwarding-drop packets and full firewall reinspection. A prior live stream closed,
its target stopped and the deny configuration was verified. Private namespace TLS
proofs passed approved TLS, mismatched SNI, redirects and metadata DNS rebinding;
stalled DNS completed in 2.00 seconds.

The real guest reboot changed boot ID
`bf4c2d04-399e-4db7-85d8-7089ab7c1f81` to
`2eaf3c4f-e371-4561-bc4f-0ff88feb1a16`, preserving exact kernel bytes, filesystem
UUID, all six project observations and writer-lock inodes. Two retained containers
stayed stopped with automatic restart disabled. Post-boot sandbox/WAL, each tree's
EDQUOT, cross-UID denial and containment passed. The operator-owned writer lock was
successfully acquired as its recorded numeric owner, not root.

| Immutable source | Scope and manifest SHA-256 |
| --- | --- |
| Snapshot 5, `/opt/epm/qual-source-5` | Network, principal, connected, egress/service fixtures and both before-reboot proofs; generic container continuation uses this unchanged snapshot. `21dc74388d9e1bf93b84832fd0d4e4e4fe276e921e912b215d4088adea069a7f` |
| Snapshot 7, `/opt/epm/qual-source-7` | Final real setup and repeated-setup proof. Only `gcp/install_services.py` differs from snapshot 5. `405c033e05dd08c71fbd54a7d72783d497ac171380703747dc63dfd8f9bc9b92` |
| Snapshot 8, `/opt/epm/qual-source-8` | Corrected direct-data post-reboot owner-lock proof; only installer and that helper differ from snapshot 5. Matches current selected source. `14234af65e27dfcd27dd4f16a597afaa1b06ecc21550ee60d079910f9be2ac3b` |

Application/runtime policy hashes are unchanged across these snapshots. The direct
helper correction did not rewrite the original before-reboot record or relax the
production lock. Generic reboot continued against its exact original source pin.
Snapshot 3 was patched during diagnosis and is not claimed as immutable final input.

## Validation matrix

| Area | Result |
| --- | --- |
| Happy paths | Fresh native setup/artifacts, two-owner quotas/sandbox, connected network/stream/TLS, hardened services, repeated real setup, actual reboot and approved reset passed. |
| Invalid combinations | Wrong cloud target/zone/ranges, nonblank/partitioned/mounted disks, malformed/alternate-endpoint credentials and externally connected metadata-control namespaces reject. |
| Retry/idempotency | Existing output/credential cannot be overwritten; staged invalid credential leaves no final file and valid retry succeeds. Repeat setup preserves identity/data. Process timeout is never counted as successful network denial. |
| Rollback | Real WAL exhaustion/reopen preserved the original row. Private credential staging validates before publication; failures remain inspectable. No new business transaction behavior. |
| Persistence/schema | Exact installed available schemas validate; missing stores stay unavailable. Mount UUID, six quota projects, lock inodes and stopped no-restart containers survive actual reboot. |
| Backup/restore | No H05 recovery acceptance. Only the expressly approved old VM/boot disk was removed; off-host backups were unchanged. |
| Query budget/N+1 | No directory/list projection added. Bounded setup/probe operations and three-project-per-binding checks; no new application query-budget claim. |
| Cloud boundaries | Scoped resource IAM/no project grant, IAP-only SSH, retained data disk, real public denial and direct-origin denial verified. |

Final focused validation: **61 tests passed** across GCP setup, network probes,
source/reboot custody, packaging and the owning network adapter. Ruff check and
format check passed for all **16 H02.9 Python files** using the application config.
No suppressions, full suite or frontend source/tooling changes. The earlier Operator
artifact build checked contracts and compiled its packaged frontend.

## Failures retained and resolved

Private evidence remains under
`/Users/dcai/Desktop/Property-Management-Data/hosted-mvp-qualification/H02.9/`.
The validation manifest lists allowlisted log/result hashes without credential bytes.

1. Generic-kernel extras assumption failed on GCP; actual quota support was verified.
2. Docker omitted empty IPRange. Normalization restores only that empty representation;
   nonempty ranges and isolation options remain exact.
3. The original five-second probe stall was not traced. A later syscall trace showed
   numeric `setpriv` consulting Google OS Login metadata before dropping privileges.
   An isolated stalled-metadata control reproduced timeout, while direct numeric
   subprocess credentials started in about 36 ms with cleared supplementary groups.
   The network/proxy/stream fixtures now avoid that lookup without relaxing deadlines
   or firewall. A hung expected-denial probe still fails.
4. An initial network command selected an old ARM64 reference; native evidence uses
   the exact AMD64 fixture. An unsupported egress `--run` invocation executed no proof;
   the corrected invocation passed. Neither mistaken invocation is counted as a pass.
5. Restricted offline wheel build needed access to its existing cache; the same
   closed constraints succeeded with authorized cache access.
6. Provider `Endpoint` and concurrent service-refresh failures led to the staged
   credential and ordered-start fixes described above; original logs remain retained.
7. Root acquisition of an operator-owned writer lock correctly failed. The corrected
   helper tests the recorded owner, preserving the production guard and original
   persisted observations. Initial SSH banner/reboot diagnostics are also retained.

## Operations handoff and remaining owners

The new host is stopped to retain qualification resources without a running VM.
To resume only this target:

```sh
gcloud compute instances start epm-h02-host \
  --project=project-47b72bb7-ba90-42c9-910 --zone=us-west1-b
```

Recheck protected service state and closed ingress after starting. Do not rerun disk
formatting or a completed before-reboot fixture. Preserve old failed/successful labs,
archives, candidate metadata and the completed reset receipt. The one-time reset is
not a normal installation step and must not be replayed against another resource ID.

H02.9 has no remaining implementation work. H02.10 owns capacity/headroom and a
versioned admissible profile; H02.11 owns consolidated acceptance. H03–H05 still own
real identity/access, Admin/operator admission, final owned stores/assets and encrypted
recovery/restore. Their final artifacts require owning proof before qualified-release
promotion or H06 invitations. This infrastructure handoff grants neither.
