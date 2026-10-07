# FIN-003 — Portfolio and Property Money Summaries

October 6, 2026

## Status and purpose

Confirmed technical design for FIN-003, based on [FEATURE_BACKLOG.md](FEATURE_BACKLOG.md), [ARCHITECTURE.md](ARCHITECTURE.md), [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md), [DECISIONS.md](DECISIONS.md), the dependency designs, and current implementation. The operator confirmed all fourteen recommendations on October 6, 2026; they are recorded under **Resolved design decisions** and govern the implementation contracts below. The backend read contracts, APIs, persistence indexes, and focused acceptance tests are implemented. See [FIN-003_TEST_MATRIX.md](FIN-003_TEST_MATRIX.md) for slices, validation evidence, and the two adjacent prepaid-check fixture failures. The pre-implementation gap assessment below is retained as design rationale.

FIN-003 supplies truthful, source-backed portfolio/property summaries of recorded rent, actual expenses/refunds, and separate deposit obligations/activity. It answers how the recorded operating money compares over a selected period. It does not establish a bank balance, spendable cash, accounting profit, legal deposit entitlement, or an owner's distribution entitlement.

Deliver backend read models/APIs and validation first. UI-001 renders the Money experience, OPS-001 composes contextual property/owner views, and DASH-001 consumes the same summary contracts. Do not build React in this slice.

## Dependencies and boundaries

| Item | Contribution to FIN-003 |
| --- | --- |
| FIN-001 | Recorded rent receipts, allocations, expectations, immutable corrections, recipient identity |
| FIN-002 | Actual paid property expenses, independently dated refunds, categories, payer facts, lifecycle |
| FIN-008 | Deposit accounts, receipts, approved/completed settlement snapshots, actual refunds, retained correction history |
| PORT-002 / LEASE-001 | Transitive source prerequisites: retained property/space identity, property time zone, receipt lease-to-property mapping |
| AUDIT-001 / LOCAL-001 | Transitive infrastructure: source audit history, workspace readiness and consistent local database access |

The existing three FIN prerequisites remain sufficient as product-level dependencies. Source protocols may need extensions within FIN-003's implementation; their existence must be verified before claiming readiness. This design introduces no dependency on OWNER-001/002/005, RPT-001/002, OPS-001, or UI-001, which consume its results.

OWNER-003 is not a second money source. A verified report contributes only through its linked FIN-001 receipt. Pending/rejected reports contribute no money; an existing receipt contributes once even when a report later adopts it. No OWNER-003 dependency is needed for basic aggregation. Verified report provenance, if later displayed, requires an optional source-owned reader and does not change amounts.

FIN-007 is not a new income source. A scheduled check contributes nothing; its confirmed receipt contributes through FIN-001, and a returned/voided receipt contributes nothing. No scan of scheduled checks is needed for the core totals.

Maintenance quotes/work costs, HOA claimed amounts, unsigned leases, draft receipts/forms, unsynchronized contractual rent, owner disbursements, management-fee calculations, opening balances, imported financial history, and bank feeds are not inferred or created by FIN-003. RPT-001 owns broader reports and OWNER items own owner calculations.

## Current implementation and gaps

