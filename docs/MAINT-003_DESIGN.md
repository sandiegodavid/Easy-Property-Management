# MAINT-003 — Append-Only Work Journal and Completion Evidence

## Purpose

`MAINT-003` gives each Maintenance issue an append-only account of work that started, progressed, became blocked, and reached an operator-reviewed outcome. Journal entries may reference the stable provider assignment that supplied the work context, and completion evidence attaches to the journal entry that it supports.

The boundary is deliberate:

- Maintenance owns issue-backed work entries, actual work timing, completion outcomes, correction lineage, and completion-evidence associations.
- MAINT-002 owns received quotes, quoted schedule dates, provider selection, and assignment history.
- Providers owns manually entered prior-work notes that did not originate in the application's Maintenance workflow. It does not receive copied MAINT-003 outcome rows.
- Files owns immutable file metadata, content, storage state, and generic links.
- Finance owns confirmed paid expenses, refunds, and financial totals.
- Appointments record whether a scheduled visit occurred; they do not establish that repair work was completed.

This is a backend/API design. The deferred operator experience remains in `UI-001`.

## Current baseline and dependencies

The current implementation already provides:

- MAINT-001 issues, lifecycle, appointments, non-financial cost context, expense links, follow-up tasks, evidence, reporter attribution, audit history, and bounded list projections.
- MAINT-002 immutable quotes, provider assignment history, assignment snapshots, quote and assignment documents, and neutral Provider context readers. Its current implementation does not yet persist the newly agreed quoted earliest-work-start and estimated-work-finish dates and must be revised before MAINT-003 can compare quoted and actual timing.
- FILE-001 storage-neutral records and domain-owned target validation.
- AUDIT-001 same-transaction events, append-only audit triggers, and fail-closed presentation policies.
- LOCAL-002 encrypted backup/export/restore and exact current-schema validation.

The implemented schema has no work-journal table or work-journal FILE-001 target. Issue detail currently projects child collections together; MAINT-003 must not add an unbounded journal collection to that projection.

MAINT-003 directly depends on `AUDIT-001`, `FILE-001`, `MAINT-001`, and `MAINT-002`. FILE-001 is direct because MAINT-003 introduces completion-evidence targets and purposes rather than merely consuming an existing target.

## Scope

MAINT-003 provides:

- Immutable journal entries for work start, progress, blockage, completion, general notes, and explicit corrections.
- Required actual occurrence time plus a property-time-zone snapshot distinct from server recording time.
- Optional reference to a stable current or ended MAINT-002 assignment belonging to the same issue.
- Operator-reviewed completion classifications without changing issue, assignment, or appointment lifecycle.
- Optional completion photos, work reports, and supporting documents linked through FILE-001 after entry creation.
- Nonbranching append-only correction lineage rather than PATCH, archive, or deletion.
- Client-keyed idempotent creation, atomic audit events, exact schema/data validation, bounded reads, and encrypted backup/export/restore coverage.
- Maintenance-owned provider-history projections for later UI, reporting, and AI consumers without copying records into Providers.

MAINT-003 does not provide:

- Issue resolution/reopening, assignment ending/reassignment, or appointment completion as a side effect of a journal entry.
- Mutable journal rows, hidden edits, deletion, archival, or restoration of journal entries.
- Quote requests, provider selection, assignment, or quoted schedule changes.
- Prices, hourly rates, material amounts, invoice state, payment state, or actual spending.
- Provider ratings, automatic preferred/avoid changes, autonomous recommendations, or provider contact.
- A requirement that completion evidence exist before an entry can be recorded.
- React screens. `UI-001` owns journal entry, timeline, evidence, correction, and adjacent explicit lifecycle actions.

## Domain design

### Journal facts are append-only

Every journal entry is a durable statement recorded at a point in time. After insertion, the row cannot be updated or deleted. SQLite triggers reject both operations, and exact schema validation requires those triggers.

An error is corrected by appending a complete replacement entry with `corrects_entry_id` and a required correction explanation. One entry may be corrected at most once, preventing branching interpretations. The original remains visible in history; current summaries use the latest non-superseded fact in the correction chain.

