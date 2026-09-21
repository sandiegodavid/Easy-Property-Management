# OWNER-004 — Owner Concern Tracking

## Purpose

`OWNER-004` gives the local operator one durable, auditable record for a rental, lease, tenant, or vacancy concern raised by a client owner. It preserves who raised the concern, the property-local context at that time, the operator's handling state, related communications, and optional follow-up tasks without turning Communications or Tasks into the authoritative concern record.

This is a backend/API design. `UI-001` owns the deferred operator interface. No application code is included here.

## Current implementation baseline

The repository already provides most source facts and coordination seams required by OWNER-004:

- `PORT-001` records effective-dated client-owner relationships and represents local-operator ownership separately without a Party ID.
- `PORT-003` owns space occupancy and availability history.
- `TEN-001` owns reusable Party identity, contact methods, and tenant profiles.
- `LEASE-001` owns leases, participants, dates, and lease-backed occupancy transitions.
- `COM-001` owns immutable recorded communications, participant snapshots, typed context links, and communication-created task follow-ups.
- `TASK-001` owns action lifecycle, due dates, reminders, and the generic related-record link; its design already names `owner_concern` as a related entity type.
- `AUDIT-001` supplies fail-closed, correlated append-only history.
- `OWNER-003` is implemented in `owner-accounting`, whose responsibility is financial owner workflows. No operational owner-management module or owner-concern schema currently exists.

The product remains greenfield and latest-format-only. OWNER-004 updates the current baseline and development workspaces; it introduces no legacy adoption or compatibility behavior.

## Scope

OWNER-004 provides:

- one authoritative record for each distinct concern raised by a selected client-owner Party;
- one required property and a primary concern type of `general_rental`, `lease`, `tenant`, or `vacancy`;
- validated optional or type-required space, lease, and tenant context;
- property-local raised-time semantics and immutable identity/context snapshots;
- priority and an explicit open, in-progress, resolved, dismissed, and reopened lifecycle;
- duplicate warnings with explicit independent-concern confirmation, never automatic merging;
- zero or more linked COM-001 communications, including an optional validated originating communication;
- optional atomic TASK-001 follow-up creation and later additional follow-ups;
- nonbranching replacement lineage for incorrectly targeted concerns;
- bounded list/detail projections, audit privacy, exact schema/data validation, and encrypted backup/restore.

OWNER-004 does not provide:

- a concern raised by the local operator acting as an owner; the local operator uses the appropriate task, communication, maintenance, lease, tenant, or portfolio workflow directly;
- owner login, remote submission, authentication, a portal, or an external inbox; `INTAKE-001` and `PORTAL-002` own those later boundaries;
- email/SMS delivery or ingestion;
- attachments or evidence files; a later revision must add `FILE-001` deliberately if that becomes necessary;
- repair intake, lease amendments, tenant-profile changes, occupancy or availability changes, listings, notices, legal findings, or financial effects;
- automatic status synchronization with communications, tasks, leases, parties, occupancy, availability, or maintenance issues;
- destructive deletion of concerns or silent merging of duplicates.

## Architecture and ownership

### A separate owner-management module owns concerns

OWNER-004 introduces a backend `owner-management` module. It owns concern commands, policy, persistence, HTTP contracts, read projections, audit presentation, exact schema/data validation, and property-archive guard behavior.

The existing `owner-accounting` module remains financial: owner-reported rent provenance, future balances, disbursement approvals, and disbursement history. A concern is operational case management, not accounting. UI navigation may present both modules under the plain-language **Owner management** area without merging their persistence or policy.

### Concern, communication, and task are independent records

An owner concern is not merely a communication or task:

- OWNER-004 owns who raised the concern, its authoritative type and context, priority, handling lifecycle, and resolution.
- COM-001 owns each interaction, participant/contact snapshot, occurrence time, correction history, and communication body.
- TASK-001 owns each concrete action, due time, reminder, and completion/cancellation lifecycle.

Completing or cancelling a task never resolves or dismisses a concern. Resolving, dismissing, or reopening a concern never completes, cancels, or reopens a task. Correcting a communication never rewrites concern attribution or context.

### Source modules remain authoritative

OWNER-004 consumes neutral facts through transaction-aware application protocols composed at bootstrap:

- Party identity and current lifecycle;
- effective-dated Portfolio client ownership;
- property, space, property time zone, occupancy, and availability context;
- lease identity and effective participant relationships;
- recorded communication participation and context;
- generic task creation/read projection; and
- append-only audit recording.

