# Rent, expenses, deposits and money summaries

## Authority and money representation

Finance owns immutable rent expectations, recorded receipts/allocations, actual paid expenses/refunds, prepaid checks, deposit accounts/settlements and financial summaries. Currency is USD. Store integer cents, calculate with exact decimal rules and expose canonical decimal strings; browser floating-point sums are not authoritative.

Lease terms are read through source-owned transactional ports. Lease execution never creates expectations or payments. Operational repair estimates/quotes and pending owner reports are not spending or income. Financial corrections retain void/replacement history and original operation results.

## Rent schedule and receipts

The operator synchronizes one explicit Lease term and confirms its schedule anchor. Monthly cadence uses the configured due day with per-month clamping; weekly cadence uses seven-day intervals. Covered periods are inclusive. First/final stubs use actual calendar-day proration with decimal half-up rounding and a reconciled final rounding remainder. Exclusive Lease end/move-out becomes the preceding covered date; explicit rent-responsibility end is inclusive.

Expectations retain source term, dates, amount and generation decisions. Later contract changes do not overwrite them. Record one receipt and explicitly allocate it across eligible expectations; allocating never creates additional income. Partial/unpaid/late classifications use server facts and property-local dates. Likely duplicate payments require operator review.

The read-only `POST /api/leases/{id}/rent-expectations/preview` shares synchronization's schedule planner. It returns up to 240 new/retained periods, exact rounded amounts and day fractions, term/responsibility boundaries, Property time zone and captured rent-ledger revision. Voided snapshots remain explicitly labeled. It writes no expectations, receipts or audit events. Synchronization rechecks the ledger revision and immutable schedule inside its normal write transaction.

The browser requires an explicit term, preview and anchor/period confirmation; changed request inputs invalidate approval. Responsibility overrides require their own confirmation and reason. Rent lists provide settlement, timeliness and due-range filters with Expected, Money received and Still due labels and receipt-allocation drill-downs. Receipts expose date/recipient/replacement and void-history filters. Integer-cent allocation totals remain visible and submission is disabled until receipt and allocation totals match. A replacement prefills the voided predecessor without editing it; the last non-voided receipt supplies an editable actual-method suggestion. Expectation detail retains mark-missed/clear-missed reasons and dates; these are operational decisions, not legal determinations.

Each receipt freezes the actual payment method: external automatic bank payment, transfer, check, cash, online or other, with safe masked references. The last receipt may provide an editable suggestion, not an expected method. Rent and prepaid-check mutations share the Lease rent-ledger revision, UUID keys and read-only command recovery.

The receipt form explicitly records money already received; automatic bank payment means an external arrangement, never debit authorization or a live connection. `GET /api/leases/{id}/rent-receipts/payment-method-suggestion` supplies the latest non-voided receipt's snapshot or 204. The operator can edit it; a replacement instead starts from its voided predecessor. Changing kind clears method-specific label/reference/note fields. Other requires a trimmed 1–200 character explanation, retained and shown with that receipt; other kinds have no Other note.

Optional labels are at most 100 characters. Optional references are trimmed, at most 80 characters, and use an optional plain ASCII label, at least two • or * mask characters and at most four final ASCII digits. Examples are `•••• 1234` and `Check •••• 9182`; cash normally has no reference. The source-owned safe-reference pattern is shared by domain commands, HTTP validation and recoverable receipt drafts. Invalid raw references cannot become saved form data or receipt metadata. Labels/references/notes remain contextual, and no payment accounts, credentials, initiation or expected-method records are added.

## Prepaid checks

One future-dated check covers exactly one complete expectation period and eligible lease payer. Scheduling creates a property-local reminder, not income. Deposit eligibility is derived from the local day. Explicit deposit validates open amount and atomically creates/adopts the compatible receipt, allocations and Task effects. Return voids the linked receipt atomically. Void/replace retains nonbranching lineage; a never-deposited replacement has no receipt or deposit event.

