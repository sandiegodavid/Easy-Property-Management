# Runtime, storage and capacity

[Foundation guides](README.md) · [Runtime/guardian runbook](../operations/runtime-supervision.md) · [Capacity trial procedure](../deployment/gcp-host-setup.md#capacity-measurement)

## Private storage and writer identity

Each inventory-bound operator has a distinct retained host UID/GID and three ext4
project trees. Protected deployment inputs select the mount UUID and canonical,
nonoverlapping roots; browser requests do not select paths or limits. Establish
project inheritance and rounded byte/inode ceilings before granting writer access.
Partial preparation retains protected mode-000 destinations; never adopt/relabel a
populated tree or automatically recycle its principal/project IDs.

| Tree | Contents and access |
| --- | --- |
| Workspace | Owning business database, files and bounded business-local work. |
| Control | Separate access/recovery state. Root is read-only to the container; only `data/` is writable. Stable `writer.lock` is precreated outside replaceable business data. |
| Scratch | Bounded temporary/upload/export/backup staging; `/tmp` and `/var/tmp` use the same accounted tree. No unlimited temporary fallback. |

Every permitted business opener shares the control-tree lock. One Uvicorn worker;
no competing initializer or scheduler opens another writer. Replacement confirms
old-writer stop before mounting the same business tree read-write for its successor.
Preserve lock device/inode and acknowledged data. Local native lock defaults remain
unchanged. Recovery-owned staging/switching is still unavailable.

## Sandbox and independent containment

Runtime roots/images are read-only; direct registered UID mapping, dropped capabilities,
no-new-privileges, architecture-specific seccomp/ioctl restrictions and named AppArmor
are combined. No host namespaces/network/PID, devices, Docker socket or published
operator ports. User-namespace remapping would require fresh qualification.
Bound memory/swap, CPU, PIDs, descriptors, shared memory and rotating logs; disable cores.
A running process alone does not prove correct mounts, enforcement or readiness.

Docker restart is `no`. One guarded host supervisor owns starts/restarts. It requires
current inventory/qualification/external-deny checks and owner readiness. Before start,
fsync a protected immutable **stop-only** exact-container-ID projection. A singleton
owner lease/readiness epoch and start/stop barrier prevent stale owners from starting.

Missing/corrupt inventory cannot prevent containing a registered container. Stop
projections grant no allocation, rebind or start authority and are not another inventory.
Startup/shutdown and systemd ExecStopPost contain registered targets before readiness.
Unknown prerequisites keep runtimes stopped/held; unreachable engine or unverifiable
stop remains unresolved. Preserve original and containment/persistence failures together.
Stop scans are bounded to 4,096 records as a safety bound, not an admission cap.

Native diagnosis required two narrow sandbox corrections: receive TERM/KILL from
Ubuntu's exact `runc` AppArmor peer, and allow the missing native `chmod` alias alongside
fchmod/fchmodat. Owned chmod succeeds; protected-root/control-lock mutations still
fail. No unconfined profile or relaxed deadline was used. Current native/compat
and connected proofs are indexed in [qualification](qualification-and-handoff.md).

## Candidate capacity and physical reservations

The [versioned measured profile](../qualification/reports/HOSTED_MVP_H02_10_CAPACITY_PROFILE.json)
records limits used in the synthetic capacity trial, not derived production tier
sizing, entitlements or admission authority. The byte/inode constants below were
chosen trial inputs: passing that workload did not establish their adequacy for the
50 MB allowance or any paid tier. Production sizing remains subject to the
[per-tier acceptance gate](../design/mvp/subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance).

| Per-runtime trial input | Bound |
| --- | --- |
| Memory / CPU | 768 MiB / 250 millicores; shared memory is included in RAM accounting |
| PIDs / descriptors | 64 / 512 |
| Workspace physical ceiling — unqualified tier-sizing trial | 256 MiB / 8,192 inodes |
| Control | 64 MiB / 4,096 inodes |
| Scratch | 128 MiB / 4,096 inodes |
| Shared memory | Read-only 1 MiB |
| Host logs / metadata | Three 2-MiB log slots; additional 1-MiB/1,024-inode metadata reservation |

Shared reservation: 1.5-GiB RAM, 500 millicores, 512 PIDs, 4-GiB data/100,000
inodes and 9-GiB boot/300,000 inodes. Future recovery reserve: 512-MiB RAM and
1-GiB data/20,000 inodes. Headroom does not qualify the largest restore workflow;
recovery stays unavailable until that workflow is measured and supported.
Free logical allowance remains **50,000,000 bytes** under the usage owner. Backup
bytes are excluded from operator logical quota but still need physical reservations.
Kernel rounding, operational headroom and downgrade overage are separate concepts.

The pure planner counts full pending, active, retained, unknown and cleanup-pending
commitments. Check total reservations and actual available resources separately;
credit already materialized usage only once. Incomplete/stale/future observations,
unknown limits, changed profile/revision, duplicate identity and overflow fail closed.
The collector counts all retained kernel **hard limits**, not just live file sizes,
and checks current projects and shared services without recursive business-data scans.
The usage/admission owner must serialize durable holds/CAS; planning alone reserves nothing.

Six was the bounded test population, not a product cap. With this candidate CPU budget,
a seventh full hold exceeds 2,000 millicores (500 shared + 7 × 250); actual admission
must still recompute every current commitment and physical observation. Unknown or
insufficient capacity rejects rather than bypassing the gate.

## Measured workload and limits

Two, five and six isolated runtimes passed real local property API reads against empty
business workspaces and loaded SQLite/WAL/consistent scratch backup work. Each actor's
separate benchmark holds 48,000 × 1,024-byte payloads. It is not retained file evidence,
a production dataset or end-to-end hosted operator workflow.

| Population | Empty-workload worst actor p95 | Loaded-workload worst actor p95 |
| --- | --- | --- |
| 2 | 6.92 ms | 6.49 ms |
| 5 | 11.55 ms | 9.14 ms |
| 6 | 9.20 ms | 11.76 ms |

Phases target ten seconds; completing a backup can extend them. Loaded request counts
are small because iterations copy the database; these are observations, not a production
SLO. Cgroup peaks are cumulative: loaded peak 389.7 MiB; fault peak reached the
768-MiB ceiling. Least host available memory in the fault phase was 3.37 GiB.
All six actors preserved acknowledged SQLite rows through saturation/reopen, enforced
byte/inode/deleted-open/PID/FD/shm bounds and survived a bounded OOM-killed child.
Logs retained three files/about 4.38 MB each. Every fixture container stopped afterward.

The [full measurement](../qualification/reports/HOSTED_MVP_H02_10_VALIDATION.json)
retains CPU/throttling and source/policy/image identities; private evidence retains
IO/PSI and independent samples. An earlier trial refused the extra runtime because
unexplained host memory use exceeded shared reserve. That cause remains unresolved;
a later successful run does not remove the need for fresh refusal checks.

Repeated backup initially failed with SQLite EIO. Explicitly closing target connections
fixed it at the same 128-MiB scratch limit; a connection context manager alone does
not close it. Cross-platform evidence validation uses Linux errno values, not the
inspecting Mac's constants. Incomplete faults, mismatched cgroup/quota budgets or
failed containment cannot publish a measured candidate.

Code: [private storage](../../../application/apps/server/app/modules/host_agent/infrastructure/private_storage.py),
[container policy](../../../application/apps/server/app/modules/host_agent/infrastructure/container_policy.py),
[stop registry](../../../application/apps/server/app/modules/host_agent/infrastructure/stop_registry.py),
[supervisor](../../../application/apps/server/app/modules/host_agent/infrastructure/supervisor.py),
[capacity planner](../../../application/apps/server/app/modules/host_agent/application/capacity.py).
