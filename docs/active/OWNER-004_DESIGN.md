# OWNER-004 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Owner operational concerns](../modules/owner-management.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 53, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Concern context/lifecycle/resolution, linked conversations and optional Task follow-up, with independent source authority and interrupted-write recovery.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

OWNER-004 backend/API scope is complete when:

1. The operator can record one concern from a historically eligible client-owner Party with valid property and type-specific context.
2. Local-operator ownership is never converted into a fake Party or inferred raising owner.
3. Concern, communication, task, and source-module lifecycles remain independent and authoritative in their owning modules.
4. Lease, tenant, vacancy, and general-rental context is validated in one transaction and retained through immutable snapshots.
5. Duplicate candidates are shown, independent duplicates require confirmation, and no records are merged automatically.
6. Active fields, explicit terminal transitions, reopening, and target correction preserve complete audit history and nonbranching lineage.
7. COM-001 can retain typed concern links and OWNER-004 can atomically create idempotent TASK-001 follow-ups.
8. Unresolved concerns block property archival without blocking unrelated Party, tenant, lease, ownership, or operational-state history.
9. List/detail reads are bounded and set-based, and generalized audit presentation redacts sensitive narratives and identities.
10. Exact schema/data validation and encrypted backup/restore preserve concerns, snapshots, operations, links, tasks, lineage, and correlated audit evidence.

The overall feature remains incomplete until UI-001 supplies the operator workflow and DASH-001 supplies the agreed owner-action presentation.

## Validation and delivery references

- [Current module and focused tests](../modules/owner-management.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/OWNER-004_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
