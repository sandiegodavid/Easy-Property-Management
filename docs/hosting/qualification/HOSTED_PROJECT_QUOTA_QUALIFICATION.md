# Project quota and sandbox qualification — Slice 8A

November 1, 2026: **passed on the isolated local ARM64 Linux VM**. This establishes
platform feasibility for the tested boundary, not live-host qualification, tier
overhead measurements, host capacity, provisioning or permission to enable a
project-backed operator. Those remain in Slices 8B–8H and 9.

## Delivered boundary

`hosted_admin/infrastructure/project_quota.py` is a private root-only adapter for
an explicitly bound ext4 mount UUID, directory, nonzero project ID and service
UID. It rejects changed filesystem identity/features, symlinked/unprotected
ancestors, missing inheritance, missing hard limits and disabled enforcement.
Hard bytes are rounded upward to 1,024-byte quota blocks; observations report
kernel allocation/inodes separately from limits. They never substitute host free
space or claim a usable workspace allowance. Empty-destination initialization
does not recursively convert existing content. The explicit stopped-writer
descendant check is bounded to 100,000 entries; it is not an HTTP usage scan.

Ext4 can retain quota **accounting** after enforcement is disabled. The probe
therefore checks both project flags from `Q_XGETQSTATV`, as well as actual limits;
`Q_GETINFO`, mount-option text and a successful service start are insufficient.

The candidate service boundary combines **both**:

- `project_sandbox.py`: native syscall architecture, a systemd syscall allowlist,
  no capabilities/privilege gain or namespaces/mount/quota-control calls, a
  read-only host filesystem and three explicitly writable project directories.
  `/tmp`, `/var/tmp` and TMPDIR use the scratch project. `/run` and `/dev/shm` are
  read-only rather than unaccounted writable tmpfs storage.
- `quota_sandbox_exec.c`: a seccomp filter inherited across exec/children that
  permits only `FIOCLEX`, `TCGETS` and `FIONBIO` ioctl requests. All other ioctl
  encodings are denied, including filesystem/project mutation and compatibility
  encodings. A blanket ioctl denial broke CPython's script-open path because it
  uses `FIOCLEX`; the narrow harmless allowlist preserves normal operation.

Neither component alone is the qualified boundary. The systemd allowlist also
denies unlisted future syscall interfaces; any new kernel/systemd/tool/profile
requires fresh qualification. No service can choose a project ID or private path
through HTTP. Existing loop-backed installations and their sandbox are unchanged.
Collector failure uses existing independent Admin observation failure/staleness
presentation; the focused console test proves access observations can still
succeed without inventing healthy storage. Binding this collector to the new
protected inventory and usable tiers belongs to subsequent slices.

## Observed evidence

- [Before reboot](reports/HOSTED_ADMIN_8A_2026-11-01_BEFORE_REBOOT.json)
- [After reboot](reports/HOSTED_ADMIN_8A_2026-11-01_AFTER_REBOOT.json)

These are actual harness outputs with different boot IDs, source/tool/launcher
digests, kernel configuration digest, filesystem UUID, sandbox properties and
per-case results. Source/tool pins were compared again before post-reboot tests.
They are evidence, not signed provisioning grants or capacity-promotion inputs.

Environment: retained `epm-quota-test` Lima VM, Ubuntu 24.04.5 ARM64,
`6.8.0-142-generic`, e2fsprogs 1.47.0, systemd 255, libseccomp 2.5.5. Two fresh
non-login Unix identities ran transient services over one disposable shared ext4
image with separate workspace, scratch and control project directories. The
kernel rejected a real statically compiled ARM32 ELF with `ENOEXEC` before
sandboxing; compatibility ioctl encodings were tested directly and denied.
This does not claim a successful compat-program sandbox test on hardware that
cannot execute that ABI. The harness requires `SIGSYS` if ambient compat execution
is supported. x86 or another ARM kernel/hardware combination remains unqualified.