FILE-001 associations remain independently correctable. Archiving an incorrect file link does not alter or remove its journal entry.

### Entry kinds describe observations, not lifecycle state

`entry_kind` is exactly one of:

- `work_started` — actual work began.
- `progress_update` — work advanced but no final outcome is asserted.
- `work_blocked` — work could not proceed or requires another action.
- `work_completed` — an outcome was reported or observed.
- `general_note` — work-related context that does not fit another kind.
- `correction` — a complete replacement for one prior entry.

These kinds do not start, resolve, reopen, or cancel the issue; end or replace an assignment; or complete an appointment. UI-001 may offer an explicit adjacent action, but each lifecycle operation remains separately confirmed and audited through its owning endpoint.

Appointment `outcome_note` means only that the scheduled visit occurred and records its appointment-specific result. Repair progress and completion are MAINT-003 facts.

### Source and operator verification remain explicit

`source_kind` is exactly one of:

- `operator_observation` — directly observed or established by the local operator.
- `provider_report` — reported by the assigned provider or provider representative.
- `other_report` — reported by another source and entered by the operator.

The local operator is the application actor for MVP entry creation even when the underlying information came from someone else. A `work_completed` entry separately records whether the outcome was operator-verified. A provider statement, attached photograph, or uploaded work report does not automatically constitute operator verification.

### Completion is an outcome fact, not automatic closure

A `work_completed` entry requires:

- `outcome_status`: `completed`, `partially_completed`, or `unsuccessful`;
- an outcome summary; and
- `follow_up_required`: strict boolean.

No star rating or numeric provider score is stored. Multiple attempts are legitimate: a partial or unsuccessful outcome may be followed by more work and another completion entry. Corrections supersede erroneous facts; later attempts do not supersede truthful earlier attempts.

Issue resolution, assignment ending, and appointment completion remain independent. A completed work entry may coexist with an open issue or current assignment until the operator deliberately completes those separate workflows.

### Actual and quoted schedule facts stay separate

MAINT-002 quotes may retain optional `earliest_work_start_on` and `estimated_work_finish_on` property-local dates as provider-supplied schedule facts. They are comparison inputs, not promises enforced by lifecycle automation.

MAINT-003 stores actual entry occurrence instants. For one assignment, projections may derive:

- actual first work start from the earliest effective assignment-linked `work_started` entry;
- actual completion from the earliest effective operator-verified `work_completed` entry whose outcome is `completed`;
- recorded assignment-to-start duration from `maintenance_assignments.assigned_at` to actual first work start; and
- quoted-versus-actual schedule context from the assignment's selected quote and effective journal entries.

`assigned_at` is the time the selection was recorded, not a provider-contact or dispatch timestamp. Derived duration must therefore be labeled “recorded assignment to work start,” never generic “response time.” Quoted start/finish dates, actual start/finish facts, and their provenance remain visible to future provider-selection logic.

### Journal narratives do not become accounting records

Entries may describe labor, materials, delays, replaced components, and work performed. They store no money. MAINT-001 retains internal estimates and work-reported monetary context; FIN-002 remains the sole source of confirmed paid expenses and refunds.

Issue-linked expenses may be shown beside an issue outcome. Even when an expense provider matches an assignment provider, MAINT-003 does not claim that the expense is an exact assignment cost because the existing expense link is issue-scoped. A future allocation design is required before exact per-assignment cost metrics are presented.

### Assignment context is optional and stable

An entry always references one retained issue. `assignment_id` is optional to support operator-managed, DIY, or otherwise unassigned work. When present, the assignment must belong to the same issue; both current and ended assignments are valid because entry recording may be delayed.

Provider identity and historical display context come from the referenced assignment. The journal request does not accept a separate provider Party ID or provider-name snapshot. Party or provider archival after assignment does not invalidate later historical entry recording.

An unassigned entry contributes to issue history but not provider-specific outcome history.

### Providers keeps manual history separate

