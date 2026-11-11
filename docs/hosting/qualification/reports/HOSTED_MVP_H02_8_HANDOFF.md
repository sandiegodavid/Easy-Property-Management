# H02.8 development and isolated native qualification handoff

Delivered November 12, 2026, within Mac Docker/Desktop and native ARM64 lab scope.
The [executable runbook](../../deployment/linux-development-and-qualification.md)
contains source transfer, exact-image probes, development origins, native prerequisites,
actual reboot continuation and retention/shutdown commands. The
[validation manifest](HOSTED_MVP_H02_8_VALIDATION.json) records exact pins, failed
attempts, successful cases and raw-evidence hashes. This is scoped infrastructure
evidence, not an aggregate v1 promotion proof or permission to admit customers.

## Delivered behavior and observations

- Deterministic source-only archive with per-file hashes; links, caches, tests,
  environment/data files and compiled assets excluded. Existing output cannot be
  overwritten. The tested manifest matches the current selected source files.
- Exact-ID Docker Desktop probe driver verifies component/image identity and runs
  installed candidate checks with no network, writable root or mounted checkout.
  Only the probe source is read-only mounted; synthetic stores use disposable tmpfs.
  Fresh current Admin and Operator AMD64 candidates passed on the ARM64 Desktop
  engine under emulation. Missing owned stores remain unavailable, not initialized.
- Development Compose provides explicit `127.0.0.1:18801` and `:18802` origins,
  fixed health-only modes, non-root/read-only containers, dropped capabilities,
  bounded memory/PIDs/logs, no restart policy and no data/credential volumes.
  Both origins returned the safe unavailable page. No mock login or production
  admission adapter was added. The development bridge does not provide production
  outbound isolation; the native connected fixture tests that separate boundary.
- Stopped baseline VMs `epm-quota-test` and `epm-h02-runtime` were preserved. A new
  retained clone, `epm-h02-8`, ran source-only inputs with no host-folder mounts.
  Native Ubuntu ARM64 kernel `6.8.0-149-generic` and Docker `29.1.3` are pinned
  separately from Desktop's engine and emulated AMD64 candidates.
- Current native runtime proof passed bytes/inodes/deleted-open quotas, WAL failure
  and rollback, ioctl/mount/namespace and cross-UID denials, cgroup/log limits,
  second-writer denial, lock-preserving replacement, quota-off negative control,
  missing-inventory containment and actual guardian SIGKILL/restart behavior.
- A real guest reboot changed the Linux boot ID. Two exact registered Docker
  containers remained stopped with automatic restart disabled. All six project
  quotas/usage and both stable lock inodes survived. The continuation remounted
  only its lab image and re-proved sandbox/WAL, each tree's EDQUOT and cross-UID
  denial. Exact source/kernel/Docker pins were unchanged; repeating the completed
  continuation performed no actors/remount or command replay.
- The connected current-source proof passed after explicit bridge-filter setup,
  including current network inspection and containment after firewall loss.

All laboratories, including failures, remain in the retained stopped clone. Local
Compose containers/network were removed after verification; new candidate images and
all private logs/archives/reports remain under the location in the validation manifest.
Neither original VM was started or modified; no cloud, provider or user data was used.

## Validation matrix

| Area | Result |
| --- | --- |
| Happy paths | Fresh source archive; two exact installed-image probes; both loopback origins; real native runtime, connected sandbox and actual reboot continuation passed. |
| Invalid combinations | Mutable/unsafe image selectors, linked source inputs, changed source/manifest bytes and existing output paths reject. Missing quota/bridge prerequisites failed closed and are retained as failures. |
| Retry/idempotency | Archive/report outputs are exclusive; post-reboot continuation rejects the same boot or changed pins and returns the completed result without replay. Docker restart policy remains `no`. |
| Transaction rollback | Native WAL exhaustion retained the original row after failure/reopen. No production transaction/receipt behavior changed by the lab tooling. |
| Persistence/schema | Installed-image probes validate owning resources with synthetic stores; missing H03/H05 stores remain unavailable. Kernel quota observations and lock inodes survived actual reboot. No DDL or migration added. |
| Backup/restore | No backup implementation changed. The reboot proof is persistence evidence, not H05 authenticated/encrypted recovery or restore acceptance. |
| Query budget | No directory/projection implementation changed. Regular native checks inspect one binding/three projects; source hashing is an explicit qualification operation, never a business request. |
| Isolation/platform | Native ARM64 Linux/Docker results and Desktop/emulated AMD64 results have separate exact source/image/kernel/tool pins. No new ARM32/compat or native AMD64 pass is claimed. |

Focused validation: **44 tests passed** across the new lab tests, existing packaging
and artifact tests. Ruff check and format check passed for all changed Python files
using `application/pyproject.toml`; no suppressions or rule changes. No full suite ran.
The Operator candidate build checked contracts and rebuilt its packaged frontend;
no frontend source or frontend tooling was changed.

## Failed attempts retained

1. The clone's first boot selected kernel 6.8.0-149, without matching quota extras.
   `quota_v2` could not load. Installing only that kernel's matching package in the
   clone resolved the prerequisite; neither baseline VM was altered.
2. The first connected run after reboot lacked `br_netfilter` sysctls. It rejected
   before runtime start. Its lab and raw traceback are retained; explicit module and
   both bridge-filter sysctls preceded a fresh successful run. Production checks were
   not changed to mutate or assume these prerequisites.
3. A restricted-sandbox offline wheel build exited 2. The same closed pinned build
   succeeded with access to its existing build cache; no dependency constraint changed.
4. Docker Desktop did not publish ports for the initial `internal` development
   bridge. Actual inspection showed empty published mappings despite running
   processes. The corrected development bridge publishes only loopback ports;
   in-container and host requests then both returned the expected HTTP 503.

## Remaining owners

H02.9 must qualify the actual native AMD64/GCP platform, exact target kernel bytes,
protected boot setup, provider configuration and target-host reboot. ARM64 lab evidence
and emulated AMD64 execution cannot establish those gates. H02.10 owns measured
capacity/headroom; H02.11 owns consolidated acceptance. H03–H05 still own real
identity/access/Admin and recovery behavior, and H06 owns invitations. No current
candidate became a qualified release and ingress remains held.
