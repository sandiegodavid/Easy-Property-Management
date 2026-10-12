# VEND-CAT-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Providers, categories and reputation](../modules/providers.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Browser workflows for this feature are recorded as delivered in UI-001 Slice 50. Retain the feature acceptance gate until its owning requirements and final cross-workflow acceptance are verified; this reorganization does not mark the backlog complete.

## Remaining work

Validate delivered catalog/assignment lifecycle, Uncategorized, taxonomy separation, revision-safe recovery and final cross-workflow proof.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Retained operator requirements

UI-001 presents category management under **Settings → Provider categories**. The operator can add, rename, describe, reorder, archive, restore, and inspect provider counts. Archived categories are visually separate and never appear in normal category pickers.

The Providers directory shows compact category labels, supports one category filter plus Categorized/Uncategorized coverage, and keeps free-form Services as separate detail. The provider create/edit workflow supports multiple category selection and preserves an unfinished provider as an ordinary uncategorized record only after the provider itself is successfully saved.

The interface explains the distinction in plain language:

- **Categories** organize the directory and later recommendations.
- **Services** describe the provider's specific offerings or practice areas.

Legal / Attorney appears as a category. An attorney's practice areas appear under Services. Opening or linking a legal engagement uses LEGAL-001 and does not create a Maintenance assignment.

## Acceptance constraints to verify

VEND-CAT-001 is complete when:

1. A new workspace contains the seven confirmed initial editable categories with stable identities and deterministic order.
2. The operator can lifecycle-manage categories without deletion or rewriting free-form provider services.
3. A provider can hold multiple retained category assignments, while Uncategorized remains explicit and queryable.
4. Provider create, list, detail, search, filtering, archive/restore, and import-facing contracts expose category state without N+1 queries or partial writes.
5. Category and assignment retries are idempotent, conflicts are explicit, and every effective mutation is atomically audited.
6. Category archive/restore preserves assignment history, and provider archive/restore does not destroy classification.
7. Maintenance, Finance, service labels, legal engagements, and AI decisions keep their own ownership and lifecycle boundaries.
8. Typed APIs use the shared `404/400/409/413/422` error conventions and never accept unknown fields.
9. Exact latest-schema validation and encrypted backup/export/restore preserve the complete catalog, assignment, idempotency, and audit state.
10. Focused tests cover the validation matrix, including fixed query budgets and current greenfield seed/schema verification.

## Validation and delivery references

- [Current module and focused tests](../modules/providers.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/VEND-CAT-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