The Scheduled checks view offers lifecycle/eligibility queues and Property, Lease, Space, payer and expectation filters, with bounded cursor pages. Detail and command review display the Property time zone/local day, period, payer, reminder and correlated receipt. Future checks have no detail deposit action. Reminder acknowledgement never changes financial state. Scheduling selects full, fully outstanding non-prorated periods; receipt adoption offers compatible check receipts from a bounded page and is revalidated by Finance. Leaving that selection empty creates a receipt, never an automatic adoption. Returned/voided check replacement prefills its immutable predecessor without rewriting it. Lost deposit responses reconcile the original command key rather than depositing again.

Prepaid API and unfinished-form contracts apply the same trimmed safe-reference grammar as actual receipt methods, including replacement. No raw check/account/routing number or check image is accepted. FIN-007 acceptance evidence is in the [October 13 completed record](../archive/designs/FIN-007_DESIGN_COMPLETED_2026-10-13.md); browser context is owned by [check-context.tsx](../../application/apps/web/src/workflows/check-context.tsx).

## Actual expenses and refunds

An Expense is confirmed paid spending for one Property and optionally one of its Spaces, with category, durable payee, payer and optional Provider. Categories have their own catalog revision/receipt namespace. Expense/refund commands share Expense revision; category changes never rewrite Expense history.

Evidence is linked after the Expense exists through Files. Estimates, invoices not yet paid and recurring payables are outside this actual-spending record. Corrections explicitly void/replace; refunds have their own received date and retained history. Do not use an Expense detail's lifetime net amount as a selected-period total.

The browser shows named Property/Space/category context, paid-to and payer facts, refunded/net amounts, active evidence and lifecycle status. Filters cover Property, Space, category, Provider, payer kind/Party, paid-date range, evidence and voided history. Creation offers bounded Property/Provider choices, limits Spaces to the selected Property and displays its local time zone. A Provider replaces the merchant-label choice; a Party payer must have owned the Property on the paid date. Archived references require explicit historical confirmation and a reason before they become selectable.

Read-only `POST /api/expenses/duplicate-review` returns at most ten active candidates matching Property, paid date, exact amount/currency and normalized merchant or Provider identity. The browser reviews these before preparing an immutable create attempt, with Open existing, Go back and Record separately choices. Creation rechecks under the write transaction; a late race never changes or automatically resends an unresolved payload. The shared SQL predicate filters payees before applying the limit.

The committed result offers Add evidence or Skip; upload failure leaves spending saved. Evidence archival retains the link/reason in contextual history. Category correction requires its own reason, while a notes-only edit omits category fields. Expense and refund replacements prefill their voided predecessors without rewriting them, and refunds remain independently dated and bounded by active spending.

## Security deposits

One account per Lease snapshots an explicit term/agreed amount. Deposit receipts/refunds are separate from rent and expense money. Receipts retain payer and recipient snapshots; historical entries require explicit confirmation where applicable. No receipt is inferred from agreement alone.

A settlement has draft, approved, completed and voided states. Draft deductions/credits are editable; approval freezes selected receipt membership, evidence snapshots and arithmetic. Every approved deduction requires an allowed explicit File, finalized inspection, rent-expectation or Expense source. The amount is operator-entered; evidence does not decide tenant liability. Deductions cannot exceed held receipts plus credits.

Refund due equals approved receipts plus credits less deductions. Actual partial refunds are retained payments. Completion requires exact refund fulfillment or confirmed zero-dollar closure. Late receipts remain visibly unsettled; voiding a settlement does not erase truthful refunds. Correction requires a replacement settlement and preserved lineage. The settlement deadline is operator-recorded, with source/rule notes, rather than a calculated legal determination. Account commands share the account revision.

