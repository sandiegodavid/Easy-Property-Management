# VEND-CAT-001 — Configurable Provider Categories

## Status and authority

This is the confirmed backend/API and UI-handoff design for `VEND-CAT-001`. It is based on [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md), [ARCHITECTURE.md](ARCHITECTURE.md), [FEATURE_BACKLOG.md](FEATURE_BACKLOG.md), [DECISIONS.md](DECISIONS.md), [VEND-001_DESIGN.md](VEND-001_DESIGN.md), [MAINT-001_DESIGN.md](MAINT-001_DESIGN.md), [MAINT-002_DESIGN.md](MAINT-002_DESIGN.md), and [UI-001_DESIGN.md](UI-001_DESIGN.md), plus the current implementation.

The decisions under **Resolved contradictions and decisions** are authoritative for this feature and reconcile the ambiguities found during design. No application code is included.

## Outcome

`VEND-CAT-001` gives the workspace one operator-configurable provider-category catalog and lets each provider belong to zero or more categories. Categories make the provider directory easier to scan and filter, give Legal / Attorney a first-class classification, and provide stable category identities for later reviewed AI diagnosis and provider suggestions.

The feature does not replace VEND-001 free-form service labels. A category answers the broad question “what kind of provider is this?” while service labels capture specific offerings or practice areas such as `eviction representation`, `water-heater repair`, or `commercial landscape maintenance`.

## Scope and boundaries

VEND-CAT-001 provides:

- one workspace-owned flat category catalog;
- initial editable categories for Legal / Attorney, Landscaping, Electrical, HVAC / A/C, Appliance repair, Plumbing, and General maintenance;
- create, rename, describe, order, archive, and restore behavior for categories;
- multiple category assignments per provider with retained assignment history;
- category-aware provider creation, detail, list, search, and filtering;
- an explicit Uncategorized filter so missing classification remains visible;
- bounded consumer-neutral category projections for later AI and UI consumers;
- atomic audit history, current-schema validation, and encrypted backup/export/restore coverage; and
- typed API contracts and the UI handoff consumed by UI-001.

VEND-CAT-001 does not provide:

- a hierarchical category tree, aliases, icons, colors, or per-category custom fields;
- conversion, synchronization, or inference between categories and free-form provider service labels;
- a deterministic mapping between Maintenance issue categories and provider categories;
- assignment eligibility, automatic provider selection, quote requests, communications, or maintenance assignment;
- AI diagnosis, ranking, or recommendation behavior;
- legal-matter engagement or legal practice-area records;
- expense categories or any mapping to Finance categories;
- external provider discovery or live reputation data; or
- React implementation before UI-001.

## Current implementation baseline

VEND-001 and VEND-002 are implemented in the `vendors` module. The current implementation already supplies:

- shared Party-backed provider identity;
- provider profile lifecycle and preferred/avoid state;
- free-form service and service-area records;
- manually recorded work history and references;
- reputation links;
- typed provider routes and response models;
- a transaction-oriented provider unit of work and transaction-aware consumer context reader;
- fail-closed audit presentation policy;
- exact provider-schema validation; and
- backup/restore coverage through the workspace database.

The current implementation has no category table, provider-category assignment, category API, category filter, category response field, seed catalog, or category read port. `ProviderSearchCommand` and `GET /api/providers` filter only by free-form service label, service area, selection status, work-history property, and reference presence. `SQLiteProviderContextReader` exposes profile state but no categories. The exact schema validator and current greenfield schema know only the existing VEND-001/VEND-002 tables.

VEND-CAT-001 should extend the existing `vendors` module. A separate category module would split one provider aggregate and add unnecessary cross-module coordination.

## Domain design

### Categories and service labels remain distinct

Provider categories are controlled workspace vocabulary. They have stable IDs, operator-managed display names, lifecycle state, and ordering. Provider service labels remain provider-specific, free-form, normalized offerings with their own lifecycle.

