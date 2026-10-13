# TASK-002 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Task guide](../../modules/tasks.md). The [original design](TASK-002_DESIGN.md) retains the 13 accepted decisions. This closes source/browser waiting workflows and typed consumer facts, not broader DASH-001 Home composition or performance acceptance.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Waiting set/complete-context replacement, timed reschedule, explicit date/zone removal, visible unscheduled state and confirmed clear | Passed |
| Invalid combinations | Exact revision/key contracts, invalid/offsetless dates and zones, terminal waiting and unpaired fields; stale edits preserve operator input | Passed |
| Timing/independence | Exact-instant actionable classification, future-today remains scheduled, all-day deadlines; priority/deadline and pending reminders survive waiting/date removal; clearing is not completion | Passed |
| Idempotency/retry | Concurrent same-key mutation, changed reuse/stale conflicts, semantic no-op receipts, lost reschedule response reconciles one dispatch; original deleted/terminal Task receipts remain recoverable | Passed |
| Rollback | Receipt/audit/database/commit failures roll back waiting and keep keys reusable; completion racing reschedule cannot leave terminal waiting | Passed |
| Persistence/backup | Pair/timestamp/lifecycle constraints, append-only receipt and tampered/missing-history rejection; encrypted restore preserves waiting rows, original operations and audit history, and rejects corrupt archives | Passed |
| Query budgets | Populated bounded pages/counts use one consistent snapshot with four-SELECT ceiling; capped parent previews, full totals and 15-minute revision/runtime-bound continuations | Passed |
| Integration | TASK-001 summary buckets, reminders, deadline/priority filters, lifecycle history, linked concern follow-up and source-independent completion remain unchanged | Passed |

## Results and limitations

- Focused Task backend directory: **120 passed**.
- Packaged `work.spec.ts --grep 'Task|Waiting|Reminder'`: **15 passed**, including two new waiting cases, against real temporary workspaces.
- Frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace passed.
- Repository-wide formatting remains blocked by unchanged `application/demo/dataset.json` and `application/demo/README.md`; bundle-size warnings are informational.
- No full suite or independent manual usability review ran. No unrelated review findings or other source lifecycles are closed here.
