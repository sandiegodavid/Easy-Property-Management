# Private runtime and physical-limit proof — H02, with H04

Case authority: [runtime_limits.json](runtime_limits.json). Use the
[common safety/runner interface](README.md), [quota reuse guide](../HOSTED_PROJECT_QUOTA_REUSE.md)
and its pinned import manifest. Historical systemd/ext4 reports do not qualify Docker/GCP.

## Setup and invocation

H02 must first finish its detailed host/agent/Docker design. Prepare two synthetic
operators on an explicitly disposable Linux filesystem; pin kernel, filesystem,
mounts, UID mapping, enforcement mechanism, seccomp/capability profile and all
workspace/control/scratch byte/inode ceilings. Input fixes 4,096-byte write chunks,
maximum attempted allocation, timeouts, host abort reserve and owned cleanup IDs.
Never infer safety from a path string or run against a live data device.

Run separate native Linux, actual Docker and exact GCP target reports. Preserve the
retained Lima baseline before lab changes, leave it stopped afterward, and retain
a recoverable snapshot for reboot tests. The existing imported harness is reviewed
input only; it requires root Linux and explicit `EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1`,
not permission to execute it here. H01 does not invoke it.

Reserved future command (currently exit 3, no input read/output/mutation):

```bash
.venv/bin/python -m app.platform.hosted_proofs execute --spec ../docs/hosting/qualification/specifications/runtime_limits.json --inputs /private/proof/inputs.json --output /private/proof/report.json --phase run
```

Reboot continuation uses the same IDs/input digest and `--phase after-reboot`; never
rerun resource allocation as a new request. H02 pins actual native/Docker/GCP setup commands.

## Workload and pass/fail controls

| Case | Required workload / observable result |
| --- | --- |
| `private_registered_mounts` | Enumerate all writable locations and registered roots/UIDs/mounts. Verify identity before start and cross-check actual resource generation/image; unknown roots fail closed. |
| `cross_operator_denial` | Operator A attempts B's mount, private store, evidence and IDs through filesystem and API. All denied without leaking existence/content; Admin has no direct business DB/Docker socket. |
| `byte_inode_exhaustion` | Independently fill each configured tree to byte and inode limits using fixed chunks/one-byte files; attempt one extra write/create and capture EDQUOT/ENOSPC classification, deleted-open attribution and retained prior bytes. |
| `wal_commit_fsync_failure` | Inject SQLite/WAL/journal growth exhaustion at commit and fsync; compare committed rows/files/receipts and reopened state. No false success or silent data loss; capture original error plus cleanup outcome. |
| `control_scratch_bounds` | Saturate upload/spool/container-layer/tmpfs/log/control/scratch paths in turn; demonstrate each is bounded and cannot consume another operator's protected reserve. No writable bypass. |
| `sandbox_escape_denial` | Attempt ioctl/project reassignment, mount/namespace/capability escape and descendant inheritance bypass as actual container UID. Preserve complete allowlisted exploit workload and denied observations. |
| `disabled_enforcement_control` | In an independent disposable negative fixture disable the selected enforcement and show the positive workload now detects the breach. Restore/recreate fixture; never run this control against the admitted target. |
| `remount_reboot_replace` | Record boot/mount/source IDs, actual remount/reboot and stopped-container replacement; reverify ceilings, ownership, data/receipts and denied escape workload without reallocating identity. |
| `one_writer_and_drain` | Attempt second writer and mutation during maintenance drain; prove source fences and retained original-result lookup, not process-lock folklore. |
| `warm_population_capacity` | Admit one through five warm synthetic operators sequentially; record resident memory/CPU/I/O/headroom under fixed workload plus backup activity. Attempt sixth only if qualified headroom permits; no hard-coded cap. |
| `concurrent_admission_commitments` | Synchronize two admission requests that individually fit but jointly exceed the remaining envelope; at most the qualified capacity commits. Pending/unknown reservations count; repeat after lost response/restart. |

## Evidence and cleanup

Retain source/tool/image/profile hashes, actual errno/kernel/mount observations,
transaction/file integrity comparisons, before/after boot IDs, sandbox results and
capacity measurements. Record exact measured population, not a general scaling claim.
Stop on unknown identity/free capacity, preserve failed/unknown allocations and cleanup
receipts. Root cleanup is explicit against owned lab IDs only. H02/H04 decide actual
physical reserve sizes from results; no production tier profile is selected by H01.
