# FIN-003 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Finance guide](../../modules/finance.md#summary-reads-and-query-boundaries). The [original design](FIN-003_DESIGN.md) retains calculation rationale. This closes explicit-period recorded-money reporting and source drill-down, not bank reconciliation, owner entitlement/statements, generalized reports or Home/DASH presentation.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Portfolio/Property rent, paid expenses and independently dated refunds; exact signed USD remainder; separate deposit period activity and current all-date obligations; source/account drill-down | Passed |
| Invalid combinations | Missing/invalid/oversized periods and scopes, unknown filters, malformed cursors, missing relationships/currencies and integer overflow fail closed | Passed |
| Correction/retry | Voids/replacements restate original dates; surviving refunds remain independent; owner-report adoption does not duplicate receipts; stale/expired/epoch-changed continuations require explicit restart | Passed |
| Consistent reads | One snapshot survives concurrent financial changes; repeated/empty reads perform no writes; source-write rollback and intermediate read failure never publish partial totals | Passed |
| Deposit/date semantics | Signed positive/negative account reconciliation, late receipts, replacement decisions, distinct approval/completion dates and Property-local DST boundaries | Passed |
| Persistence/backup | Integrity failure sanitization and readiness gating; encrypted restore reproduces exact summary/source values and original Finance operation/revision rows while invalidating old cursors | Passed |
| Query budgets | Long history and one/many rows have bounded set-based reads and indexed period access; Unicode property cursors and source pages have no gaps; browser summary does not fetch per-row detail | Passed |
| Browser navigation | Explicit inclusive period, matching totals, unavailable amounts not zero, Rent less net expenses label; Property/metric/account drill-down preserves scope/revision and discards incompatible cursors | Passed |

## Results and limitations

- `test_money_summary.py`: **21 passed**.
- Packaged `money.spec.ts --grep reporting`: **3 passed**. Real temporary-workspace calculations/source detail are supplemented by controlled stale-response and collection-cursor fixtures.
- Frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace passed.
- Repository-wide formatting remains blocked by unchanged `application/demo/dataset.json` and `application/demo/README.md`; bundle-size warnings are informational.
- No full suite or independent manual usability review ran. No financial mutations, schema compatibility work, unrelated review closure or future owner/reporting workflows were added.
