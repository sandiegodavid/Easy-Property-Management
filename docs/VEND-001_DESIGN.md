# VEND-001 — Shared Parties API and Provider Foundation

## Purpose

`VEND-001` gives the operator a durable local provider directory while completing the dedicated `parties` API promised by the architecture. A provider is an individual or organization party with a provider-specific profile; it is not a separate copy of a name or party-owned contact method.

The feature is useful before maintenance workflows exist. The operator can maintain a trustworthy shortlist of people and companies, what they say they do, where they work, prior manually recorded work, references, and whether the operator prefers or avoids them. `MAINT-002` later selects a provider for a quote or assignment. `VEND-002` adds manually recorded reputation links. Neither is pulled into this slice.

## Scope

VEND-001 provides:

- A dedicated `parties` API for reusable individual and organization identities, replacing the party routes currently exposed by `portfolio`.
- Provider profiles created with a new party or designated from an existing active party.
- Searchable, lifecycle-managed provider services and service-area labels.
- Local provider work-history notes, optionally tied to a current property.
- Local references with bounded contact and context fields.
- Explicit `neutral`, `preferred`, or `avoid` selection status; `avoid` requires an operator reason.
- Archive and restore for provider profiles and shared party identities without deleting history.
- Typed API contracts, atomic audit events, current-schema validation, and encrypted backup/export/restore coverage.

VEND-001 does not provide:

- Configurable provider categories, category hierarchy, or issue-routing taxonomy. `VEND-CAT-001` owns those. VEND-001 service labels are operator-entered normalized offerings, not categories.
- Reputation URLs, ratings, review ingestion, monitoring, or provider discovery. Those belong to `VEND-002`, `VEND-004`, and `VEND-005`.
- Quote requests, appointment scheduling, provider assignment, repair outcomes, costs, or a maintenance work journal. `MAINT-001`, `MAINT-002`, and `MAINT-003` own those workflows.
- Provider onboarding, background checks, insurance, licensing, tax forms, payment credentials, bank details, or legal verification.
- Sending communications, external account connections, autonomous provider selection, or AI contact actions.
- A React provider screen. This slice delivers the backend/API contract; a later dedicated provider UI slice may place it within Maintenance as described by the architecture.

## Core decisions

### Shared identity remains in `parties`

`parties` owns the canonical identity and its common fields: stable UUID, individual/organization kind, display name, timestamps, and identity archive state. TEN-001 establishes multi-valued `party_contact_methods` as the only reusable email and phone source; scalar email and phone fields do not exist on `parties`. A party can have multiple roles over time: for example, an organization can be both a client owner and a plumbing provider. `provider_profiles` only adds provider-specific state and always uses `party_id` as its primary key and foreign key.

The dedicated party API owns common identity create, read, patch, list, archive, restore, and contact-method operations. `portfolio` stops exposing `/api/parties` routes once VEND-001 is implemented. Tenant, provider, owner, and later role APIs create or designate a party through the application-level transaction protocols introduced by TEN-001; they must not construct `PartyModel` or import another role module's persistence adapter.

Inline provider creation reuses TEN-001's operator-reviewed identity workflow. Exact active normalized contact matches return the typed `possible_duplicate_party` conflict; the operator selects an existing identity or explicitly confirms creation of a separate party. Name-only candidates remain warnings, and identities are never merged automatically.

Archiving a shared party is intentionally stricter than archiving a role profile. It requires explicit confirmation and is rejected while any active role that requires an available identity remains, including active provider profiles, tenant profiles, or current/future client-owner relationships. Archiving a provider profile never archives the shared party. New roles register a role-activity guard through the parties application port rather than making the parties module import downstream infrastructure.

### Provider state is an operator decision, not a rating

`selection_status` is exactly one of:

- `neutral`: no saved preference.
- `preferred`: the operator would normally consider the provider first.
- `avoid`: the operator does not want the provider suggested or selected without deliberate review.

An `avoid` status requires a nonblank bounded `selection_reason`. A preferred or neutral status may retain an optional internal reason, but this is not an external rating or legal conclusion. Later AI suggestions may use the status as one bounded signal but must explain it and require operator review.

### Services and service areas are simple searchable labels

Provider service offerings and service areas have independent stable IDs and lifecycle state. Each stores a display value plus a normalized case-folded value for uniqueness and search. A service area is a human-entered coverage label such as `Portland metro` or `Multnomah County`; it is not geocoded, a legal jurisdiction, or a promise that work is available. An optional ISO country code is allowed only to disambiguate a label.

