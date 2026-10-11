# FIN-002 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Rent, expenses, deposits and money summaries](../modules/finance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 52, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Actual paid expenses, category administration, evidence, independently dated refunds, corrections and safe payee/payer context.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Retained operator requirements

UI-001 adds **Money > Expenses** with filters matching the API and plain-language columns Date paid, Property, Space, Category, Paid to, Paid by, Amount, Refunded, Net, Evidence, and Status. Voided records are hidden by default but can be included. Every amount opens its expense, refund, evidence, and correction source records.

**Record expense** requires property, category, paid date, decimal amount, payee/provider choice, payer, and description. Space, reference, and notes are optional. Provider search excludes archived providers and displays a separate merchant-label path. Selecting a property limits spaces and shows its local time zone. The client creates and retains the UUID idempotency key across retries.

When the API identifies likely duplicates, the screen shows bounded candidates and offers **Open existing**, **Go back**, or **Record separately**. It never merges automatically. After the expense is saved, the workflow moves to **Add evidence**. Upload errors leave the expense visibly saved and provide retry/skip actions.

Detail supports category/notes updates, evidence-link archival, refund recording, and explicit void-and-replace flows. Void/replacement screens preserve the old record and show lineage. Historical selection of an archived property, space, provider, or category is visually exceptional and requires confirmation plus a reason.

## Acceptance constraints to verify

FIN-002 is complete when:

1. The operator can record one exact, positive, already-paid USD expense for one property and optional child space, with a Finance category, durable payee, payer, description, date, and idempotent retry behavior.
2. Provider-backed and free-text payees, archived historical references, and party-funded expenses obey the documented cross-module guards without direct persistence coupling.
3. Likely duplicates are shown for operator review and are never merged automatically.
4. Expense and refund corrections preserve explicit void/replacement lineage; active refunds cannot exceed or outlive their active expense.
5. Zero to twenty FILE-001 evidence links can be added after creation, and an incorrect association can be archived with retained history rather than deleted.
6. FIN-002 contains no bills, due dates, recurrence, reminders, payment initiation, multi-property allocations, maintenance workflow state, or portfolio aggregate reporting.
7. Typed API/application contracts, fail-closed audit presentation, exact schema validation, and encrypted backup/export/restore preserve the complete record.
8. UI-001 delivers the documented expense creation, duplicate review, evidence, filtering, refund, and correction workflows before FIN-002 is marked complete.

## Validation and delivery references

- [Current module and focused tests](../modules/finance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/FIN-002_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
