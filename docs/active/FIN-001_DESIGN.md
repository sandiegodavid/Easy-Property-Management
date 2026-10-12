# FIN-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Rent, expenses, deposits and money summaries](../modules/finance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 52, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Explicit schedule-anchor confirmation, rent synchronization, receipt/allocations/corrections and exact server-backed outstanding/timeliness presentation.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Retained operator requirements

UI-001 adds a **Money** workflow with **Rent expectations** and **Recorded receipts** views. The expectation list uses the plain-language columns Expected, Money received, Still due, Due date, Covered period, and Needs attention while retaining the precise settlement/timeliness labels in detail and accessible help text. Filters mirror the API, and every amount drills into its receipt allocations rather than presenting an unexplained total.

From an executed lease, **Synchronize rent expectations** requires the operator to select one term. It displays the property time zone, term amount/frequency, suggested recurrence anchor, effective term/responsibility boundary, and a complete preview of every full or prorated period before confirmation. Prorated rows show their covered-day fraction and rounded amount. A responsibility override is visually exceptional and requires its own confirmation and reason.

**Record receipt** generates the UUID idempotency key in the client, defaults `receivedByPartyId` to null (local operator), permits selection of an existing shared party, and allocates 1–100 amounts against still-open expectations from one lease/currency. `FIN-006` pre-fills the required editable actual-method snapshot from the latest non-voided receipt for that lease; it is not a saved expected-payment instruction. The screen continuously shows receipt total, allocated total, and remaining balance and cannot submit until they are equal. **Void and replace** first confirms the void reason and then opens a prefilled new receipt with explicit replacement lineage and a new idempotency key; it never edits the old record.

An unpaid ended period remains **Late** unless the operator chooses **Mark missed**, confirms, and records a reason. Detail shows the review history and provides **Clear missed classification** with a new reason. The UI never describes these operational labels as a legal conclusion, never initiates collection, and does not expose a portfolio money aggregate before FIN-003.

## Acceptance constraints to verify

FIN-001 is complete when:

1. An operator can synchronize accurate, nonduplicated recurring expectation snapshots for one selected term of an eligible executed lease using a confirmed recurrence anchor, deterministic edge proration, responsibility boundary, and bounded horizon.
2. Each expectation clearly shows expected, received, outstanding, settlement, and timeliness state without asserting legal delinquency or applying a hidden grace period.
3. A receipt can be allocated across one lease’s eligible expectations atomically; totals, currency, lifecycle, and over-allocation rules are enforced under concurrency.
4. Receipt corrections are explicit void-and-replace chains; expectation corrections are void-only until a future adjustment workflow. Both retain correlated audit history and use no physical deletion.
5. FIN-006 actual receipt-method snapshots and FIN-007 check/deposit status extend this slice under their own designs; reusable expected-method storage, bank integration, and automatic collection remain absent.
6. Typed HTTP and application contracts provide controlled `400`, `404`, `409`, `413`, and `422` outcomes.
7. Exact schema validation and encrypted backup/export/restore preserve all FIN-001 data and audit history.

## Validation and delivery references

- [Current module and focused tests](../modules/finance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/FIN-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