The application prevents duplicate active normalized service offerings or service areas within one provider. `VEND-CAT-001` later introduces configurable categories and provider-category assignments without redefining or deleting these operator-entered service labels.

### Historical context is retained but does not impersonate Maintenance

Provider work history is a manually entered historical note. It may optionally reference `properties.id`, records a performed-on date, summary, optional outcome note, and lifecycle timestamps. It does not create an issue, quote, assignment, expense, cost, work order, or maintenance completion claim.

Provider references are separately auditable local notes. They may include an optional reference name, organization, relationship/context, email, phone, and notes. A reference is not promoted automatically to a shared party because the operator may have limited information or no permission to create a reusable contact. Contact values are never exposed in generalized activity presentation.

## Data model

All IDs are UUIDs. Timestamps are timezone-aware UTC text. Every bounded text field is normalized before persistence where noted. All records remain in the workspace SQLite database and participate in the current-format-only baseline, validation, backup, export, and restore.

### Existing `parties`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `party_kind` | Required `individual` or `organization`; immutable after creation. |
| `display_name` | Required trimmed display text, 1–240 characters. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

Reusable email and phone records live in TEN-001's party-owned `party_contact_methods`. Provider APIs return those shared records where contact context is needed but do not copy them into provider tables.

### `provider_profiles`

| Field | Rule |
| --- | --- |
| `party_id` | Primary key and required foreign key to `parties.id`. One profile per party. |
| `selection_status` | Required `neutral`, `preferred`, or `avoid`; defaults to `neutral`. |
| `selection_reason` | Optional bounded text except required for `avoid`. |
| `notes` | Optional 4,000-character internal provider context. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

### `provider_services`

| Field | Rule |
| --- | --- |
| `id`, `party_id` | Stable UUID and required provider-profile reference. |
| `display_name`, `normalized_name` | Required service offering label and required normalized lookup value. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

The database enforces unique active `(party_id, normalized_name)` values.

### `provider_service_areas`

| Field | Rule |
| --- | --- |
| `id`, `party_id` | Stable UUID and required provider-profile reference. |
| `display_name`, `normalized_name` | Required human-entered coverage label and normalized lookup value. |
| `country_code` | Optional uppercase two-letter ISO code; not a geocoding result. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

The database enforces unique active `(party_id, normalized_name, country_code)` values, treating an absent country code as a distinct explicit value through a normalized non-null storage key.

### `provider_work_history`

| Field | Rule |
| --- | --- |
| `id`, `party_id` | Stable UUID and required provider-profile reference. |
| `property_id` | Optional reference to `properties.id`; if supplied, the property must be active or archived-but-retained. |
| `performed_on` | Required local ISO date; it may be historical but not invalid text. |
| `summary` | Required bounded account of work or prior experience. |
| `outcome_notes` | Optional bounded operator observation. It is not a maintenance outcome record. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

### `provider_references`

| Field | Rule |
| --- | --- |
| `id`, `party_id` | Stable UUID and required provider-profile reference. |
| `reference_name`, `organization_name`, `relationship` | Optional bounded context fields; at least one of name, organization, or relationship is required. |
| `email`, `phone` | Optional bounded local contact fields. They are not normalized as reusable party identity and are redacted from generalized activity. |
| `notes` | Optional bounded internal reference context. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

All provider child records are archived rather than physically deleted. Archive actions reject already-archived records; restoration verifies parent-provider availability and active uniqueness before restoring.

## Workflows and invariants

### Create or designate a provider

The operator either supplies a valid new `PartyCreateCommand` or references exactly one existing active party. The service creates the party when needed, inserts the profile and any initial service/area/reference records, and records all changes in one immediate transaction using one correlation ID. A party already holding a provider profile yields a controlled conflict.

Initial provider services, areas, work-history notes, and references are optional. A provider can be recorded before the operator knows its coverage or history.

### Update identity and provider profile

The shared party PATCH updates the mutable display name only; contact changes use the party-contact endpoints and their independent lifecycle. Provider PATCH updates selection status, selection reason, and notes. Setting `avoid` without a reason is invalid; changing away from `avoid` may clear the reason explicitly or retain it as internal context.

An archived party cannot be edited. An archived provider cannot receive profile or child-record changes until restored.

### Maintain services, areas, work history, and references

Each child record supports create, PATCH, archive, and restore. Mutations are controlled by the provider profile's active state. Archived data remains visible in a history-inclusive query but is excluded from default search and selection results.

Work history may be corrected, but the audit ledger records its before and after snapshots. It must not be used as an assignment, invoice, or evidence that a repair was accepted. References are factual operator records, not endorsements inferred from review sites.

