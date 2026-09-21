# MAINT-002 — Quote Comparison and Provider Assignment

## Purpose

`MAINT-002` lets the operator record comparable provider quotes for an existing maintenance issue and retain an explicit history of which saved provider was assigned. It extends the Maintenance aggregate without turning Provider records into work orders or turning quote amounts into accounting transactions.

The boundary is deliberate:

- Maintenance owns received quotes, comparison, selection, assignment history, and assignment-specific instructions.
- Parties owns provider identity and reusable contact methods.
- Providers owns provider-profile lifecycle, preference state, services, service areas, references, reputation context, and manually recorded historical outcomes.
- Files owns quote and assignment document metadata, bytes, storage integrity, and generic links.
- Finance owns confirmed expenses, refunds, and financial reporting. A quote or assignment is never evidence that money was paid.
- `MAINT-003` later owns append-only work journal entries and completed-work outcomes.

This is a backend/API design. The deferred operator experience remains in `UI-001`.

## Current baseline and dependencies

The current implementation already provides:

- MAINT-001 issue lifecycle, appointments, informational cost contexts, expense links, follow-up tasks, FILE-001 projections, audit history, exact-schema validation, and backup/restore.
- MAINT-004 reporter attribution and linked communication summaries.
- VEND-001 stable provider Party IDs, active/archived provider profiles, free-form service and service-area labels, and `neutral`, `preferred`, or `avoid` selection status.
- FILE-001 generic file records and maintenance-owned link validation.
- AUDIT-001 same-transaction events and privacy presentation.

The implemented Maintenance schema has no quote, assignment, provider-selection, or work-order table. `SQLiteProviderContextReader` currently exposes only provider-profile identity and archive state. Maintenance already receives Party operations for reporter identity, but it has no provider context dependency. The current Maintenance projection executes one set-based query per child type and must retain that bounded behavior.

The backlog now lists `AUDIT-001`, `FILE-001`, `VEND-001`, and `MAINT-001` as direct dependencies. AUDIT-001 is not left implicit through MAINT-001 because MAINT-002 directly creates new audited entity types.

## Scope

MAINT-002 provides:

- Manual recording of a received quote from an existing saved provider.
- Multiple comparable quote options per issue, including multiple options from the same provider.
- Exact USD total, received date, optional validity date, scope summary, terms/notes, and a durable provider display snapshot.
- Explicit withdrawal and replacement history for incorrect, superseded, or provider-withdrawn quotes.
- Selection of an exact quote or a confirmed direct assignment when no quote exists.
- At most one current assignment per issue, with atomic reassignment and retained prior assignments.
- Deliberate override when assigning a provider currently marked `avoid`.
- FILE-001 documents for quotes and assignments.
- Typed APIs, idempotent create/reassign operations, atomic audit history, exact current-schema validation, bounded reads, and encrypted backup/export/restore coverage.

MAINT-002 does not provide:

- Sending quote requests, email/SMS delivery, or provider responses. `VEND-003` and connected Communications own those later workflows.
- Provider discovery, autonomous ranking, category-based matching, or AI recommendations. `VEND-CAT-001`, `ISSUE-AI-004`, and later provider-discovery work own those capabilities.
- Line-item estimating, tax calculation, purchase orders, bills, payables, payment initiation, or recurring costs.
- Confirmed actual spending. FIN-002 expenses remain the only paid-expense records.
- Work progress, labor/material journal entries, completion evidence, or provider outcome history. `MAINT-003` owns that journal.
- Changes to issue status, appointments, tasks, or communications as a side effect of quote or assignment operations.
- React screens. `UI-001` owns quote entry/comparison, assignment, reassignment, and history presentation.

## Domain design

### Quotes are provider offers, not estimates or expenses

A quote is an immutable received offer associated with one maintenance issue and one saved provider Party. It is separate from MAINT-001 `operator_estimate` and `work_reported` cost context:

- an operator estimate is internal informational context;
- a quote is an externally attributed provider offer;
- a FIN-002 expense is confirmed actual spending.