| Existing evidence | Design consequence |
| --- | --- |
| [Rent source models](../application/apps/server/app/modules/finance/infrastructure/sqlalchemy_models.py:18) store receipts by `lease_id`, with date, amount, recipient, and void/replacement lineage; no property ID on the receipt | Resolve property/space through a retained lease-location source projection. Do not count one receipt once per allocation. |
| [Finance transaction ports](../application/apps/server/app/modules/finance/application/ports.py) expose receipt/expectation pages and batched projections | Useful facts exist, but no portfolio sum/grouping contract exists. Public list pagination must not be used to compute totals. |
| [Expense persistence](../application/apps/server/app/modules/finance/infrastructure/sqlalchemy_models.py:118) stores property/date/category/payer; refunds have their own received dates | Aggregate each event on its own date. Lifetime `netAmount` on an expense detail is not a period expense total. |
| [Expense context reader](../application/apps/server/app/modules/finance/infrastructure/expense_context_reader.py) calculates active refund totals for selected expenses | Suitable for deduction evidence context, not cross-period cash-movement reporting or portfolio aggregation. |
| [Deposit models](../application/apps/server/app/modules/finance/infrastructure/sqlalchemy_models.py:189) retain account property/space plus settlement/receipt/refund facts | Set-based aggregation is possible without reading other modules' persistence. |
| [Deposit account view](../application/apps/server/app/modules/finance/application/deposit_service.py:361) exposes active received/refunded totals, variance, settlement state, and unresolved state | It does not expose a complete portfolio obligation formula; do not sum account detail calls or call `varianceAmount` a liability. |
| [Deposit settlement rules](FIN-008_DESIGN.md) retain truthful refunds when a settlement is voided/replaced | Refunds must be summed at account level, not only under the current settlement. Corrections can temporarily require reconciliation. |
| [Lease source port](../application/apps/server/app/modules/leases/application/ports.py:22) and [Portfolio source port](../application/apps/server/app/modules/portfolio/application/ports.py:20) provide transactional/batched contexts | They do not currently establish a bounded composable all-history lease/property relation for reporting. Add a neutral source contract rather than importing source SQLAlchemy models into Finance. |
| [API composition](../application/apps/server/app/bootstrap/api.py) registers rent/expense/deposit workflows | No FIN-003 money-summary service/router is currently registered. |
| [SQLite engine](../application/apps/server/app/platform/sqlite_engine.py) supports explicit deferred transactions and immediate writes | One deferred read transaction can provide a consistent snapshot across all summary queries without acquiring the writer reservation. |

These are implementation gaps relevant to FIN-003, not a general re-review of prerequisite features. No tests were run because this is a design-only task.

## Monetary semantics

### Operating period totals

Use recorded cash-movement dates and the current corrected state of each source. API fields are explicit; UI labels can use familiar words.

| Field | Formula for inclusive `fromOn..throughOn` |
| --- | --- |
| `rentReceived` | Sum each non-voided FIN-001 receipt once, by `received_on` |
| `expensesPaid` | Sum non-voided FIN-002 expenses by `paid_on` |
| `expenseRefundsReceived` | Sum non-voided refunds whose parent expense is active, by the refund's `received_on`, regardless of the parent's paid date |
| `netRecordedExpenses` | `expensesPaid - expenseRefundsReceived` |
| `operatingRemainder` | `rentReceived - expensesPaid + expenseRefundsReceived` |

“Money remaining” is labeled **Rent less net expenses** with explanatory text: “Recorded rent received minus paid expenses, plus expense refunds, for this period.” The result can be negative. It excludes deposits, borrowing, capital contributions, other income types not yet recorded, owner transfers, and unrecorded spending; it is not spendable cash.

Rent received by a non-null Party is included in the property's operating totals even when the local operator never held it. The recipient is disclosed as source context, not inferred as the property's owner. FIN-001 permits a saved recipient Party; only OWNER-003 separately verifies an owner report. Similarly, expenses are included regardless of the recorded payer. Do not claim a local-operator cash position from these totals.

Allocation amounts do not create additional income. A $1,200 receipt allocated across two expectations contributes $1,200 on its received date, even if the expected periods lie in different months. No period-based revenue accrual or income recognition from a lease term is introduced.

A refund received in February against January spending is a February refund. February `netRecordedExpenses` may therefore be negative. Do not filter refunds through the parent's expense date or reduce the January spending silently in a February-only cash-movement report. Voiding an erroneous source does restate current results for its original business date; this is correction, not a newly dated cash reversal.

### Deposit period activity