Owner-management must not import another module's SQLAlchemy models or concrete repositories. Portfolio, Leasing, Tenants, Communications, and Tasks must not gain owner-concern-specific policy or response objects. Source adapters expose consumer-neutral facts; owner-management decides eligibility and shapes its responses.

## PORT-001 and OWNER-004 alignment

PORT-001 distinguishes `client_owner` Party ownership from `local_operator` ownership with no Party ID. OWNER-004 preserves that distinction:

- the raising owner must be one selected Party with an effective `client_owner` relationship to the concern property on the property-local raised date;
- a mixed property is eligible only through the specifically selected client-owner Party;
- `local_operator` ownership never causes the server to synthesize a Party or infer a raising owner;
- PORT-001 ownership is operational relationship evidence, not a legal conclusion about title, beneficial interest, percentage share, or authority;
- ending ownership or archiving the Party later does not rewrite a valid historical concern; and
- an open concern does not keep a former owner relationship active.

Normal creation selects an active Party. An archived Party may be selected only for a backdated concern when the historical client-owner relationship was effective and the operator supplies explicit historical-selection confirmation and a bounded reason. OWNER-004 stores the owner display-name snapshot but never copies contact methods or creates a separate owner identity.

## Concern type and context rules

Every concern has one required primary `concern_type`:

| Type | Meaning | Required context |
| --- | --- | --- |
| `general_rental` | A general rental-operation or property-management concern not better represented by the other types. | Property; space optional. |
| `lease` | A concern about one saved lease, its terms, dates, renewal, termination, or administration. | Property, matching space, and lease. |
| `tenant` | A concern about one tenant in the context of a saved lease relationship. | Property, matching space, lease, and tenant Party. |
| `vacancy` | A concern about occupancy or availability of one rentable space. | Property and space. |

One type is primary for filtering and workflow language, but the concern retains every applicable validated reference. A lease concern may identify a tenant; a general concern may identify a space. Additional context must be internally consistent rather than treated as unrelated generic links.

For a tenant concern, the selected Party must have effective lease participation for the selected lease on the property-local raised date. An active tenant profile alone is insufficient. For a lease concern, the selected lease must belong to the selected property and space. For a vacancy concern, the space must belong to the property; the space need not actually be vacant because the concern may dispute an incorrect or future state.

Normal current entry requires an active property and any supplied active space. A backdated concern may reference a retained ended lease or archived Party when the relationship was historically valid and historical selection is explicitly confirmed. Retained concerns remain readable after source lifecycle changes.

## Time and snapshots

The operator supplies an aware `raised_at_utc`. OWNER-004 resolves the property's canonical IANA time zone in the write transaction and stores `property_timezone_snapshot`. The local calendar date in that zone determines historical ownership and tenant-participation eligibility.

The raised time may not be more than five minutes in the future relative to the injected clock. `recorded_at_utc` is server-generated. The five-minute allowance handles ordinary client clock skew; it does not permit future scheduling.

The concern retains immutable snapshots needed to explain its original context:

- owner display name;
- property display name;
- optional space display name;
- optional lease display label;
- optional tenant display name; and
- for vacancy concerns, observed occupancy status, availability status, and `available_on` value at creation.

Current source state is projected separately. A later rename, archive, lease ending, move-out, occupancy change, or availability change never rewrites the snapshots.

## Core data model

All IDs are UUIDs. Timestamps are timezone-aware UTC text. Dates are ISO local dates.

### `owner_concerns`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `owner_party_id` | Required Party that raised the concern. |
| `owner_display_name_snapshot` | Required server-resolved text, 1–240 characters. |
| `property_id`, `property_display_name_snapshot` | Required stable property ID and display snapshot. |
| `space_id`, `space_display_name_snapshot` | Nullable together; required for lease, tenant, and vacancy types. |
| `lease_id`, `lease_display_snapshot` | Nullable together; required for lease and tenant types. |
| `tenant_party_id`, `tenant_display_name_snapshot` | Nullable together; required for tenant type. |
| `originating_communication_id` | Optional stable COM-001 communication ID validated at creation; narrative is never copied. |
| `concern_type` | `general_rental`, `lease`, `tenant`, or `vacancy`. |
| `summary` | Required trimmed text, 1–240 characters. |
| `description` | Required trimmed sensitive text, 1–10,000 characters. |
| `priority` | `low`, `normal`, `high`, or `urgent`; default `normal`. |
| `status` | `open`, `in_progress`, `resolved`, or `dismissed`. |
| `raised_at_utc`, `property_timezone_snapshot` | Required original occurrence instant and canonical property-zone snapshot. |
| `recorded_at_utc`, `updated_at_utc` | Required server-generated UTC timestamps. |
| `resolved_at_utc`, `resolution_summary` | Both required exactly when resolved; summary 1–4,000 characters. |
| `dismissed_at_utc`, `dismissal_reason` | Both required exactly when dismissed; reason 1–4,000 characters. |
| `replaces_concern_id` | Optional unique predecessor; cannot self-reference or branch. |
| Vacancy snapshots | Required exactly for vacancy concerns: occupancy status, availability status, and optional available-on date. |
| `idempotency_key`, `request_fingerprint` | Required immutable create-retry identity; workspace-unique key and canonical SHA-256 fingerprint. |

