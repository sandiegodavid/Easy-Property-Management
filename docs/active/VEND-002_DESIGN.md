# VEND-002 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Providers, categories and reputation](../modules/providers.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Browser workflows for this feature are recorded as delivered in UI-001 Slice 50. Retain the feature acceptance gate until its owning requirements and final cross-workflow acceptance are verified; this reorganization does not mark the backlog complete.

## Remaining work

Validate delivered manual reputation links, URL safety, archive/restore and contextual history with final cross-workflow proof.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

VEND-002 is complete when:

1. An active provider can retain, edit, archive, and restore manual Google, Yelp, Angi, and named-other reputation links without duplicate active source or URL records.
2. URLs, source names, dates, and notes are validated by both typed HTTP inputs and application commands; no external requests occur.
3. Provider detail and summary expose the documented typed reputation representations without leaking URLs or notes in generalized activity.
4. Every link mutation and its audit event commit atomically with one correlation ID; archive/restore preserves history and enforces parent/lifecycle/uniqueness rules.
5. Current-format schema validation rejects incomplete or weakened reputation-link schema/index definitions.
6. Encrypted backup, export, and restore preserve links and audit history without credentials or remote review data.
7. VEND-002 leaves categories, external monitoring, discovery, quotes, assignments, ratings, review ingestion, and automatic recommendations to their owning backlog items.

## Validation and delivery references

- [Current module and focused tests](../modules/providers.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/VEND-002_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
