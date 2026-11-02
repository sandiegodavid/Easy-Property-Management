# Slice 8B completion checkpoint

November 2, 2026 — `Admin_UI_Workflow`. **Repository implementation complete.**
The final continuation is saved in this checkout; no deployment or VM operation
was performed. The retained `epm-quota-test` VM remains stopped.

The [design](HOSTED_DEMO_ADMIN_DESIGN.md#8b--define-policy-protected-inventory-and-commitments)
records the delivered scope. [Protected storage policies and reservations](../operations/HOSTED_ADMIN_STORAGE.md)
owns the command sequence, protected inputs, recovery rules and validation matrix.
No further 8B continuation is pending. 8C–8H remain planned; source project-backend
writes, production profiles and portal mutation controls remain gated.

## Final continuation

- Finished root-adapter apply/verified-retirement and evidence-expiry regressions.
- Enforced project-ID, filesystem/mount and nested-directory separation in direct
  inventory admission and retained inventory reads, with atomic-conflict tests.
- Fixed private storage credential admission and JSON strict-tuple parsing;
  exercised grant → reserve → apply through the real private request dispatcher.
- Added the operating runbook and linked its focused matrix from the design/index.

## Validation

- **219 passed** in the focused storage/authority/operations/upgrade-deployment,
  hosted-access configuration/budget/source-command and host-inventory run.
- **42 passed** in qualification, provisioning and broker-concurrency regressions.
  The sandbox initially denied temporary Unix socket creation; the same focused
  command passed after approval to run outside the sandbox. No test was weakened.
- Ruff check and format --check passed for all **23 Slice 8B Python files**.
- Generated contracts remain reproducible (`npm run contracts:check`).
  `npm run lint`, `npm run format:check` and `npm run typecheck` passed
  (207 source files). `git diff --check` passed.
  No new UI controls or frontend source changed.
- No full suite was run. Kernel qualification remains the separate Slice 8A
  evidence; synthetic profiles and mocked effects do not qualify a live host.

## Review fixes — commit 658b6b8d findings 1–4

Addressed November 2, 2026. Fresh authorized cleanup can finish a retiring
allocation after authority/control restoration without erasing prior attempts.
The live collector reserves reclamation uncertainty; reserved projects have a
scoped zero-limit pre-apply read and strict post-apply proof. Qualified root
filesystem mounts are supported without allowing root project directories.
All 247 focused regressions and changed-file Ruff checks passed; contract
reproducibility and whitespace checks passed. No host/VM changes were made.
Resolution details remain in the named review-comments file and the updated
storage operations runbook. Unrelated in-progress design edits were preserved.
