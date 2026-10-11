# OPS-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Operator compositions, coverage and form recovery](../modules/operator.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Bootstrap, preferences, recovery and contextual directories are delivered in the frontend. Remaining search/coverage workflows and final integration acceptance are in UI-001 Slices 54 and 57.

## Remaining work

Source-backed search groups, archived/context targets, coverage causes/non-applicability and revision-safe manual review. Finish cross-workflow recovery/navigation acceptance.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

## Validation and delivery references

- [Current module and focused tests](../modules/operator.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/OPS-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