Display separate amounts: deposit receipts by received date; actual deposit refunds by paid date; settlement credit/deduction approval snapshots by the property's local date of `approved_at`; and counts of approved/completed settlements in the period. Only current non-voided receipt/refund/settlement facts contribute. A replacement approval contributes once; the voided predecessor remains available as history but contributes nothing to active totals.

Completed settlement counts use the local date of `completed_at`, not `approved_at`. Credits/deductions are settlement decisions, not cash receipts/payments. Do not include them in operating income/expenses. A deduction linked to unpaid rent does not settle the expectation or create a FIN-001 receipt. A deduction citing an expense does not reduce that FIN-002 expense.

Refunds remain active actual payments even if their authorizing settlement was later voided. Sum them through their account, including original authorization identity in drill-down. Do not drop or duplicate them when following a replacement settlement.

### Current deposit obligation, separate from the operating date filter

For each account, define:

- `R`: all current non-voided deposit receipts, across all business dates.
- `F`: all current non-voided deposit refunds, across all business dates.
- `C`, `D`: credit and deduction approval snapshots from the one current non-voided approved/completed settlement; zero when no such settlement exists. Draft values are excluded.
- `recordedDepositObligation = R + C - D - F`.

Expose the components, current settlement ID/status, current approved refund due, unsettled receipts outside its captured receipt set, and the source-owned unresolved/review state. Label this **Recorded deposit obligation**, not verified funds in a bank or a legal determination. The agreed deposit amount and `R - agreedAmount` variance are separate coverage facts; an agreement is not received money.

Example: receipts $1,000, approved credit $20, approved deductions $200, actual refund $300 yields obligation $520. The operating remainder is unchanged. After a $520 refund, the obligation is zero; FIN-008 still owns whether the settlement is explicitly completed. A zero obligation must not mark an unfinished settlement complete.

If the settlement is voided after truthful refunds, removing its current credits/deductions may produce a negative provisional obligation. Preserve the signed reconciliation value, flag the account, and do not silently clamp it to zero. Portfolio output shows `positiveObligations`, `negativeReconciliationAmount`, `netRecordedObligation`, and affected account count, so a negative account cannot silently offset another tenant's positive obligation. A negative account does not create a receivable or imply overpayment as a legal conclusion.

Late receipts after approval increase current obligation and remain visibly unsettled, even when a previous settlement is completed. The current account balance is reported at the response's read instant, **not at `throughOn`**. Historical date-cutoff balances and “what the app knew then” reconstruction are deferred; the current schema contains mutable lifecycle and category facts rather than a ready historical reporting ledger.

## Dates, scope, lifecycle, and currency

Require explicit ISO `fromOn` and `throughOn` for period endpoints, inclusive and ordered. Enforce a maximum 3,660-day range per request; avoid a process-time-zone-dependent default. UI-001 can propose a visible month/year range. A date-only source is compared directly to these calendar dates. Convert settlement UTC approval/completion instants to each property's stored IANA zone before date bucketing; never use SQLite UTC date truncation or the server's ambient zone.

One portfolio period uses the same displayed calendar-date range in each property's zone. `asOf` is the common UTC read instant; `periodBasis` states `property_local_business_date`, `financialState` states `current_corrected`, and `depositBalanceBasis` states `current_all_recorded_dates`. Do not conflate these three boundaries.

Default scope is all retained properties, including archived properties with history. An explicit `propertyState=active|archived|all` changes the report's scope consistently; show excluded counts/scope. Selected property IDs are typed UUIDs, deduplicated, and capped at 100. A property-specific endpoint returns retained history for an archived property. Archiving a property, space, Party, category, provider, or lease never voids money or hides it from an all-properties report.

Do not add owner-share, ownership-type, provider, space, category, or payer filters to the entire money summary initially: their meanings differ across source families. Expense-category drill-down can support a category filter that applies to expense/refund metrics only; never present a category-filtered expense alongside unfiltered income as a coherent filtered remainder.

