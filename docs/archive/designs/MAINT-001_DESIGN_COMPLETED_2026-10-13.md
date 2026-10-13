# MAINT-001 — completed acceptance, October 13, 2026

The remaining browser gate is complete. Current behavior is consolidated in the [Maintenance guide](../../modules/maintenance.md); the [original design](MAINT-001_DESIGN.md) and [command-readiness record](../implementation-plans/MAINT-001_COMMAND_READINESS.md) preserve policy and concurrency rationale. Existing mandatory MAINT-004 reporter contracts are used; separate MAINT-002/003/004 acceptance and unrelated review findings are not closed here. No database migration or financial authority change was added.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Property/matching-Space issue creation, appointment rescheduling/completion, cost void/replacement, paid Expense link/archive, independent follow-up, evidence archival | Passed |
| Invalid combinations | Domain category/detail and source rules; scheduled appointments block resolution; cancellation/reopen/reschedule reasons, forged child membership and separate completion facts | Passed |
| Idempotency/retry | Issue/child original receipts, stale/changed-key/no-op rules, Task tombstones, browser lost lifecycle response | Passed |
| Rollback | Coordinated Finance/Task/issue/audit and receipt-insertion failures roll back the caller transaction | Passed |
| Persistence/schema | Retained receipt/audit/schema tampering; new HTTP detail regressions for Expense void state and Task deletion state | Passed |
| Backup/restore | Encrypted retained reporter/communication and complete command-receipt/source-reader round trips | Passed |
| Query budgets | Existing constant-budget list, bounded child and one-SELECT recovery proofs; browser paging without per-row HTTP reads. New Expense chooser is bounded to 100; Property review is command/detail-only | Passed |
| Privacy/shared behavior | Contextual sensitive-data cues, retained reasons and archive metadata, normal-list archive exclusion, shared confirmation/autosave/recovery | Passed |

## Results and limitations

- Focused Python: `maintenance/tests/test_models.py`, `test_workflow.py`, `test_command_readiness.py`: **46 passed**.
- Work browser: **28 passed**, against the packaged UI and real temporary workspaces. Two new cases cover operational costs/Expense associations and rescheduling/follow-up filtering; existing creation/evidence tests now cover Space membership and archival.
- Shared components and recovery: **6 + 6 passed**.
- Changed Python Ruff check/format, frontend lint/typecheck, changed-file Prettier, generated contracts, package build and diff whitespace checks passed.
- Repository-wide `npm run format:check` remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`; the existing bundle-size warning is informational.
- Only focused suites ran. No independent manual usability review, full-suite run or broader review-queue closure is claimed.