The browser displays agreed/received/refunded amounts, signed variance, unresolved balance, Property time zone, deadline/rule notes, proposed arithmetic and frozen approval totals. Account lists support Property/Space/Lease, settlement-state, deadline-state and unresolved-balance filters. Party selection uses the bounded source-owned [Party selector](parties.md#api-and-disclosure); archived choices require historical confirmation and a reason. Likely receipt/refund duplicates are reviewed before submission, with explicit separate-payment confirmation and no automatic merge. Finance still rechecks duplicates and policy in the write transaction.

Optional simple-interest review uses `principal × annual rate × days ÷ 365`, inclusive start/exclusive end, and exact integer arithmetic rounded once half-up to cents. Positive principal, 1–100,000 integer basis points and 1–36,600 days are required. The operator reviews every input and the applied credit; a changed applied amount requires a 1–1,000 character override reason. Changed reviewed inputs invalidate confirmation. The server recalculates and retains the inputs, day count and result; the calculator never determines a statutory rate.

Read-only `GET /api/security-deposits/{id}/deduction-source-preview` reviews one explicit inspection, rent or Expense reference through Finance's transaction ports, checks membership and displays current lifecycle/outstanding-rent facts. It creates no source or deduction. Changed selections require review again; actual writes and approval recheck eligibility and freeze source facts. Missing draft evidence is explained separately from approval readiness.

Receipt/refund replacements prefill voided predecessors and retain both lineage directions. Draft evidence can be archived before deleting an incorrect deduction, while file IDs, archive reasons and association history remain retained. Evidence projections consume the shared FILE-001 metadata reader, expose availability/verification facts without provider locators, hide archived associations from normal lists and disable opening unavailable content. Approval/completion, exceptional timing, overages and recipient overrides remain explicit confirmations; recorded refunds do not send money.

## Reporting semantics

For an explicit inclusive property-local date range:

| Metric | Authority |
| --- | --- |
| Rent received | Each current non-voided receipt once, on received date |
| Expenses paid | Non-voided paid Expense on paid date |
| Expense refunds | Active refund of an active Expense, on refund received date |
| Net recorded expenses | Expenses paid minus refunds received |
| Rent less net expenses | Rent received minus expenses paid plus refunds received |

These figures describe recorded activity, not bank balance, profit or owner entitlement. A February refund against January spending belongs to February; corrected source state can restate the original date. Scheduled checks and pending owner reports contribute nothing. Deposit activity is shown separately.

Current recorded deposit obligation is all active receipts + current approved credits − current approved deductions − actual refunds, across all recorded dates. It is current at `asOf`, not a historical balance at the period end. Preserve negative reconciliation values and expose positive/negative components independently. Zero obligation does not complete a settlement automatically.

## Summary reads and query boundaries

`MoneySummaryService` provides portfolio/property totals, bounded property pages and source drill-down. Require explicit dates, maximum 3,660 days, and at most 100 explicit Property IDs. Default reporting includes retained archived Properties. No ownership-share or local-operator cash inference is made.

Read under one deferred snapshot and captured instant, using a source-owned Lease-location relation and set-based Finance aggregates. Preaggregate children to prevent multiplicative joins. Missing relationships and overflow fail the affected result; they do not silently omit or clamp money. Cursor/source revisions reject changed views. Source drill-down shares normalized scope and returns bounded data.

Money → Reporting requires an explicit inclusive period and defaults to all retained Properties, with active/archived scope choices. Portfolio and Property totals show exact signed USD values, source counts and `asOf`; operating remainder is labeled **Rent less net expenses**, not profit, cash or owner entitlement. Period deposit activity and current all-date deposit obligations remain separate. Metric/account links preserve period, scope and source revision while clearing collection-specific cursors. Property rows open same-period scoped reporting; Property context is a separate link. Changed or unavailable views retain their filters for an explicit restart and never substitute zero amounts.

## API families

Rent expectation/receipt/ledger routes, `/api/prepaid-checks`, Expense/category/refund routes and deposit account/settlement routes own writes. Money summary/source routes own reads. Use each router's typed contracts for exact fields and domain error codes; use Finance's command-key recovery for immutable original results. [Owner rent reports](owner-accounting.md) create/adopt receipts through Finance's transaction port, rather than writing a second income source.

## Browser workflow boundary

Money browser views separate Rent, Received rent, Expenses, Deposits, Scheduled checks, Owner reports, category administration and explicit-period Reporting. Registered forms preserve aggregate revisions and original results; actual refunds, void/replacement and settlement actions remain explicit. Evidence upload is an independent recoverable step, so failure preserves committed money. Reporting uses bounded FIN-003 source/property pages with integer USD formatting. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/finance/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/finance/application).
- [HTTP contracts](../../application/apps/server/app/modules/finance/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/finance/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `finance_command_revisions`, `finance_command_operations` | [command_models.py](../../application/apps/server/app/modules/finance/infrastructure/command_models.py) |
| `rent_expectations`, `rent_expectation_timeliness_reviews`, `rent_receipts`, `rent_receipt_allocations`, `prepaid_checks`, `prepaid_check_operations`, `expense_categories`, `expense_category_command_operations`, `expenses`, `expense_refunds`, `security_deposit_accounts`, `security_deposit_receipts`, `security_deposit_settlements`, `security_deposit_settlement_receipts`, `security_deposit_deductions`, `security_deposit_deduction_sources`, `security_deposit_credits`, `security_deposit_refunds` | [sqlalchemy_models.py](../../application/apps/server/app/modules/finance/infrastructure/sqlalchemy_models.py) |

## Validation

DASH-001's source rent-attention reader projects current positive outstanding expectations using active allocations, local due dates and Finance's effective review policy. Home's recorded-money projection reuses the FIN-003 caller-snapshot reader and exact metric drill-downs; reports, scheduled checks and deposit activity remain separate from received rent. See the [Slice 5 validation matrix](../archive/validation/DASH-001_CONTRACT_EXAMPLES_COMPLETED_2026-10-14.md#slice-5-rent-attention-and-recorded-money), [rent attention tests](../../application/apps/server/app/modules/finance/tests/test_attention_reader.py) and [Home money integration tests](../../application/apps/server/app/modules/operator/tests/test_home_money.py).

FIN-001 acceptance was completed on October 12, 2026; its [completed acceptance record](../archive/designs/FIN-001_DESIGN_COMPLETED_2026-10-12.md) records the matrix and focused results. Other Finance backlog items retain their own acceptance gates. The following executable specifications are entry points for future focused validation.

FIN-002 acceptance completed on October 13, 2026: [focused matrix and results](../archive/designs/FIN-002_DESIGN_COMPLETED_2026-10-13.md). Current Expense browser implementation is in [expense-context.tsx](../../application/apps/web/src/workflows/expense-context.tsx), [money-command.tsx](../../application/apps/web/src/workflows/money-command.tsx) and [Money browser tests](../../application/apps/web/tests/money.spec.ts).

FIN-008 acceptance completed on October 13, 2026: [focused matrix and results](../archive/designs/FIN-008_DESIGN_COMPLETED_2026-10-13.md). Deposit-specific browser review is in [deposit-context.tsx](../../application/apps/web/src/workflows/deposit-context.tsx), alongside the shared Money commands/records and browser tests.

FIN-006 acceptance completed on October 13, 2026: [focused matrix and results](../archive/designs/FIN-006_DESIGN_COMPLETED_2026-10-13.md). The actual-method review and client guard are in [rent-context.tsx](../../application/apps/web/src/workflows/rent-context.tsx); backend method, privacy, idempotency and portability cases remain in `test_finance.py`.

- [test_category_command_readiness.py](../../application/apps/server/app/modules/finance/tests/test_category_command_readiness.py).
- [test_commands.py](../../application/apps/server/app/modules/finance/tests/test_commands.py).
- [test_consumer_commands.py](../../application/apps/server/app/modules/finance/tests/test_consumer_commands.py).
- [test_expenses.py](../../application/apps/server/app/modules/finance/tests/test_expenses.py).
- [test_finance.py](../../application/apps/server/app/modules/finance/tests/test_finance.py).
- [test_money_context.py](../../application/apps/server/app/modules/finance/tests/test_money_context.py).
- [test_money_summary.py](../../application/apps/server/app/modules/finance/tests/test_money_summary.py).

FIN-003 acceptance completed October 13, 2026: **21 money-summary backend tests and 3 focused reporting browser cases passed**. The [completed acceptance matrix](../archive/designs/FIN-003_DESIGN_COMPLETED_2026-10-13.md) covers corrections, independently dated refunds, signed deposit reconciliation, archived scope, concurrent snapshots, bounded queries, encrypted restore and stale-view drill-down. Home/DASH presentation and future owner accounting/reporting extensions remain separate features.

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
