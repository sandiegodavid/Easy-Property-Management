# FIN-009 Checkpoint — Late Fees

Date: November 27, 2026  
Owning design: [FIN-009_DESIGN.md](FIN-009_DESIGN.md)  
Status: **✅ Complete (Slices 1–6 delivered and validated)**

---

## 1. Delivered Scope

- **Schema & integrity (`application/database/` & Finance infrastructure):**
  - Added 6 tables (`late_fee_policy_versions`, `late_fee_assessments`, `late_fee_waivers`, `late_fee_lease_waivers`, `late_fee_receipts`, `late_fee_receipt_allocations`) and `rent_receipts.payment_batch_id` in [0001_initial_schema.py](../../application/database/sqlite-migrations/versions/0001_initial_schema.py), with immutability triggers, partial unique indexes, and restore-time conservation checks (receipt-to-allocation equality and waivers + active allocations ≤ assessed amount) in [schema_validation.py](../../application/apps/server/app/modules/finance/infrastructure/schema_validation.py).
  - Updated database index docs ([overview.md](../database/overview.md), [schema-resources.md](../database/schema-resources.md)) and [finance.md](../modules/finance.md).

- **Policy versioning & deterministic preview engine:**
  - Effective-dated, operator-confirmed lease late-fee policies (`fixed_flat`, `percentage_once`, `daily_flat`, `fixed_plus_daily_flat`; `half_up`/`floor`; `unpaid_rent_at_grace_end`/`current_unpaid_rent`/`scheduled_rent`), non-overlapping active windows, superseding, and unused-policy voiding in [late_fee_service.py](../../application/apps/server/app/modules/finance/application/late_fee_service.py) and [late_fee_router.py](../../application/apps/server/app/modules/finance/api/late_fee_router.py).
  - Read-only property-zone calculation preview ([late_fee_calculator.py](../../application/apps/server/app/modules/finance/domain/late_fee_calculator.py)) with step-by-step math, `previewFingerprint`, `FIN-007` scheduled prepaid check and `PAY-001` processing payment warnings, SQL candidate filtering (open or late-paid periods before the 24-row cap), explicit `rentExpectationId` selection, and keyset `cursor`/`nextCursor` continuation.

- **Assessment, auto-assessment, waiver, correction, receipts & `FIN-003` reporting:**
  - Idempotent write-authorized automatic late-fee assessment (`POST /api/late-fees/sync`, scoped by `leaseId`/`propertyId`/`rentExpectationId`, plus workspace startup; committed via `auto_assess_late_fees` Finance command ledger advancing `rentLedgerRevision`, cursor-paged across all candidates; `GET` list routes remain strictly read-only) for confirmed policies (including bounded daily accrual up to caps/max days; skipping processing payments, voided unreplaced assessments, waived occurrences, `D9` voided/returned receipts under the selected calculation basis, and active/revoked lease-level waiver windows), alongside explicit operator assessment, append-only per-occurrence partial/full waivers, **lease-level waivers** (`GET/POST /api/leases/{lease_id}/late-fee-waiver` and `/revoke`, with atomic all-or-nothing bulk waiver of currently unpaid fees), void and void-and-replace corrections, `sourceDriftWarning`, and active-late-fee protection when voiding rent expectations.
  - Portfolio/lease assessment queue with SQL `settlementStatus` filtering before pagination and continuation cursors bound to normalized filters + 15-minute `asOf` TTL.
  - Standalone `late_fee_receipts` (with `FIN-006` masked-reference enforcement, void, and linked replacement) and atomic combined rent + late-fee receipts (`payment_batch_id`), plus separate `lateFeesReceived` / `lateFeeReceiptCount` reporting and drill-down in `MoneySummaryService`.

- **Shared portal read port & `PAY-001` integration contracts:**
  - Scoped `LateFeeReadPort` (`operator`, `tenant`, `owner` projections) in [late_fee_read_adapter.py](../../application/apps/server/app/modules/finance/infrastructure/late_fee_read_adapter.py) ensuring identical assessed math across portals while redacting previews, voided assessments, and internal operator notes from tenant/owner views.
  - `PAY-001` Finance contracts in [pay001_late_fee_adapter.py](../../application/apps/server/app/modules/finance/application/pay001_late_fee_adapter.py): oldest-rent-then-oldest-fee allocation with `PendingPaymentReader` reservations, `scheduled_on` due-date cutoff and `rent_only` / `rent_and_assessed_late_fees` autopay mandate fences, durable `payment_attempt_id` replay idempotency (including `unappliedProcessorFunds`), provider-attempt deduplication without manual heuristics, atomic bank-return reversals, and partial refund attribution validation.

- **Operator UI, contracts & manual:**
  - Regenerated `@epm/contracts` OpenAPI snapshot and TypeScript types.
  - Registered all 8 `FIN-009` late-fee command forms in backend `OPS-001` recovery (`command_forms.py`, `operator_command_forms.py`, `operator_finance_commands.py`) and wired server-backed `OPS-001` recovery (`useOpsRecoveryCommand` + `LeasePendingRecoveryBanner`) across every consequential late-fee mutation in [late-fees.tsx](../../application/apps/web/src/workflows/late-fees.tsx), alongside preview race/pagination-revision guards, period selection + continuation, void-and-replace assessment flow, and standalone/combined payments with `Other` method notes and self-clearing duplicate review.
  - Added `/money?record=late_fee_assessment&id=<uuid>` detail view and late-fee receipt **Void** / **Record replacement** actions with bidirectional links in [money-records.tsx](../../application/apps/web/src/workflows/money-records.tsx), single-form **Include assessed late fees** (`D15`) in **Record rent receipt** ([money-command.tsx](../../application/apps/web/src/workflows/money-command.tsx)), and `Late fees received` reporting row in [money-reporting.tsx](../../application/apps/web/src/workflows/money-reporting.tsx).
  - Updated operator documentation in [manual/money.md](../../manual/money.md) and [manual/leases-and-inspections.md](../../manual/leases-and-inspections.md).

---

## 2. Current Validation Results

| Check | Command / Scope | Result |
| --- | --- | --- |
| Finance late-fee, command & OPS-001 pytest suites | `pytest test_late_fee_policies.py test_late_fee_preview.py test_late_fee_assessments.py test_late_fee_receipts_and_reporting.py test_late_fee_portal_and_pay001.py test_commands.py test_consumer_commands.py test_finance_command_forms.py` (includes `LOCAL-002` encrypted backup/restore & restore corruption rejection for active and voided receipts) | **Passed** |
| Python lint & formatting | `ruff check` & `ruff format --check` on all changed Finance/Operator Python files | **Passed** |
| OpenAPI & TypeScript contracts | `cd application && npm run contracts:check` | **Passed** |
| Frontend lint, format & typecheck | `cd application && npm run lint && npm run format:check && npm run typecheck` | **Passed** (0 warnings/errors; 216 source files) |
| Frontend build & package | `cd application && npm run package:web` | **Passed** |
| Playwright browser acceptance | `cd application && npm run test:web -- apps/web/tests/late-fees.spec.ts` (end-to-end workflow, OPS-001 reload recovery & Money resubmission guard, in-flight duplicate input lock & signature binding, bidirectional assessment/receipt links, single-form combined split, preview pagination revision fence, 390/900/1440px reflow, Light/Dark themes, keyboard nav, WCAG 2.1 AA `axe-core`) | **Passed** (`5 passed`) |