Currency is USD. Aggregate in integer cents; format API amounts as canonical signed decimal strings with exactly two places. Do not apply the individual-entry maximum to portfolio sums. Detect integer aggregation overflow and return unavailable/error; never round through floating point or cap a total silently. If unexpected non-USD data reaches a validated workspace, fail the affected summary rather than converting it.

## Service and read-model design

Add a separate `MoneySummaryService` and dedicated application/read ports inside `finance`; do not expand receipt/deposit command services into a dashboard coordinator. Finance infrastructure can query its own rent/expense/deposit tables. Cross-module identity, location, audit marker, and readiness come from source-owned application ports composed at bootstrap. OPS/DASH consume a bounded `MoneySummaryReader`, not Finance repositories.

The neutral location boundary is a source-owned, composable lease-location relation with exactly `leaseId`, `spaceId`, `propertyId`, retained property label/state, and time zone. This permits indexed SQL grouping/filtering without materializing every historical lease ID. The owning source adapter resolves joins; Finance does not import Leasing/Portfolio models. The application protocol declares the relation's columns and transaction/read-only restrictions, not arbitrary SQL execution. Implementers must review this small query-composition contract against the architecture's abstraction/overhead rule; an alternative using batched facts must demonstrate equally bounded memory/queries before adoption.

Same-source Finance aggregates are set-based. Preaggregate refunds and deposit children before joining; never join receipt allocations, refund rows, deduction rows, and credit rows together and sum multiplied values. Use approved settlement snapshots as the monetary authority, with line-item sums only for validation/drill-down. A property appears once even with several spaces, leases, recipients, or owners.

Use one explicit deferred read transaction for scope, totals, counts, property slice, and context/provenance. An exception closes/rolls back the read and returns no mixed-snapshot composite. No financial write, automatic synchronization, audit mutation, keyring call, file read, or AI operation is triggered by these GETs.

Missing source relationships are integrity failures, not omitted rows. The summary must not silently lose a receipt because an inner join cannot resolve its retained lease/property. Verify orphan counts or rely on qualified workspace validators plus an explicit guarded relation contract; retained lifecycle filters must not exclude valid historical leases.

### Freshness and pagination

Each response carries `asOf`, normalized filters, `contractVersion`, a source read revision, and section availability. Keyset cursors include version, workspace/runtime epoch, filter fingerprint, source revision, and last sort key/ID. Property rows sort by normalized display name then stable property ID. Source rows sort by business date descending, source kind, then ID.

Use a neutral AUDIT-owned append marker to detect changes between requests, paired with a runtime epoch rotated on reopen/restore. Current audit IDs/timestamps alone are not a proven monotonic marker; do not use `MAX(occurred_at)` to guarantee freshness. An implementation may expose an opaque marker backed by the append-only SQLite insertion order without making it a portable business ID. This is a new read contract, not an existing API assumption. Conservatively invalidate on any audited workspace change if narrower change tracking would add unnecessary machinery.

Continuation/drill-down requests can require the summary revision. If it changed, return `409 money_view_changed` and refresh instead of combining old totals with new pages. Cursor validation is bounded and rejects changed filters/workspace/epoch. No database transaction remains open across HTTP requests. No durable report snapshot or new financial revision table is introduced by default.

## API contracts

All routes require a ready validated workspace, typed query models with unknown fields forbidden, direct-caller validation, and explicit response schemas. Default page size is 50; maximum is 100. No unbounded “all transactions” endpoint.

| Method/path | Result |
| --- | --- |
| `GET /api/money/summary` | Portfolio period operating totals, separate deposit period activity/current obligation, scope/coverage facts, source revision, metric drill-down descriptors |
| `GET /api/money/properties` | Keyset property page and matching full-scope totals/count; zero-record retained properties remain distinguishable from unavailable sources |
| `GET /api/properties/{propertyId}/money-summary` | Same calculation contract for one retained property |
| `GET /api/money/sources` | Bounded contributions for one metric and identical scope/date/revision, with totals/counts, source IDs, dates, signed contribution, reason, and detail route |
| `GET /api/money/deposit-accounts` | Bounded account components/current-obligation page; not filtered to accounts opened during the operating period |

