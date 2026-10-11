# INGEST-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Retained source evidence and provenance](../modules/intake.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Manual source admission/import, evidence comparison with retained revisions, correction/supersession, dismissal/reopening, source-operation recovery and fail-closed evidence disclosure remain UI-001 obligations. They are independent of UI-002 issue-proposal approval or connected-assistant setup. Track their browser acceptance explicitly in the UI delivery matrix; they must not disappear behind the AI-controls slice.

## Remaining work

Manual retained-source workflows listed above, evidence unavailable states, sensitive-read audit, complete attachment manifests and replay/recovery.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

1. The operator can retain a bounded message, note, or transcript with qualified provenance and optional FILE-001 attachments without configuring AI or an assistant.
2. The initial accepted envelope and every correction remain immutable and distinguishable from extracted, proposed, or official issue fields.
3. Exact idempotent replay returns the same result; changed payload reuse fails; a trusted account/source replay across connection contexts resolves to one source.
4. Unverified identity or matching content never silently merges sources and instead remains qualified or creates a reviewable duplicate candidate.
5. A source cannot become `ready` while declared attachment content is unavailable, mismatched, over limit, or linked to another entity.
6. Corrections change the source revision/fingerprint and make any earlier AI draft stale; original evidence remains readable.
7. Technical failure, unprocessed evidence, active review, resolution, and dismissal remain distinct states with legal reasoned transitions.
8. A communication can link to a retained source, but importing evidence creates no communication and changing either record never rewrites the other.
9. No public request can claim assistant identity, verified account provenance, or permission; future assistant transports use the trusted internal admission boundary.
10. General activity and list responses redact sensitive evidence while contextual detail remains useful to the local operator.
11. Exact schema/data validation, encrypted backup/restore, and future SaaS export preserve source, revision, attachment-reference, dedup, operation, and audit integrity.
12. Invalid, oversized, duplicate, stale, interrupted, and restart-recovery cases have typed outcomes and cannot create an official issue.

The backend can be marked complete when these criteria pass. The feature remains pending operator UI until UI-001, and issue conversion remains unavailable until INGEST-002.

## Validation and delivery references

- [Current module and focused tests](../modules/intake.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/INGEST-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
