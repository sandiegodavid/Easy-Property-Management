# OWNER-003 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Owner-reported rent](../modules/owner-accounting.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 52, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Claim/evidence entry, edit/reject and explicit adopt/create receipt verification, historical owner context, duplicate prevention and changed Finance/report revisions.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

OWNER-003 backend/API scope is complete when:

1. The operator can record one client-owner's direct-rent report with who reported it, when, how funds were received, exact USD amount/date, lease/property context, and evidence.
2. Pending and rejected reports never affect income, expectations, balances, statements, or disbursements.
3. Verification requires evidence and an explicit human decision and atomically links exactly one compatible active FIN-001 receipt.
4. Verification can adopt an existing receipt or create one through Finance without bypassing receipt/allocation, payment-method, idempotency, duplicate, or concurrency rules.
5. The same reported money cannot create duplicate income or be linked to two owner reports.
6. Historical client-owner eligibility and identity snapshots preserve truthful past reports without inventing ownership percentages or legal entitlement.
7. Pending corrections, terminal replacement lineage, FIN-001 void/replacement history, and FILE-001 link archival retain full history without destructive edits.
8. List/detail reads are bounded and set-based, and downstream consumers derive money only from active FIN-001 receipts.
9. General audit presentation redacts financial and identity-sensitive data while contextual history retains authorized provenance.
10. Exact schema/data validation and encrypted backup/restore preserve reports, operations, evidence, receipt/allocation links, replacement chains, and correlated audits.

The overall feature remains incomplete until its operator workflow is delivered through the agreed UI backlog scope.

## Validation and delivery references

- [Current module and focused tests](../modules/owner-accounting.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/OWNER-003_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