Quote totals never enter Finance totals, owner balances, expense reports, or the issue's confirmed-spending total. Selecting a quote does not create an expense. If work is later paid, the operator records a FIN-002 expense and links it through the existing MAINT-001 expense-link workflow.

The MVP records one total amount rather than quote line items. The scope and terms remain bounded text and attached documents. This keeps comparison useful without prematurely designing estimating, tax, or payable subsystems.

### Quote history is immutable and correction is explicit

A received quote may be active or withdrawn. Withdrawal requires confirmation and a bounded reason. An incorrect or revised quote is not patched in place: the operator withdraws it and creates a replacement with `replacesQuoteId`. The replacement must belong to the same issue and provider, and one withdrawn quote can be replaced only once.

Expiration is derived from `validThrough`; it is not a mutation or stored lifecycle state. A quote can remain historically readable after expiration, provider archival, issue resolution, or assignment changes.

Multiple active quote options from the same provider are permitted because a provider may offer materially different scopes. Each quote therefore has a required operator-facing label. The comparison view identifies the exact quote rather than assuming one quote per provider.

### Assignment is the authoritative selection record

There is no mutable `selected` flag on a quote. A quote was selected when an assignment references it. This prevents quote and assignment state from disagreeing and preserves historical selections after reassignment.

An assignment belongs to one issue and one provider. It may reference one active, non-expired quote for that same issue and provider. A direct assignment without a quote is permitted only with explicit confirmation and a bounded reason. This supports emergencies and known-provider work without fabricating a quote.

At most one assignment is current for an issue. Reassignment is one atomic operation that ends the current assignment with a reason and creates the replacement assignment. An explicit end-assignment action is available when no replacement is selected. Ended assignments are never deleted or reactivated.

Assignment does not start, resolve, reopen, or cancel an issue. It does not create or reschedule an appointment, task, communication, journal entry, or expense. New assignments require an `open` or `in_progress` issue; retained assignment history remains readable after the issue becomes terminal.

### Provider identity is referenced and historical display is snapshotted

Every quote and assignment stores the stable provider Party ID and a bounded provider display-name snapshot resolved by the server. The API never accepts a caller-supplied snapshot. The stable Party remains the identity source; the snapshot only preserves historical readability after a rename or archive.

Creating a quote or assignment requires both an active Party and an active provider profile. Existing records remain valid if either is archived later. Detail may show current provider/profile state as context, but current state never rewrites the snapshot or invalidates retained history.

Provider selection status is checked when assignment is created or replaced:

- `neutral` and `preferred` providers may be assigned normally.
- `avoid` requires `avoidOverrideConfirmed = true` and a bounded operator reason.

The provider's own sensitive `selectionReason` remains in Providers and is not copied into Maintenance. Maintenance stores only the assignment-time status snapshot and the operator's assignment override reason. Recording a quote from an avoided provider remains allowed because receipt is a fact, not a selection.

Provider service and area labels are advisory display/search context, not assignment eligibility. MAINT-002 cannot require a category match because VEND-001 labels are free-form and `VEND-CAT-001` is later in the backlog.

### Quote and assignment documents use FILE-001

Files are linked after the quote or assignment exists. Maintenance extends its FILE-001 validator with:

| Entity type | Allowed purposes | Active-link limit |
| --- | --- | --- |
| `maintenance_quote` | `quote_document`, `supporting_document` | 10 |
| `maintenance_assignment` | `assignment_document`, `supporting_document` | 10 |

Maintenance stores no filename, hash, media type, path, storage state, or provider locator. Incorrect file links are archived through FILE-001. Upload failure does not roll back a truthful quote or assignment; the saved target remains available for an upload retry.

## Data model

All IDs and idempotency keys are UUIDs. Timestamps are aware UTC text. Quote dates are property-local ISO dates. Amounts use the existing exact USD convention: API decimal strings with exactly two fractional digits and persisted integer cents.

