# PORT-003 — Occupancy and Availability Design

## Purpose

`PORT-003` makes the inventory created by `PORT-002` operationally useful. The operator can see which rentable spaces are occupied, vacant, or not yet classified, and separately record whether and when each space is available to rent.

The distinction matters: a vacant office suite may be unavailable during repairs, while an occupied home may be expected to become available on a future date. The application must never infer availability from occupancy alone.

PORT-003 provides a reliable portfolio-to-space status view before tenant and lease records exist. Later leasing modules will connect their records to this status model rather than replacing it.

## Scope

PORT-003 is delivered through two formally separate scopes:

| Scope | Contents | Delivery timing |
| --- | --- | --- |
| Backend and API | Domain rules, persistence, audit history, schema validation, backup/restore coverage, summaries, filters, and typed API operations. | Current PORT-003 implementation work. |
| Operator UI | React portfolio summaries and filters, space status cards, review-status prompts, classification forms, and occupancy/availability change, replacement, and cancellation actions. | Delivered by `UI-001`, immediately before `DASH-001`. |

The backend and API scope can be reviewed and verified independently. That does not complete PORT-003 as a user-facing feature. The backlog must remain **In progress** until both scopes meet their acceptance criteria.

PORT-003 provides:

- A current occupancy state for every active rentable space: **Occupied**, **Vacant**, or **Unknown**.
- An effective-dated occupancy timeline that preserves prior states.
- A separate current availability state: **Available now**, **Available on a date**, **Not available**, or **Unknown**.
- Property-level and portfolio-level counts derived from active spaces.
- Filters for occupancy and availability, including spaces needing classification.
- A guided action for changing occupancy and another for changing availability.
- Atomic audit history for every status change.
- Explicit source metadata so later lease and listing workflows can become the source of a status without losing manually recorded history.

All new spaces begin with **Unknown** occupancy and **Unknown** availability unless the operator supplies an initial state during creation. Unknown is a real attention state; it is never silently treated as vacant or available.

## Explicit boundaries

PORT-003 does not provide:

- Tenants, occupants, lease participants, lease dates, move-in or move-out workflows, rent, deposits, condition reports, or notices. These belong to `TEN-001`, `LEASE-001`, `INSP-001`, and finance modules.
- Rental listings or publication. `LIST-001` consumes availability but owns marketing status.
- Apartment buildings or apartment units. Apartment support remains a future extension.
- Reservations, leads, showings, applicant holds, cleaning turns, repair schedules, or detailed vacancy reasons.
- Automatic lease-to-occupancy or listing-to-availability synchronization until those source modules exist.
- Destructive deletion of status history.

An occupancy state is an operational fact recorded by the operator or a later trusted source. It is not proof of legal possession, tenancy, or a valid lease.

## Core product decisions

### Occupancy and availability remain separate

| Situation | Occupancy | Availability |
| --- | --- | --- |
| Tenant currently lives in a home and no move-out is expected | Occupied | Not available |
| Tenant occupies a home but plans to leave next month | Occupied | Available on a date |
| Empty suite is ready for a new tenant | Vacant | Available now |
| Empty suite is undergoing repairs | Vacant | Not available |
| Imported or newly created record has not been reviewed | Unknown | Unknown |

The UI may suggest a likely availability choice after an occupancy change, but the operator must confirm it. Saving **Vacant** does not automatically publish or mark the space **Available now**.

### Occupancy uses effective-dated periods

Each space has a non-overlapping occupancy timeline. A period begins on `starts_on` and ends immediately before `ends_on`; a null end means it is open-ended. The current state is the period active today.

Changes are appended in chronological order:

- A change may start today or on a future date.
- A future change remains scheduled and does not affect today’s status.
- A change cannot be inserted before an existing later transition.
- A second change on the same date is rejected by the normal endpoint. A dedicated cancel-and-replace action may revise a scheduled transition atomically.
- Correcting older historical data is deferred until reporting requirements justify a guided timeline-repair workflow.

This matches the effective-date conventions used by ownership relationships and avoids rewriting history.

### Availability is a current operator intention

Availability is kept as one current record per space, with audit history preserving prior values. Its allowed combinations are:

- `available_now`: `available_on` must be null.
- `available_on`: `available_on` is required and cannot be earlier than today.
- `not_available`: `available_on` must be null.
- `unknown`: `available_on` must be null.

When the stored `available_on` date arrives, the displayed state becomes **Available now**, but the original entered date remains available for history and reporting. A background job is not required merely to advance the display label.

### Sources are explicit

PORT-003 writes `source_kind = manual`. Later modules may use `lease` or `listing` with a source record ID. A source does not bypass application invariants or audit requirements.

When a later source owns a status, the UI identifies it—for example, “Occupied from lease ending June 30”—and prevents an unreviewed manual edit from silently contradicting it. The detailed conflict policy belongs to the integrating module.

