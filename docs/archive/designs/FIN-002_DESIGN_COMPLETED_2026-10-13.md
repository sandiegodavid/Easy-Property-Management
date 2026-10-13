# FIN-002 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Finance guide](../../modules/finance.md#actual-expenses-and-refunds). The [original design](FIN-002_DESIGN.md) preserves requirements and rationale. This pass closes the remaining browser acceptance over existing Expense/category/refund revisions, atomic commands and immutable original responses. No persistence format or schema changes were required.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | Merchant and Provider payees, Property/Space/time-zone context, Party payer, category/notes correction, refund creation/void/replacement and Expense replacement | Passed |
| Invalid combinations | Exactly-one payee, archived-reference confirmation/reason, Party ownership, date/currency/amount checks, refund limits and lifecycle/source membership | Passed |
| Idempotency/retries | Same-key original results, changed reuse, stale revisions, duplicate confirmation, one-dispatch lost-response reconciliation and separate evidence retry | Passed |
| Rollback | Expense/refund/category audit and receipt failures roll back atomically; duplicate review is read-only; evidence failure preserves saved spending | Passed |
| Persistence/schema | Exact schema, retained audit/privacy and nonbranching correction history | Passed |
| Backup/restore | Encrypted Expense/evidence/refund/audit and category-command original-result round trips | Passed |
| Query budgets | Duplicate review performs one SELECT with SQL payee predicates and LIMIT 10; existing many-provider page and context-reader regressions remain bounded | Passed |
| UI integration | Combined directory filters, named context, duplicate actions, post-save evidence/skip, archive history, category correction and refund replacement | Passed |
| Accessibility | Money suite includes narrow light/dark receipt review with axe; native labeled Expense controls and explicit confirmations exercised in browser workflows | Passed for automated scenarios; no separate manual accessibility audit |

Focused validation from `application/`:

- `test_expenses.py`, `test_consumer_commands.py`, `test_category_command_readiness.py`: **52 passed** together.
- `money.spec.ts`: **24 passed**, including four new Expense acceptance cases and shared Money regression coverage.
- Shared component tests: **6 passed**; command-recovery tests: **6 passed**.
- Frontend lint, complete type checking, changed-file formatting, configured changed-Python Ruff checks/formatting, reproducible OpenAPI/TypeScript contracts, Vite build, local wheel packaging and diff whitespace checks: passed.

Root `npm run format:check` remains incomplete due to existing `demo/dataset.json` and `demo/README.md` formatting; those unrelated files were preserved. The build retains its informational bundle-size warning. The full application suite was not run. Other Finance/Owner-accounting features and pending review comments retain their separate acceptance gates.