### `maintenance_quotes`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `issue_id` | Required Maintenance issue reference. |
| `provider_party_id` | Required stable Party/provider reference. |
| `provider_display_name_snapshot` | Required server-resolved trimmed text, 1–240 characters. |
| `label` | Required option label, 1–200 characters. |
| `scope_summary` | Required sensitive description, 1–4,000 characters. |
| `amount_minor` | Required positive integer from 1 through 9,999,999,999 cents. |
| `currency_code` | Required exact value `USD`. |
| `received_on` | Required property-local ISO date. It cannot be after the current property-local date. |
| `valid_through` | Optional property-local ISO date on or after `received_on`. |
| `terms_notes` | Optional sensitive text, maximum 4,000 characters. |
| `replaces_quote_id` | Optional unique self-reference to a withdrawn quote for the same issue and provider. |
| `withdrawn_at`, `withdrawal_reason` | Both null while active and both required after confirmed withdrawal. |
| `idempotency_key`, `request_fingerprint` | Required create-retry identity and canonical semantic fingerprint; key unique for quote creation. |
| `created_at` | Required UTC timestamp. |

Indexes support issue comparison, provider history, active quote lookup, and replacement validation. Database checks enforce USD, positive integer amounts, paired withdrawal fields, valid bounded stored values, and non-self replacement. Application validation enforces issue/provider availability, property-local dates, replacement lineage, and quote-backed assignment rules.

### `maintenance_assignments`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `issue_id` | Required Maintenance issue reference. |
| `provider_party_id` | Required stable Party/provider reference. |
| `provider_display_name_snapshot` | Required server-resolved trimmed text, 1–240 characters. |
| `quote_id` | Optional quote reference; when present it must match the assignment issue and provider and be active and non-expired at assignment time. |
| `provider_selection_status_snapshot` | `neutral`, `preferred`, or `avoid` at assignment time. |
| `selection_reason` | Optional bounded operator rationale; required for a direct assignment without a quote. |
| `avoid_override_reason` | Required exactly when the status snapshot is `avoid`; otherwise null. |
| `instructions` | Optional sensitive assignment instructions, maximum 4,000 characters. |
| `replaces_assignment_id` | Optional unique reference to the assignment atomically ended by this reassignment. |
| `assigned_at` | Required server-generated UTC timestamp. |
| `ended_at`, `end_reason` | Both null while current and both required after an explicit end or reassignment. |
| `idempotency_key`, `request_fingerprint` | Required create/reassign retry identity and canonical semantic fingerprint; key unique for assignment creation. |

A partial unique index permits at most one assignment with `ended_at IS NULL` per issue. A unique `replaces_assignment_id` prevents branching replacement history. Exact validation rejects issue/provider/quote mismatches, broken replacement chains, multiple current assignments, and missing assignment/quote audit evidence.

No separate quote-selection table is added. Assignment references are the selection history.

## Workflows and invariants

### Record a received quote

`POST /api/maintenance-issues/{issueId}/quotes` validates an active issue, active Party/provider profile, exact amount, local dates, optional replacement, and idempotency in one immediate transaction. It inserts the quote and one audit event. It does not contact the provider or attach a file in the same operation.

### Withdraw or replace a quote

`POST /api/maintenance-quotes/{quoteId}/withdraw` requires confirmation and reason. Repeating a withdrawal is a conflict. A replacement uses the normal create endpoint with `replacesQuoteId` after the original is withdrawn.

Withdrawal does not rewrite an existing assignment that historically selected the quote. Detail surfaces the quote's current withdrawn state so the operator can decide whether reassignment is needed.

### Compare quotes

`GET /api/maintenance-issues/{issueId}/quote-comparison` returns active and withdrawn quote options ordered by active first, non-expired first, amount ascending, received date descending, and ID for stability. It exposes stored provider snapshots, optional current provider/profile state, document counts, and whether each quote appears in current or historical assignments.

The server does not calculate a winner, score providers, infer scope equivalence, or treat lowest price as recommended. Different scopes remain visibly different.

### Assign or reassign a provider

`POST /api/maintenance-issues/{issueId}/assignments` creates the initial assignment or atomically replaces the current one. A replacement supplies `replacesAssignmentId`, confirmation, and an end reason. It validates provider availability and any quote reference in the same transaction and writes correlated audit events for the ended and created assignments.