`metric` is an enum, including rent received, expenses paid, expense refunds, net recorded expenses, operating remainder, deposit receipts, deposit refunds, settlement credits/deductions, and current deposit obligation components. Composite metric drill-down returns a signed union: rent `+`, paid expense `-`, expense refund `+` for operating remainder. For net expenses, expense is `+` and refund is `-`. The signed contribution total must exactly equal the displayed metric under the same revision.

Source summaries disclose only necessary identity/date/amount/context; free-form notes, masked method details, source evidence, and audit snapshots remain in existing contextual detail workflows. Include `sourceKind`, `sourceId`, `propertyId`, optional lease/space/account IDs, current lifecycle, related parent/authorization IDs, contribution, and an API/detail-route descriptor. Do not return private file paths. Metric descriptors make financial drill-down available now; RPT-002 later generalizes report drill-down and is not a prerequisite or duplicate finance engine.

The summary uses distinct `operating`, `depositActivity`, and `depositObligations` sections. Successful empty source sets have zeros and truthful record counts. Unavailable required sources have null monetary values plus typed reason/recovery; dependent composite metrics are unavailable. No fallback to a fabricated zero or cached result labeled fresh. The backend fails the whole summary on database/integrity failure; OPS/DASH may preserve unrelated successfully loaded non-money sections.

Errors use [shared API problems](../application/apps/server/app/platform/api_errors.py): 422 malformed filters/ranges; 413 excessive request/cursor/filter content; 404 unknown property/source; 409 stale cursor/revision; 503 workspace unavailable/busy; sanitized server error for a read/integrity failure. There is no idempotency key because FIN-003 has no commands. Repeated GETs under identical source state return identical amounts and no new rows/audit events.

## Persistence, performance, and portability

No new income, expense, allocation, liability, or settlement ledger is created. Summaries are derived. Do not cache authoritative totals in a second table or persist an unsupported bank/owner balance. Add only required read indexes in the latest greenfield schema, updating metadata/schema validators consistently; no legacy migration compatibility work.

Index candidates to qualify with query plans: receipt business date/lifecycle/lease/ID; refund business date/lifecycle/expense/ID; settlement status/approval/account; refund account/date/lifecycle; lease-location join keys. Existing expense property/date and deposit account/location indexes can be reused. Measure before adding redundant indexes.

Initial query budgets per response: at most 12 SELECTs for portfolio summary, 16 for property-page plus matching totals, and 8 for one source/account page. Budgets include scope, integrity, revision, and batched context reads; exclude transaction-control statements. They are fixed with row count. SQL may scan indexed qualifying source rows for an aggregate; Python may not load the entire history or perform a query/account-detail request per displayed row. No generic evidence or provider-context fan-out is needed.

Bound returned properties/accounts/contributions at the database; aggregate full filtered scope separately. A source projection used by a page is batched for at most the page's IDs. Avoid a variable-length all-history `IN` list. Test representative long-history portfolios and inspect query plans, SQL statement count, intermediate row multiplicity, and integer boundaries.

Derived values need no backup schema of their own. Backup/restore of source facts must reproduce summaries under the same explicit filters and current corrected state. Response timestamps/runtime revisions can change after restore; amounts, source identity, and calculation meaning must not. Cursors from an old runtime/workspace are invalid.

## Consumer and operator handoff

Money shows recorded rent, paid expenses, expense refunds, rent less net expenses, and a separate deposits section. Each metric opens contributions or deposit accounts. Period and property scope remain visible. Current deposit obligation is labeled with its current read instant, even when the operating period is historical.