Examples:

| Category | Possible service labels |
| --- | --- |
| Legal / Attorney | Eviction representation; lease review; fair-housing advice |
| Plumbing | Water regulator replacement; drain clearing; leak repair |
| HVAC / A/C | Heat-pump service; furnace repair; seasonal inspection |
| General maintenance | Turnover work; handyman work; minor carpentry |

No background job or write workflow derives one representation from the other. Renaming or archiving a category never edits a provider's service labels. Editing a service label never creates, renames, or assigns a category.

### The MVP catalog is flat

The initial catalog has no parent-child relationships. A provider may hold multiple categories when its work crosses trades. Flat categories are easier to configure, import, filter, audit, and present within the small-portfolio MVP.

Specific capability belongs in VEND-001 service labels. If later usage demonstrates a need for hierarchical browsing, a future feature may add parent relationships without changing category IDs or rewriting existing assignments.

### Initial categories are editable workspace data

The current greenfield workspace initialization seeds these active categories:

1. Legal / Attorney
2. Landscaping
3. Electrical
4. HVAC / A/C
5. Appliance repair
6. Plumbing
7. General maintenance

They are ordinary category rows with stable UUIDs, not hard-coded enums. The operator may rename, reorder, archive, restore, or add categories. Code, AI contracts, and downstream records refer to category IDs rather than seed labels.

Seed insertion is deterministic for a newly initialized workspace and covered by current-schema/seed validation. The project is greenfield, so implementation updates the single current schema and initializer without a compatibility or data-migration path.

### A provider may have zero or more categories

Category assignment is many-to-many:

- a provider may be uncategorized while initially entered or imported;
- a provider may have several categories;
- duplicate active assignment of the same category to one provider is rejected or returned as an idempotent replay;
- normal assignment requires an active provider profile and active category;
- archived providers and archived categories are unavailable for new assignments; and
- no category assignment changes preferred/avoid state or service labels.

Uncategorized providers remain visible through an explicit directory filter and coverage indicator. The application must not hide them or pretend the directory is fully classified.

### Category and assignment lifecycles retain history

Categories and assignments use archive/restore rather than deletion.

Archiving a category requires confirmation and a bounded reason. It removes the category from normal pickers, filters, AI category catalogs, and effective provider classifications. It does not rewrite or archive each provider assignment. Retaining those relationships makes category restoration predictable and preserves which providers had used it.

Restoring a category makes its still-active assignments effective again. Restoration is rejected when another active category has reused the normalized name. The category's audit history explains prior names and lifecycle changes.

Archiving an individual provider-category assignment also requires confirmation and a reason. It removes only that provider's relationship. Restoring an assignment requires an active provider and active category and fails if another active assignment for the pair exists.

Archiving a provider profile does not mutate its category assignments. They remain retained but ineffective while the provider is archived and become effective again if the profile is restored.

### Renaming changes current classification, not historical events

A category rename updates the current shared vocabulary. Provider directory/detail views show the current category name. The append-only audit ledger preserves previous names.

Downstream records that need to explain a past decision must store their own category ID plus display-name snapshot. For example, a later AI recommendation retains the category identity and label used by that run. VEND-CAT-001 itself does not add snapshots to Maintenance assignments because MAINT-002 does not currently use category eligibility.

### Categories are advisory context, not assignment eligibility

Provider categories support search, browsing, imports, and later explainable AI signals. They do not prevent an operator from recording a quote or assigning a provider in MAINT-002.

Maintenance issue categories and provider categories remain separate taxonomies. This feature adds no string comparison or implicit equivalence. ISSUE-AI-003 may later propose one active provider-category ID from the catalog with rationale and operator review. ISSUE-AI-004 may use effective category assignments as one ranking signal. Neither feature may contact or assign a provider automatically.

Legal / Attorney follows the same provider-category model. Practice areas remain optional VEND-001 service labels. A legal-matter engagement belongs to LEGAL-001 and is never represented as a Maintenance assignment.

