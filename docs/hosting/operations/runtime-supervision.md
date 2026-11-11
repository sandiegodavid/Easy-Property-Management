# Private storage, sandbox and runtime supervision

[Tool source](../../../application/deploy/hosted-mvp/sandbox) · [Foundation guides](../foundation/README.md)

This is a candidate host boundary, not a deployed application. H02.7 owns the fresh
hosted composition; H03–H05 own source identity and recovery. Normal hosted startup
and customer ingress remain unavailable. Use the [handoff and validation matrix](../qualification/reports/HOSTED_MVP_H02_5_HANDOFF.md)
for delivered scope and the [native result](../qualification/reports/HOSTED_MVP_H02_5_NATIVE.json)
for tested sources, kernel, image and observations.

## Runtime ownership

The private host agent derives workspace/control/scratch projects from its owning
inventory. It verifies ext4 accounting **and enforcement**, assigns inheritance and
hard byte/inode ceilings, then grants the operator's distinct UID/GID access. Interrupted
preparation retains mode-000 trees; it never adopts or relabels an existing tree.

Operator containers get a read-only image/root, dropped capabilities, no-new-privileges,
native-architecture syscall allowlist and named AppArmor profile. Scratch backs `/tmp`
and `/var/tmp`. The control root is read-only; only its `data/` directory is writable.
The stable `writer.lock` inode is precreated outside replaceable business data and
opened read-only for exclusive locking. Every permitted business-opening process must
use that same lock. Local native workspace defaults remain unchanged.

Memory/swap, CPU, PIDs, file descriptors, shared memory and rotating logs are bounded
by an explicitly supplied profile. No Docker automatic restart, host namespaces,
extra capabilities/devices, root/Docker socket mount or published ports are permitted.
H02.5 uses network `none`; H02.6 must implement and requalify the registered bridge,
gateway and controlled outbound boundary. The fault profile is not a production capacity
or Free entitlement profile; H02.10 owns measured reservations and sizing.

## Independent stop-only containment

Protected setup creates `/var/lib/epm-host/stop-targets` as root-owned 0700 before a
service starts. `StopRegistry` does not create inventory or adopt running containers.
It fsyncs an immutable exact-container-ID projection before any permitted start. Only
host root can access it; it is never mounted in an Operator. It contains non-secret
scope/identity references solely for safe stop/owning lookup. Inventory remains the
only allocation/start authority. Keep these projections when inventory is unavailable;
never reconstruct inventory from them or from Docker labels.

One guardian holds the owner lease. A start also needs its current readiness epoch,
current inventory/qualification/external-deny checks and the shared start/stop barrier.
Startup and shutdown contain every registered target before any new start readiness.
A crash after start still leaves its stop projection. Lost stop replies require actual
inspection; an unreachable engine or still-running target retains `stop_verified=false`
and needs attention. Bad records do not skip other valid targets. Records are bounded
at 4,096 as a protected scan-safety bound, not an operator entitlement/admission limit;
retirement cleanup must preserve exact ownership and cannot blindly delete them.

`epm-host-guardian.service` supplies the systemd singleton/restart/ExecStopPost handoff.
It restarts only the guardian, never containers. The standalone guardian intentionally
runs containment-only and publishes no start readiness until H02.7 composes the real
owning agent ports. Do not install qualification adapters or enable this candidate on
an existing host as a shortcut. Protected installed paths, directory reservation,
service ordering and production qualification remain owning setup/launch work.

For a **previously configured isolated host only**, the narrow stop command is:

```sh
/opt/epm/agent/bin/python -B -m app.modules.host_agent.infrastructure.supervisor \
  --registry /var/lib/epm-host/stop-targets --contain-all
```

This never starts, repairs, reallocates or deletes a runtime. If its outcome is unknown,
keep external denial and investigate; do not report containment from a request alone.
An operator workflow or browser must not accept this path or Docker identifiers.

## Reproduce the native proof in the retained clone

The original Lima `epm-quota-test` remains the stopped recoverable baseline. The
separate retained clone `epm-h02-runtime` contains Docker and private test dependencies.
It has no host mounts/credentials and is stopped when idle. Start it explicitly:

```sh
limactl start epm-h02-runtime --tty=false
```

Copy only current runtime `.py`/required `.c` sources under `apps/server/app` (exclude
`tests`, caches and compiled assets), plus this sandbox folder, in an archive preserving
their application-relative paths. Do not copy `.git`, credentials, workspace content,
Mac environments or previous lab outputs. The prior exact source archive is retained
privately under `hosted-mvp-qualification/H02.5/native-final-source.tar`; use fresh
sources for a new qualification, not that archive as proof of subsequent edits.

```sh
limactl copy /private/path/source-only.tar epm-h02-runtime:/tmp/source-only.tar
limactl shell --workdir=/tmp epm-h02-runtime sh -c \
  'mkdir -p /tmp/epm-h02-source && tar -xf /tmp/source-only.tar -C /tmp/epm-h02-source'
limactl shell --workdir=/tmp/epm-h02-source epm-h02-runtime sudo env \
  EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 \
  PYTHONPATH=/tmp/epm-h02-source/apps/server \
  /var/lib/epm-h02-runtime-tools/bin/python -B \
  deploy/hosted-mvp/sandbox/qualify_runtime.py --run
```

The explicit opt-in harness requires root Linux, disabled Python optimization and a
fresh guarded laboratory via the imported `Laboratory.create`. It never accepts an
existing data device as its target. Each run creates a disposable loop-backed ext4
image, synthetic users, root-owned source snapshot and isolated test image. The service
snapshot lives outside `/tmp` because the hardened guardian uses `PrivateTmp`.

Retain the printed lab root, `h02-runtime-result.json`, source/profile/tool hashes,
`guardian-fixture.json`, systemd journal, kernel denials and image identity privately.
Failure retains the lab and emits a failed result. Diagnostic timing output exists
only in the explicit qualification fixture; production guardian output is sanitized.
Test-only source/admission adapters are never production authority. The harness creates
transient systemd units; it stops/removes their test containers but preserves lab data.

After collecting evidence:

```sh
limactl stop epm-h02-runtime --tty=false
limactl list --format '{{.Name}} {{.Status}}'
```

Do not delete either VM or qualified/failed laboratory trees during routine cleanup.
Shutdown is not a host-reboot qualification pass. H02.8/H02.9 must re-prove native
AMD64/GCP, reboot and changed source/runtime/UID/security configuration separately.

## Hardened guardian signal regression

The Ubuntu host runs the container runtime helper under the AppArmor profile `runc`.
The initial Operator policy accepted signals only from `unconfined` or the same
Operator profile. Kernel audit records therefore denied TERM/KILL from `runc`; Docker
fell back to a later direct kill after the original test deadline. The policy now allows
**receive TERM and KILL only** from that exact host profile. It does not allow arbitrary
signals/peers, weaken seccomp or use unconfined mode. The unchanged 12-second proof
passed, with a measured diagnostic stop of 41 ms instead of 12.068 s.

The [systemd service contract](https://www.freedesktop.org/software/systemd/man/256/systemd.service.html)
defines ExecStopPost cleanup after unexpected exits/restarts. The native test actually
kills the guardian, verifies its stop hook and restart, and proves the container stays
stopped; the documented behavior alone is not qualification.

For current reproducible development and native/reboot procedures, use the
[H02.8 lab runbook](../deployment/linux-development-and-qualification.md). It preserves the stopped baselines and separates
Desktop/emulated AMD64 from native ARM64 and future target-host acceptance.
