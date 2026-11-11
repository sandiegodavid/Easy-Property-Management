# Project-quota qualification reuse for H02

Imported November 10, 2026 from `Admin_UI_Workflow` at
`cba6a7bf2561de06634abbddff0b60782949e6fc`, staying on `hosted_mvp`.
This is a selective import for [H02](../design/mvp/delivery-plan.md#implementation-slices),
not H02 implementation or runtime activation. Complete H02's detailed design before
adapting or integrating these components.

## Imported scope

The original package namespace is retained to preserve imports and reproducibility;
only empty package markers plus these files/tests are copied. No Admin router,
provisioning service, schema, billing, collector, source storage ledger or production
activation path is imported.

| File under `application/apps/server/app/modules/hosted_admin/` | Use |
| --- | --- |
| `infrastructure/project_quota.py` | Root-only Linux ext4 primitives: protected bindings, filesystem/enforcement checks, inheritance, byte/inode limits and observations |
| `infrastructure/project_sandbox.py` | Original systemd sandbox candidate; not a Docker configuration |
| `infrastructure/quota_sandbox_exec.c` | Original narrow ioctl seccomp launcher; preserve together with the sandbox intent |
| `infrastructure/quota_actor.py` | Adversarial unprivileged-UID workload for disposable Linux testing |
| `infrastructure/project_quota_qualification.py` | Explicit-opt-in root Linux harness, fresh disposable image, reboot continuation and guarded cleanup |
| `tests/test_project_quota.py` | Focused contracts/mocked failures; not native enforcement proof |

Exact upstream blob IDs/SHA-256 values, evidence hashes and source-pin comparisons are
in [PROJECT_QUOTA_IMPORT_MANIFEST.json](PROJECT_QUOTA_IMPORT_MANIFEST.json).
No file is wired into bootstrap, a portal, host-agent endpoint or source admission.
Do not interpret the imported namespace as a complete hosted Admin implementation.

## Historical evidence and its limits

Unchanged imported report files:

- [Before reboot](reports/HOSTED_ADMIN_8A_2026-11-01_BEFORE_REBOOT.json): `awaiting_reboot`.
- [After reboot](reports/HOSTED_ADMIN_8A_2026-11-01_AFTER_REBOOT.json): `passed` for its pinned sources/environment.

These describe a local ARM64 Linux VM, Ubuntu 24.04.5, kernel `6.8.0-142-generic`,
ext4, systemd sandbox and seccomp launcher. Tested properties include byte/inode
EDQUOT, deleted-open attribution, cross-user/project and ioctl escape rejection,
disabled-enforcement negative control, remount and actual VM reboot. They do not
qualify Google Cloud, Docker, production tier sizes or current source activation.

**The imported branch tip is not the historical qualification snapshot.** Current
`project_quota.py`, `project_quota_qualification.py` and `project_sandbox.py` differ
from the historical report's source SHA-256 pins. `quota_actor.py` and
`quota_sandbox_exec.c` match. Preserve original evidence unchanged; rerun native
qualification with all current source/tool hashes before claiming a new pass.

The [original qualification text](../archive/project-quota-Admin_UI_Workflow/HOSTED_PROJECT_QUOTA_QUALIFICATION.md)
and [original retained-VM runbook](../archive/project-quota-Admin_UI_Workflow/LOCAL_LINUX_VM.md)
are preserved byte-for-byte as historical snapshots. Their relative links describe
the upstream branch's wider document tree; this import deliberately does not bring
that old implementation plan or Slice 8C stack into current delivery.

## Development versus native qualification

| Environment | Intended use | Evidence boundary |
| --- | --- | --- |
| Docker Desktop on the Mac | Routine hosted-container development, portal/browser/API integration | Does not prove native ext4/project enforcement, privileged host operations or Google VM compatibility |
| Retained Lima `epm-quota-test` | Isolated ARM64 Linux quota/sandbox/host-agent and reboot qualification | Exact guest/kernel/filesystem/source/tool pins only; Docker qualification needs its actual container setup |
| Target Google VM | Final deployment/storage/runtime qualification | Exact admitted cloud image, filesystem, Docker and source configuration |

Keep the Lima VM stopped when unused and preserve existing lab trees/evidence. It was
observed stopped on November 10, 2026, configured with 2 CPUs, 4 GiB memory and a
20 GiB virtual disk; inspect current state again before use. The earlier runbook's
no-host-mount/plain-VM assumptions are historical, not a claim about uninspected
current guest packages. No Docker installation or guest configuration change is
performed by adopting this development split.

Before installing Docker or updating kernel/filesystem/tools in the qualification VM,
preserve a recoverable baseline and record the modified runtime/source pins; rerun
applicable native proofs. Use distinct source snapshots and disposable laboratories,
not the previous qualified trees as a mutable development checkout. H02 must first
have a detailed design for any VM/container setup changes. Routine Mac development
can proceed separately; it does not require starting or modifying the retained lab.

## Current verification

From `application/`, the import was checked with:

```bash
.venv/bin/python -m pytest apps/server/app/modules/hosted_admin/tests/test_project_quota.py -q --tb=short
.venv/bin/ruff check apps/server/app/modules/hosted_admin
.venv/bin/ruff format --check apps/server/app/modules/hosted_admin
```

Result: 23 focused tests passed; Ruff check and format check passed for all eight
Python files, including empty package markers. This runs on the development Mac.
No privileged harness, VM reboot, native C/Linux sandbox or cloud test was run here.

## Required H02 adaptation and requalification

1. Design the restricted host-agent/resource bindings against the current schema
   master. Preserve UUID/ownership/symlink/project inheritance and kernel enforcement
   checks. Do not import old Admin schemas or activate project-backed sources.
2. Use a disposable qualified Linux environment to rerun the imported primitive
   harness with its current source hashes, native tools and reboot proof. The retained
   VM runbook is a reference; verify actual VM/runtime state before relying on it.
   Native harness requires root Linux, no optimized Python and explicit
   `EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1`; never point it at a live data device.
3. Adapt the complete sandbox/security intent to actual non-root Docker runtimes.
   Re-prove byte/inode limits, actual UID mapping, inheritance/descendants, cross-
   workspace access, project/quota/mount/namespace mutation denial and reboot/replace
   persistence. Old systemd properties/seccomp proof do not automatically qualify Docker.
4. Account/bound every writable location, including SQLite/WAL, uploads/staging,
   private auth/recovery storage, scratch, logs and container writable/tmpfs paths.
   Native H02/GCP qualification must cover the exact filesystem, kernel and mount setup.
5. Measure physical limits/headroom for Free 50 MB and the admitted warm population,
   backup/restore staging and private control reserves. Historical 8A/8C fault fixtures
   are not production tier profiles. H04 owns logical measurement/reservations; its
   source-ledger work on the upstream branch needs separate design/review before reuse.
6. Record exact current image/source/schema/tool pins and actual results in the
   [acceptance register](HOSTED_MVP_ACCEPTANCE.md). Keep source activation unavailable
   until current runtime/native/cloud gates pass; no fallback to a `du` check alone.
