# MAINT-002 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Issues, appointments, quotes and work journals](../modules/maintenance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 53, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Quote comparison including paired quoted work dates, Provider context, explicit quote/direct selection, avoid override, assignment/reassignment and history.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

MAINT-002 backend/API scope is complete when:

1. The operator can record multiple labeled, provider-attributed quote options for an active issue and compare their exact totals, scope, dates, and documents.
2. Quotes remain distinct from internal cost context and confirmed expenses, and no quote/assignment operation changes Finance.
3. Quote withdrawal/replacement is explicit, idempotent creation is safe, and historical quote/selection records are never overwritten.
4. One current provider assignment is enforced per issue; reassignment atomically ends the old assignment and retains both audit-backed records.
5. Quote-backed assignment validates exact issue/provider identity; direct assignment and avoided-provider selection require explicit confirmation and reasons.
6. Current provider/profile state is validated through neutral source-owned facts, while stored Party IDs and display snapshots preserve historical readability.
7. Quote and assignment documents use FILE-001 without duplicating storage metadata.
8. Issue lifecycle, appointments, tasks, communications, journals, and expenses do not transition implicitly.
9. List/detail/comparison reads remain bounded and set-based with no provider or file N+1 behavior.
10. Exact schema validation and encrypted backup/restore preserve quotes including quoted schedule dates, assignment history, file links, audit history, replacement lineage, and stable IDs.

The overall operator workflow remains pending until `UI-001` supplies quote comparison and assignment screens. Work execution and outcome history remain pending until `MAINT-003`.

## Validation and delivery references

- [Current module and focused tests](../modules/maintenance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/MAINT-002_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
