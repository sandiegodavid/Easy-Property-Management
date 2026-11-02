# Slice 8A checkpoint

November 1, 2026 — `Admin_UI_Workflow`; saved uncommitted.

**Slice 8A is repository delivered and passed on the retained local ARM64 VM.**
The [qualification report/runbook](../qualification/HOSTED_PROJECT_QUOTA_QUALIFICATION.md)
owns the matrix, actual before/after-reboot JSON, versions/digests, compatibility
limits, repeat commands and private installation procedure. The
[VM runbook](../qualification/LOCAL_LINUX_VM.md) owns start/stop and file transfer.

Delivered: private ext4 project probe/empty-tree initializer/hard-limit adapter,
bounded descendant validation, systemd plus inherited seccomp launcher, and an
opt-in disposable filesystem harness using two non-login service identities.
The source/tool-pinned run proved byte/inode EDQUOT, deleted-open charging,
SQLite WAL/checkpoint, native/compat-encoding mutation denial, child exec,
cross-project/user isolation, accounted temporary paths, no leaked writable
descriptors/raw-image access, invalid bindings/descendants, disabled/missing
enforcement, remount and actual VM power-cycle persistence. ARM32 ELF execution
was rejected by this kernel/hardware before sandboxing; this is explicitly
recorded rather than claimed as successful compat sandbox execution.

Focused repository validation: 36 pytest tests passed; all six changed Python
files passed Ruff check/format. The C launcher compiled with warnings as errors.
No frontend code or current operator provisioning changed. Existing Admin
independent failed-observation presentation is covered without a new destination.
No full suite, live-host inspection/change, tier qualification or Slice 8B work.

The Linux VM is retained as requested and stopped when idle. Preserve evidence
before explicit cleanup of harness images/users using the runbook; never delete
the VM itself. No further Slice 8A implementation is pending. Next would be 8B;
this is not a live capacity or deployment grant.

Continue honoring usage stops: weekly remaining 2%, five-hour remaining 5%.