Show “No recorded transactions” where appropriate, not “All finances handled.” FIN-003 can expose source counts and notes such as no rent receipts/deposit accounts recorded; it does not certify complete lease synchronization or complete expenses. OPS-001 owns broader coverage/applicability. Do not depend on OPS to calculate FIN-003 totals, which would create a cycle.

Owner views may display property totals with clear property scope; they cannot allocate amounts by ownership shares or call those values owner balances/statements. OWNER-002 must use payer/recipient/verified provenance and its own entitlement/reimbursement/reserve rules. Expense refunds currently lack an explicit recipient, and deposit refunds do not identify the funding holder; FIN-003 must not invent those facts for future owner calculations.

## Validation matrix and acceptance examples

| Area | Required tests/evidence |
| --- | --- |
| Happy paths | Portfolio equals all property rows; mixed self/client-managed properties; properties with several spaces/leases; one receipt with several allocations; owner-reported adopted receipt counted once |
| Invalid combinations | Bad UUID/date/range/cursor, unsupported metric/scope combination, missing retained location, non-USD corruption, cross-workspace cursor, integer overflow; no partial reassuring totals |
| Date semantics | Rent paid early for future expectation; refund in a different month/year from expense; negative net expense/remainder; timezone midnight/DST approval/completion boundaries |
| Deposit isolation | Receipts/refunds excluded from operations; approved credits/deductions separate; draft ignored; settlement void/replacement with surviving refunds; late receipt after completion; negative reconciliation not clamped/netted away |
| Idempotency/retry | Repeated GET has no writes; retried source mutation does not double money; lost source response already handled by source idempotency; changed revision rejects continuation |
| Transaction rollback | Exception after intermediate read returns no mixed result; concurrent source mutation cannot alter a response's read snapshot; test source mutation rollback causes no summary change |
| Persistence/schema | Approved snapshots reconcile; voided/replacement/source references valid; orphan location does not disappear; new indexes included in exact greenfield validation |
| Backup/restore | Recompute same amounts/source IDs after source backup/restore; runtime revision refresh invalidates old cursors; no secret/path disclosure |
| Query/N+1 | Fixed query counts across 1/50 properties and long histories; parent-child joins never multiply contributions; bounded result pages; no all-history Python materialization |
| UI handoff | Drill-down contribution sum equals metric; archived history visible; current vs period labels; unavailable differs from empty; property totals are not owner entitlement |

Concrete reconciliation fixture: January rent receipt $1,200 with two allocations, January paid expense $400, February refund $100. January operating remainder is $800; February is $100 when no other operations occurred. Add deposit receipt $1,000 in January, $200 approved deduction and $300 refund in February: operating results stay unchanged, deposit activity is separate, and current obligation is $500. Voiding an erroneous January receipt changes January rent to zero in the current corrected report; it is not counted as a February expense.

Acceptance requires every numeric metric to have an exact source explanation, all source lifecycle/date distinctions above to hold, a consistent read boundary, validated bounded contracts for consumers, and no autonomous mutation. FIN-003 can be backend-verified while the complete operator experience remains pending UI-001.

## Implementation sequence

1. Establish calculation definitions and reconciliation fixtures from the confirmed remainder, deposit-obligation, period/correction, and current-only balance semantics below.
2. Specify typed money queries/results/contributions and source-owned lease/location and revision ports; verify source readiness without changing their business rules.
3. Implement set-based Finance read projections and the single deferred transaction boundary; qualify indexes and query budgets against source fixtures.
4. Add summary/property/contribution/account APIs and shared problem handling; register the reader at bootstrap for future OPS/DASH consumers.
5. Complete reconciliation, lifecycle, timezone, concurrency, overflow, query-budget, and backup/restore tests.
6. Deliver consumer contracts and defer React to UI-001. RPT/OWNER extensions remain separate.

## Resolved design decisions

All fourteen recommendations were accepted by the operator on October 6, 2026. The original contradictions and gaps are retained here to explain each decision; accepting a contract does not imply that its implementation gap is already closed.