## Persistence model

### `provider_categories`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `display_name` | Required trimmed operator-facing name, 1–160 characters. |
| `normalized_name` | Unicode-normalized, whitespace-normalized, case-folded uniqueness key. |
| `description` | Optional operator-facing explanation, at most 1,000 characters. |
| `display_order` | Required nonnegative integer used before normalized name and ID for deterministic ordering. It is not unique. |
| `revision` | Exact positive integer, initially 1 including seeds; increments once per effective category command. |
| `created_at`, `updated_at` | UTC timestamps. |
| `archived_at`, `archive_reason` | Both null while active; both required when archived. Reason is 1–1,000 characters. |
| `create_idempotency_key`, `create_request_fingerprint` | Required creation-operation UUID and canonical request fingerprint for safe retry. Operator/API creation uses a client-generated key; seeded rows use reserved deterministic initializer keys. |

The database enforces lifecycle pairing, nonblank bounded names, nonnegative order, and one active normalized name through a partial unique index. Archived normalized names may be reused; restoring an older category then requires resolving the conflict explicitly.

Indexes support active ordered catalog reads and normalized-name lookup.

### `provider_category_assignments`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `provider_party_id` | Required provider-profile reference. |
| `category_id` | Required provider-category reference. |
| `created_at`, `updated_at` | UTC timestamps. |
| `archived_at`, `archive_reason` | Both null while active; both required when archived. |
| `create_idempotency_key`, `create_request_fingerprint` | Required client-generated UUID and canonical request fingerprint for lost-response replay. |

A partial unique index permits at most one active assignment per `(provider_party_id, category_id)`. Foreign keys preserve retained provider and category history. Indexes support provider-to-category and category-to-provider reads without per-provider queries.

### Seed identity

The category seed definitions use stable UUID constants and deterministic order. Current-schema initialization inserts the seven seeds exactly once for a new workspace. Runtime code never branches on those IDs; their stability exists for fixtures, imports, backups, and later SaaS migration.

## Application and transaction design

The existing Provider unit of work owns category writes. Provider application code validates commands and orchestrates persistence through new transaction operations; it does not import SQLAlchemy models.

Required transaction operations include:

- load/list categories with explicit archive state;
- insert/replace a category;
- load category assignments for one or a bounded set of providers;
- insert/replace an assignment;
- count effective provider assignments by category; and
- record correlated audit changes.

All category and independent assignment commands require persisted UUID idempotency keys and canonical semantic fingerprints:

- same key and same semantic fingerprint returns the immutable original result before current lifecycle/revision checks, with no new audit event;
- same key and changed content returns `409 provider_category_idempotency_conflict` for categories or `409 provider_idempotency_conflict` for assignments; and
- normalized-name or active-pair collision under a different key returns the appropriate uniqueness conflict.

Category creation requires expected revision zero; patch/archive/restore require the positive current category revision. Seeds start at revision one. Independent assignment commands require the positive current Provider revision; assign and restore additionally require the current positive category revision. Exact integer validation rejects booleans and coercible values for direct callers and HTTP callers. Stale commands return `409` with the current category or Provider snapshot. An effective mutation advances only its owning revision once. Category archive/restore never rewrites assignments or advances Provider revisions.

Under a new key, a semantic no-op patch/archive/restore records a durable receipt without changing the business timestamp/revision or emitting a business mutation audit. An archived record retried with a different reason conflicts. Under an existing key, payload, expected revision, target and action must match the original command exactly.

### UI-001 Slice 26 receipt authority (approved October 9, 2026)

The current greenfield baseline adds `provider_category_command_operations` with stable UUID `id`, category foreign key, action (`create`, `patch`, `archive`, `restore`), globally unique UUID `idempotency_key`, canonical `request_json`, lowercase SHA-256 `request_fingerprint`, exact integer `expected_revision` and `resulting_revision`, canonical `result_json`, correlation UUID and UTC creation timestamp. Update/delete/replace triggers make the ledger append-only. Keys are global within this category ledger; assignment operations use the separate globally keyed Provider command ledger from Slices 24–25 with actions `assignment_create`, `assignment_archive`, and `assignment_restore`.

