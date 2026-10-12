# LEASE-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Leases, renewals and termination](../modules/leases.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Browser workflows for this feature are recorded as delivered in UI-001 Slice 51. Retain the feature acceptance gate until its owning requirements and final cross-workflow acceptance are verified; this reorganization does not mark the backlog complete.

## Remaining work

Validate the delivered contract/participant/renewal/termination and physical-timeline workflows, independent Lease/Space revisions, document recovery and final cross-workflow proof.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

LEASE-001 is complete when:

1. An operator can record residential or commercial draft leases for one active rentable space with initial terms and the required participant role.
2. Executing, ending, terminating, and voiding a lease create only valid lease-owned occupancy timeline changes and never infer availability; requesting or accepting an early termination does not end truthful occupancy.
3. Current and future lease occupancy is conflict-checked against valid space history, and manual routes cannot overwrite lease-owned records.
4. Lease participants reuse active tenant profiles without duplicating shared identity or contact data, and active/scheduled relationships enforce archive guards.
5. Terms, deposits, dates, renewal options, document links, and lifecycle state are audit-backed and survive encrypted backup/export/restore.
6. The API has explicit request/response contracts and controlled `400`, `404`, `409`, `413`, and `422` behavior.
7. The UI provides the deferred operator workflows before the backlog item is marked done.
8. An operator can record and negotiate a job-relocation termination request, retain proposal history, accept an agreement without premature vacancy, and complete it only with confirmed actual move-out.
9. Every term exposed to FIN-001 has positive integer base rent and the fixed `USD` currency code enforced at both application and database boundaries.

## Validation and delivery references

- [Current module and focused tests](../modules/leases.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/LEASE-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
