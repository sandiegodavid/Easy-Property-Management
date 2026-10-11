# MAINT-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Issues, appointments, quotes and work journals](../modules/maintenance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 53, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Issue/appointment/cost/Expense-link/follow-up workflows and distinct status, appointment completion, work completion and verified repair outcome.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

MAINT-001 backend/API scope is complete when:

1. An operator can record an issue for an active property and optional matching space, with required category, priority, reported time, summary, and description.
2. Issue start, resolution, cancellation, and reopen transitions enforce their invariants and retain append-only audit history.
3. Appointments use the property time zone, retain reschedule/completion/cancellation history, and block issue resolution while still scheduled.
4. Estimates and work-reported amounts remain clearly non-financial and cannot affect Finance totals.
5. Confirmed spending is represented only by validated links to existing FIN-002 expenses; Maintenance stores no copied actual amount.
6. Issue, appointment, and cost-context evidence uses FILE-001 validation and archival without duplicating file metadata.
7. Maintenance-created TASK-001 follow-ups are atomic with their creation audit and remain lifecycle-independent from the issue.
8. List/detail projections use bounded set-based queries and expose no N+1 behavior as page size or linked-record count grows.
9. All retained maintenance records, links, task relations, evidence, audit events, and correction lineage survive encrypted backup/restore with stable IDs.
10. Typed APIs reject unknown or malformed fields and return controlled `404`, `400`, `409`, `413`, and `422` outcomes.
11. Retrying any included issue or child command with the same key and full semantic payload returns its original immutable response before current validation, without duplicate rows, Tasks, revisions or audits. Changed-payload reuse and stale revisions return typed `409` with current issue revision. Effective commands advance the shared revision once; no-op edits persist receipts without advancing it. Receipt schema, audit evidence and replay survive encrypted restore.

Overall MAINT-001 must not be marked as a finished operator workflow until `UI-001` delivers the maintenance interface and MAINT-004 delivers reporter attribution.

## Validation and delivery references

- [Current module and focused tests](../modules/maintenance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/MAINT-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