Database checks enforce closed vocabularies, field pairing, type-required context, terminal timestamp/narrative pairs, nonblank bounds where SQLite can enforce them, and non-self replacement. Application policy enforces cross-record ownership, property/space/lease/tenant consistency, historical eligibility, future-time limits, duplicate handling, and lifecycle transitions.

Indexes support `(status, priority, raised_at_utc, id)`, `(owner_party_id, status, raised_at_utc)`, `(property_id, status, raised_at_utc)`, `(space_id, status)`, `(lease_id, status)`, `(tenant_party_id, status)`, and `(concern_type, status)`.

### `owner_concern_follow_up_operations`

Coordinated follow-up creation stores an append-only operation record containing:

- client-generated idempotency key;
- canonical request fingerprint;
- concern ID and resulting TASK-001 task ID;
- correlation ID and creation timestamp.

This record exists only to make an uncertain cross-module response safely replayable. It is not a generic workflow engine or a second task link. TASK-001's `related_entity_type`, `related_entity_id`, and durable label remain the relationship authority.

## Workflows and invariants

### Create a concern

Creation validates, in one immediate transaction:

1. active or explicitly confirmed historical owner selection;
2. client-owner eligibility on the property-local raised date;
3. property and type-specific context consistency;
4. tenant participation when required;
5. the future-time limit;
6. optional originating communication compatibility;
7. likely duplicate candidates; and
8. optional follow-up input.

The command then stores the concern and audit event. When requested, it creates one TASK-001 task through generic transaction operations under the same correlation ID. The concern task uses `related_entity_type = 'owner_concern'`, the concern ID, and the stored summary as its durable label.

### Duplicate review

Likely duplicates are active concerns with the same owner, property, type, and overlapping supplied context. The service returns a bounded set of candidate IDs before creating a second record. The operator may confirm that the concern is independent and provide a 1–1,000-character reason. The reason joins the idempotency fingerprint and audit context but is not a mutable concern field. OWNER-004 never merges records automatically.

### Patch an active concern

While a concern is open or in progress, the operator may patch summary, description, and priority. An omitted field remains unchanged. An empty or semantically identical patch is a no-op without a timestamp or audit event.

Owner, property, space, lease, tenant, type, and raised time are immutable. A wrong target is dismissed and replaced explicitly so communications and tasks are not silently moved to a different subject.

### Lifecycle

Allowed transitions are:

- `open` to `in_progress`, `resolved`, or `dismissed`;
- `in_progress` to `open`, `resolved`, or `dismissed`; and
- `resolved` or `dismissed` to `open` through confirmed reopening with a reason.

Resolution requires confirmation and a resolution summary. Dismissal requires confirmation and a dismissal reason. Reopening requires confirmation and a reason, clears the prior terminal fields, and records them in the before snapshot. Requesting the current state again returns a typed conflict and does not overwrite timestamps or add an event.

Reopening requires an active property. If the property was archived after the concern closed, the operator must restore it before reopening; this preserves the rule that an archived property cannot retain unresolved work.

### Correct target context

To correct owner/property/space/lease/tenant/type/raised-time context, the operator dismisses the source and creates a replacement with `replaces_concern_id`. Replacement lineage is one-to-one, nonbranching, acyclic, and immutable. Communications and tasks remain linked to the record they originally described; the UI shows lineage rather than silently moving them.

### Communications

A concern may have zero or more linked communications. OWNER-004 adds `owner_concern` to COM-001's typed link vocabulary and composition validator. Communication records remain immutable under COM-001 rules and retain their own property-time-zone snapshots.

An optional `originating_communication_id` is not stored as copied narrative. At creation, the selected communication must be recorded, inbound, include the selected owner as sender or reporter, and have compatible property-derived context. Owner-management retains the stable source ID as provenance and projects its current correction lineage. A concern may also be created without a communication because the concern record itself is valid manual intake; the UI must not fabricate a communication.

