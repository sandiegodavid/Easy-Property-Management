# PORT-003 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Portfolio, ownership and occupancy](../modules/portfolio.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Browser workflows for this feature are recorded as delivered in UI-001 Slice 50. Retain the feature acceptance gate until its owning requirements and final cross-workflow acceptance are verified; this reorganization does not mark the backlog complete.

## Remaining work

Validate the delivered Space/status/ownership forms against all acceptance constraints, then complete final UI context/theme/accessibility/restart/restore proof.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Retained operator requirements

This section defines the PORT-003 requirements for the deferred UI-001 experience. It is not a separate React delivery owned by this feature. OPS-001 composes property directory and overview read models from the typed PORT-003 source API and other source facts; UI-001 renders those results without duplicating occupancy or availability rules in the browser.

### Portfolio and property list

Each property row adds a plain-language occupancy summary and an availability indicator. Filters include:

- Occupied
- Vacant
- Available now
- Available later
- Not available
- Needs classification

Unknown states use neutral text and a visible **Review status** action. Colors are supplementary and never the only status signal.

The PORT-003 property source endpoint is bounded even though OPS-001 owns the final cross-domain directory. It uses a stable sort with an ID tie-breaker and an opaque cursor, enforces a maximum page size, and returns `items`, `nextCursor`, `matchingTotal`, and `asOf`. Changing a filter resets the cursor. Occupancy, availability, ownership, lifecycle, and attention filters combine with AND semantics; a multi-space property matches an occupancy or availability filter when any active space matches it. Results and totals use identical predicates and one consistent read snapshot.

### Property detail

Each rentable-space card shows:

- Space name and kind.
- Current occupancy.
- Scheduled next occupancy transition, if present.
- Current availability and date, if applicable.
- Source label, such as **Recorded manually**.
- Typed attention reasons and the applicable resolution action.
- Primary actions: **Change occupancy**, **Correct occupancy** when applicable, and **Change availability**.

The page does not show a tenant name or lease link until those modules exist.

## Acceptance constraints to verify

### Backend and API scope

The backend and API scope is complete when:

1. Every active space has an explicit occupancy state and availability state, including `unknown` when not yet classified.
2. Typed API responses distinguish occupied, vacant, available-now, available-later, not-available, and unknown spaces.
3. Occupancy changes preserve a non-overlapping effective-dated timeline; scheduled changes do not affect the current state early.
4. Availability is never inferred solely from occupancy, and invalid availability/date combinations are rejected.
5. Property and portfolio counts are derived from active spaces and link conceptually to the matching source records.
6. Occupied or scheduled-for-occupancy spaces cannot be archived through PORT-002 lifecycle actions.
7. Every change and scheduled cancellation is audited atomically with one correlation ID per operator action.
8. Current-schema validation and encrypted backup/restore preserve the complete status records and audit history.
9. No endpoint requires tenant or lease records before `TEN-001` and `LEASE-001` are implemented.
10. Current and scheduled states are derived from one injected `asOf` instant using each property's time zone; responses disclose both the instant and effective local date.
11. An erroneous current manual occupancy transition can be corrected with a required reason, and a future manual transition can be atomically rescheduled to another valid date, without deleting history.
12. Mutation revisions and idempotency prevent lost updates and make retry after an interrupted response safe.
13. Property source results are cursor-bounded with stable ordering, matching totals, and documented multi-space filter semantics.
14. Status responses distinguish recorded from effective availability and expose typed attention reasons with resolution identifiers.

### UI-001 integration scope

The UI-001 integration scope is complete when:

1. The React portfolio view shows portfolio and property occupancy/availability summaries and supports every documented filter.
2. Property detail shows a status card for each active rentable space, including current occupancy, all discoverable scheduled changes, availability, source, and review status.
3. Guided forms support initial classification, later completion of either unknown value, occupancy and availability changes, current-status correction, and scheduled change cancellation or rescheduling.
4. The UI uses plain language, provides drill-down from summary counts, and does not rely on color alone.
5. UI-level tests cover the primary workflows, validation feedback, and API error states.

PORT-003 reaches overall **Done** only after both the backend/API and UI-001 integration scopes pass their respective acceptance criteria. Until then, its backlog status remains **In progress**, even if the backend/API scope is complete.

## Validation and delivery references

- [Current module and focused tests](../modules/portfolio.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Active operator design](UI-001_DESIGN.md) and [delivery matrix](UI-001_IMPLEMENTATION_MATRIX.md).
- [Historical full design](../archive/designs/PORT-003_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
