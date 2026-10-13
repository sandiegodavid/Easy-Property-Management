# FIN-001 — completed acceptance, October 12, 2026

Current behavior is consolidated in the [Finance guide](../../modules/finance.md). The [original design](FIN-001_DESIGN.md) preserves requirements and rationale. This pass delivers the remaining rent preview/confirmation, allocation-total, filter and timeliness-history requirements, using existing atomic ledger commands and immutable original responses.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | Explicit term/anchor preview, recurrence/proration, partial and multi-period receipts, method suggestion, void/replacement and missed/clear review | Passed |
| Invalid combinations | Override confirmation/reason, changed preview inputs, mismatched allocation totals, source membership, currency, over-allocation and malformed HTTP/direct commands | Passed |
| Idempotency/retries | No-op synchronization, concurrent receipt retries, changed reuse, stale ledger, original responses after void/source changes and command recovery | Passed |
| Rollback | Receipt/allocation/revision/receipt-audit failures roll back together; schedule preview performs no writes | Passed |
| Persistence/schema | Immutable command/audit history, schema checks, replacement chains and safe method metadata | Passed; no persistence changes |
| Backup/restore | Encrypted Finance round trips preserve receipt/allocations/method history and original command results/revisions | Passed |
| Query budgets | Preview executes a bounded number of reads in one deferred snapshot; indexed recovery and set-based historical source projections retain regression coverage | Passed |
| UI integration/accessibility | Exact outstanding/filter/receipt drill-down, complete retained/new preview, separate responsibility approval, disabled unbalanced submission and narrow receipt review with axe in both themes | Passed |

Focused validation from `application/`:

- `test_finance.py`: **43 passed**.
- `test_commands.py`: **15 passed**.
- `test_consumer_commands.py`: **13 passed**.
- `money.spec.ts`: **20 passed**, covering the shared Money integration alongside FIN-001.
- Frontend lint, complete type checking, changed-file formatting, configured Ruff checks/formatting, reproducible contracts, Vite build, local wheel packaging and diff whitespace checks: passed.

The OpenAPI/TypeScript artifacts were regenerated from current bootstrap, including previously stale Home declarations. Root `npm run format:check` remains incomplete due to existing `demo/dataset.json` and `demo/README.md` formatting. The full application suite was not run. FIN-006/007 and other Finance acceptance remain separate; this feature records operator-entered money and operational timeliness without automatic collection or legal conclusions.