| Area | Focused proof |
| --- | --- |
| Happy paths | Real UID writes, SQLite WAL commit/checkpoint, nested files and accounted temporary files succeed under the complete boundary |
| Isolation/escapes | Native/compat mutation ioctls on files and directories, child exec inheritance, cross-user access, cross-project links/renames, raw-image access, mount/quota/user-namespace calls and unbudgeted writable paths fail |
| Hard limits | Unprivileged block and inode exhaustion return `EDQUOT`; allocated bytes/inodes do not exceed hard limits; deleted-open bytes remain charged; the other operator's evidence hash is unchanged |
| Invalid facts | Wrong UUID, project-zero descendant, symlink, missing mount and disabled enforcement are rejected; with enforcement deliberately off, the negative control can exceed the limit |
| Retry/persistence | Remount preserves facts; a real VM stop/start changes boot ID, preserves all six project observations and still enforces an actual write limit |
| Transaction behavior | SQLite commit/checkpoint is exercised; storage-policy receipts/compensation are not introduced in 8A and remain in 8B/8F |
| Recovery | Reboot evidence pins are verified; business backup/restore and destination project rebinding remain explicitly in 8D |
| Bounds/read failures | Explicit scan bound and metadata-only observations; sanitized failure in the existing independent Admin runtime section |

Repository checks: **36 focused pytest tests passed** across project contracts,
console reads and observation adapters. All six changed Python files passed Ruff
check and format check. The launcher compiled with `-Wall -Wextra -Werror`; the
real Linux harness passed, including reboot, with no skipped kernel case.
No frontend code changed and no full application suite was run.

## Repeat locally

Follow [the retained VM runbook](LOCAL_LINUX_VM.md). Inside the guest, install the
base tools plus the matching optional kernel modules and compatibility compiler:

```bash
sudo apt-get install -y linux-modules-extra-"$(uname -r)" gcc-arm-linux-gnueabihf
sudo modprobe quota_v2
```

The minimal Ubuntu image initially lacked `quota_v2`; a configured kernel option
alone did not make the test mount work. On x86, use its appropriate native/multilib
toolchain instead and qualify that environment independently.

Copy only `project_quota.py`, `project_sandbox.py`, `quota_actor.py`,
`quota_sandbox_exec.c` and `project_quota_qualification.py`, retaining their
`app/modules/hosted_admin/infrastructure/` paths, into a root-owned guest source
directory such as `/var/lib/epm-s8a-code`. Do not copy business workspaces or secrets.
From that directory in the guest:

```bash
sudo env EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 python3 -m \
  app.modules.hosted_admin.infrastructure.project_quota_qualification run \
  > /tmp/epm-quota-before.json
```

Save that JSON outside the guest and record its generated `root` value. Stop and
start only this local VM from macOS. Do not change the copied source or tools
between phases. Inside the guest source directory, substitute that exact root:

```bash
sudo env EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 python3 -m \
  app.modules.hosted_admin.infrastructure.project_quota_qualification \
  after-reboot --root /var/lib/epm-quota-qualification-REPLACE_WITH_EXACT_ROOT \
  > /tmp/epm-quota-after.json
```

Retrieve the result with `limactl copy`. Only `status: passed` with all required
results and matching source/tool pins establishes this harness run. A failed run
retains its tree/identities for diagnosis, and must remain failed in evidence.
The harness refuses missing explicit opt-in, non-root/non-Linux execution and
optimized Python, which could disable assertions. It formats only its freshly
created image, never an existing device or the VM root disk.

After preserving results, explicit cleanup uses the same root:

```bash
sudo env EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 python3 -m \
  app.modules.hosted_admin.infrastructure.project_quota_qualification \
  cleanup --root /var/lib/epm-quota-qualification-REPLACE_WITH_EXACT_ROOT
```

Cleanup refuses a busy unmount rather than forcing it. Retain uncertain artifacts
and identities until inspected. This removes only that harness image/tree/users;
keep the VM itself and stop it when idle.

## Private installation boundary

Before any production installation, inspect filesystem UUID/features, inode size,
quota support/modules and the exact service sandbox on the separately authorized
host. The tested harness creates a new ext4 image with `quota,project`, 256-byte
inodes and an initialized project-quota inode, then mounts it with enforcement.
Those image/format/mount commands are **test-only**, not per-operator provisioning.

An existing filesystem may need offline checks, feature enablement, unmounting or
reboot, depending on its current features and kernel. There is no universal safe
online-enable command: stop for an explicit private maintenance plan if features
are absent. Add operator must never perform host feature changes. A shared data
filesystem may be separately installed only when necessary and authorized.
Re-prove real UID writes, byte/inode enforcement, all escape interfaces and
persistence on the exact target; no fallback to application-only limits is allowed.

Technical interfaces:
[Linux quota ABI](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/dqblk_xfs.h),
[filesystem attribute ABI](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/fs.h),
[systemd syscall and filesystem sandbox](https://www.freedesktop.org/software/systemd/man/255/systemd.exec.html).