A direct assignment supplies no quote and requires `directAssignmentConfirmed = true` plus `selectionReason`. An avoided provider additionally requires `avoidOverrideConfirmed = true` and `avoidOverrideReason`.

Same-key/same-payload retries return the created assignment and its current representation without repeating the end transition or audit events. Same-key/different-payload reuse returns a typed `409`.

### End an assignment

`POST /api/maintenance-assignments/{assignmentId}/end` requires confirmation and reason. It ends only the current assignment and does not change the issue or any linked record.

## Read behavior and performance

Issue list may add `providerPartyId`, `hasActiveQuote`, and `hasCurrentAssignment` filters. Its summary adds active quote count and the stored current-assignment provider snapshot. It does not load provider details or quote narratives.

Issue detail adds quote summaries, assignment history, and their FILE-001 link summaries. The dedicated quote-comparison endpoint returns full quote comparison fields.

Reads remain set-based and bounded independently of page size:

- one Maintenance query for quotes for all requested issue IDs;
- one Maintenance query for assignments for all requested issue IDs;
- one FILE-001 batch query per new entity type when detail requires files;
- at most one Party batch query and one Provider batch query for distinct provider IDs on detail/comparison;
- no Party, Provider, or File query on the default issue list because stored snapshots and Maintenance-owned counts are sufficient.

The existing `ProviderContextReader` needs the smallest neutral extension that returns profile availability and selection status for one or many Party IDs. Existing Party operations supply identity availability and display names. Providers must not gain `maintenance_quote_eligible()`, assignment policy, Maintenance response objects, or Maintenance-named adapters. Maintenance owns eligibility, override policy, snapshots, and response shaping in accordance with `ARCHITECTURE.md` SRP guidance.

## API contract