1. **“Money remaining” is undefined and sounds like available cash.** Existing receipts/expenses have payer/recipient facts but no bank balance, opening cash, or complete transfer ledger. Decision: `operatingRemainder = rentReceived - expensesPaid + expenseRefundsReceived`, labeled Rent less net expenses; no spendable-cash claim.
2. **Expense detail net amounts versus period reporting.** FIN-002's lifetime refund netting is insufficient when refunds occur in another period. Decision: independently date paid expenses and refund receipts; permit negative period net expenses.
3. **Rent receipt versus allocation/expectation period.** Income could be double-counted or attributed to expected periods. Decision: one contribution per active receipt on its received date; no accrual or expectation-derived income.
4. **Deposit liabilities are not defined by the backlog or current account view.** Agreed deposit/variance, receipts less refunds, and settlement-adjusted obligation are different values. Decision: show all components and current `R + C - D - F`, excluding drafts, with positive obligations and negative reconciliation separately.
5. **Approved deductions have no rent/expense handoff.** FIN-008 explicitly does not settle rent or create income, even for unpaid-rent deductions. Decision: keep all deductions/credits outside operating totals. Any later recognition/allocation workflow requires a separate design to prevent duplicate collection/income.
6. **Settlement replacement does not replace actual refunds.** Current source rules preserve those payments. Decision: account-level active refund sums across all authorizing settlements; voided decision snapshots do not contribute; negative provisional obligations require review rather than zero-clamping.
7. **Period activity versus historical deposit balances.** Mutable lifecycle/settlement state does not supply a ready historical knowledge ledger. Decision: date-filter period activity but report current all-date obligation separately; no historical-cutoff liability or report-as-originally-issued promise in FIN-003.
8. **Time-zone and default-period choice are missing.** The portfolio has multiple property zones. Decision: explicit inclusive dates, property-local event dates, common UTC read instant, and maximum 3,660-day range; UI proposes a visible range.
9. **Archive scope and unrecorded data are undefined.** Active-only defaults would erase historical money; zeros could imply complete coverage. Decision: all retained properties by default, explicit state filter, record counts, and no completeness certification.
10. **No bounded receipt-to-property reporting port exists.** Receipts lack direct property IDs; current contexts do not establish portfolio reporting. Decision: neutral source-owned composable lease-location relation, with a qualified bounded alternative only if it meets the same query/memory budget. Do not copy financial facts or import external persistence into Finance.
11. **Stable cursor/revision semantics are absent.** Audit timestamps/UUIDs are not a proven monotonic change token. Decision: source-owned opaque append marker plus runtime epoch, consistent reads per request, and 409 on changed-revision continuation; no permanent report snapshot by default.
12. **Aggregate bounds and availability are unstated.** Portfolio totals can exceed individual-entry limits; partial sources could produce misleading remainders. Decision: exact signed aggregate decimals, explicit overflow failure, no fabricated zeros, and one fail-closed money composite on read/integrity failure.
13. **Drill-down is scheduled later despite mandatory source visibility.** RPT-002 depends on reporting that already depends on FIN-003. Decision: financial contribution/account drill-down is intrinsic to FIN-003; RPT-002 later generalizes report navigation without becoming a prerequisite.
14. **Owner consumers may mistake property remainder for entitlement or holder balance.** Recipient/payer data does not determine ownership shares, and expense refunds lack holder identity. Decision: expose neutral property/source facts only; OWNER-002 owns its missing holder, fee, reserve, reimbursement, and entitlement decisions. Do not add a circular owner dependency.

These confirmed decisions establish the FIN-003 implementation contract without expanding it into reconciliation workflows, owner accounting, financial mutation, or full bookkeeping. Backend delivery and focused validation are recorded in [FIN-003_TEST_MATRIX.md](FIN-003_TEST_MATRIX.md); the operator UI remains part of UI-001.
