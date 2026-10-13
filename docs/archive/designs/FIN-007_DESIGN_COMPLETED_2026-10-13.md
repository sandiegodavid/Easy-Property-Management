# FIN-007 — completed acceptance, October 13, 2026

The remaining browser gate is complete. Current behavior is consolidated in the [Finance guide](../../modules/finance.md#prepaid-checks); the [original design](FIN-007_DESIGN.md) retains historical rationale. No payment initiation, check images, bank integration or persistence migration was added.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Money scheduling/deposit/return, replacement/void, future-check queue and reminder/receipt context; Finance compatible-receipt adoption | Passed |
| Invalid combinations | Full-period/payer/duplicate/lifecycle validation in Finance; safe masked-reference API and OPS contracts; future detail has no deposit action | Passed |
| Idempotency/retry | Prepaid command original-response replay, changed reuse and stale revisions; browser lost deposit response makes one dispatch and recovers one receipt/allocation | Passed |
| Rollback | Reminder failure rolls back check and ledger reservation; correlated Finance command tests | Passed |
| Persistence/schema | Current schema validation, malformed replacement lineage, retained method/reference checks | Passed |
| Backup/restore | Encrypted prepaid replacement round trip compares checks, operations, receipts, Tasks and audit rows | Passed |
| Bounded/read-only projection | Existing bounded expectation/receipt pickers and cursor queue; new Property context only on individual review/detail, not per queue row; injected property-midnight eligibility test proves no DML/revision change | Passed; no new full-list query-budget claim |
| Browser/shared behavior | 37 Money browser cases; six shared components and six recovery cases | Passed |

## Commands and limitations

- Focused Python: `test_finance.py`, `test_commands.py`, `test_consumer_commands.py`, and `operator/tests/test_finance_command_forms.py`: **96 passed**.
- Money browser: **37 passed**, against the rebuilt packaged frontend and real temporary workspaces.
- Shared components/recovery: **6 + 6 passed**.
- Changed Python Ruff check/format, frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace checks passed.
- Repository-wide `npm run format:check` remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`. Their formatting was not changed for this feature. The existing bundle-size warning is informational.
- Only focused suites ran. No separate manual UI acceptance or broader review queue closure is claimed.