`provider_work_history` remains a mutable, manually entered note about experience outside the application's issue/assignment workflow. MAINT-003 is authoritative for issue-backed work and outcomes. No journal event automatically creates, edits, archives, or restores a Providers-owned row.

Provider-facing UI, reporting, and AI consumers may combine two clearly labeled read sources:

- manually entered prior experience from Providers; and
- issue-backed work outcomes from a bounded Maintenance-owned projection filtered by assignment provider Party ID.

The Maintenance projection exposes source facts and derived schedule labels; it does not change provider preference or produce an opaque ranking.

### Completion evidence belongs to the journal entry

Files are linked only after the journal entry exists. Maintenance extends its FILE-001 validator with:

| Entity type | Allowed purposes | Active-link limit |
| --- | --- | ---: |
| `maintenance_work_journal_entry` | `completion_photo`, `work_report`, `supporting_document` | 20 |

Completion evidence is never stored as an MAINT-002 assignment document. Invoice, receipt, and proof-of-payment purposes remain FIN-002 expense evidence. The same immutable file record may have separate valid links when one document legitimately supports both workflows.

Evidence is optional. Upload or link failure leaves the truthful journal entry intact and retryable; MAINT-003 does not add draft/finalized entry states merely to coordinate file publication.

## Data model

All IDs and idempotency keys are UUIDs. Timestamps are aware UTC text. The property time zone is the issue property's stored canonical IANA zone at entry creation. Text is trimmed before persistence and is bounded as specified.

### `maintenance_work_journal_entries`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `issue_id` | Required retained Maintenance issue reference. |
| `assignment_id` | Optional MAINT-002 assignment reference; when present, it must belong to the same issue. |
| `entry_kind` | `work_started`, `progress_update`, `work_blocked`, `work_completed`, `general_note`, or `correction`. |
| `corrected_entry_kind` | Required only when `entry_kind = correction`; one of the five non-correction kinds. Otherwise null. |
| `source_kind` | `operator_observation`, `provider_report`, or `other_report`. |
| `occurred_at_utc` | Required aware UTC instant at which the described work fact occurred. It cannot be more than five minutes after the server's current time. |
| `occurred_timezone` | Required server-resolved issue-property IANA time-zone snapshot. |
| `summary` | Required operator-facing text, 1–240 characters. |
| `detail` | Optional sensitive narrative, maximum 4,000 characters. |
| `outcome_status` | Required when the effective substantive kind is `work_completed`; `completed`, `partially_completed`, or `unsuccessful`. Otherwise null. |
| `outcome_summary` | Required when the effective substantive kind is `work_completed`, 1–4,000 characters. Otherwise null. |
| `follow_up_required` | Required strict boolean when the effective substantive kind is `work_completed`. Otherwise null. |
| `operator_verified` | Required strict boolean when the effective substantive kind is `work_completed`. Otherwise null. |
| `corrects_entry_id` | Required only for `correction`; unique self-reference to an entry on the same issue. Otherwise null. |
| `correction_reason` | Required only for `correction`, 1–1,000 characters. Otherwise null. |
| `idempotency_key`, `request_fingerprint` | Required create-retry identity and canonical semantic fingerprint; key unique for journal creation. |
| `recorded_at_utc` | Required server-generated UTC timestamp. |

A correction carries the complete replacement fact: its source, occurrence instant, summary, optional detail, assignment reference, and completion fields are interpreted as the corrected version. `entry_kind = 'correction'` identifies lineage, while a separate `corrected_entry_kind` stores which substantive kind the replacement represents. `corrected_entry_kind` is required for corrections, uses the five non-correction kinds, and is null otherwise.

The effective substantive kind is `corrected_entry_kind` for a correction and `entry_kind` otherwise. All kind-specific database and application checks use that effective kind.

Database checks enforce allowed enums, completion-field pairing, correction-field pairing, non-self correction, bounded stored values, and journal immutability triggers. A unique `corrects_entry_id` prevents branching. Application and restore validation enforce same-issue assignment/correction relationships, property-zone validity, idempotency fingerprints, and audit continuity.

