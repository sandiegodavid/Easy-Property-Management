# FIN-008 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Rent, expenses, deposits and money summaries](../modules/finance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 52, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Account/receipt/settlement/deduction/source/credit/refund flows, reviewed simple-interest calculator, explicit approval/completion, deadline context and unsettled/corrected history.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

FIN-008 backend/API scope is complete when:

1. One current-format account per lease snapshots one explicit lease term and supports multiple immutable receipts.
2. Receipt and refund retries are idempotent, likely duplicates require review, and corrections form retained void-and-replace chains.
3. Deposits never create rent income; deductions never create or copy expenses; inspection classifications never create deductions.
4. Every approved deduction has an allowed active source, and source snapshots remain stable after later changes.
5. Approval freezes exact receipt membership and satisfies `refund due = receipts + credits - deductions` with exact cents.
6. Interest calculations use the documented inputs, day convention, and half-up rounding, with reasons for applied overrides.
7. Refund totals cannot exceed the approved refund due, and completion requires exact payment or explicit zero-refund confirmation.
8. Deadlines use property-local dates and operator-entered rule context without statutory inference or legal-compliance claims.
9. Party selection, archived sources, overages, exceptional settlement timing, and recipient overrides enforce the documented confirmations.
10. Every aggregate mutation and file-link guard is transaction-scoped, concurrent-safe, and atomically audited.
11. Global activity redacts sensitive financial context while contextual history and encrypted backup/restore preserve complete records.
12. Tests cover happy paths, zero-dollar closure, partial and multiple receipts/refunds, duplicate and idempotency cases, stale sources, post-approval receipts, correction chains, archive/history selection, rounding edges, FILE-001 limits, concurrency, audit redaction, and restore rejection.

The overall backlog item remains incomplete until UI-001 delivers and verifies the operator workflow described here.

## Remaining interest-calculator interaction

Use `principal × annual rate × days ÷ 365`, with inclusive start/exclusive end and exact decimal half-up rounding once to cents. The entered day count must equal `endsOn - startsOn`. Principal/rate are positive; rate bounds are 1–100,000 basis points and period at most 36,600 days. If applied credit differs from the calculation, require a 1–1,000 character reason. Show inputs and result for operator confirmation; this is a calculation convenience, not a statutory rate/deadline determination.

## Validation and delivery references

- [Current module and focused tests](../modules/finance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/FIN-008_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