## Data model

### `space_occupancy_periods`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID. |
| `space_id` | Required reference to `spaces`. |
| `occupancy_status` | `occupied`, `vacant`, or `unknown`. |
| `starts_on`, `ends_on` | Effective date range. `ends_on`, when present, is later than `starts_on`. |
| `record_state` | `valid`, `cancelled`, or `superseded`. Only `valid` periods participate in the timeline. |
| `superseded_by_id` | Optional reference to the replacement period when a scheduled transition is revised. |
| `source_kind` | Initially `manual`; reserved current values also include `lease`. |
| `source_id` | Null for manual records; required when a source record owns the period. |
| `note` | Optional concise operator explanation. |
| `created_at`, `ended_at`, `cancelled_at` | UTC record timestamps. |

Database constraints enforce allowed states, valid source pairing, valid ranges, and at most one valid open-ended period for a space. The application transaction enforces chronological ordering and prevents overlapping valid periods, including scheduled future periods.

### `space_availability`

| Field | Rules and meaning |
| --- | --- |
| `space_id` | Stable primary key and reference to `spaces`; exactly one record per space. |
| `availability_status` | `available_now`, `available_on`, `not_available`, or `unknown`. |
| `available_on` | Required only for `available_on`. |
| `source_kind` | Initially `manual`; reserved current values also include `listing` and `lease`. |
| `source_id` | Null for manual records; required for a module-owned source. |
| `note` | Optional concise operator explanation. |
| `updated_at` | UTC timestamp for the current record. Prior values remain in `AUDIT-001`. |

Every new `space` receives an initial occupancy period and availability record in the same transaction as space creation. This guarantees that an active space always has a readable state, even when both are unknown.

## Derived status and summaries

For a given date, the application derives occupancy from the matching period. It does not persist a second mutable `current_occupancy` field.

Only active spaces under active properties participate in current portfolio summaries. Archived records remain available in history.

Property summaries expose:

- Total active spaces.
- Occupied, vacant, and unknown counts.
- Available-now count.
- Scheduled-availability count and nearest availability date.
- A `needsAttention` count for active spaces with unknown occupancy or availability.

Portfolio summaries aggregate the same counts without collapsing the source records. Every count must link to the matching filtered space list when reporting drill-down arrives.

For a single-space home, the property can show a direct phrase such as **Occupied · Not available**. For offices, it shows a compact summary such as **3 suites · 2 occupied · 1 available now**.

## Business rules and workflows

### Set initial status

After a property is created, the property detail page prompts the operator to classify any unknown spaces. The short form asks:

1. Is this space occupied, vacant, or unknown?
2. Is it available now, available on a date, not available, or unknown?
3. Optional note.

Both values save atomically under one correlation ID. The operator may leave either value unknown and return later.

The classification operation accepts either occupancy, availability, or both. A value that remains unknown can be completed later without rewriting the value already classified. When an unknown occupancy period began before the classification date, the application ends that historical unknown period and starts the classified period today.

### Change occupancy

The **Change occupancy** action shows the current state and any scheduled next state. The operator selects the new state, effective date, and optional note, then confirms.

The transaction ends the applicable prior period, creates the new period, and writes correlated audit events. If the date is in the future, the current state remains unchanged and the UI labels the transition **Scheduled**.

### Change availability

The **Change availability** action displays occupancy for context but requires an explicit availability selection. The application validates the date combination and replaces the current availability record in the same transaction as its audit event.

### Cancel or replace a scheduled occupancy change

The operator may cancel the latest future manual transition or replace it with another transition on the same date. The action removes no history: it marks the scheduled period as cancelled or superseded, reopens the preceding valid period when necessary, and records the prior and resulting timeline in the audit ledger. Source-owned future transitions cannot be cancelled outside their owning module.

Status responses expose the complete ordered future transition timeline so every scheduled transition has a discoverable stable ID. The singular next-transition field remains a convenience for compact displays.

### Archive safeguards

- An occupied space cannot be independently archived.
- A property cannot be archived while any active space is currently occupied.
- A scheduled future occupancy transition must be cancelled before its space or property is archived.
- Vacant or unknown spaces still require the existing explicit archive confirmation.
- Later lease and listing modules add guards for active source records.

## User experience

This section defines the required React operator experience. It is a product contract for the deferred UI scope, not a claim that the current API implementation provides these screens. The future UI must consume the typed PORT-003 API instead of duplicating occupancy or availability rules in the browser.

### Portfolio and property list

Each property row adds a plain-language occupancy summary and an availability indicator. Filters include:

- Occupied
- Vacant
- Available now
- Available later
- Not available
- Needs classification

Unknown states use neutral text and a visible **Review status** action. Colors are supplementary and never the only status signal.

