# H02.5 — Private projects, sandbox and guarded lifecycle

Delivered within the component/ARM64-lab scope on November 11, 2026, continuing partial
commit `da8aec4a` on `hosted_mvp`. The [runtime runbook](../../operations/runtime-supervision.md)
explains the guard, stop-only projection and repeatable isolated tests. Exact observations
and tested runtime sources are in the [native report](HOSTED_MVP_H02_5_NATIVE.json);
[validation metadata](HOSTED_MVP_H02_5_VALIDATION.json) pins the changed source and checks.
No live demo, cloud resources, customer data or original quota-test VM were changed.

## Delivered behavior

- Three private ext4 projects per inventory-bound operator, distinct retained UID/GID,
  inheritance and byte/inode ceilings established before writer access. No adoption,
  reformat or automatic cleanup after a partial preparation failure.
- Read-only container root, bounded writable paths, native syscall/ioctl allowlist,
  AppArmor, no-new-privileges, dropped capabilities and explicit resource/log ceilings.
  Control data is writable separately from its read-only stable writer-lock root.
- Guarded create/start/stop/repair/stopped-limit changes, immutable original receipts,
  inspect-only uncertain retries and actual sandbox/mount/quota checks. No blind repeat
  allocation or competing Docker restart loop.
- Independent, protected **stop-only** exact-ID projections before starts; current
  singleton lease/readiness epoch and a start/stop barrier. Missing/corrupt inventory
  can no longer prevent containing an already registered container. Projections cannot
  allocate, rebind or start a runtime and are not an alternate inventory database.
- Bounded guardian polling and systemd ExecStopPost recovery after process death.
  Unknown checks keep targets stopped/held with sanitized attention. Failed stop/engine
  observations are never reported as verified containment. Original and containment/
  persistence failures are retained together where applicable.

The standalone unit defaults to containment-only; production authenticated source,
qualification and external-deny composition stays with H02.6/H02.7. No test grant or
normal hosted application route is enabled by this slice. Artifact rebuilding and
promotion remain independently gated; the H02.4 images predate this runtime change.

## Hardened test diagnosis and fix

The failed lab `epm-quota-qualification-vscmtzyf` missed its stop deadline. Reproduction
in `_249hwma` instrumented only the private fixture and isolated the delay to Docker's
stop request. The kernel reported AppArmor `operation="signal"`, `denied_mask="receive"`,
signals TERM/KILL and `peer="runc"`. The policy only allowed `unconfined` and same-profile
signals. Docker's fallback took 12.068 s; this was not an HTTP or inventory-read problem.

The fix permits receive TERM/KILL from the **exact host runc profile**. No other policy
was relaxed, and the test deadline was unchanged. The focused corrected reproduction
`pgqr6n95` stopped in 0.041 s and passed unknown-inventory and guardian-SIGKILL recovery.
The complete corrected run `sizrozul` then passed all recorded native cases, with the
hardened service settings. Failed labs/journals remain privately retained; historical
partial reports are unchanged. Guest journals use UTC; the report date is the operator's
November 11 Pacific date.

## Focused validation matrix

| Area | Observed result and limit |
| --- | --- |
| Happy paths | Two synthetic owners/six projects, actual Docker starts, WAL/file writes, stopped replacement and log rotation passed on native ARM64 Linux. |
| Invalid combinations | Unsafe locks/projections, changed sandbox settings, missing/stale owner readiness, competing initialization, live-writer repair/limit changes and unknown prerequisites reject. Native mutation ioctls, quota/mount/namespace calls, sibling reads and unbudgeted writes are denied. |
| Idempotency/retry | Real NativeEffects plus SQLite receipt tests prove no duplicate create/repair/start after lost/failed result commits. Unknown effects inspect original identity. Partial limits remain unknown until the entire desired physical profile is verified. |
| Rollback/failure | Mode-000 partial reservations never grant writers. All three trees enforce byte/inode/deleted-open EDQUOT. WAL exhaustion produced SQLITE_IOERR_WRITE (778); rollback/reopen retained the original row and valid integrity. Lost stop responses are independently inspected; uncertain stops stay unresolved. |
| Persistence/schema | Existing inventory owns UID/project/binding/fence records and exact revisioned observations. No new DDL/schema migration. Stable control-lock device/inode survived container replacement. Original receipts survive attention updates and consistent inventory snapshots. |
| Backup/restore | Inventory snapshot/reattach regression and replacement preserve identities/receipts/control lock. H05 still owns authenticated/encrypted/off-host recovery; no restore completion is asserted here. |
| Query bounds | Guards read one owning target and three kernel projects; no recursive usage scan on regular checks. Stop projection scans have a 4,096-record safety bound, not an operator admission cap. Recursive attribution scans are explicit stopped-lab checks. No database writer spans Docker/quota effects. |
| Supervisor recovery | Stale owner epochs cannot authorize starts. Missing/corrupt inventory stops from exact protected IDs. Real systemd guardian SIGKILL, ExecStopPost and one service restart left the container stopped. No unsafe automatic recreation/restart. |
| Resource limits | Actual cgroup CPU/memory/swap/PID and descriptor/core ceilings matched; shared memory/control/root writes were blocked. Docker log rotation retained at most two bounded files under the explicit workload. These fault sizes are not production capacity. |
| Local compatibility | Local workspace lifespan retains its existing writer lock; explicit hosted locking does not change the default local composition. |

Result: **277 focused tests passed in 48.82 s**, no full suite or browser tests.
Ruff check and format --check passed on all **20 H02.5 changed Python files**, using the
application configuration. No frontend implementation/tooling changed.

## Qualification limits and handoff

Native lab: retained clone `epm-h02-runtime`, Ubuntu 24.04 ARM64, kernel
6.8.0-147-generic, Docker 29.1.3; exact versions and tested source hashes are in the
report. Six 8-MiB/256-inode project ceilings are deliberate fault fixtures, not Free
entitlements or an accepted production capacity profile. A test workload image proves
this sandbox boundary; it does not qualify the complete hosted Operator application.

The original `epm-quota-test` remains the stopped recoverable baseline. The clone and
all labs are retained and stopped when idle. Private raw results, complete source pins,
archives and journals remain under `hosted-mvp-qualification/H02.5/` outside Git.

H02.6 retains actual ingress/egress/secret proofs; H02.7 actual hosted launch and safe
unavailable UI; H02.8/H02.9 exact AMD64/GCP and actual host-reboot requalification;
H02.10 measured warm capacity and physical headroom; H02.11 aggregate acceptance.
H03–H05 source/auth/recovery gates and H06 invitation authority remain unavailable.
Neither a valid stop projection, running guardian nor a passing ARM64 component proof
can close those gates.
