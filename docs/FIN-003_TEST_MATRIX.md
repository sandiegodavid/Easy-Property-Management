# FIN-003 implementation and focused validation

The backend implements the current-corrected read contract in [FIN-003_DESIGN.md](FIN-003_DESIGN.md).
React remains part of UI-001. No financial ledger, cache, reporting snapshot,
compatibility migration, or GET-triggered mutation is added.

## Implementation slices

1. **Contracts/ports:** typed money queries, summaries, contributions and account
   components; `MoneySummaryReader`; Portfolio-owned property/space SQL relations;
   Leasing-owned retained location relation; Audit-owned append marker.
2. **Implementation:** Finance-owned set-based contribution and account queries,
   exact integer calculations, property-local settlement dates, a single deferred
   read transaction, and revision/filter/runtime-bound keyset cursors.
3. **Persistence:** four measured read indexes in current Finance metadata. The
   baseline creates these from metadata; the exact Finance schema validator checks
   the same definitions. No new tables are needed. Workspace refresh rotates the
   runtime epoch; ledger insertion order is an opaque, runtime-scoped append marker.
4. **Tests:** real SQLite reconciliation, lifecycle, concurrency, corruption,
   query-plan/query-budget, typed HTTP, and encrypted backup/restore coverage.
5. **Integration:** five Money routes and the typed reader are composed at
   bootstrap. Future OPS/DASH consumers use `app.state.money_summary_reader` or the
   `MoneySummaryReader` contract rather than Finance persistence.

## Validation matrix

Focused acceptance tests live in
`application/apps/server/app/modules/finance/tests/test_money_summary.py`.

| Area | Evidence |
| --- | --- |
| Happy paths | January $1,200 receipt with two allocations and $400 expense produces $800; independent February $100 refund produces $100; every metric equals its signed source contributions. |
| Recipient/provenance | A client-owner receipt adopted by an OWNER-003 report contributes once; pending report and later adoption do not change money. Property sums equal portfolio sums. |
| Invalid combinations | Invalid range/date/UUID/state, boolean page bounds, malformed or excessive cursors, unknown filters/properties, unexpected currency, missing lease locations, and database integer overflow fail without partial results. |
| Deposit isolation | Receipts and refunds stay outside operations; draft credits are excluded; approved credits use snapshots; voided decisions preserve actual refunds and authorization IDs; replacement approval contributes once; signed negative reconciliation is retained. |
| Date boundaries | Approval and completion use different timestamps and LA local calendar dates around UTC midnight and the spring DST transition; independently dated expense refunds are not filtered by their parent's paid date. |
| Completion/late receipts | Refunding the full obligation does not implicitly complete an approved settlement; explicit completion clears unresolved state; a later receipt raises obligation and remains unsettled even after completion. |
| Retry/freshness | Repeated reads create no rows or audit events. Continuation rejects changed filters, audited mutations, workspace/runtime identity, and explicit source revision. HTTP workspace refresh invalidates the old revision. |
| Workspace readiness | All four bootstrapped direct reader methods reject failed refreshes and a stopped runtime with typed `workspace_unavailable` (503) before opening a money read transaction. Failed validation retries remain unavailable; successful validation/restart restores reads and rotates the revision. |
| Transactions | Concurrent correction after the snapshot marker leaves the current response unchanged. An intermediate read failure returns no composite; rolled-back source writes leave results unchanged. |
| Persistence/schema | Current baseline and exact validation accept the added indexes. EXPLAIN uses the lifecycle/date indexes; broken source relationships and non-USD corruption are rejected by the read guard. |
| Archive/empty scope | Archived properties remain in all-scope reports and property-specific reads; state filtering reports excluded counts. Zero-record retained properties are available with zero counts. |
| Query budgets | Property paging at 1 and 50 properties has the same statement count and SQL limits; source paging at 1 and 151 expenses has constant cost and at most 50 returned rows. Account pages keep positive and negative accounts separate and return one bounded slice. Summary <=12, property page <=16, sources/accounts <=8. |
| Backup/restore | Encrypted LOCAL-002 round trip preserves operating/deposit results and stable contribution IDs; a new runtime rejects the old cursor. |
| API/UI handoff | Explicit response schemas and operation IDs; decimal strings, filters, shared instant/revision, temporal basis and detail routes; malformed requests use 422, oversized content 413, missing properties 404, changed views 409. |

The composable location relations are narrow source-owned SELECT projections,
including archived/historical leases. Finance imports only their application
contracts. Aggregates scan source rows in SQLite; Python receives grouped totals
or bounded pages, never all historical IDs or per-record context queries.

## Focused validation result — October 6, 2026

- FIN-003 acceptance module: 21 passed (including direct-reader workspace readiness regressions).
- Finance modules plus Workspace API integration run: 80 passed, 2 failed,
  14 subtests passed (before the last two FIN-003 acceptance tests were added).
- The two failures are existing prepaid-check fixtures:
  `test_prepaid_check_can_adopt_one_compatible_existing_receipt` and
  `test_prepaid_check_deposit_is_correlated_with_one_expectation`. Their lease
  fixture begins November 1 while their injected payer-eligibility clock is
  October 8. The unchanged eligibility rule rejects the not-yet-occupying payer.
  These are adjacent FIN-007 test issues and are not changed by FIN-003.
- Focused unused-import checks and `git diff --check` pass.
- The full application suite was not run, as requested.