### Archive and restore

Provider-profile archive requires explicit confirmation. It does not archive the party or child records. It makes the profile and active child records unavailable to normal provider search and future selection. Restore makes the profile active; each child retains its own archived state.

Shared-party archive uses the role-guard protocol described above. The service returns a 409 conflict if its identity is still active as a provider, tenant, or current/future client owner. No operation cascades a destructive deletion.

### Search

`GET /api/providers` accepts typed filters:

- `archiveState`: `active` (default), `archived`, or `all`.
- `search`: literal, case-insensitive text matching provider name, active service labels, active service areas, active reference context, or active work-history summary/outcome text. SQL LIKE metacharacters are escaped.
- `service`, `serviceArea`: normalized literal filters over active service or area labels.
- `selectionStatus`: `neutral`, `preferred`, or `avoid`.
- `propertyId`: work-history association filter.
- `hasReference`: boolean filter.

The list uses bounded joins/batched projections rather than one query per provider. It returns identity, profile selection state, active service/area summaries, and counts; detail returns all active data by default and archived history only when explicitly requested.

## API contract

All routes require a ready workspace. Mutations require the writer lock. Request models use `extra="forbid"`, strict booleans for confirmations, typed ISO dates, and command-level revalidation for direct callers. Every response uses explicit Pydantic models; no untyped dictionaries are part of the public contract.

### Shared parties

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/parties` | Create a reusable individual or organization identity with optional initial party contact methods after duplicate review. |
| `GET` | `/api/parties` | List identities with active/archived and text-search filters. |
| `GET` | `/api/parties/{partyId}` | Return one shared identity and derived active role summaries. |
| `PATCH` | `/api/parties/{partyId}` | Update mutable common identity fields. |
| `POST` | `/api/parties/{partyId}/contact-methods` | Add one reusable party contact method through the TEN-001 contract. |
| `PATCH` | `/api/parties/{partyId}/contact-methods/{methodId}` | Edit one reusable party contact method. |
| `POST` | `/api/parties/{partyId}/contact-methods/{methodId}/archive` | Archive one method, applying typed role-reference resolutions atomically when supplied. |
| `POST` | `/api/parties/{partyId}/contact-methods/{methodId}/restore` | Restore one method after its party is active. |
| `POST` | `/api/parties/{partyId}/archive` | Archive an identity after explicit confirmation and role guards. |
| `POST` | `/api/parties/{partyId}/restore` | Restore an archived identity. |

### Providers

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/providers` | Atomically create an inline party and provider profile after duplicate review; supports explicit `confirmedNewParty`. |
| `POST` | `/api/providers/from-party/{partyId}` | Designate an existing active party as a provider. |
| `GET` | `/api/providers` | Search/list provider profiles. |
| `GET` | `/api/providers/{partyId}` | Return identity, profile, services, areas, work history, and references. |
| `PATCH` | `/api/providers/{partyId}` | Update selection state and provider notes. |
| `POST` | `/api/providers/{partyId}/services` | Add a service offering. |
| `PATCH` | `/api/providers/{partyId}/services/{serviceId}` | Edit one service offering. |
| `POST` | `/api/providers/{partyId}/services/{serviceId}/archive` | Archive one offering with confirmation. |
| `POST` | `/api/providers/{partyId}/services/{serviceId}/restore` | Restore one offering. |
| `POST` | `/api/providers/{partyId}/service-areas` | Add a service area. |
| `PATCH` | `/api/providers/{partyId}/service-areas/{areaId}` | Edit one service area. |
| `POST` | `/api/providers/{partyId}/service-areas/{areaId}/archive` | Archive one area with confirmation. |
| `POST` | `/api/providers/{partyId}/service-areas/{areaId}/restore` | Restore one area. |
| `POST` | `/api/providers/{partyId}/work-history` | Add manually recorded past work. |
| `PATCH` | `/api/providers/{partyId}/work-history/{entryId}` | Correct one work-history entry. |
| `POST` | `/api/providers/{partyId}/work-history/{entryId}/archive` | Archive one work-history entry with confirmation. |
| `POST` | `/api/providers/{partyId}/work-history/{entryId}/restore` | Restore one work-history entry. |
| `POST` | `/api/providers/{partyId}/references` | Add a provider reference. |
| `PATCH` | `/api/providers/{partyId}/references/{referenceId}` | Update one reference. |
| `POST` | `/api/providers/{partyId}/references/{referenceId}/archive` | Archive one reference with confirmation. |
| `POST` | `/api/providers/{partyId}/references/{referenceId}/restore` | Restore one reference. |
| `POST` | `/api/providers/{partyId}/archive` | Archive a provider profile after explicit confirmation. |
| `POST` | `/api/providers/{partyId}/restore` | Restore a provider profile. |

