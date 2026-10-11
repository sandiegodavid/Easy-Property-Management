# MAINT-003 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Issues, appointments, quotes and work journals](../modules/maintenance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 53, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Issue-backed append-only work journal, outcome/evidence and separate verification; journal entry must not implicitly close source records.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

MAINT-003 backend/API scope is complete when:

1. The operator can append actual work start, progress, blocked, completion, note, and correction facts to a retained issue.
2. Entries are immutable at the database and API boundaries; corrections are append-only, nonbranching, and retain the original.
3. Optional assignments are same-issue stable references and support current, ended, archived-provider, and unassigned work history without copied provider identity.
4. Completion outcomes distinguish source, operator verification, result, and follow-up need without changing issue, assignment, or appointment lifecycle.
5. Journal narratives contain no money; quotes, cost context, and actual expenses remain in their owning records.
6. Completion evidence links to journal entries through FILE-001 and remains optional, portable, and independently correctable.
7. Issue detail remains bounded, complete history is cursor-paginated, and provider history is a bounded Maintenance-owned projection with no N+1 behavior.
8. Quoted schedule dates and actual effective work timing remain distinct and can be compared without overstating recorded assignment time as provider response time.
9. Audit presentation protects sensitive narratives, and exact validation plus encrypted backup/restore preserve rows, corrections, links, triggers, audit events, and stable IDs.
10. Providers' manual prior-work notes remain distinct from issue-backed outcomes and are never synchronized by duplicated writes.

The overall operator workflow remains pending until `UI-001` supplies the journal timeline, evidence, correction, and explicit adjacent lifecycle actions.

## Validation and delivery references

- [Current module and focused tests](../modules/maintenance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/MAINT-003_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
