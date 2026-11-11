# H02.10 measured candidate capacity handoff

Delivered November 13, 2026 within synthetic native AMD64/GCP capacity scope.
No customer/operator admission, release promotion or recovery readiness is enabled.

The [candidate profile](HOSTED_MVP_H02_10_CAPACITY_PROFILE.json) binds the exact
private measurement bytes, immutable source and runtime policy. The
[validation record](HOSTED_MVP_H02_10_VALIDATION.json) records sanitized measured
limits, populations, CPU deltas, latency and containment. The
[runbook](../../deployment/gcp-host-setup.md#h0210-capacity-trial)
explains how to repeat the opt-in fixture without business data or provider changes.

## Scope and measured results

Target: retained `epm-h02-host`, GCP project `project-47b72bb7-ba90-42c9-910`,
zone `us-west1-b`, e2-standard-2, 2 vCPUs/8 GiB, 20-GiB boot/50-GiB ext4 quota data.
Kernel `7.0.0-1017-gcp`; exact filesystem/policy/source/image pins are in the records.
Four shared daemons remained populated at every host sample. Distinct numeric
principals and quota projects isolate six read-only-root/no-network containers.

Each actor initializes a valid empty business workspace and exercises the real local
property API. Loaded phases add a separate 48,000 × 1,024-byte synthetic SQLite
payload, WAL updates and repeated consistent backup to bounded scratch. This is
physical application/SQLite IO measurement, not a production dataset or hosted
end-to-end operator workflow. Each phase targets ten seconds; backup completion can
extend it. Loaded request counts are small because each iteration copies the database;
these observed p95 values are not a production SLO or statistically broad benchmark.

| Runtimes | Phase | Successful requests | Worst actor p95 ms | Largest cumulative cgroup peak MiB | Least host available GiB |
| --- | --- | --- | --- | --- | --- |
| 2 | empty | 358 | 6.92 | 191.5 | 6.71 |
| 2 | loaded | 8 | 6.49 | 389.7 | 6.59 |
| 5 | empty | 888 | 11.55 | 389.7 | 6.24 |
| 5 | loaded | 15 | 9.14 | 389.7 | 6.03 |
| 6 | empty | 1071 | 9.20 | 389.7 | 6.07 |
| 6 | loaded | 15 | 11.76 | 389.7 | 5.88 |
| 6 | fault | — | — | 768.0 | 3.37 |

The fault row has no request-distribution p95; every
actor instead completes one surviving application read after its faults. Cgroup peaks
are cumulative since start, not independently reset for each phase. CPU usage and
throttling deltas are in the validation record; raw evidence retains IO, PSI, quotas
and every host/runtime sample rather than substituting idle CPU for reserved capacity.

All six actors proved workspace/control/scratch byte exhaustion, deleted-open charging,
control inode exhaustion, SQLite rollback/reopen preserving acknowledged data, PID and
FD exhaustion, read-only shared memory and a bounded OOM-killed child while the app
survived. Rotating logs retained three files/about 4.38 MB per actor below the declared
three × 2-MiB allowance. All six containers stopped and no stop failures remained.
Exit 137 after the fixture stop deadline is containment, not an unobserved application
success; all application/fault results were collected before stopping.

## Candidate budget and admission boundary

Per runtime: 768-MiB RAM, 250 millicores, 64 PIDs, 512 FDs, read-only 1-MiB shm;
256-MiB workspace/8,192 inodes, 64-MiB control/4,096 and 128-MiB scratch/4,096;
three 2-MiB log slots plus 1-MiB/1,024-inode boot metadata reservation. Full ceilings
are reserved even for retained/cleanup-pending resources. Shared reserve holds
1.5-GiB RAM, 500 millicores, 512 PIDs, 4-GiB data and 9-GiB boot plus declared
inodes. Future-recovery reserve holds 512-MiB RAM and 1-GiB data/20,000 inodes.
The 50,000,000-byte Free logical allowance is separate. These physical reserves are
candidate inputs exercised by the trial, not production entitlements or H05 recovery
proof. Shared memory is already charged within the RAM ceiling.

Fresh planning counted every retained kernel project hard limit, all current runtime
holds and unknown/unbounded records; an incomplete observation never becomes a clean
admission result. Both total reservations and actual available resources must fit.
Six runtimes is the bounded measurement population, not a product cohort cap. With
these inputs, a seventh full runtime would exceed the 2,000-millicore CPU reservation
budget (500 shared + 7 × 250); H04 must still recompute current physical and durable
commitments, not infer authority from that arithmetic or from this file.

## Corrected failures and limits

- Actual application startup exposed a missing native `chmod` alias in the sandbox.
  Only that alias was added alongside existing fchmod/fchmodat. Changed-policy native
  security requalification passed owned chmod and protected-path denials; previous
  runtime-policy acceptance is not inherited.
- Repeated scratch backup initially failed with SQLite EIO. Explicitly closing backup
  connections fixed it without increasing the 128-MiB scratch ceiling.
- Trial 4 passed two/five workloads but refused the sixth: host memory consumption
  outside recorded runtime use exceeded the shared reserve. Its cause remains
  unexplained; retain it as observed environmental variability, not a fixed bug or
  fabricated capacity pass. Fresh trial 5 permitted the sixth and passed all phases.
  Future admissions must use current complete observations and refuse that condition.
- The final Linux artifact also validates from macOS. Evidence errno values use the
  Linux ABI (EDQUOT 122, EAGAIN 11), not the inspecting machine's errno constants.
  This post-measurement portability correction preserves native Linux behavior and
  changes no workload, runtime policy or measured budget. Native source pin remains
  immutable snapshot 5; H02.11 owns final-source consolidated acceptance.

## Validation and remaining owners

72 focused tests pass: pure planning/rounding/unknown/freshness/revision/overflow;
collector malformed/missing/retained projects; evidence mismatch/partial/fault failures;
original-error-plus-cleanup containment; source custody and changed sandbox regressions.
Changed-file Ruff check/format check pass on all ten Python files. No full suite or
frontend changes.

| Area | Evidence |
| --- | --- |
| Happy paths | Actual 2/5/6 application, loaded/WAL/backup and six fault workloads. |
| Invalid combinations | Unknown/incomplete/stale/mismatched observations and permissive artifacts reject. |
| Idempotency/retry | Pure planning never mutates; holds/revisions/repeated identities tested. H04 owns durable serialized commits/reconciliation. |
| Rollback | Native quota/WAL preserves acknowledged row; failed stop test retains original error and stops remaining containers; no profile on failure. |
| Persistence/schema | No DDL; strict versioned candidate plus exact measurement/source/policy identity checked. |
| Backup/restore | Consistent bounded synthetic SQLite backup measured. Whole-workspace/off-host restore remains unavailable pending H05. |
| Query/performance | Bounded kernel/cgroup observations, no recursive business-data scan; CPU/RSS/IO/PSI/latency evidence retained. |

Private raw evidence:
`/Users/dcai/Desktop/Property-Management-Data/hosted-mvp-qualification/H02.10/`:
`source-5.tar/json`, `measurement-5.json`, `candidate-profile-5.json`,
`published-5.json`, `live-host-memory-5.jsonl`, native logs and failed-trial records.
Native lab `/srv/epm/data/qualification/h02-capacity-37b1582717894e2a8585828b47ed3e40`;
source `/opt/epm/capacity-source-5`. All prior labs/UIDs/projects are retained and counted.

H04 owns actual serialized admission and logical metering; H05 owns recovery; H02.11
owns consolidated/final-source acceptance and promotion. No invitation or consequential
browser controls are enabled. The qualification VM and disks are stopped and retained
once the stop receipt in `final-stop.log` is verified; provider configuration, unrelated
resources and Lima baselines are unchanged.