Errors are explicit: malformed request models return `422`; missing parties, profiles, child records, or properties return `404`; business-rule errors return `400`; lifecycle, active-role, uniqueness, and concurrent-write conflicts return `409`.

## Audit, privacy, and portability

Every mutation persists all domain rows and `AUDIT-001` events in one immediate transaction. A multi-row create, designation, or coordinated update uses one correlation ID. Event entity types are `party`, `party_contact_method`, `provider_profile`, `provider_service`, `provider_service_area`, `provider_work_history`, and `provider_reference`.

Audit snapshots retain stable IDs, lifecycle state, normalized values needed to explain uniqueness, and ordinary business fields. General activity presentation redacts party contact-method values and extensions, reference email/phone, reference notes, provider notes, work-history outcome notes, and selection reasons. Contextual provider history can reveal the protected record to the local operator. All policies are registered before events can be written, preserving the current fail-closed audit behavior.

Provider records participate in exact current-schema validation and `LOCAL-002` encrypted backup/export/restore. Backups include the SQLite rows and append-only audit history. VEND-001 introduces no provider credentials, external tokens, or remote-source metadata, so no new secret exclusion path is necessary.

## Implementation outline

1. Complete common party creation/patch/list/archive/restore behavior behind the `parties` application service, ports, SQLite adapter, domain model, audit policy, typed router, and guard protocols established by TEN-001. Remove the duplicated party routes and direct party persistence from `portfolio`; retain party contact methods as the single reusable TEN-001 contract.
2. Add provider SQLAlchemy models, constraints, and module-owned exact schema validation to the current greenfield Alembic baseline. Extend product table allowlists, workspace/archive validation, and backup/restore verification.
3. Add provider domain values and typed commands for profile, services, areas, work history, and references. Normalize labels and enforce active-row uniqueness, lifecycle rules, selection-reason rules, and property reference validity.
4. Implement a transaction-oriented provider unit-of-work port and SQLite adapter. The provider application service explicitly coordinates writes and audit changes; it does not import SQLAlchemy models or create concrete repositories.
5. Compose parties and providers in the bootstrap layer, register audit presentation policies, and expose typed FastAPI routes with consistent readiness and 404/400/409/422 mapping.
6. Add regression tests for identity reuse, duplicate candidates and explicit creation override, role/contact guards, direct-command validation, normalized duplicates, archive/restore, search escaping and filters, audit rollback/correlation/redaction, exact-schema rejection, and encrypted backup/restore.

## Acceptance criteria

VEND-001 is complete when:

1. Shared party identities are created, listed, updated, archived, and restored through the dedicated `parties` API rather than `portfolio` routes.
2. An operator can create a provider with a new party or designate one existing active party without duplicating identity data.
3. Provider services, service areas, manually recorded past work, references, and preferred/avoid state are lifecycle-managed, searchable, and retain stable history.
4. `avoid` always includes an explicit reason, active normalized service/area duplicates are rejected, and provider work records never impersonate maintenance records.
5. Shared-party archive respects role guards; provider archive never destroys party identity or child history.
6. Provider and party writes are atomic with correlated append-only audit events; generalized activity redacts contact and sensitive internal-context fields.
7. Typed APIs reject unknown/malformed input and return controlled 404/400/409/422 outcomes.
8. Exact latest-schema validation and encrypted backup/export/restore preserve provider data, relationships, and audit history.
9. VEND-001 leaves configurable categories, reputation links, discovery, quote selection, assignments, costs, and communications to their owning backlog items.

## Dependencies and follow-on work

VEND-001 requires `PORT-001` for the shared party identity, `TEN-001` for party-owned contacts and guard protocols, and `AUDIT-001` for its append-only ledger. It uses existing `LOCAL-001` and `LOCAL-002` workspace capabilities without a new data location.

`VEND-002` adds manually recorded reputation links to a provider profile. `VEND-CAT-001` adds configurable provider categories and assignments. `MAINT-002` selects a saved provider for quotes or assignments, while `MAINT-003` becomes the authoritative work journal. `FIN-002` can reference the stable provider identity for an expense. `ISSUE-AI-004` may rank saved providers only after these source records exist and must not contact or assign one automatically. `VEND-003` and `VEND-005` own direct quote requests and external discovery respectively.