Indexes support `(issue_id, occurred_at_utc, recorded_at_utc, id)`, `(assignment_id, occurred_at_utc)`, and correction lookup. Provider history resolves provider Party IDs through assignment records in one bounded set-based query; provider identity is not duplicated in the journal table.

## Workflows and invariants

### Record a work entry

`POST /api/maintenance-issues/{issueId}/work-journal` validates the retained issue, optional same-issue assignment, source, actual occurrence instant, property time-zone snapshot, kind-specific fields, and idempotency in one immediate transaction. It inserts exactly one immutable entry and one audit event.

`sourceKind = provider_report` requires an assignment reference so the retained assignment identifies which provider supplied the report. Other unassigned work may use `operator_observation` or `other_report`; MAINT-003 does not accept an otherwise unanchored provider identity.

Entries on `open` or `in_progress` issues require no additional confirmation. Entries on `resolved` or `cancelled` issues require `historicalEntryConfirmed = true`. That confirmation is request policy and is not stored as mutable lifecycle state; the audit reason identifies historical entry creation.

The service does not require an active property, active space, active provider, current assignment, or nonterminal issue because the journal may record retained history. An assignment-linked occurrence may predate the server-recorded `assigned_at` when the operator is backfilling truthful history; in that case projections expose both facts but omit assignment-to-start duration rather than return a negative or misleading metric.

### Correct an entry

The same create endpoint records a correction by supplying `entryKind = correction`, `correctsEntryId`, `correctedEntryKind`, and `correctionReason` with the complete corrected semantic payload. The target must belong to the same issue and must not already have a direct correction.

Same-key/same-payload retry returns the same entry. Same-key/different-payload reuse, cross-issue correction, correction branching, and self-correction return typed conflicts.

### Attach completion evidence

After creation, the existing FILE-001 upload/link operation accepts `entityType = maintenance_work_journal_entry`, the entry ID, and an allowed purpose. Maintenance validates the retained target and the 20-active-link limit in FILE-001's transaction. `completion_photo` requires an effective `work_completed` entry; `work_report` and `supporting_document` may support any effective substantive kind. Incorrect associations are archived through FILE-001 with confirmation and reason.

### View issue journal

`GET /api/maintenance-issues/{issueId}/work-journal` returns a stable cursor-paginated chronological or reverse-chronological timeline. It includes original and correction entries with explicit lineage and an effective/superseded indicator. Default page size is 50, maximum 100.

Issue detail returns only:

- the latest ten journal entries;
- total retained entry count;
- effective work-start and completion summaries when derivable; and
- active completion-evidence count.

It does not load the complete journal or full file metadata for entries outside the preview.

### View provider issue-backed history

`GET /api/maintenance-work-journal?providerPartyId={partyId}` returns a bounded cursor-paginated Maintenance projection of entries connected through assignments for that provider. It includes issue/property labels, assignment and quote schedule context, effective outcome fields, and clearly labeled derived timing. It excludes unassigned entries and does not return Providers-owned manual work-history rows.

This endpoint is a consumer-neutral source projection. Provider screens may compose it with Providers APIs without either module copying the other's rows or importing its persistence models.

## API contract