All routes require a ready workspace; mutations require the writer lock. Request models reject unknown fields and use typed UUIDs, strict booleans, ISO dates, and exact decimal strings. Application commands repeat essential validation for direct callers.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/maintenance-issues/{issueId}/quotes` | Record a received quote or replacement. |
| `GET` | `/api/maintenance-issues/{issueId}/quote-comparison` | Return comparable current and historical quote options. |
| `POST` | `/api/maintenance-quotes/{quoteId}/withdraw` | Withdraw an incorrect, superseded, or provider-withdrawn quote. |
| `POST` | `/api/maintenance-issues/{issueId}/assignments` | Assign or atomically reassign a provider. |
| `POST` | `/api/maintenance-assignments/{assignmentId}/end` | End the current assignment without selecting a replacement. |
| `GET` | `/api/maintenance-issues` | Add optional provider/quote/assignment filters and summary fields. |
| `GET` | `/api/maintenance-issues/{issueId}` | Include quote summaries, assignment history, and linked files. |

Malformed requests return `422`; missing issues, quotes, assignments, Parties, or provider profiles return controlled `404`; invalid amounts, dates, direct-assignment confirmation, and provider override inputs return `400`; lifecycle, stale replacement, changed idempotency, quote mismatch, and concurrent-current-assignment conflicts return typed `409` responses.

## Audit, privacy, schema, and portability

Entity types are `maintenance_quote` and `maintenance_assignment`. Every mutation writes domain rows and audit events in the same immediate transaction. Atomic reassignment uses one correlation ID for the ended and created assignment events.

General activity may show issue ID, provider display snapshot, quote label, amount/currency, received date, assignment lifecycle, and whether selection was quote-backed. It redacts quote scope, terms notes, assignment instructions, selection rationale, avoided-provider override reason, withdrawal reason, and end/reassignment reason. Contextual Maintenance history may show the complete authorized record. Provider-owned notes and avoid reasons are never copied into Maintenance audit snapshots.

The current greenfield baseline, SQLAlchemy models, product table allowlist, module-owned exact schema validator, retained-data validator, audit-policy registry, FILE-001 target validation, and encrypted backup/export/restore validation must include both new tables and their file links. Restore validates stored structural and historical integrity; it does not re-evaluate quote expiration or provider eligibility against the restore date.

## Implementation outline

1. Implement the authoritative decisions recorded below without reopening quote, assignment, taxonomy, or migration scope implicitly during schema work.
2. Add quote/assignment commands, lifecycle rules, idempotency, audit policies, application ports/service methods, persistence models, and typed routes within Maintenance.
3. Add the small consumer-neutral Provider context-reader extension and compose it with existing Party operations at bootstrap; do not place Maintenance operations in Providers.
4. Extend Maintenance's FILE-001 validator with quote and assignment targets and purposes.
5. Extend issue list/detail projections with two set-based Maintenance child queries and bounded source-owned batch readers; assert query budgets before accepting another abstraction or query.
6. Update the current greenfield schema baseline, product allowlist, exact/retained-data validation, backup/restore coverage, and audit-policy registration. Do not add compatibility tables or dual-read/write paths.
7. Add tests for quote validation and alternatives, provider availability, avoided-provider override, direct assignment, selection and reassignment, idempotency, correction lineage, issue-lifecycle independence, file links, audit privacy, exact schema/data rejection, query budgets, concurrency, and restore integrity.
8. Deliver the operator workflow through the existing `UI-001` scope.

## Backend acceptance criteria

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
10. Exact schema validation and encrypted backup/restore preserve quotes, assignment history, file links, audit history, replacement lineage, and stable IDs.

The overall operator workflow remains pending until `UI-001` supplies quote comparison and assignment screens. Work execution and outcome history remain pending until `MAINT-003`.

## Contradictions and design decisions

The following contradictions or ambiguities were found during design review. The decisions below are now authoritative for MAINT-002 implementation.

### 1. The original backlog dependencies omitted AUDIT-001

Quotes, withdrawal, provider selection, override, and reassignment are durable business decisions requiring append-only history, but the original MAINT-002 row omitted AUDIT-001 while MAINT-003 explicitly listed it.

Decision: add completed `AUDIT-001` as a direct MAINT-002 dependency. Do not rely only on MAINT-001's transitive dependency when MAINT-002 directly creates new audited entity types.

### 2. The backlog does not distinguish quote, estimate, work-reported amount, and expense

MAINT-001 explicitly says provider quotes must not be stored as cost contexts, and Architecture says Finance alone owns confirmed expenses.

Decision: use the separate quote model above. Quote totals are neither MAINT-001 cost context nor FIN-002 expense amounts, selecting a quote creates no expense, and paid work is recorded separately through FIN-002.

### 3. “Compare quotes” could imply quote-request delivery

MAINT-002 depends on VEND-001 but not Communications or connector work. `VEND-003` later owns sending quote requests directly to providers and depends on MAINT-002.

Decision: MAINT-002 manually records received quotes only. It stores no request/sent/delivery state and sends nothing. VEND-003 may later correlate requests and responses without redefining the quote record.

### 4. It is unspecified whether every assignment requires a quote

Requiring a quote would force fabricated records for emergencies or trusted-provider work. Allowing unrestricted no-quote assignment would weaken the meaning of comparison and selection.

Decision: allow either an exact quote-backed assignment or a confirmed direct assignment with a required reason. Never synthesize a zero-dollar or placeholder quote.

### 5. Quote correction, withdrawal, expiration, and selection lifecycle are unspecified

A mutable `selected` flag plus mutable quote fields would conflict with audit history and assignment replacement. Treating expiration as a background mutation would add unnecessary jobs and time-based writes.

Decision: make quote facts immutable; withdraw with confirmation/reason; replace through a one-to-one lineage; derive expiration from `validThrough`; and derive selection exclusively from assignment references. Allow multiple labeled options from one provider.

### 6. The meaning of `avoid` during quote receipt and assignment is unspecified

VEND-001 says an avoided provider should not be suggested or selected without deliberate review, but it does not define a MAINT-002 enforcement rule.

Decision: allow recording a quote from an avoided provider, but require confirmed override and a Maintenance-owned reason to assign that provider. Snapshot only the selection status; do not copy the Providers-owned avoid reason.

### 7. Provider archival during an active assignment is unspecified

Blocking provider-profile archival would require a new reverse guard from Providers into Maintenance. Allowing archival can leave a current assignment pointing to a provider no longer available for new selection.

Decision: do not add the reverse guard. Preserve the assignment and snapshot, surface current provider/profile archival as a warning, and require an active Party/profile only for new quote or assignment operations. Reassignment remains an explicit operator action.

### 8. Provider-category compatibility cannot be enforced yet

Maintenance has a fixed issue taxonomy, VEND-001 has free-form service labels, and configurable provider categories are deferred to `VEND-CAT-001`. Treating similar strings as equivalent would silently couple unrelated taxonomies.

Decision: do not enforce or infer category/service compatibility in MAINT-002. Provider search may show VEND-001 service/area context, but the operator makes the selection. A future explicit mapping design may add validated suggestions without rewriting history. This taxonomy boundary is also recorded in `DECISIONS.md`.

### 9. Assignment relationships to issue status, appointments, and MAINT-003 are missing

Automatically starting an issue, attaching appointments to a mutable “current provider,” or completing assignments from issue resolution would introduce hidden synchronization and ambiguous history.

Decision: keep quote, assignment, issue, and appointment lifecycles independent. Store immutable assignment history at issue level and do not add a provider ID to existing appointments in this slice. MAINT-003 journal entries reference stable issue and optional assignment IDs without making journal events mutate assignment, issue, or appointment status automatically. The MAINT-003 backlog outcome now states this boundary explicitly.

### 10. Quote financial granularity is unspecified

The backlog does not say whether comparison includes line items, tax, deposits, currencies, or payment schedules. Implementing those now would approach estimating and payable subsystems.

Decision: store one positive exact USD total plus bounded scope and terms. Defer line items, tax arithmetic, deposits, multi-currency, approvals, and payable state until a concrete workflow requires them.

### 11. Assignment document scope is not explicit

FILE-001 is a dependency, clearly supporting quote documents, but the backlog does not say whether work authorizations or assignment documents belong here or in the later journal.

Decision: permit bounded `assignment_document` and `supporting_document` links on the assignment as designed above. These are authorization/context files, not journal entries or proof of completed work. Completion evidence remains with MAINT-003, as now stated in its backlog outcome.

### 12. Schema adoption is not specified

The repository uses one exact current greenfield baseline and has no compatibility/adoption framework for Maintenance schema versions.

Decision: update the current baseline and rebuild development workspaces/fixtures. No customer workspace migration is required. Do not weaken non-null constraints or add compatibility, adoption, or dual-read/write paths.

### 13. The original repair-reporting dependencies omitted MAINT-002

`RPT-001` promises repair reports and drill-down but originally depended only on MAINT-001 and MAINT-004 for Maintenance facts. Reports that show selected providers, quote-versus-actual context, or assignment history require MAINT-002.

Decision: add MAINT-002 to `RPT-001` and treat quote totals as operational comparison facts, never expenses.

## Dependencies and follow-on work

MAINT-002 requires completed `AUDIT-001`, `FILE-001`, `VEND-001`, and `MAINT-001`. It consumes Parties and Portfolio indirectly through those implemented boundaries and requires no new ownership of their data.

Follow-on ownership remains:

- `MAINT-003` — append-only work journal and repair outcomes, optionally referencing stable assignments.
- `UI-001` — quote comparison, direct/quote-backed assignment, override confirmation, reassignment, and history screens.
- `VEND-003` — sending quote requests; it may later correlate delivery with Maintenance quotes.
- `VEND-CAT-001` — configurable provider categories and any explicit mapping to Maintenance issue categories.
- `ISSUE-AI-004` — explainable saved-provider suggestions; it must never assign or contact a provider automatically.
- `FIN-002` — actual paid expenses linked to an issue after payment is known.
- `RPT-001` — repair reporting and drill-down using Maintenance-owned quote and assignment facts without treating quote totals as spending.
