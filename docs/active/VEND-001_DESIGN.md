# VEND-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Providers, categories and reputation](../modules/providers.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Browser workflows for this feature are recorded as delivered in UI-001 Slice 50. Retain the feature acceptance gate until its owning requirements and final cross-workflow acceptance are verified; this reorganization does not mark the backlog complete.

## Remaining work

Validate delivered profile/shared identity/services/areas/history/reference/avoid-state workflows and final cross-workflow proof.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

VEND-001 is complete when:

1. Shared party identities are created, listed, updated, archived, and restored through the dedicated `parties` API rather than `portfolio` routes.
2. An operator can create a provider with a new party or designate one existing active party without duplicating identity data.
3. Provider services, service areas, manually recorded past work, references, and preferred/avoid state are lifecycle-managed, searchable, and retain stable history.
4. `avoid` always includes an explicit reason, active normalized service/area duplicates are rejected, and provider work records never impersonate maintenance records.
5. Shared-party archive respects role guards; provider archive never destroys party identity or child history.
6. Provider and party writes are atomic with correlated append-only audit events; generalized activity redacts contact and sensitive internal-context fields.
7. Typed APIs reject unknown/malformed input and return controlled 404/400/409/413/422 outcomes.
8. Exact latest-schema validation and encrypted backup/export/restore preserve provider data, relationships, and audit history.
9. VEND-001 leaves configurable categories, reputation links, discovery, quote selection, assignments, costs, and communications to their owning backlog items.

## Validation and delivery references

- [Current module and focused tests](../modules/providers.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/VEND-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