### Property detail

Each rentable-space card shows:

- Space name and kind.
- Current occupancy.
- Scheduled next occupancy transition, if present.
- Current availability and date, if applicable.
- Source label, such as **Recorded manually**.
- Primary actions: **Change occupancy** and **Change availability**.

The page does not show a tenant name or lease link until those modules exist.

## API contract

All endpoints require a ready workspace. Request models reject unknown fields, and application commands independently enforce the same invariants for non-HTTP callers.

| Method | Path | Intent |
| --- | --- | --- |
| `GET` | `/api/properties` | Add occupancy and availability summaries and filters to property results. |
| `GET` | `/api/portfolio/status-summary` | Return portfolio-wide active-property and active-space occupancy, availability, nearest-date, and attention totals. |
| `GET` | `/api/properties/{propertyId}` | Return each current space with current and scheduled occupancy plus availability. |
| `GET` | `/api/spaces/{spaceId}/status` | Return the space’s current state, next scheduled transition, complete ordered future timeline, availability, and source metadata. |
| `PUT` | `/api/spaces/{spaceId}/occupancy` | Append a manual effective-dated occupancy transition. |
| `POST` | `/api/spaces/{spaceId}/occupancy/scheduled/{periodId}/cancel` | Cancel the latest future manual transition. |
| `PUT` | `/api/spaces/{spaceId}/occupancy/scheduled/{periodId}/replace` | Supersede the latest future manual transition with a replacement on the same date. |
| `PUT` | `/api/spaces/{spaceId}/availability` | Replace the current manual availability intention. |
| `PUT` | `/api/spaces/{spaceId}/classification` | Atomically classify either or both unknown status values for an existing space. |

PORT-002 property and space creation requests gain optional initial `occupancy` and `availability` objects. Omission creates explicit unknown records.

Date fields are typed ISO calendar dates at the HTTP boundary. Errors distinguish missing resources (`404`), malformed inputs including invalid date text (`422`), invalid business transitions (`400`), and concurrent or source-ownership conflicts (`409`).

## Audit, safety, and portability

Each occupancy or availability use case explicitly requests its domain and audit writes through the portfolio unit of work. Related changes share one correlation ID. Audit entity types are `space_occupancy` and `space_availability`, each with a registered presentation policy.

Snapshots include stable IDs, effective dates, states, source references, and operator notes. They do not infer tenant identity or legal status. Cancelling or superseding a scheduled transition records both the prior and resulting timeline state.

The new tables participate in exact current-schema validation and `LOCAL-002` backup, export, and restore. Restoration preserves stable IDs, timelines, availability dates, and audit history.

## Implementation outline

1. Add SQLAlchemy models and the current Alembic baseline schema for occupancy periods and one-to-one availability records, including exact module-owned schema validation.
2. Extend space creation so unknown or supplied initial state records are created atomically with each space.
3. Add typed application commands and portfolio unit-of-work operations for occupancy transitions, scheduled cancellation, and availability changes.
4. Extend property queries to load current/scheduled statuses in bounded queries and derive property/portfolio summaries without per-space queries.
5. Add typed FastAPI contracts for the backend and API scope.
6. Add tests for status separation, effective dates, source pairing, overlap prevention, archive guards, atomic audit rollback, summaries, and backup/restore.
7. In `UI-001`, implement the React portfolio summaries and filters, space status cards, review prompts, and guided classification/change/cancel/replace actions defined in **User experience**.

## Acceptance criteria

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

### Operator UI scope

The operator UI scope is complete when:

1. The React portfolio view shows portfolio and property occupancy/availability summaries and supports every documented filter.
2. Property detail shows a status card for each active rentable space, including current occupancy, all discoverable scheduled changes, availability, source, and review status.
3. Guided forms support initial classification, later completion of either unknown value, occupancy and availability changes, and scheduled change cancellation or replacement.
4. The UI uses plain language, provides drill-down from summary counts, and does not rely on color alone.
5. UI-level tests cover the primary workflows, validation feedback, and API error states.

PORT-003 reaches overall **Done** only after both the backend/API and operator UI scopes pass their respective acceptance criteria. Until then, its backlog status remains **In progress**, even if the backend/API scope is complete.

## Dependencies and follow-on work

PORT-003 requires `PORT-002`. It supplies the inventory-status foundation for `LEASE-001`, `LIST-001`, `DASH-001`, `RPT-001`, and later vacancy-risk features.

`TEN-001` adds people and lease participants. `LEASE-001` introduces lease-owned occupancy periods and move-in/move-out rules. `INSP-001` records condition evidence at those milestones without becoming another occupancy source. `LIST-001` introduces listing-owned availability context. Those modules must use the source fields and transaction boundary defined here rather than maintaining competing status flags.