All routes require a ready workspace; mutations require the writer lock. Request models reject unknown fields and use typed UUIDs, strict booleans, aware instants, and bounded strings. Application commands repeat essential validation for direct callers.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/maintenance-issues/{issueId}/work-journal` | Record an immutable entry or append-only correction. |
| `GET` | `/api/maintenance-issues/{issueId}/work-journal` | Page through complete issue journal history. |
| `GET` | `/api/maintenance-work-journal` | Page through issue-backed work history filtered by provider Party ID. |
| `GET` | `/api/maintenance-issues/{issueId}` | Include bounded journal preview and derived counts/summaries. |

There is no PATCH, archive, restore, or delete endpoint for a journal entry.

Malformed requests return `422`; missing issues, assignments, or correction targets return controlled `404`; invalid text, occurrence time, kind-specific fields, or terminal-issue confirmation return `400`; changed idempotency, assignment mismatch, correction mismatch/branching, and concurrent conflicts return typed `409` responses.

## Read behavior and performance

Journal queries use stable keyset cursors over `occurred_at_utc`, `recorded_at_utc`, and `id`. Page size defaults to 50 and is bounded at 100. Effective correction status is resolved set-wise for the page and relevant lineage, not with one query per entry.

Issue list does not load journal rows. It may later add explicitly designed filters, but MAINT-003 does not silently expand the existing list query. Issue detail uses one bounded journal-preview query and grouped counts. FILE-001 metadata is loaded only for preview or journal-page entry IDs.

Provider history uses one Maintenance query joining assignments and issue context for a bounded page. It must not query Providers once per row. Quoted schedule context comes from the assignment's referenced quote within Maintenance. Current Party/provider state is not required to explain retained work history.

## Audit, privacy, schema, and portability

The audit entity type is `maintenance_work_journal_entry`. Entry creation and its audit event commit in one immediate transaction. Because correction is a new entry, it creates its own audit event and never writes an update event against the original journal row.

General activity may show issue ID, entry kind or corrected substantive kind, assignment/provider display snapshot when available, occurrence time, outcome classification, verification flag, and follow-up-required flag. It redacts detail, outcome narrative, correction reason, and evidence descriptions. Contextual Maintenance history may show the complete authorized record.

The current greenfield baseline, SQLAlchemy model, product table allowlist, exact schema validator, immutable journal triggers, retained-data validator, audit-policy registry, FILE-001 target validator, and encrypted backup/export/restore validation must include the new table and links.

Restore validation rejects:

- missing issue, assignment, correction, file-link, or audit relationships;
- assignment or correction references crossing issue boundaries;
- branching or self-referential correction lineage;
- invalid enums, kind-specific nullability, text bounds, UUIDs, timestamps, zones, or fingerprints;
- missing or incompatible update/delete triggers;
- missing, duplicate, or mismatched creation audit evidence; and
- invalid work-journal FILE-001 purposes or active-link counts.

Restore does not re-evaluate current issue, property, provider, or assignment availability because retained journal history remains valid after lifecycle changes.

## Application structure

Add a focused `WorkJournalService` inside the Maintenance module. It owns journal commands, policy, response shaping, and transaction orchestration while reusing Maintenance's immediate SQLite transaction and module-owned readers. Do not further enlarge the existing general `MaintenanceService`, create a generic workflow framework, or move journal rules into Files, Providers, or platform code.

The persistence adapter may share the Maintenance unit-of-work implementation where that preserves one transaction and query budgets, but the application protocol should expose journal-specific operations rather than untyped generic row access.

## UI-001 workflow

UI-001 must provide:

- an append-only issue timeline with source and operator-verification labels;
- assignment/provider and quoted schedule context when present;
- actual occurrence time displayed in the stored property-time-zone snapshot;
- entry creation with terminal-issue confirmation when required;
- completion outcome and follow-up fields;
- evidence upload/link after entry creation;
- explicit original/correction presentation and effective-value labeling; and
- separate, deliberate controls for issue resolution/reopening, assignment ending/reassignment, and appointment completion.

The UI must never imply that uploading completion evidence resolved the issue, paid an expense, ended an assignment, or rated a provider automatically.

## Implementation outline

1. Apply the authoritative decisions in this design without introducing mutable journal state or copied Provider/Finance data.
2. Add the immutable journal model, constraints, indexes, triggers, exact schema validation, and retained-data validation to the current greenfield baseline.
3. Add typed journal commands, `WorkJournalService`, application protocol operations, SQLite persistence, idempotency, audit policy, and typed routes.
4. Extend Maintenance's FILE-001 validator with the work-journal target, purposes, and limit.
5. Add bounded issue preview, paginated issue journal, and provider-filtered Maintenance projections with explicit query budgets.
6. Update product table allowlists, backup/export/restore verification, and audit-policy registration. Add no compatibility tables or dual-read/write paths.
7. Add regression coverage for enums, occurrence times, source/verification semantics, terminal history confirmation, assignment matching, multiple attempts, immutable triggers, correction lineage, idempotency, lifecycle independence, evidence, privacy, exact-schema rejection, query budgets, concurrency, and encrypted backup/restore.
8. Deliver the operator workflow through the existing `UI-001` scope.

## Backend acceptance criteria

MAINT-003 backend/API scope is complete when:

1. The operator can append actual work start, progress, blocked, completion, note, and correction facts to a retained issue.
2. Entries are immutable at the database and API boundaries; corrections are append-only, nonbranching, and retain the original.
3. Optional assignments are same-issue stable references and support current, ended, archived-provider, and unassigned work history without copied provider identity.
4. Completion outcomes distinguish source, operator verification, result, and follow-up need without changing issue, assignment, or appointment lifecycle.
5. Journal narratives contain no money; quotes, cost context, and actual expenses remain in their owning records.
6. Completion evidence links to journal entries through FILE-001 and remains optional, portable, and independently correctable.
7. Issue detail remains bounded, complete history is cursor-paginated, and provider history is a bounded Maintenance-owned projection with no N+1 behavior.
8. Quoted schedule dates and actual effective work timing remain distinct and can be compared without overstating recorded assignment time as provider response time.
9. Audit presentation protects sensitive narratives, and exact validation plus encrypted backup/restore preserve rows, corrections, links, triggers, audit events, and stable IDs.
10. Providers' manual prior-work notes remain distinct from issue-backed outcomes and are never synchronized by duplicated writes.

The overall operator workflow remains pending until `UI-001` supplies the journal timeline, evidence, correction, and explicit adjacent lifecycle actions.

## Contradictions and design decisions

### 1. Completion evidence lacked a direct FILE-001 dependency

Decision: add `FILE-001` directly to MAINT-003 because the feature introduces its own file target, purposes, limits, validation, and restore rules.

### 2. Providers and Maintenance both appeared to own historical outcomes

Decision: Providers owns manually entered experience outside the issue workflow; Maintenance owns all issue/assignment-backed journal and outcome facts. Provider-facing views compose labeled projections and never duplicate rows.

### 3. Mutable provider history cannot serve as an append-only journal

Decision: retain the existing mutable/audited Providers notes for manual prior experience, but never use them as a substitute for immutable MAINT-003 facts or silently mix their semantics in AI inputs.

### 4. Appointment completion could be mistaken for repair completion

Decision: appointment completion records only the visit lifecycle. Work completion is an explicit MAINT-003 entry and has no automatic appointment effect.

### 5. Labor/material journal narrative could duplicate cost records

Decision: journal entries may describe labor and materials but store no money. MAINT-001 and FIN-002 remain the monetary sources.

### 6. Repair reporting omitted the journal dependency

Decision: add MAINT-003 to RPT-001 so completion and work-history reporting has its authoritative source.

### 7. Provider selection needs quoted and actual schedule context

Decision: MAINT-002 quotes add optional paired property-local `earliest_work_start_on` and `estimated_work_finish_on` dates. MAINT-003 records actual occurrence instants and derives carefully labeled assignment-to-start and quoted-versus-actual context. Exact assignment cost remains out of scope without allocation.

### 8. An unbounded journal would violate read budgets

Decision: issue detail uses a ten-entry preview and grouped counts; complete issue/provider history uses stable cursor pagination with bounded FILE-001 projections.

## Dependencies and follow-on work

MAINT-003 requires completed `AUDIT-001`, `FILE-001`, `MAINT-001`, and `MAINT-002`. It uses MAINT-002 assignment/provider snapshots and quote schedule facts without directly depending on current Provider eligibility.

Follow-on ownership remains:

- `UI-001` — journal timeline, completion entry, evidence, correction, and separate lifecycle actions.
- `RPT-001` — repair reporting and source-record drill-down using journal outcomes without treating narratives as finance facts.
- `ISSUE-AI-004` and `AI-REC-002` — explainable advisory use of clearly sourced manual history, issue-backed outcomes, quoted/actual schedule context, and financial context; never automatic provider contact or assignment.
- `FIN-002` — confirmed spending and refunds; a later allocation design is required for exact assignment cost.
- `VEND-CAT-001` — provider categories and explicit issue-category mapping.
