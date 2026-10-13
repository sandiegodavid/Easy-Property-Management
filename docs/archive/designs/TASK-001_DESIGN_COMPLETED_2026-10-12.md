# TASK-001 — completed acceptance, October 12, 2026

TASK-001 is complete. Current behavior is consolidated in the [Task module guide](../../modules/tasks.md). The [original design](TASK-001_DESIGN.md) retains the original requirements and rationale; this record closes the four browser interactions left open by the October 12 reconciliation.

## Delivered interactions

- The Task directory combines priority and overdue/today/next-seven-day/all/no-date filters with status and related-record criteria, preserves them across bounded cursor pages, and resets the cursor when criteria change.
- Inline quick add begins with title and due-date/no-date choice; date selection creates an all-day deadline in the displayed browser time zone, while optional details support exact times and other zones. It uses the existing saved-form, validation, command identity, and original-result recovery flow. Choosing no date clears both deadline fields and all-day state.
- Completion checkboxes appear inside expanded Task rows and open the existing confirmation form. No lifecycle write occurs before confirmation.
- Completed/cancelled history displays the retained outcome note and timestamp together, including a read-only outcome section on detail. Page and summary facts supply these presentations without additional row-detail requests.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | `work.spec.ts`: combined filters, inline quick add, confirmed completion, completed/cancelled history, existing creation/lifecycle/reminder/waiting flows | Passed |
| Invalid combinations | Completion without confirmation remains rejected; existing backend suite covers deadline/time-zone and related-record validation | Passed |
| Idempotency and retries | Saved creation input survives reload; original creation identity, stale-source review, lost deletion and original-result reconciliation browser cases | Passed |
| Transaction rollback | Existing Task backend suite covers audit-write rollback and atomic command receipts | Passed; no persistence changes |
| Persistence/schema | Existing Task backend suite covers current tables, checks and retained command data | Passed; no schema changes |
| Backup/restore | Existing Task backend encrypted restore coverage; earlier UI-001 Slice 57 browser restore evidence retained | Backend passed; Slice 57 browser restore not rerun |
| Query budgets | Combined 26-record filtered cursor traversal has no gaps/duplicates; existing browser case issues no per-row detail HTTP requests; backend summary/read budgets remain covered | Passed |

Commands run from `application/`:

- `node scripts/python.mjs -m pytest apps/server/app/modules/tasks/tests -q`: **120 passed**.
- `npm run test:web -- apps/web/tests/work.spec.ts --grep 'Task|task|Reminder|Waiting'`: **12 passed**, against the updated packaged web assets.
- `npm run lint` and `npm run typecheck`: passed, including the complete frontend project.
- Prettier checks on all changed frontend files: passed.
- `git diff --check`: passed.

Repository checks outside this feature remained incomplete: `npm run format:check` failed on existing `demo/dataset.json` and `demo/README.md` formatting; `npm run package:web` stopped at `contracts:check` because generated contracts lag the new Home API. The focused browser build used `npm run build --workspace @epm/web` followed by `node scripts/python.mjs scripts/package_web.py`; both passed. No lint rules or contract checks were relaxed. These adjacent artifacts were not changed as part of TASK-001.

The [completed UI-001 matrix](../implementation-plans/UI-001_IMPLEMENTATION_MATRIX_COMPLETED_2026-10-12.md) preserves the earlier core Task workflows and cross-workflow acceptance. Later modules' linked-Task integrations remain owned by those features.
