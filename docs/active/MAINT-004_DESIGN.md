# MAINT-004 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Issues, appointments, quotes and work journals](../modules/maintenance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 53, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Required contextual reporter selection, report-time eligibility, historical confirmation and reasoned reporter correction, distinct from Communications participants.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

MAINT-004 backend/API scope is complete when:

1. Every newly created official issue has exactly one valid owner, tenant, manager, or staff reporter attribution.
2. Party identity is referenced rather than copied, while the bounded display snapshot preserves historical readability.
3. Owner and tenant roles are validated against the issue property/space and reported date using source-owned facts.
4. The approved local-operator manager/staff rule is typed and does not create fake Party or authorization records.
5. Reporter correction requires confirmation and reason, writes one atomic audit event, and never rewrites linked communications.
6. COM-001 can create, correct, list, filter, and validate communication records linked to `maintenance_issue`, and those links survive workspace backup/restore.
7. Maintenance list/detail and later report inputs expose reporter filters and summaries without N+1 queries.
8. Ingestion or AI workflows cannot create an official issue while reporter attribution is unresolved.
9. Audit presentation redacts reporter identity in general activity while contextual history remains useful.
10. Reporter attribution and communication links survive exact-schema validation and encrypted backup/restore with stable IDs.

The overall operator workflow remains pending until `UI-001` supplies issue intake, reporter selection/correction, and linked communication history.

## Validation and delivery references

- [Current module and focused tests](../modules/maintenance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/MAINT-004_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
