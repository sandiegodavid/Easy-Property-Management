# INSP-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Condition inspections and comparisons](../modules/inspections.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Browser workflows for this feature are recorded as delivered in UI-001 Slice 51. Retain the feature acceptance gate until its owning requirements and final cross-workflow acceptance are verified; this reorganization does not mark the backlog complete.

## Remaining work

Validate delivered checklist/report/acknowledgment/correction/comparison and evidence workflows, independent revisions, draft-only association archival and final settlement-context integration.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

INSP-001 is complete when:

1. The operator can finalize one pre-move-in and one post-move-out condition report for a lease and space while preserving both independently.
2. Reports support residential and office checklist templates, observations with observed dates and explicit completion, photos/documents, tenant presence, and per-active-participant acknowledgment state. Evidence uses the same links with the default local adapter or, when configured, the optional S3 adapter.
3. Post-move-out observations can be compared with the pre-move-in baseline and classified only through an explicit operator decision.
4. Inspection evidence becomes eligible for a typed maintenance-issue link after `MAINT-001` and for later deposit settlement without creating either record implicitly.
5. Finalized history cannot be silently rewritten; corrections, file links, and comparisons are atomic and audited.
6. The workflow prompts at appropriate lease milestones but never blocks recording truthful occupancy or lease lifecycle facts.
7. Typed APIs, current-schema validation, and encrypted backup/export/restore preserve the complete inspection record.
8. An incorrect draft-observation evidence link can be archived with explicit confirmation and reason, while finalized and superseded evidence remains immutable and correction-based.
9. The guided operator UI is delivered before the backlog item is marked done.

## Validation and delivery references

- [Current module and focused tests](../modules/inspections.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/INSP-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