Category original results contain `category` (including its effectiveProviderCount at commit), `revision`, and `operationId`. Assignment original results contain `kind=assignment`, `item`, the raw category snapshot, the revised Provider `profile`, `revision`, and `operationId`. These snapshots exclude live Party/contact/child enrichments. Count or name changes after commit do not alter replay. Initial assignments created by the compound Provider-create command remain inside its revision-one receipt; they do not gain independent receipts or extra increments.

Source writes, revision changes, original results, metadata-only receipt audits and contextual mutation audits commit in one immediate transaction. Required audit or receipt failure rolls back everything. `GET /api/provider-categories/operations/{operationId}` and `/operations/by-key/{key}` recover category results with one indexed read; assignments use the existing Provider recovery endpoints. Recovery is read-only. Request/response/conflict models are typed and operation IDs stable; no OPS registration or consequential browser control is enabled here.

Exact current-schema validation includes both ledgers and immutability trigger bodies. Retained-data validation reconstructs category histories from registered seed origins, validates canonical requests and fingerprints, revision lineage/tips, original effective counts, assignment ownership and category freshness, and correlated receipt/mutation evidence. Backup/restore retains and validates these rows and original results. This replaces the former current-representation retry semantics, with no compatibility migration.

Provider creation and DATA-002 provider intake may supply zero or more category IDs. Provider profile creation and initial category assignments commit in the same immediate transaction. Initial assignment identities are derived within that owning create operation rather than accepted as separate client operations. An invalid, archived, or duplicate category rejects the whole provider operation; no partially categorized provider is created. This feature does not otherwise redesign VEND-001 provider-create retry behavior.

## Read behavior and performance

### Category catalog

Catalog reads support `archiveState=active|archived|all` and optional normalized text search. Normal pickers return only active categories. Settings can include archived categories and effective provider counts.

Ordering is deterministic: `displayOrder`, normalized name, then category ID. Duplicate display-order values are valid, avoiding fragile reorder-wide writes.

### Provider list and detail

The provider list adds:

- `categoryId`: require one effective assignment to the active category;
- `categoryState=categorized|uncategorized`: coverage filter; and
- category summaries in each provider row.

Category filtering uses stable IDs, not labels. Search may match active category display names in addition to the existing identity, service, area, work-history, and reference text. A provider with only assignments to archived categories is Uncategorized for normal directory behavior.

Provider detail returns effective category summaries by default. `includeArchived=true` also returns archived assignments and assignments whose categories are archived, with both lifecycle states explicit.

Provider list assembly must batch category assignments and categories for the returned provider set. It must not issue one query per provider. The current unpaginated provider list is an adjacent pre-existing bounded-read gap; this feature should add a capped `limit` and opaque cursor rather than expand the unbounded response further. Recommended defaults are 100 and maximum 200.

### Consumer-neutral context reader

Providers exposes a transaction-aware application protocol that returns bounded effective category facts:

- one provider's category IDs and display labels;
- categories for a bounded provider-ID set; and
- the active category catalog for later reviewed AI workflows.

The reader owns provider persistence knowledge. Maintenance, AI, import, and UI composition must not import Provider SQLAlchemy models. The reader supplies facts only; consumers own eligibility, ranking, and presentation policy.

## API contract

All routes require a ready workspace; mutations require the writer lock. Request models reject unknown fields and use strict booleans, typed UUIDs, bounded text, and direct-command revalidation. Responses use explicit models.

### Category settings

