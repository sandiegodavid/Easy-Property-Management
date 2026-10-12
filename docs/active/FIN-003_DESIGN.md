# FIN-003 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Rent, expenses, deposits and money summaries](../modules/finance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 52, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Explicit-period portfolio/Property money, exact amounts, archived scope, deposit separation, source drill-down, matching totals and stale-view restart.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

## Validation and delivery references

- [Current module and focused tests](../modules/finance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/FIN-003_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