A communication participant's `reporter` role describes that interaction only. It never establishes or changes the concern's authoritative raising owner.

### Follow-up tasks

An optional initial follow-up may be created atomically with the concern. Additional follow-ups use `POST /api/owner-concerns/{concernId}/follow-ups`, a client idempotency key, TASK-001's validated creation policy, and one shared correlation ID. Task priority may be initially prefilled from concern priority but is independently editable and never synchronized afterward.

### Source changes and archive guards

Owner, tenant, lease, occupancy, availability, communication, and task lifecycle changes do not transition a concern. Current state is projected as context only.

An unresolved (`open` or `in_progress`) concern blocks property archival through the architecture's transaction-aware cross-module guard protocol. The operator must resolve or dismiss it first. OWNER-004 adds no Party-role or contact-method archive guard, and it does not block an owner relationship from ending, a Party or tenant profile from being archived, a lease from ending, or a space's operational state from changing.

Restore validation checks retained structure and historical snapshots. It does not re-evaluate past owner or tenant eligibility against current state.

## API contract

All routes require a ready workspace. Mutations require the writer lock. Request contracts forbid unknown fields and use typed UUIDs, strict booleans, aware timestamps, exact enums, and bounded text. Application commands repeat essential validation.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/owner-concerns` | Create one concern, optionally with an originating communication and initial follow-up. |
| `GET` | `/api/owner-concerns` | Return a bounded cursor page with structured filters. |
| `GET` | `/api/owner-concerns/{concernId}` | Return complete context, snapshots, lifecycle, lineage, communications, and tasks. |
| `PATCH` | `/api/owner-concerns/{concernId}` | Change only allowed active concern fields. |
| `POST` | `/api/owner-concerns/{concernId}/start` | Move an open concern to in progress. |
| `POST` | `/api/owner-concerns/{concernId}/resolve` | Resolve with confirmation and summary. |
| `POST` | `/api/owner-concerns/{concernId}/dismiss` | Dismiss with confirmation and reason. |
| `POST` | `/api/owner-concerns/{concernId}/reopen` | Reopen a terminal concern with confirmation and reason. |
| `POST` | `/api/owner-concerns/{concernId}/follow-ups` | Atomically create a related TASK-001 action. |

There is no destructive delete endpoint.

List filters include owner, property, space, lease, tenant, concern type, priority, status, raised local-date range, active-task state, and linked-communication presence. Default ordering is urgent/high priority first, then raised time descending and ID descending. Cursor pagination defaults to 100 and allows at most 500.

Malformed requests return `422`; missing records return `404`; invalid relationships, bounds, time, or context return `400`; stale lifecycle, duplicate review, idempotency reuse, replacement, and concurrency conflicts return typed `409` with machine-readable codes and bounded candidate identifiers.

## Read behavior and performance

List projections contain concern identity, summary, type, priority, status, owner/property/space snapshots, raised local time, active follow-up count, and linked-communication count. They exclude full descriptions, terminal narratives, communication bodies, task notes, and audit history.

Detail returns full operator-authorized concern context, replacement lineage, current source-state summaries, bounded recent communication summaries, and up to 20 related task summaries ordered by most recently updated first. Full communication history remains available from COM-001 filtered by `owner_concern` and ID; complete follow-up-task history, including terminal tasks, is retrieved through cursor-paginated `GET /api/tasks?relatedEntityType=owner_concern&relatedEntityId={concernId}&includeVoided=true`.

Reads must be set-based. One concern page query may be followed by bounded batch queries for current Party/context state, task projections, and communication counts or summaries. No owner, property, lease, tenant, task, or communication N+1 queries are allowed. Query-budget tests make this constraint explicit.

## Audit, privacy, and portability

Audit entity types are `owner_concern` and `owner_concern_follow_up_operation`; coordinated creation also emits the TASK-001 `task` event. Creation, patches, transitions, replacement lineage, and follow-up creation are fail-closed on required events in the same transaction and correlation.

General activity may show concern type, priority, status, property context, and non-sensitive lifecycle labels. It must redact description, owner and tenant identifiers and display snapshots, lease and communication identifiers, resolution/dismissal/reopening narratives, historical-selection and duplicate-confirmation reasons, idempotency keys, and task notes. Contextual owner-management history may display the permitted details to the local operator. Communication bodies remain governed by COM-001 and are never copied into owner-concern audit snapshots.

The greenfield baseline, module exact schema/data validator, expected-table registration, audit-policy registry, COM-001 typed-link constraint, archive validator, product validator, and encrypted backup/export/restore coverage include concerns, operation records, snapshots, lineage, task references, communication links, and correlated audit history. Operation records are append-only.

Retained-data validation rejects invalid context combinations, missing parents, invalid status/nullability pairs, broken or branching replacement lineage, invalid source communications, orphaned concern-linked tasks or communications, missing operation results, missing required audit history, and archived properties that retained unresolved concerns.

## UI-001 operator workflow

UI-001 delivers:

- client-owner search/select constrained by property context;
- property and type-specific space, lease, and tenant selection;
- active-by-default selection with explicit confirmed historical selection;
- raised local time, type, summary, description, and priority entry;
- bounded likely-duplicate warnings with select-existing or create-independent choices;
- optional originating communication and optional initial follow-up;
- open/in-progress work queues and resolve, dismiss, reopen, and replace actions;
- linked communication history and task status without synchronized lifecycle;
- original snapshots beside clearly labeled current source state; and
- end-to-end tests for validation, duplicate review, lifecycle, history, privacy, and error states.

The initial DASH-001 owner-actions card includes unresolved urgent/high owner concerns and drill-down. It does not infer concern state from generic task state.

## Future intake contract

`INTAKE-001` may accept a remote or connected-source submission and suggest owner, property, type, context, urgency, and duplicate candidates. That record is untrusted intake, not an official owner concern. Only operator approval invokes OWNER-004's authoritative create command. Intake never changes leases, tenants, occupancy, availability, tasks, or maintenance records automatically.

## Implementation outline

1. Add the `owner-management` module with concern values, commands, lifecycle, idempotency, persistence, ports, service, routes, audit policy, exact schema/data validation, and tests.
2. Add small consumer-neutral source-reader extensions for property/space status, lease/participant context, recorded communication provenance, and bounded task/communication projections.
3. Extend COM-001's typed link vocabulary and composition validator with `owner_concern` without moving concern policy into Communications.
4. Compose generic TASK-001 transaction operations for atomic follow-up creation and add the property archive guard through existing cross-module protocols.
5. Update the current Alembic baseline, product-table allowlist, archive validation, audit registry, and encrypted backup/restore validation without compatibility paths.
6. Add regressions for historical ownership and tenancy, mixed properties, type/context rules, time zones, future time, duplicates, lifecycle, replacement lineage, task/communication independence, idempotency, concurrency, archive guards, privacy, query budgets, corruption, and restore.
7. Deliver the operator workflow through UI-001 and the owner-action summary through DASH-001.

## Backend acceptance criteria

OWNER-004 backend/API scope is complete when:

1. The operator can record one concern from a historically eligible client-owner Party with valid property and type-specific context.
2. Local-operator ownership is never converted into a fake Party or inferred raising owner.
3. Concern, communication, task, and source-module lifecycles remain independent and authoritative in their owning modules.
4. Lease, tenant, vacancy, and general-rental context is validated in one transaction and retained through immutable snapshots.
5. Duplicate candidates are shown, independent duplicates require confirmation, and no records are merged automatically.
6. Active fields, explicit terminal transitions, reopening, and target correction preserve complete audit history and nonbranching lineage.
7. COM-001 can retain typed concern links and OWNER-004 can atomically create idempotent TASK-001 follow-ups.
8. Unresolved concerns block property archival without blocking unrelated Party, tenant, lease, ownership, or operational-state history.
9. List/detail reads are bounded and set-based, and generalized audit presentation redacts sensitive narratives and identities.
10. Exact schema/data validation and encrypted backup/restore preserve concerns, snapshots, operations, links, tasks, lineage, and correlated audit evidence.

The overall feature remains incomplete until UI-001 supplies the operator workflow and DASH-001 supplies the agreed owner-action presentation.

## Dependencies and follow-on work

OWNER-004 directly requires completed `AUDIT-001`, `TASK-001`, `PORT-001`, `PORT-003`, `TEN-001`, `LEASE-001`, and `COM-001`. It consumes source-owned facts through application protocols and owns no source-module persistence.

Follow-on ownership remains:

- `UI-001` — complete concern intake, duplicate review, lifecycle, communication, task, and history workflow.
- `DASH-001` — unresolved urgent/high owner-action summaries and drill-down.
- `INTAKE-001` — secure direct owner/tenant submissions followed by operator review.
- `PORTAL-002` — authenticated owner access without redefining concern authority.
- future reporting — owner-concern metrics and source-record drill-down through the reporting module.