| Method | Path | Intent |
| --- | --- | --- |
| `GET` | `/api/provider-categories` | List/search categories with archive state and effective-provider counts. |
| `POST` | `/api/provider-categories` | Create one category with an idempotency key. |
| `PATCH` | `/api/provider-categories/{categoryId}` | Rename, describe, or reorder one category. |
| `POST` | `/api/provider-categories/{categoryId}/archive` | Archive after confirmation and reason. |
| `POST` | `/api/provider-categories/{categoryId}/restore` | Restore after confirmation and normalized-name conflict validation. |

### Provider classification

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/providers/{partyId}/category-assignments` | Assign one active category with an idempotency key. |
| `POST` | `/api/providers/{partyId}/category-assignments/{assignmentId}/archive` | Remove one current classification after confirmation and reason. |
| `POST` | `/api/providers/{partyId}/category-assignments/{assignmentId}/restore` | Restore one retained classification. |
| `GET` | `/api/providers` | Extend the existing list with category filters, category summaries, a cap, and cursor. |
| `GET` | `/api/providers/{partyId}` | Extend detail with effective or explicitly included archived category history. |

Provider create accepts optional `categoryIds`. Category create and assignment create require `idempotencyKey`. Lifecycle bodies require `confirmed: true` and a reason where specified. Patch rejects an empty request and treats a no-op as a read without changing timestamps or audit history.

Malformed request models return `422`; oversized request content returns `413`; missing providers, categories, or assignments return `404`; invalid business data returns `400`; idempotency mismatch, active-name/assignment uniqueness, lifecycle, stale-state, and concurrent-write conflicts return `409`.

## Audit, privacy, and portability

Every mutation and its `AUDIT-001` event commit atomically under one correlation ID. New audit entity types are `provider_category` and `provider_category_assignment`.

Category names and provider classification may appear in general activity. Descriptions, archive reasons, idempotency keys, request fingerprints, and internal provider selection reasons remain redacted from general activity; contextual Provider history may show the complete local record. Audit presentation policies are registered before the first category event can be written.

The new rows, seed identities, assignments, and audit history participate in exact current-schema validation and LOCAL-002 encrypted backup/export/restore. Restore validates foreign keys, lifecycle pairings, UUIDs, normalized values, active uniqueness, registered seed identity consistency, timestamps, idempotency fingerprints, and correlated audit evidence.

No new credentials, remote metadata, or file content are introduced.

## UI handoff

UI-001 presents category management under **Settings → Provider categories**. The operator can add, rename, describe, reorder, archive, restore, and inspect provider counts. Archived categories are visually separate and never appear in normal category pickers.

The Providers directory shows compact category labels, supports one category filter plus Categorized/Uncategorized coverage, and keeps free-form Services as separate detail. The provider create/edit workflow supports multiple category selection and preserves an unfinished provider as an ordinary uncategorized record only after the provider itself is successfully saved.

The interface explains the distinction in plain language:

- **Categories** organize the directory and later recommendations.
- **Services** describe the provider's specific offerings or practice areas.

Legal / Attorney appears as a category. An attorney's practice areas appear under Services. Opening or linking a legal engagement uses LEGAL-001 and does not create a Maintenance assignment.

## Implementation outline

1. Implement the authoritative decisions below and preserve the aligned VEND-CAT-001, ISSUE-AI-003, and DATA-002 backlog contracts.
2. Add category and assignment records, constraints, seed definitions, indexes, and idempotency fields to the single current greenfield schema.
3. Extend Provider exact-schema/retained-data validation, product table allowlists, archive validation, and backup/restore verification.
4. Add strict category/assignment domain values, commands, models, transaction operations, and consumer-neutral read projections.
5. Extend ProviderService and its existing unit of work so provider creation plus initial categories is atomic, retry-safe, and audited.
6. Extend list/detail projections with batched categories, category/coverage filters, and bounded cursor pagination.
7. Register audit presentation policy and typed routes with the shared workspace gate and error conventions.
8. Add focused Provider, API, schema, audit, import-contract, and backup/restore regression tests.
9. Leave React implementation to UI-001 and AI behavior to ISSUE-AI-003/004.

## Validation matrix

| Area | Required validation |
| --- | --- |
| Happy paths | Seed catalog exists; create/rename/reorder/archive/restore category; assign several categories; archive/restore one assignment; create provider with initial categories; filter/search and Uncategorized behavior. |
| Invalid combinations | Blank/oversized names; duplicate normalized active names; invalid order; unknown/archived provider or category; duplicate active assignment; mismatched provider/assignment path; restore conflicts; false confirmation; missing archive reason; unknown request fields; oversized content returns 413. |
| Idempotency and retry | All category and assignment commands replay immutable original results; changed-payload conflicts and stale revisions; concurrent same-key assignment submissions; new-key no-ops retain receipts without business timestamp/revision changes or mutation audits. |
| Transaction rollback | Audit failure, assignment failure, seed validation failure, and provider-with-initial-categories failure roll back every business and audit row. |
| Persistence/schema | Exact columns, nullability, checks, foreign keys, partial unique indexes, seed identities, normalized values, lifecycle pairs, idempotency fingerprints, registered audit policy, and rejection of tampered retained rows. |
| Backup/restore | Encrypted backup/export/restore preserves category IDs, custom names/order/descriptions, archived state/reasons, assignments, seed identities, idempotency replay, and audit history. |
| Query budget/N+1 | Provider list with 1, 100, and 200 rows uses a bounded fixed query count; category catalog count query is set-based; detail does not query once per category; cursor pages are stable under equal order/name values. |
| Cross-feature boundaries | Service labels remain unchanged; Maintenance issue categories remain unchanged; category archive does not rewrite MAINT-002 assignments; Legal / Attorney classification creates no legal engagement; Finance expense categories remain independent. |

## Backend acceptance criteria

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

## Dependencies and follow-on work

VEND-CAT-001 directly requires completed `VEND-001` and `AUDIT-001`. It reuses the existing workspace, Provider unit of work, Party-backed provider identity, LOCAL-002 backup, and shared API error infrastructure.

Follow-on consumers are:

- `ISSUE-AI-003` — proposes one active provider-category identity from the current catalog with rationale and operator review;
- `ISSUE-AI-004` — uses effective provider-category assignments as one explainable ranking signal;
- `DATA-002` — maps imported provider category values to reviewed existing/new categories and commits selected assignments atomically with provider creation;
- `LEGAL-001` — links attorney/law-firm providers to legal matters while keeping practice areas in services;
- `UI-001` — delivers Settings category management and category-aware provider directory/detail workflows; and
- future explicit taxonomy mapping — may map Maintenance issue categories to provider categories without string inference or historical rewrites.

## Resolved contradictions and decisions

### 1. “Configurable categories” does not define the configuration lifecycle

The backlog does not say whether categories can be renamed, reordered, archived, restored, or deleted.

**Decision:** support create, rename, optional description, display order, archive, and restore. Never delete retained categories.

### 2. VEND-001 delegates category hierarchy, but the backlog does not request a hierarchy

VEND-001 says VEND-CAT-001 owns any category hierarchy, while the backlog only asks for configurable categories.

**Decision:** use a flat MVP catalog. Keep specific offerings and attorney practice areas in free-form service labels. Defer parent/child categories until observed usage justifies them.

### 3. The examples do not establish a seed contract

The backlog says “such as,” so it is unclear whether the listed values are guaranteed defaults or only examples. UI-001 requires Legal / Attorney to exist as a formal category.

**Decision:** seed the seven listed categories, using `Legal / Attorney` and `HVAC / A/C` as display labels. Treat every seed as editable workspace data with a stable UUID.

### 4. Category and free-form service behavior could be confused

VEND-001 already stores normalized service labels, and UI-001 calls Legal / Attorney a service category with practice-area labels.

**Decision:** keep two parallel concepts. Categories are controlled broad classifications; VEND-001 services are provider-specific details. Do not migrate, infer, or synchronize them.

### 5. Provider-category cardinality and requiredness are unspecified

The Product Brief confirms multiple categories but does not say whether at least one is mandatory.

**Decision:** allow zero or more. Surface Uncategorized as a first-class coverage state so incomplete classification is visible without blocking provider capture/import.

### 6. Category and assignment archival semantics are unspecified

It is unclear whether archiving a category should cascade to every provider assignment or whether restoring it should restore previous classification.

**Decision:** retain assignments unchanged and compute effective classification from active provider + active assignment + active category. Category restoration then predictably restores still-active relationships; an individual assignment can be archived separately.

### 7. Rename semantics and historical display are unspecified

It is unclear whether provider assignments should snapshot a category label or follow renames.

**Decision:** assignments follow the current category name because they describe current capability. Audit preserves prior names. Downstream historical decisions, including AI recommendations, store their own ID/label snapshot.

### 8. Maintenance-to-provider taxonomy mapping remains deliberately undefined

MAINT-001 owns fixed issue categories, while DECISIONS.md prohibits treating similar strings as equivalent until an explicit mapping exists.

**Decision:** do not add a deterministic mapping in VEND-CAT-001. ISSUE-AI-003 may propose a stable active provider-category ID from the catalog, but category compatibility remains advisory and operator-reviewed. Design an explicit mapping later only if non-AI routing needs it.

### 9. The original ISSUE-AI-003 row had a dependency contradiction

ISSUE-AI-003 promises to suggest an appropriate provider category but does not depend on VEND-CAT-001. ISSUE-AI-004 does depend on it.

**Decision:** add VEND-CAT-001 as a direct ISSUE-AI-003 dependency and require its output to reference an active category ID plus label snapshot rather than an unconstrained string. The updated backlog row reflects this dependency and output contract.

### 10. The original backlog row omitted AUDIT-001 as a direct dependency

VEND-CAT-001 introduces mutable settings and retained assignment lifecycle that require atomic audit history.

**Decision:** add AUDIT-001 as a direct dependency even though VEND-001 already depends on it; the category feature independently relies on the audit contract. The updated VEND-CAT-001 backlog row reflects this dependency.

### 11. Import-time category assignment is not defined

DATA-002 depends on VEND-CAT-001, but neither backlog row says whether a provider may be committed before category assignments or how unknown imported labels are handled.

**Decision:** let reviewed import operations map each normalized source value to an existing category, create a reviewed new category, or skip it. Commit provider creation and selected assignments atomically; never silently create or fuzzy-match a category. DATA-002's design and backlog outcome reflect this rule.

### 12. Category use during Maintenance assignment is ambiguous

The product uses categories for provider search and issue routing, but MAINT-002 explicitly permits operator selection without category compatibility.

**Decision:** retain MAINT-002 behavior. Category match is advisory context and never a hard assignment guard in this slice.

### 13. The existing provider list is unpaginated

Adding category summaries and filters to the current unbounded list would widen an existing query-budget risk and conflict with the architecture's bounded-read rule.

**Decision:** add a capped provider-list page with default 100, maximum 200, stable name/ID ordering, and an opaque cursor as part of the VEND-CAT read-contract extension. Keep category assembly set-based.

### 14. Mutation retry behavior is missing

The current VEND-001 child-create routes do not provide a durable lost-response replay contract. Category creation and assignment are especially likely to collide on retry because both enforce uniqueness.

**Decision:** as approved in UI-001 Slice 26, require revisions and persisted UUID keys for every category and assignment command. Replay immutable original results; record accepted new-key no-op receipts without business mutation audits.

### 15. Seed restoration and edited seed identity are unspecified

A configurable seed can be renamed or archived, so startup must not recreate it under its original label.

**Decision:** seed only during new-workspace initialization. Validate stable seed IDs if present, but never reinsert or reset a seed during ordinary startup, restore, or schema validation.
