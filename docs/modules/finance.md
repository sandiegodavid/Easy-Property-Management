# Rent, expenses, deposits and money summaries

## Authority and money representation

Finance owns immutable rent expectations, recorded receipts/allocations, actual paid expenses/refunds, prepaid checks, deposit accounts/settlements and financial summaries. Currency is USD. Store integer cents, calculate with exact decimal rules and expose canonical decimal strings; browser floating-point sums are not authoritative.

Lease terms are read through source-owned transactional ports. Lease execution never creates expectations or payments. Operational repair estimates/quotes and pending owner reports are not spending or income. Financial corrections retain void/replacement history and original operation results.

## Rent schedule and receipts

The operator synchronizes one explicit Lease term and confirms its schedule anchor. Monthly cadence uses the configured due day with per-month clamping; weekly cadence uses seven-day intervals. Covered periods are inclusive. First/final stubs use actual calendar-day proration with decimal half-up rounding and a reconciled final rounding remainder. Exclusive Lease end/move-out becomes the preceding covered date; explicit rent-responsibility end is inclusive.

Expectations retain source term, dates, amount and generation decisions. Later contract changes do not overwrite them. Record one receipt and explicitly allocate it across eligible expectations; allocating never creates additional income. Partial/unpaid/late classifications use server facts and property-local dates. Likely duplicate payments require operator review.

Each receipt freezes the actual payment method: external automatic bank payment, transfer, check, cash, online or other, with safe masked references. The last receipt may provide an editable suggestion, not an expected method. Rent and prepaid-check mutations share the Lease rent-ledger revision, UUID keys and read-only command recovery.

## Prepaid checks

One future-dated check covers exactly one complete expectation period and eligible lease payer. Scheduling creates a property-local reminder, not income. Deposit eligibility is derived from the local day. Explicit deposit validates open amount and atomically creates/adopts the compatible receipt, allocations and Task effects. Return voids the linked receipt atomically. Void/replace retains nonbranching lineage; a never-deposited replacement has no receipt or deposit event.

## Actual expenses and refunds

An Expense is confirmed paid spending for one Property and optionally one of its Spaces, with category, durable payee, payer and optional Provider. Categories have their own catalog revision/receipt namespace. Expense/refund commands share Expense revision; category changes never rewrite Expense history.

Evidence is linked after the Expense exists through Files. Estimates, invoices not yet paid and recurring payables are outside this actual-spending record. Corrections explicitly void/replace; refunds have their own received date and retained history. Do not use an Expense detail's lifetime net amount as a selected-period total.

## Security deposits

One account per Lease snapshots an explicit term/agreed amount. Deposit receipts/refunds are separate from rent and expense money. Receipts retain payer and recipient snapshots; historical entries require explicit confirmation where applicable. No receipt is inferred from agreement alone.

A settlement has draft, approved, completed and voided states. Draft deductions/credits are editable; approval freezes selected receipt membership, evidence snapshots and arithmetic. Every approved deduction requires an allowed explicit File, finalized inspection, rent-expectation or Expense source. The amount is operator-entered; evidence does not decide tenant liability. Deductions cannot exceed held receipts plus credits.

Refund due equals approved receipts plus credits less deductions. Actual partial refunds are retained payments. Completion requires exact refund fulfillment or confirmed zero-dollar closure. Late receipts remain visibly unsettled; voiding a settlement does not erase truthful refunds. Correction requires a replacement settlement and preserved lineage. The settlement deadline is operator-recorded, with source/rule notes, rather than a calculated legal determination. Account commands share the account revision.

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

DASH-001's source rent-attention reader projects current positive outstanding expectations using active allocations, local due dates and Finance's effective review policy. Home's recorded-money projection reuses the FIN-003 caller-snapshot reader and exact metric drill-downs; reports, scheduled checks and deposit activity remain separate from received rent. See the [Slice 5 validation matrix](../active/DASH-001_CONTRACT_EXAMPLES.md#slice-5-rent-attention-and-recorded-money), [rent attention tests](../../application/apps/server/app/modules/finance/tests/test_attention_reader.py) and [Home money integration tests](../../application/apps/server/app/modules/operator/tests/test_home_money.py).

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_category_command_readiness.py](../../application/apps/server/app/modules/finance/tests/test_category_command_readiness.py).
- [test_commands.py](../../application/apps/server/app/modules/finance/tests/test_commands.py).
- [test_consumer_commands.py](../../application/apps/server/app/modules/finance/tests/test_consumer_commands.py).
- [test_expenses.py](../../application/apps/server/app/modules/finance/tests/test_expenses.py).
- [test_finance.py](../../application/apps/server/app/modules/finance/tests/test_finance.py).
- [test_money_context.py](../../application/apps/server/app/modules/finance/tests/test_money_context.py).
- [test_money_summary.py](../../application/apps/server/app/modules/finance/tests/test_money_summary.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
