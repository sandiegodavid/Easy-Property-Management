# UI-001 implementation slices

Status: backend readiness in progress — October 9, 2026. Slices 41–43 below remain planned; UI-001 is not complete.

Scope alignment — October 9, 2026: INGEST-002 issue-proposal review and its
feature-specific AI approval modes, Intake attention consequences, coordinated
Maintenance writes and OPS recovery registration belong to UI-002. The former
planned Slice 40 is tracked in [UI-002's preliminary design](UI-002_DESIGN_preliminary.md#ingest-002--issue-review-readiness-and-recovery-former-slice-40).
None of that work gates UI-001. Delivered generic AI-governance and local-operator
Intake contracts remain in this matrix; their delivery does not enable INGEST-002.
No React implementation is enabled before the backend readiness gate.

## Slice 1: Typed built-in AI configuration and review contracts

1. Contracts/ports: explicit response models for Settings, connection configuration and
   tests, registered actions/adapters, action limits, redaction profiles, draft pages,
   evidence detail, review history, and review commands. Existing application read ports
   are reused. Payload/confidence JSON remains action-schema-owned rather than inventing
   a parallel universal domain payload.
2. Implementation: all JSON AI routes declare a response model and stable operation ID.
   Execution location and draft-state filters use enumerated API values. Configuration
   exposes runtime/artifact facts needed for truthful on-device setup.
3. Persistence: draft detail selects immutable provenance from its existing Run join;
   no new table, connection, lookup, transaction, or compatibility migration. Provider
   request identifiers and credential values are not exposed in these projections.
4. Tests: real SQLite-backed HTTP tests validate settings replay, configuration,
   profiles/limits, draft edit/dismiss/approve, current-source facts, and frozen provenance.
5. Integration: production OpenAPI discovery is deterministic and must not open or
   initialize a workspace or start its runtime.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | Settings/configuration/profile/limit and draft review HTTP responses validate against named models |
| Invalid combinations | Unknown execution location/state, non-boolean settings, and secret-bearing extra response fields are rejected |
| Idempotency/retry | Identical settings-command retry returns its original timestamp and result |
| Transaction rollback | Existing AI-governance focused tests cover failed approval/audit writes; this slice does not change transaction ownership |
| Persistence/schema | Existing current-format AI-governance validation tests remain required; this slice changes only projections, not schema |
| Backup/restore | Existing AI-governance encrypted round-trip tests remain required; no additional persisted fields |
| Query budget | Draft detail remains two bounded governance SELECTs; frozen provenance is returned by the existing joined SELECT |
| Privacy | Governed input excludes dropped fields; connection responses expose credential presence, not secrets |
| Integration | Production OpenAPI is reproducible without workspace initialization/open or runtime startup |

## Slice 2: Bounded property recognition and shared-snapshot sources

1. Contracts/ports: source-owned property directory, narrow Party identity and Lease
   participant relations, and a Finance summary reader accepting the caller's connection.
   The existing bounded Task preview contract is reused. OPS exposes typed property cards
   with enumerated filters, accurate totals, capped previews, query echo and temporal metadata.
2. Implementation: `GET /api/operator/properties` selects membership and count in SQL,
   applies the stable database-derived Unicode sort key and cursor, and hydrates only
   selected IDs. Effective owner and tenant recognition uses each property's local date.
   Continuations freeze the instant and reject changes in filters, runtime, audit marker,
   or property-local calendar, and expire after 15 minutes.
3. Persistence: no schema changes or new transactions. Related previews use windowed
   set-based queries. Finance supports SQL relation scopes above the public 100-ID bound
   without expanding them into Python ID lists. OPS composes Finance and Task readers on
   its existing connection; Slice 3 adds property/owner overviews.
4. Tests: actual SQLite source reads cover Unicode no-gap paging, membership filters,
   ownership and tenant-date boundaries, exact totals, bounded previews, one-versus-100
   query budgets and concurrent writes. Shared Finance/Task reads use the caller's
   connection and instant. Finance results match FIN-003 and see transaction-visible state.
5. Integration: bootstrap injects all source readers explicitly and advertises only the
   implemented directory capabilities. Coverage is explicitly unavailable; an empty
   source list does not imply reviewed or complete coverage.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | Typed property directory and actual source-owned Finance/Task projections |
| Invalid combinations | Enumerated filters, malformed/expired/mismatched cursors, unavailable workspace, invalid clock |
| Idempotency/retry | Real COM command receipt reconciles an interrupted response without redispatch; changed payload does not reconcile |
| Transaction rollback | Failed OPS reconciliation audit rolls back recovery and operation together while preserving the separately committed COM command |
| Persistence/schema | No persisted fields added; existing OPS/FIN/TASK validators remain unchanged |
| Backup/restore | Existing focused OPS and FIN encrypted round-trip tests; this slice adds no retained fields |
| Query budget | Directory ceiling 30 SELECTs at 1/100 items; at most 3 recognition previews; FIN relation scope above 100 properties; no nested source connections |
| Snapshot consistency | Concurrent write between marker and source projection does not change the result; new read sees the committed change |
| Command safety | Task creation was gated here; slice 7 supplies its durable contract. Receipt mismatch and audit rollback cannot manufacture committed outcomes |

## Slice 3: Owner recognition and property/owner context overviews

1. Contracts/ports: Portfolio-owned owner membership and context reader; source-owned
   Lease, Task, Maintenance, Communication and owner-concern summary readers. SQL metadata
   relations preserve domain ownership without expanding large scopes into Python IDs.
   Typed owner cards and discriminated overview sections expose counts, provenance,
   section continuations and View all targets, never unrestricted URLs.
2. Implementation: owner selection, archive/property-state filters and literal Unicode
   name/address matching execute before cursor/limit selection. Current relationships
   use each property's local date and end-exclusive intervals; former/all history and
   archived Parties are explicit options. Historical owner detail remains accessible.
   Each overview executes under one deferred snapshot and captured instant. Collections
   default to 10/max 50; directories default to 50/max 100 with three-property previews.
3. Persistence: source readers perform count and bounded selection on the caller's
   connection. They do not load narrative bodies, Task notes, or private descriptions.
   Communications are deduplicated across links; rent-record and renewal references stay
   source-owned. Communication follow-up Tasks remain discoverable. No schema changes,
   nested transactions or additional persisted state are introduced.
4. Tests: actual source graphs verify membership, local midnight, Unicode paging, large
   owner scopes, independent failure, snapshot consistency, metadata privacy, typed HTTP
   responses and encrypted restore. Counts stay within the existing 30-statement directory
   and 50-statement overview ceilings as page size grows.
5. Integration: bootstrap explicitly injects all readers and advertises owner-directory
   and context-overview capabilities. Missing money periods are explicitly unavailable;
   selected-period money is whole-property FIN-003 activity, not owner entitlement.
   Coverage remains explicitly unavailable until the coverage source is implemented.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | Actual owner/property/lease/issue/communication/concern/waiting-Task graphs and explicit-period Finance summaries |
| Invalid combinations | Invalid filters, bounds, subjects, periods and section continuations; not-ready reads never open the database |
| Retry/continuation | Stable Unicode pages without gaps; section/filter/period/subject-bound cursors; expiry, date-boundary and restored-epoch rejection |
| Transaction/consistency | Concurrent ownership write cannot alter later sections or money scope within the original snapshot; no mutable commands added |
| Persistence/schema | Populated fixtures pass full current-schema validation; no new stored fields or migration |
| Backup/restore | Encrypted archive preserves identities, section records/counts and source money; old cursors fail after restore |
| Query/size budgets | 1 versus 100 distinct owner cards has constant query count; 1 versus 50 nested items has constant query count; owner money scope exceeds 100 properties without truncation |
| Partial failure | Known section storage failure preserves successful sections; membership failure fails the collection; programming errors are not hidden |
| Privacy/provenance | No communication bodies, issue/concern descriptions or Task notes; every successful section carries shared asOf and source revision |

## Slice 4: Registered grouped metadata search

1. Contracts/ports: a neutral bounded metadata-search reader, explicitly registered at
   bootstrap for properties, spaces, related client owners, tenants, leases, recorded
   communications, maintenance issues and Tasks. Source adapters own their queries;
   OPS never queries foreign tables or performs per-result service calls. Additional
   provider/legal/HOA/Intake/AI sources remain unregistered.
2. Implementation: `GET /api/operator/search` returns typed groups with full matching
   counts, bounded slices, availability, shared temporal provenance and internal identity
   targets. Groups default to 10/max 50 hits. A group continuation requests that group
   alone and binds normalized query, archive option, bounds, source marker, local calendar,
   runtime identity and captured instant. Query echo preserves the submitted text and
   separately exposes its normalized form. Matching is literal Unicode NFKC/casefold
   substring matching (`instr`), so SQL wildcard characters have no special meaning.
3. Persistence: count predicates are identical to selection predicates before cursors;
   SQL applies ordering and LIMIT before results reach Python. Each simple source uses
   two SELECTs, owner recognition at most three, plus two shared marker/calendar SELECTs.
   SQLite plans reuse ownership lookup indexes; literal substring matching and normalized
   ordering may scan/sort within SQLite, never hydrate an unbounded Python collection.
   No tables, indexes, mutable records, independent sessions or transactions are added.
4. Tests: real source graphs cover all eight groups, narrow-column/privacy checks, Unicode
   pagination, exact totals, explicit archived history, hidden destinations, independent
   source failure, one-snapshot reads, fixed per-group/page-size budgets and encrypted
   restore. Search excludes communication bodies, issue descriptions, Task notes, tenant
   notes/contact details, financial evidence and raw Intake/recovery/AI payloads.
5. Integration: bootstrap advertises metadata-search capability and injects the registry
   and service explicitly. OpenAPI declares named response models and a stable operation
   ID. Failed groups have null counts/results, never successful-looking empty arrays.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | Actual registered source identities, labels, context and typed targets across all eight groups |
| Invalid combinations | Two-non-whitespace-character minimum, 240-character maximum, unknown group/fields, invalid limits, malformed cursor, readiness guard |
| Retry/continuation | Unicode no-gap/no-duplicate pages; independent group cursors; changed query/archive/bounds/group/runtime, expiry and source-write conflicts |
| Transaction/consistency | Concurrent ownership mutation between groups cannot change later counts in the original snapshot; all sources use one connection and reads do not write |
| Persistence/schema | Real populated sources pass current-schema validation; registry rejects duplicate registrations; no persisted changes |
| Backup/restore | Encrypted round trip preserves result identities, metadata and counts; restored runtime rejects old search cursors |
| Query/size budgets | At most four SELECTs per registered type plus two shared; 1 versus 50 hits keeps constant cost; populated 100-owner/property fixture, SQL LIMIT and indexed ownership plans |
| Partial failure | Known source failure marks only that group unavailable; programming defects propagate rather than being hidden |
| Privacy | Excluded fields neither matched nor selected; hidden destinations remain searchable; archived records require explicit inclusion |

## Slice 5: Area-specific coverage and durable reviews

Delivered October 8, 2026: contracts/ports, source-owned implementations,
current-baseline persistence, focused tests, and runtime/validation/backup integration.

- `GET /api/operator/coverage/{kind}/{subjectId}/{area}` provides typed occupancy,
  lease, rent, deposit (Space), and maintenance (Property) coverage. Source failures
  are unavailable, not fabricated Missing or Recorded results. Reads share one
  connection, snapshot, and captured UTC instant; dates use the source property's zone.
- Portfolio, Leasing, Finance, and Maintenance own their bounded source facts.
  Audit supplies scoped entity-relation markers. Evidence revisions omit unrelated
  preferences, OPS review events, and unrelated maintenance changes to rent context.
- `POST .../reviews` requires the expected evidence revision, basis, reason,
  optional future property-local review date, and UUID idempotency key. One immediate
  transaction validates source facts, appends the decision/replay result, and audits it.
  Identical retries replay before evidence checks; changed keys/payloads conflict.
- The latest greenfield baseline adds `operator_coverage_reviews` with exact schema
  validation and append-only UPDATE/DELETE triggers. The decision itself retains
  its operation identity and complete replay result indefinitely; no separate mutable
  source-fact cache is persisted. Correlated audit binds the immutable response but
  omits the free-form reason. `GET /api/operator/coverage/operations/{key}` retrieves
  the durable result without reinterpreting newer facts.
- Current-schema/workspace-open/archive/restore validation checks canonical requests,
  fingerprints, identifiers, UTC/property-local dates, result identities, owning
  target existence, and complete correlated review evidence. Encrypted backup and
  restore preserve review rows, operation responses, and audit history exactly.
- Normal acknowledgment cannot fill unknown status, create a lease/account, or
  synchronize rent. No-deposit terms may justify non-applicability; existing tracking
  context and ended-lease deposits remain visible. No issues is not proof of no
  maintenance problems: an explicit property review is required.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | Real property/space, executed lease/rent source facts, deposit setup, explicit maintenance acknowledgment, typed API and OpenAPI |
| Invalid combinations | Wrong area/subject, unknown target, unsupported non-applicability, past/local-date review deadlines, unknown API fields |
| Idempotency/retry | Same-key concurrent review commits one row/event; replay after source/date changes and encrypted restore; changed payload and stale evidence return 409 |
| Rollback | Audit failure leaves no review row; actual Portfolio evidence mutation before review rejects stale acknowledgment without a write |
| Persistence/schema | Exact table/check/index/trigger inventory; immutable history; rewritten fingerprint, reason or correlation rejected during workspace open and backup |
| Backup/restore | Compare every review field and correlated audit before/after encrypted LOCAL-002 round trip; original operation still replays |
| Query/size budgets | Per-subject area read capped at eight SELECTs; one connection; no read-side writes or full source-history hydration |
| Time/source triggers | Property-local midnight, selected next-review date, effective availability transition, source changes versus unrelated OPS writes |

Coverage is reusable through the application service and transaction port. Slice 6
integrates bounded batches into directories and overviews without per-subject reads.
No Home urgency or DASH-001 queue policy is implemented here.

## Slice 6: Batched directory and overview coverage

Delivered October 8, 2026: source-owned batch contracts, implementations, typed
read responses, focused integration tests, and existing bootstrap composition.
No new persisted state or write workflow is introduced.

- Property and owner cards expose a `coverage` preview: at most five area results,
  exact `matchingTotal`, explicit `hasMore`, availability, captured `asOf`, global
  cursor provenance, and a scoped View all target. This is not a whole-property
  or whole-owner completeness claim based on a truncated recognition preview.
- The overview `coverage` section is independently paginated (1–50 entries),
  counting maintenance per property and occupancy/lease/rent/deposit per space.
  Portfolio applies scope, history visibility, stable Unicode ordering, count,
  cursor and limits before hydration. Owner scopes use effective ownership
  relations, not the directory's three-property recognition preview.
- Portfolio locations, relevant lease/term facts, financial aggregates, scoped
  audit markers, Maintenance evidence and latest OPS decisions are batch-loaded
  on the caller's connection. Fact batches permit at most 500 distinct subjects;
  empty batches issue no SQL. Single and batch paths share derivation rules.
- All results use the enclosing read transaction and instant. Area evidence
  revisions, property-local dates, last review, triggers and resolution targets
  match standalone reads. Known coverage failures affect only coverage; absent
  source configuration is unavailable, while an empty valid scope is available
  with an exact zero count. Unexpected programming failures propagate.
- Existing current-schema and encrypted portability proofs remain applicable:
  the integration derives coverage from retained source facts and review history,
  without adding tables or storing duplicate coverage state.

### Slice 6 validation matrix

| Area | Focused proof |
| --- | --- |
| Happy paths | Typed property/owner previews and full overview coverage; populated lease/rent/deposit and Maintenance facts match standalone reads |
| Invalid combinations | Existing cursor scope/expiry guards; batch over-limit rejection before SQL; unavailable collections cannot fabricate counts, items or provenance |
| Retry/continuation | Unicode multi-page traversal has no gaps/duplicates and stable totals; review acknowledgment is reflected by the next composition |
| Transaction/rollback | One deferred connection, one instant, no read writes; concurrent ownership writes cannot alter later coverage in the same snapshot; existing review rollback proof retained |
| Persistence/schema | No schema changes; existing source and append-only decision validation remains in force |
| Backup/restore | Existing encrypted source/review round-trip and replay proofs rerun with the shared batch derivation |
| Query/size budgets | 1 versus 100 property cards keeps constant query cost within 30 statements; 101-property owner scope hydrates at most five preview/50 page entries; populated whole overview including money stays within 50 statements |
| Partial availability | Source failures leave directory membership and other overview sections intact; empty current/former scopes are distinguished from unavailable coverage |

## Slice 7: Recoverable Task creation

Delivered in order: contracts/ports, implementation, current-baseline persistence,
focused tests, then bootstrap/OPS/schema/backup integration.

- `POST /api/tasks` requires exact integer `expectedRevision: 0` and UUID
  `idempotencyKey`; its typed result requires revision and `operationId`.
  `GET /api/tasks/creation-operations/{key}` returns the original response.
  Both routes declare stable OpenAPI operation IDs.
- `TaskService.create_command` owns recoverable creation. Existing `create` and
  `new_task` are non-recoverable internal creation paths, not OPS commands.
- `creation_fingerprint(TaskCreateCommand, 0)` hashes the canonical command,
  including defaults and revision zero, excluding generated IDs, time and key.
  The incomplete recovery form's fingerprint is not this command identity.
- One immediate transaction writes the Task, append-only
  `task_creation_operations` receipt and two correlated audit events. Replay
  precedes insertion and returns the original full response after later Task
  changes; changed same-key payload returns 409.
- OPS resolves `TaskCreationReceiptReader` through its existing connection,
  without creating a Task or redispatching the command.

| Validation area | Focused proof |
| --- | --- |
| Happy paths / contracts | SQLite creation, required API identity, typed response/receipt, stable OpenAPI IDs |
| Invalid combinations | Nonzero/boolean/malformed revisions, missing key/revision, changed same-key payload |
| Idempotency / retry | Concurrent duplicate creates one Task; complete initial response replays after completion; OPS resolves lost response without redispatch |
| Rollback | Receipt or audit failure leaves no Task or receipt; subsequent retry succeeds |
| Persistence/schema | Exact table and append-only triggers; canonical request/fingerprint/result, correlated audits; rewritten/deleted receipts rejected |
| Backup/restore | Encrypted LOCAL-002 round trip preserves the complete receipt and replay; full current-schema validation after restore |
| Query budgets | Narrow receipt projection uses at most one SELECT on caller's connection |

## Slice 8: Recoverable Task lifecycle and reminders

Contracts/ports → application implementation → current-baseline persistence →
focused tests → bootstrap, workspace validation and encrypted restore integration.

- Start, complete, cancel, reopen, add reminder, acknowledge and dismiss require
  exact positive integer `expectedRevision` and UUID `idempotencyKey`. Reminder
  commands use the parent Task revision, shared with TASK-002 waiting changes.
- `TaskMutationService` checks immutable replay before current lifecycle/revision
  validation. Changed reuse and stale revisions return typed 409; stale responses
  include `currentRevision`. Missing Tasks/reminders/receipts return 404.
- One immediate transaction writes the Task (exactly one revision increment),
  reminder changes, correlated audits and an append-only `task_mutation_operations`
  receipt. Terminal transitions clear waiting and dismiss pending reminders in
  that transaction. Receipts retain the complete original Task/reminder response,
  captured time and operation ID, never a projection of later state.
- All seven HTTP commands declare typed request/response models and stable
  operation IDs. `GET /api/tasks/mutation-operations/{key}` supplies durable
  source-owned lookup. No new OPS forms are registered: automatic browser attempt
  recovery still requires explicit form/receipt composition.
- Internal legacy Task lifecycle/reminder helpers remain non-recoverable owning
  workflow/test utilities, not the consequential HTTP command boundary.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | All seven commands, required HTTP identity, typed result and receipt |
| Invalid combinations | Boolean/nonpositive revisions, unknown/missing reminders, terminal reminder changes, changed payload and stale revision |
| Retry | Concurrent same-key mutation advances once; original full response replays after subsequent transitions |
| Rollback | Failed operation audit restores Task, pending reminders and receipt together |
| Persistence | Exact current table/check/index/trigger inventory, canonical requests/fingerprints, audited response reconstruction, immutable receipts and tampering rejection |
| Backup/restore | Encrypted LOCAL-002 round trip preserves receipt equality and original response replay |
| Query budget | Terminal command SELECT ceiling stays constant for 1 versus 50 reminders; necessary reminder updates remain per reminder |
| Cross-command consistency | Waiting, lifecycle and reminders share the same parent revision |

## Slice 9: Recoverable Task editing and deletion

Contracts/ports → pure edit normalization → current-baseline tombstone/receipt
constraints → focused SQLite/API tests → source-read and encrypted restore integration.

- PATCH and DELETE require the shared Task revision and UUID key. Effective edits
  increment once; unchanged normalized edits retain revision/timestamp and write
  only the durable no-op receipt and its audit. Omission differs from explicit null.
- Deletion requires exact confirmation, an open Task and no non-dismissed reminder.
  A retained tombstone preserves historical references, audits and receipts while
  ordinary detail/list/summary/search and related previews hide it. Waiting clears
  atomically; no physical record deletion compromises original response replay.
- Confirmation is also mandatory for complete/cancel/reopen/acknowledge/dismiss.
  Typed response models, stable operation IDs and source receipt lookup are shared
  with slice 8. No new OPS forms or consequential browser controls are enabled.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | Partial edit normalization, waiting preservation, explicit null, deletion and strict confirmations |
| Invalid combinations | Unknown/duplicate fields, merged relation/due pairs, terminal edits, pending/acknowledged reminder deletion guards |
| Retry | Original full responses after subsequent changes/deletion; unchanged edit receipts share a revision without effective-change events |
| Rollback | Failed operation audit restores the original Task and leaves no receipt |
| Persistence | Partial effective-revision uniqueness, tombstone constraints and audited receipt reconstruction |
| Backup/restore | Encrypted mutation-history round trip includes complete and delete cases |
| Source/query behavior | Normal source search and related previews exclude tombstones; historical direct context retains identity without extra lookup |

## Slice 10: Recoverable Communications commands

Source-owned contracts now cover draft/direct-recorded creation, draft patch,
recording and reasoned correction. Every application/HTTP command requires its
revision and UUID key; create uses zero. Effective changes advance once, including
child-only edits. No-op patches preserve timestamp/revision and retain an explicit
receipt. Replay precedes live lifecycle, references and revision checks.

Existing operation rows retain canonical requests, fingerprints and complete typed
original responses. Receipt lookup is distinct from fresh detail. Exact baseline
validation protects UPDATE, DELETE and INSERT OR REPLACE and reconstructs revision,
correction, child and audit history. Production OPS recovery uses the public owning
fingerprint and immutable source receipt, not a fresh communication projection.

| Validation area | Focused proof |
| --- | --- |
| Happy/invalid paths | All four commands; required metadata, typed results/conflicts and stable OpenAPI identities |
| Retry | Original full response after later correction/reference/Task changes; no-op receipt; changed reuse and stale revision |
| Rollback | Failure after follow-up insertion rolls back communication, Task, receipt and audits together |
| Schema/portability | Immutable trigger and canonical history validation; encrypted original-response replay after restore |
| Query budget | Replay and operation lookup each use one indexed SELECT with no detail hydration |

Full owning test matrix: [COM-001 command readiness](COM-001_COMMAND_READINESS.md).

## Slice 11: Shared Maintenance issue command revision

The approved MAINT-001 amendment makes the issue the command-concurrency aggregate
for its lifecycle and child workflows. All included commands require UUID keys and
expected revisions; create uses zero. One immediate transaction records the complete
original resource result, correlated domain effects and an immutable command receipt.
Effective commands advance the issue once even when several child records change;
no-op edits retain its revision. Caller-owned transactions are reused without nesting.

The current baseline adds `maintenance_command_receipts` with effective-revision
uniqueness and append-only protection. Typed result/conflict and receipt contracts
distinguish historical command outcomes from fresh issue detail. OPS creation recovery
resolves the receipt operation identity to the correct issue identity.

| Validation area | Focused proof |
| --- | --- |
| Happy/invalid paths | Issue/reporter/lifecycle, appointment, cost, expense link, quote, assignment, follow-up and journal commands; required metadata and stale/payload conflicts |
| Retry | Creation/child/lifecycle original snapshots after later changes; no-op receipt; follow-up replay after Task tombstone |
| Rollback | Real caller-owned Finance/Task/Maintenance writes fail atomically; receipt/audit failure leaves no partial effect |
| Schema/portability | Revision-chain and correlated audit reconstruction, immutable receipts, tampering rejection and encrypted original-response restore |
| Query/source behavior | Existing bounded projections remain; public source fingerprint and receipt preserve recoverable issue creation |

Full owning test matrix: [MAINT-001 command readiness](MAINT-001_COMMAND_READINESS.md).

## Slice 12: Portfolio manual-status receipts and conflicts

Manual occupancy, correction, cancellation, replacement/rescheduling, availability
and classification reuse the existing revision/operation contract. Mutation results
require committed operation ID/revision. Operation-ID and space/key lookups return
the original typed snapshot; changed reuse, stale revision and lifecycle conflicts
are distinct typed 409 outcomes with the complete current status read model.

Persistence rejects receipt replacement/deletion and permits only the existing
one-time atomic lease consumer-result attachment. Manual receipt checks do not
pretend to close Property/Space lifecycle or Lease draft/negotiation command gates.

| Validation area | Focused proof |
| --- | --- |
| Happy/invalid paths | Typed mutation and both receipt reads; missing/cross-space/source-owned lookup rejection; detailed conflicts |
| Retry | Original committed timestamps/status after later mutation/archival; no read-side rewrite |
| Rollback | Domain effects and receipts roll back on audit failure |
| Schema/portability | Exact conditional triggers, canonical revision/audit history and encrypted receipt/replay restore |
| Query/integration | Indexed operation lookup; atomic lease result attachment remains legal, while later rewrites are rejected |

Full owning test matrix: [PORT-003 command readiness](PORT-003_COMMAND_READINESS.md).
These slices deliver backend contracts only, not consequential browser controls or
new OPS recovery-form registrations.

### Slices 9–12 integration validation

Validated October 8, 2026 against the shared current baseline: **490 focused tests
and 138 subtests passed** across Tasks, Communications, Maintenance, Portfolio,
OPS/owner contexts, Lease/Inspection, Audit and workspace backup. An additional
**22 workspace API/service tests** and **one scoped baseline cleanup test** passed.
All changed Python files pass Ruff check and format-check using
`application/pyproject.toml`; `git diff --check` passes. No frontend sources changed,
and the complete server suite was not run.

Adjacent issue, not implemented: a complete baseline downgrade leaves five
pre-existing Intake tables/triggers. The scoped cleanup test proves removal of
the command-receipt objects changed here, not unrelated Intake cleanup.

## Slice 13: Lease command safety and recovery lookup

Delivered October 8, 2026: contracts/ports, implementation, current-baseline
persistence, focused tests and integration. The user approved shared Lease
revisions and immutable receipts for all existing Lease and child commands.

- Draft create/patch/initial-term replacement, participant add/update/remove,
  renewal add/edit/decision, and termination request/proposal/acceptance/status
  commands require the parent Lease revision and key at HTTP and application
  boundaries. Creation starts at revision one; effective changes increment once.
  Unchanged edits retain revision and timestamp but record a no-change receipt.
- Execute/end/terminate/void/termination completion require both Lease and Space
  status revisions. They preserve one atomic Portfolio source operation and
  Space increment, the original consumer result and correlated domain audits.
- The response and append-only Lease receipt commit in the original immediate
  transaction. Replay precedes lifecycle checks and returns the complete original
  result after later changes. Changed reuse and stale revisions return typed 409
  conflicts, with the latest owning status for revision conflicts.
- Public read-only recovery supports operation ID and Lease-scoped key, using
  one indexed SELECT without rehydrating current state or redispatching commands.
  Typed request/result/conflict contracts and stable OpenAPI IDs are declared.
- Exact schema and retained-history validation cover the new table, revision
  chains, canonical fingerprints, current Lease/child facts, correlated audit
  evidence and agreement with Portfolio's opaque source receipt. Encrypted
  restore preserves receipt fields and original replay responses.
- Real SQLite tests cover command families, original replay, no-change receipts,
  concurrent creation, stale aggregate revisions, audit and commit rollback,
  tampered data, encrypted portability and the one-query lookup budget.

[LEASE-001_COMMAND_READINESS.md](LEASE-001_COMMAND_READINESS.md) contains the
per-workflow inventory and validation matrix. New OPS forms and consequential
browser controls remain gated; attachments belong to Slices 17–18.

## Slice 14: Property, Space, and ownership command safety

Delivered October 8, 2026: contracts/ports, implementation, current-baseline
persistence, focused tests and integration. The user approved one shared
Property revision for these commands, separate from the existing Space status
revision used by occupancy, availability and classification.

- Property create/edit/archive/restore, ownership replacement, and Space
  add/edit/archive/restore require `expectedPropertyRevision` and a key at HTTP
  and application boundaries. Creation starts at one; effective commands and
  multi-Space cascades increment once. No-change commands retain revision/time
  and store a no-change receipt.
- Domain effects, inline owner creation, cascades, aggregate before/after
  evidence, and the original response receipt commit in one immediate
  transaction. Replay precedes lifecycle and stale checks, and cannot repeat
  ownership or cascade writes. Changed reuse and stale revisions return typed
  409 conflicts; stale conflicts contain the latest Property representation.
- One injected instant determines persisted timestamps, `asOf`, and the
  property-local effective date. Existing ownership/layout/archive/source guards
  and independent PORT-003 status contracts remain enforced.
- Typed original-result recovery supports operation ID, global key (including
  lost creation responses), and Property-scoped key, using one indexed SELECT.
  Mutation/recovery contracts have stable OpenAPI operation IDs.
- The latest greenfield baseline adds Property revisions and append-only
  `portfolio_inventory_operations`. Exact schema and retained-history validation
  cover receipts, canonical payloads, revision/inventory chains, correlated
  audits, current facts, and encrypted portability.
- Focused SQLite tests cover command families, no-ops, original replay,
  concurrent same-key creation, stale parent conflicts, independent status
  revisions, audit/commit rollback, tampering, encrypted restore and recovery
  query budgets. Integration fixtures call explicit named helpers; service
  methods retain their required public signatures.

[PORT-001_COMMAND_READINESS.md](PORT-001_COMMAND_READINESS.md) records the
workflow inventory and validation matrix. Additional OPS forms and consequential
browser controls remain gated under Slices 19–20 and subsequent UI work.

Validation: **422 focused tests and 103 subtests passed** across the changed
Portfolio, Lease, Finance, Inspection, Maintenance, Owner-report/concern,
Provider and OPS boundaries, plus Audit and encrypted workspace backup tests.
All 34 changed Python files pass Ruff check and format-check; `git diff --check`
passes. No full-suite or frontend validation is claimed.

## Slice 15: Finance and Owner-report workflow gates

Status: **source-owned backend contracts complete**. Additional OPS registration
and consequential browser controls remain gated. Approved scopes, command
inventory, persistence and validation matrix:
[Financial command readiness](FINANCE_COMMAND_READINESS.md).

- Delivered: typed Finance identities/ports, greenfield aggregate revisions and
  append-only receipts; strict metadata in HTTP and direct calls; original replay
  before lifecycle checks; typed stale/key conflicts and read-only recovery.
- Shared ledger: expectation synchronization/review/void, receipt creation/void,
  prepaid create/deposit/return/void/replace and transaction-bound Owner receipt
  creation. Each prepaid action advances once, including nested receipt and
  Task/reminder effects.
- Expense: record/patch/void and refund record/void share one Expense revision.
  Deposit: account, receipts, settlement lifecycle, deduction/credit/source
  changes and refunds share one account revision; deleted children retain their
  original response in command history.
- Owner: create/patch/verify/reject extend the existing operation authority;
  verification requires both report and ledger revisions. Receipt creation
  advances both atomically; explicit adoption advances only the report.
- Focused proofs cover no-op revisions, replay after later changes/deletion,
  financial/Task/Owner rollback, correlated audit privacy/history, bounded
  projections/recovery and encrypted portability.
- Still gated: expense-category administration, new OPS form registration and
  consequential browser transport/controls. No payment execution, bank
  integration or new accounting workflow is introduced.

Validation: **246 focused tests and 90 subtests passed** across Finance,
Owner-report, changed Maintenance/OPS coverage boundaries, Audit and workspace
baseline/open/encrypted backup tests. All 44 changed Python files pass Ruff
check/format-check; `git diff --check` passes. No full-suite or frontend validation
is claimed.

## Slice 16: Intake command recovery

Delivered October 8, 2026: source-owned command contracts for the existing Intake
workflows. OPS form registration is delivered in Slice 32; browser transport and controls
remain subsequent UI work.

| Workflow | Delivered contract | Gate |
| --- | --- | --- |
| Admission/import | Existing UUID key and canonical verified-manifest fingerprint; immutable original result with operation ID, source revision and evidence revision; lookup without republishing | Source contract delivered; no automatic resubmission |
| Evidence correction | Required source revision plus evidence revision UUID; one appended evidence revision and one source revision increment; original detailed result stored atomically | Source contract delivered; receipt disclosure requires a durable evidence-read audit |
| Source supersession | Required predecessor source/evidence revisions in the fingerprint; predecessor advances once, replacement starts at 1; original replacement result replays after later changes | Source contract delivered; trusted identity and publication rollback policies preserved |
| Attention dismissal/reopening | Required source revision, evidence revision UUID and expected attention state; detects return-to-original-state races; same-key replay returns the original result | Source contract delivered; consumer effects still require their owning transaction |
| Technical integrity | System-owned failure/restoration advances source revision without changing evidence identity | Distinct from operator commands; excluded from operator receipt recovery |

- Reuse `intake_source_operations` and its append-only triggers. Local-operator
  recovery is exposed by operation ID and by original key; missing or ineligible
  receipts return 404. Changed key reuse and stale commands return typed 409s.
- Public summaries expose `sourceRevision`, `evidenceRevisionId`, and `updatedAt`;
  the existing `revision` field continues to identify the evidence UUID.
- Caller-owned attention operations require the same source revision and retain
  the consumer correlation/atomicity. No INGEST-002, MCP, or UI-002 workflow is
  enabled by this slice.
- Current-schema validation reconstructs command revisions and original results.
  The baseline uses current model definitions; no compatibility migration is added.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Admission/import, correction, supersession, dismissal and reopening return operation metadata and separate revisions |
| Invalid combinations | Strict revision validation for direct/API callers; wrong evidence identity and stale source reject; technical receipts stay outside operator recovery |
| Idempotency/retry | Original receipt after later correction, attention and supersession; concurrent same-key correction produces one revision; changed concurrency metadata conflicts |
| Rollback | Audit failure rolls back source/revision/receipt; import commit failure releases operation-owned bytes; recovery never republishes |
| Persistence/schema | Positive integer source revision and required JSON command receipts; append-only operations; rewritten revision/receipt rejected |
| Backup/restore | Encrypted archive preserves original admission/correction receipts and latest source revision |
| Query budget | Key recovery is a bounded indexed operation lookup; sensitive disclosure adds only its required audit writes |

## Slice 17: Files and attachment command recovery

Delivered October 8, 2026: recoverable public upload and association archival,
with caller-owned attachment and verification gates inventoried separately.

| Workflow | Delivered contract | Gate |
| --- | --- | --- |
| Public upload | Required UUID key; verified-byte and normalized-metadata fingerprint; original file/link outcome and operation identity recorded with audits; read-only ID/key lookup | Source contract delivered; OPS form registration remains Slice 19 |
| Link archival | Required UUID key and association revision (active 1, archived 2); current-link 409 snapshot; original reason/time/result replay; atomic policy validation, link change, receipt and audits | Source contract delivered; no physical deletion or restoration workflow |
| Intake attachments | Existing caller-owned batch and immutable Intake operation receipt; recovery does not republish | Delivered by Slice 16; no separate Files receipt for an owning transaction |
| Inspection attachments | Validated draft-only caller-owned batch; publication rollback remains atomic with the owning report | Revision/receipt integration delivered in Slice 18 |
| Internal file reuse | Existing validated `link_existing_file` command | No standalone public endpoint or OPS form; owning workflow must provide recovery |
| Storage verification | Existing explicit continuation and `scanComplete`/clean `complete` distinction; system-owned state transitions and cleanup attention | No immutable receipt or OPS recovery registration; explicit operator continuation only |

`file_command_operations` retains immutable canonical requests and original
responses without bytes or provider locators. The current baseline, exact-schema
and retained-history validators, audit presentation registry, and portable archive
path include those receipts. No compatibility migration is added. Public upload
publishes outside the write transaction and rechecks the key inside it. Commit
failures roll back publication; post-commit release failures leave the committed
receipt recoverable. Neither ID/key lookup republishes or reloads current results.
OPS registration is delivered in Slice 33. No consequential browser control is enabled.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Actual SQLite upload/archive, metadata association revision, successful multipart API and typed results |
| Invalid combinations | Missing API key/revision returns 422; invalid direct key/revision rejected; changed reuse and stale association return typed 409 |
| Idempotency/retry | Original upload replays after archive; original archive replays; restart recovery and racing same-key uploads retain one file/receipt |
| Rollback | Receipt-audit and database-commit failures roll back bytes, metadata and receipt; post-commit release failure leaves a recoverable original result and cleanup attention |
| Persistence/schema | Append-only receipt triggers, exact schema, recomputed requests/results and required correlated file/link/operation audits; missing audit rejected |
| Backup/restore | Encrypted portable round trip preserves upload/archive IDs, original responses, archive reason and validated content |
| Query budget | Receipt recovery uses one indexed SELECT with no content or per-link read |

## Slice 18: Inspection lifecycle and attachment commands

Delivered October 8, 2026, after approval of one Inspection revision per lease
and independent template revisions. Lease and Space revisions remain separate.

| Workflow | Delivered contract |
| --- | --- |
| Report creation and correction draft | Required revision/key, canonical request, atomic original report snapshot and replay before lifecycle checks |
| Draft report editing; areas/observations; acknowledgments | Shared lease Inspection revision, immutable original results, current report/revision conflict snapshot; existing draft-only rules preserved |
| Evidence attachment | Verified-byte/metadata fingerprint, draft-only owning policy, FILE-001 batch, original evidence receipt, rollback across database commit and no re-publication on replay |
| Finalization and supersession | Atomic report-pair changes with one Inspection revision; replay retains the original finalized report even after later supersession |
| Comparison review | One lease Inspection revision; typed comparisons/revision/operation result, preserved original reviewed pair on replay |
| Checklist templates | Independent per-template revision and immutable creation/edit receipts; copied report checklists do not change |
| Evidence association archival | Delivered FILE-001 association revision/receipt and Inspection draft-only policy; distinct from Inspection attachment creation |

Append-only `inspection_command_operations`, exact-schema/retained-history
validation, privacy-safe audit presentation, ID/key recovery and encrypted
backup/restore are integrated. Every new accepted command (including a no-op)
advances its scope once. Recovery uses one indexed SELECT and never reconstructs
the response from current reports. No new OPS form or browser control is enabled.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Actual SQLite report/template/child/evidence/finalization/correction/comparison workflows |
| Invalid combinations | Required typed revision/key; direct-call validation; changed reuse and stale-state 409; draft-only lifecycle policies |
| Idempotency/retry | Racing duplicate create; original replay after edits/supersession and replaced comparison pairs; attachment retry does not publish again |
| Rollback | Receipt-audit and transaction-commit failures roll back records, receipt and publication |
| Persistence/schema | Append-only triggers, exact schema, contiguous revisions, canonical/recomputed receipt identity and correlated operation audits; tampering rejection |
| Backup/restore | Encrypted round trip compares original report/template/attachment/comparison results and evidence identities |
| Query budget | One indexed SELECT for recovery; one shared revision projection per report list |

## Slice 19: Explicit OPS recovery composition

Delivered October 8, 2026 for the approved Task, Communications, Maintenance,
and manual Portfolio workflows. This adds 43 explicit schema-version-1 forms
alongside the three existing creation/recording forms, for 46 registered forms.
It does not register Lease, Finance, Intake, Files, or Inspection recovery forms.

| Family | Newly registered form keys |
| --- | --- |
| Task lifecycle/editing | `task.edit`, `task.delete`, `task.start`, `task.complete`, `task.cancel`, `task.reopen` |
| Task reminders | `task.reminder.add`, `task.reminder.acknowledge`, `task.reminder.dismiss` |
| Task waiting/follow-up | `task.waiting.set`, `task.waiting.clear`, `task.waiting.reschedule` |
| Communications | `communication.create`, `communication.patch`, `communication.draft.record`, `communication.correct` |
| Maintenance issue/reporter | `maintenance.issue.patch`, `maintenance.reporter.correct`, `maintenance.issue.start`, `maintenance.issue.return_to_open`, `maintenance.issue.resolve`, `maintenance.issue.cancel`, `maintenance.issue.reopen` |
| Maintenance appointments | `maintenance.appointment.create`, `maintenance.appointment.update`, `maintenance.appointment.finish` |
| Maintenance cost/expense contexts | `maintenance.cost.create`, `maintenance.cost.void`, `maintenance.expense.link`, `maintenance.expense.archive` |
| Maintenance providers | `maintenance.quote.create`, `maintenance.quote.withdraw`, `maintenance.assignment.create`, `maintenance.assignment.end` |
| Maintenance follow-up/journal | `maintenance.follow_up.create`, `maintenance.journal.record` |
| Manual Portfolio status | `portfolio.occupancy.change`, `portfolio.occupancy.cancel`, `portfolio.occupancy.replace`, `portfolio.occupancy.correct`, `portfolio.occupancy.reschedule`, `portfolio.availability.change`, `portfolio.space.classify` |

`communication.record` remains the existing recorded-entry creation form;
`communication.draft.record` is the separate command to record an existing draft.
For Maintenance child mutations, the recovery source is the parent issue and its
shared revision; `targetId` identifies the child. Manual status forms use the
Space status revision, not the Property inventory revision.

Incomplete autosaves retain only explicitly allowlisted, bounded browser input.
New existing-source forms require the correct `sourceKind`, `sourceId`, and
decimal `baseSourceRevision`; their command payload contains `expectedRevision`.
Before preparing an attempt, the same immediate transaction checks source revision,
reusable lifecycle and selected child ownership. It rejects incomplete commands or
a supplied fingerprint that differs from the source contract. For these new forms,
OPS can derive the owning semantic fingerprint server-side when it is omitted.
Existing creation forms keep their established caller-provided fingerprint contract.

`GET /api/operator/recovery-forms` publishes the finite registered schemas and
fingerprint modes with a stable OpenAPI operation ID. Recovery never dispatches a
command: the caller must submit the exact source command under the recorded attempt
key. Reconciliation performs one keyed, source-owned receipt SELECT on the OPS
transaction and returns a typed bounded projection of the **original** target,
revision, status and operation ID. Full original responses remain in the source
receipt APIs rather than being copied into OPS or rebuilt from current state.

The reviewed binding registry is shared by runtime and current-schema validation.
The latest greenfield baseline's form-key constraint uses the same schema registry;
no compatibility migration is added. Retained attempt fingerprints are recomputed,
and reconciled receipt projections must match their actual source-owned receipt.
An unknown outcome cannot be discarded or silently expired. Restart, restore or
cancellation does not change its original attempt key or fingerprint. No generic
dispatcher, automatic resubmission, generated browser transport or consequential
browser control is enabled.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | All 43 new forms prepare and reconcile real SQLite Task, Communications, Maintenance and manual Portfolio receipts |
| Invalid combinations | Unknown/raw fields and oversized content rejected; incomplete attempts remain active; source revision, child ownership, lifecycle and supplied-fingerprint mismatch rejected |
| Idempotency/retry | Identical OPS prepare/reconcile retries return original receipts; source replay stays unchanged; changed owning payload is not reconciled; no-op source revisions preserved; later Portfolio state does not rewrite an earlier outcome |
| Rollback | Reconciliation audit failure leaves the attempt unresolved and the previously committed source receipt intact |
| Persistence/schema | Exact form-key check; registry/schema agreement; recomputed semantic fingerprints and actual owning-receipt comparison during workspace validation; tampered recovered result rejected |
| Backup/restore | Encrypted LOCAL-002 round trip compares attempt/source-operation rows and OPS audit correlations across all four families, then reconciles restored unknown outcomes without dispatch |
| Query/size bounds | Every new form resolves through one indexed source SELECT on the caller's connection; only scalar original-result fields are selected, not full request/response histories; existing 1/100-record OPS page budgets remain covered |

## Slice 20: Endpoint contract gate and remaining workflow inventory (delivered)

“Delivered” means the endpoint contract gate and workflow inventory are complete.
The unfinished workflows are listed under [Remaining backend readiness slices](#remaining-backend-readiness-slices).

The HTTP gate strengthens existing source-owned contracts; it does not implement
revisions or command receipts in domains that lack them. No consequential browser
controls or additional OPS recovery forms are enabled.

- Existing Task, Communications, Portfolio, Lease, Inspection, Maintenance,
  Finance, Owner-report, Intake and Files mutations/recovery keep their original
  receipt authority from Slices 7–18. Missing operation IDs and HTTP conflict
  declarations are supplied, UUID identifiers are validated at the boundary,
  and selected revision/numeric/instant fields are strict/aware. Lease and
  Portfolio keys remain bounded opaque strings where their source contracts
  permit them; they are not silently changed into UUID-only keys.
- Intake now declares typed summary, page, evidence detail, mutation and recovery
  responses. Reported occurrence-offset context and immutable original-result
  replay are retained. Owner-report evidence and allocations use typed nested
  responses rather than arbitrary dictionaries.
- Files declares typed verification, integrity-attention, metadata and conflicts,
  plus the binary attachment download contract. Publication identity is opaque
  bounded text: a local digest is not a UUID. Verification remains a separate
  writer operation, not an OPS-recoverable attachment command.
- Party/contact, Tenant, Provider/category/children and Owner-concern routes get
  explicit IDs and typed identifier boundaries without persistence redesign.
  This improves discovery but does not establish recoverable mutation safety.
- AI consumes the existing configuration and registered draft-review contracts
  and advertises its existing conflict envelope. No new action, adapter, approval
  policy or recovery form is registered. A typed response alone does not justify
  automatic retries of settings, credentials, connections or draft decisions.
- Production OpenAPI is tested for reproducibility, globally unique explicit IDs
  on the selected endpoints, concrete results/conflicts/recovery schemas, required
  concurrency fields and malformed-request rejection. Schema discovery forbids
  workspace open/initialize/runtime startup and database connections.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Existing real SQLite API tests plus `operator/tests/test_endpoint_contracts.py` and `vendors/tests/test_slice20_router_boundaries.py` |
| Invalid combinations | Malformed UUIDs, boolean revisions, naive instants, unknown fields and existing workflow-specific invalid requests; reject before domain dispatch where typed |
| Idempotency/retry | Existing command-readiness tests exercise first result, replay after later changes, typed conflict and read-only receipt lookup |
| Rollback | Existing Task, Lease, Portfolio, Inspection, Maintenance, Finance, Owner-report and Intake command tests; no new transactions or write mechanics added here |
| Persistence/schema | Existing source readiness tests validate retained receipts; this slice changes no baseline, table or retention policy |
| Backup/restore | Existing source readiness tests cover encrypted restore of retained receipts |
| Query budget | Existing source tests retain bounded projection/recovery proofs; new no-workspace schema discovery issues zero database queries |

Generated TypeScript clients, browser transport, later backlog features and
DASH-001 aggregation remain subsequent work.

## Delivered backend readiness slices 21–25

These delivered source-owned command contracts follow the Slice 20 endpoint gate.
Their implementations and focused proofs are grouped here; the ordered inventory
below now contains only remaining backend work.

### Slice 21: Party identity command recovery (delivered)

Create, edit, archive and restore require an exact Party revision and canonical
UUID key from HTTP and direct callers. Creation requires revision zero; effective
changes increment once, while unchanged patches retain revision and timestamps.
Immutable `party_command_operations` retain canonical requests, fingerprints and
original identity results. Replay precedes stale/lifecycle checks; changed key
reuse conflicts. Typed results include `revision` and `operationId`; stale
conflicts include the current identity snapshot. Read-only recovery by operation
ID or global key uses one indexed query. Mutation results contain identity
facts, not live contact/role projections. Receipts, Party/contact creation
effects and correlated audits commit together. Exact schema, retained history
and encrypted restore are covered by `parties/tests/test_identity_commands.py`.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real SQLite create/edit/archive/restore and unchanged patch |
| Invalid combinations | Direct boolean/string/negative revisions and malformed keys; typed HTTP validation and role guards |
| Idempotency/retry | Original result after later changes, ID/key recovery, changed-payload conflict, concurrent duplicate create and competing edits |
| Rollback | Creation/edit audit failure rolls back domain and receipt writes; correlated Party and metadata-only receipt events |
| Persistence/schema | Exact columns, keys, constraints, indexes and trigger bodies; canonical requests/fingerprints/results, revision chains and audit evidence; retained-history tampering rejected |
| Backup/restore | Encrypted LOCAL-002 round trip compares persisted receipts and original correlated audit rows |
| Query budget | Recovery uses one indexed SELECT without writes; focused Party consumers and deterministic no-workspace OpenAPI tests |

### Slice 22: Party contact command recovery (delivered)

Contact add, edit, archive and restore use the shared Party revision and UUID
key. Effective changes increment once; no-op edits preserve timestamps/revision
but retain receipts. Canonical requests and original typed contact results share
Slice 21's global key namespace. Replay precedes lifecycle/reference checks;
changed reuse and stale revisions conflict. Archival coordinates owning-role
preference changes on the same connection. Contact, Party revision, preference,
receipt and audit writes commit or roll back together. Exact retained validation
binds results, revision/audit history, role-reference evidence and current
contact state. Focused tests live in `parties/tests/test_contact_commands.py`.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real SQLite contact add/edit/archive/restore and unchanged edit |
| Invalid combinations | Archived-Party and missing-contact guards, canonical IDs/keys, exact revision validation and required typed requests |
| Idempotency/retry | Original result after later changes, cross-family key conflicts, concurrent same-key adds and shared revision conflicts |
| Rollback | Preference coordination and receipt-audit failure roll back contact, Party, preference and receipt changes together |
| Persistence/schema | Exact ledger, legal transitions, correlated role/audit evidence and metadata-only receipts; rewritten contacts and missing role audits rejected |
| Backup/restore | Encrypted LOCAL-002 round trip preserves contacts, preferences, revisions, receipts and correlated audit rows |
| Query budget | Recovery is one SELECT without writes; Tenant lifecycle/reference and deterministic no-workspace OpenAPI tests |

### Slice 23: Tenant command recovery (delivered)

Tenant creation/designation require revision zero; profile/preferences, archive
and restore require the current positive revision and a canonical UUID key.
Effective changes increment once; no-op patches retain revision/timestamps.
Immutable `tenant_command_operations` store canonical requests/fingerprints and
original typed results (`revision`, independent `partyRevision`, and
`operationId`). Replay precedes lifecycle/revision checks. Party/contact
effects, Tenant changes, receipts and correlated audits share one transaction;
internal contact-resolution receipts contain the Tenant result. Exact current
schema and retained history are validated on workspace open and encrypted
restore. Focused tests live in `tenants/tests/test_command_readiness.py`.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Compound Party/contact/Tenant creation, existing-Party designation, profile/preferences, archive and restore |
| Invalid combinations | Exact integer revision and UUID key validation; invalid preference/reference inputs and missing Tenant revision in contact resolutions rejected; current-profile stale conflicts |
| Idempotency/retry | Concurrent duplicate creation, changed-key conflict, omission-sensitive patches and original results after later changes |
| Rollback | Receipt-audit failure rolls back Party, contacts, Tenant profile and ledger; stale role resolution leaves state unchanged; both receipt audit chains share a correlation |
| Persistence/schema | Exact receipt schema/triggers, canonical requests/fingerprints, legal transitions, revision lineage and current profile; tampered fingerprint/result/audit/revision/trigger rejected |
| Backup/restore | Encrypted LOCAL-002 round trip compares receipt rows and original results, preserving revisions and preference/contact history |
| Query budget | Recovery uses one indexed SELECT; dependent Lease/Inspection/Maintenance/Finance fixtures and deterministic no-workspace OpenAPI tests |

### Slice 24: Provider identity and profile command recovery (delivered)

Provider creation/designation require revision zero; profile edit, archive and
restore require the current positive Provider revision and a canonical UUID key.
Effective edits increment once; no-op edits preserve revision/timestamps. Replay
precedes duplicate/lifecycle/revision checks; changed reuse conflicts, while
stale conflicts return the current profile. Immutable
`provider_command_operations` store canonical requests/fingerprints and original
results (`party`, `profile`, `revision`, `partyRevision`, `operationId`).
Results exclude live child/category enrichments, which remain read-only detail
data. Initial Party/contact/child/category effects, Provider profile, receipt and
correlated audits commit atomically. Indexed ID/key recovery returns the
original result. Exact schema, retained history and encrypted restore are
covered by `vendors/tests/test_command_readiness.py` and deterministic
no-workspace OpenAPI tests. Provider children are delivered in Slice 25;
category/assignment commands are delivered in Slice 26.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real SQLite compound creation, existing-Party designation, profile/no-op edits, archive and restore |
| Invalid combinations | Direct integer/UUID validation, required typed HTTP concurrency and current-profile stale conflicts |
| Idempotency/retry | Original result after later profile/child changes, changed-key conflicts, omission-sensitive patches, concurrent create and competing edits |
| Rollback | Receipt-audit failure rolls back identity/contact/profile/child writes; correlated events and metadata-only receipt audit |
| Persistence/schema | Exact ledger columns/constraints/indexes/FKs and immutable triggers; canonical fingerprints/results, revision transitions and current profile; retained-history tampering rejected |
| Backup/restore | Encrypted LOCAL-002 round trip compares receipt rows, revisions, original recovered results and correlated audit rows |
| Query budget | Recovery uses one indexed SELECT; mutations avoid post-commit detail reads; Provider, Maintenance, Expense and deterministic no-workspace OpenAPI tests |

### Slice 25: Provider child command recovery (delivered)

All 20 service, area, work-history, reference and reputation create/update/archive/
restore commands require the current positive Provider revision and canonical
UUID key. They share Slice 24's aggregate revision and global receipt namespace.
Effective changes advance once; unchanged updates preserve parent/child timestamps
and revision while recording their own receipt. Replay precedes current revision,
reference and lifecycle checks; changed reuse conflicts and stale conflicts return
the current Provider profile. The existing immutable `provider_command_operations`
ledger stores original typed child results (`kind`, `item`, `profile`, `revision`,
`operationId`) in the same transaction as child changes, parent revisions and
correlated audits. ID/global-key recovery is one indexed read, never a later detail
projection. Retained validation reconstructs legal child histories and validates
requests, results, correlated evidence and current rows. No new OPS forms or
consequential browser controls are enabled; category/assignment recovery is delivered in Slice 26.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real SQLite create/update/archive/restore and unchanged updates for all five child families; one parent revision per effective command |
| Invalid combinations | Direct exact revision/UUID validation, required typed HTTP metadata, active Provider/Party and child lifecycle guards, uniqueness/reference rules, detailed stale conflicts |
| Idempotency/retry | Original results after later changes and Provider archive, cross-family/changed-key conflicts, concurrent same-key children and competing shared revisions |
| Rollback | Receipt-audit failures roll back child, Provider revision and receipt for all 20 commands; original responses are built before commit |
| Persistence/schema | Expanded current baseline constraints and existing immutable ledger triggers; canonical normalized requests/results, legal revisions, correlated child/profile/receipt history and retained child tips; tampering rejected |
| Backup/restore | Encrypted LOCAL-002 round trip compares all five child families, archived history, original results, receipt rows and correlated audits |
| Query budget | Indexed one-SELECT child recovery; no post-commit detail reconstruction; focused Provider/Maintenance/Expense integration and deterministic no-workspace OpenAPI tests |

Focused tests: `vendors/tests/test_child_command_readiness.py`,
`vendors/tests/test_command_readiness.py`, `vendors/tests/test_vendors.py`, and
`operator/tests/test_endpoint_contracts.py`.

### Slice 26: Provider category and assignment command recovery (delivered)

Category create/patch/archive/restore requires a canonical UUID key and its own
revision (zero for create, positive thereafter; editable seeds start at one).
Independent assignment create/archive/restore shares the Provider revision from
Slices 24–25; assign and restore additionally require the selected category's
current revision. Category lifecycle changes do not rewrite assignments or
advance Provider revisions.

Every accepted command stores its typed original result, canonical request and
fingerprint, correlation and audit evidence before the same transaction commits.
Same-key replay precedes lifecycle/revision checks; changed reuse and stale
revisions return typed conflicts with current category or Provider state.
Effective mutations increment their owning revision once. Accepted semantic
no-ops retain a receipt without changing the timestamp/revision or writing a
business mutation audit. Category results freeze the effective-provider count
at commit; assignment results freeze the assignment, category and revised
Provider profile. Later reads and retries never reconstruct that result.

The greenfield baseline includes category revision and an append-only
`provider_category_command_operations` ledger. Category keys are globally
unique within that ledger; assignment keys share the globally unique Provider
ledger with profile and child commands. Read-only ID/key recovery is indexed,
does not open a write transaction and returns exactly the retained result.
Exact-schema and retained-history validation reconstruct seed origins, category
and assignment transitions, original counts, revision tips and correlated
receipt/mutation audits. No OPS forms or consequential browser controls are
registered or enabled by this slice.

Focused validation: `vendors/tests/test_category_command_readiness.py`,
`vendors/tests/test_command_readiness.py`,
`vendors/tests/test_child_command_readiness.py`,
`vendors/tests/test_vendors.py` and
`operator/tests/test_endpoint_contracts.py`.

| Area | Focused proof |
| --- | --- |
| Happy paths | Category create/patch/archive/restore, seed editing, assignment creation/lifecycle, current effective counts and original typed results |
| Invalid combinations | Required exact revisions/UUID keys, active Provider/category eligibility, stale category and Provider conflicts, changed archive reasons and duplicate active pairs |
| Idempotency and retry | Original results after later edits/lifecycle changes, changed-payload conflicts, audit-free replay, durable no-op receipts and concurrent same-key assignment submissions |
| Transaction rollback | All four category and three assignment command writes fail closed when receipt persistence fails; audit failure rolls back source, revisions and receipts |
| Persistence/schema | Exact receipt columns/checks/keys/indexes/triggers, category revision default, anchored seed origin, canonical requests, original results/counts and complete correlated history |
| Backup/restore | Encrypted LOCAL-002 round trip compares category/assignment/receipt rows and recovers original results; restored workspace passes current-schema validation |
| Query budget | One indexed SELECT for ID recovery; set-based effective counts and existing Provider projections; no post-commit live-detail reload; deterministic no-workspace OpenAPI contracts |

### Slice 27: Owner concern command recovery (delivered)

Concern create requires revision zero and a UUID key. Patches, confirmed
lifecycle transitions and additional follow-ups require the shared concern
revision and a UUID key. Effective mutations advance that revision once;
accepted patch no-ops retain an immutable receipt without changing the concern
timestamp/revision or adding a business mutation audit.

Each command records its canonical request, fingerprint, original typed result,
operation ID and correlation before the same transaction commits. Replay runs
before lifecycle/revision checks, returns the original result after later
changes and rejects changed key reuse. Stale revisions return the current bounded
concern detail. Creation and additional follow-ups retain the complete original
Task result with the concern response; Task insertion, concern revision,
follow-up linkage, receipts and correlated audits commit or roll back together.

Communication links use COM-001's delivered shared revision and immutable
receipts, including the existing transaction-aware `owner_concern` target
validation. Communications and Tasks keep their own lifecycle authority.
The concern receipt freezes its bounded source, communication, lineage and Task
projections at commit; recovery never reloads them from current state.

The greenfield baseline adds the shared concern revision and append-only
`owner_concern_command_operations`. Globally unique command keys and indexed
operation-ID/key recovery cover all concern commands. Exact-schema and retained
validation check canonical requests/results, revision history and correlated
concern, Task, follow-up and command audit evidence. OPS forms and consequential
browser controls remain gated.

Focused validation: `owner_management/tests/test_command_readiness.py`,
`owner_management/tests/test_owner_concerns.py`,
`operator/tests/test_endpoint_contracts.py` and
`operator/tests/test_context_sources.py`.

| Area | Focused proof |
| --- | --- |
| Happy paths | Creation, edits, lifecycle changes, additional follow-ups and accepted no-ops; one shared revision increment per effective command |
| Invalid combinations | Required exact revisions/UUID keys, lifecycle/context rules, detailed stale snapshots and global changed-key conflicts |
| Idempotency and retry | Original concern and Task results after later changes; audit-free replay; concurrent same-key submissions and competing revisions |
| Transaction rollback | Receipt/audit failures roll back concern, revision, Task, follow-up linkage and audit writes together |
| Persistence/schema | Exact ledger constraints/indexes/triggers; canonical fingerprints/results; revision tips and correlated creation/lifecycle/follow-up evidence; tampering rejection |
| Backup/restore | Encrypted LOCAL-002 round trip preserves original concern and Task results, stable identities, revisions, receipts and audit history |
| Query budget | One indexed SELECT for ID/key recovery; deterministic no-workspace typed OpenAPI contracts; existing bounded communication/Task summary projections |

### Slice 28: Expense category command recovery and Maintenance taxonomy gate (delivered)

Expense category create requires revision zero and a canonical UUID key;
patch/archive/restore requires the category's current positive revision and key.
Seeds and new categories start at revision one. Effective commands advance the
category revision once. An unchanged business-field patch records an immutable
receipt without changing the timestamp, revision or business audit history.

Same-key replay precedes lifecycle/revision checks and returns the original typed
category result with its `revision` and `operationId`. Changed reuse and stale
revisions return typed conflicts; stale responses include the current category
and revision. Category edits do not advance Expense/refund revisions or rewrite
their original receipts. Additional OPS forms and browser controls remain gated.

The greenfield baseline adds category revisions and the append-only
`expense_category_command_operations` ledger. Its category-command keys are
globally unique within that ledger. Category effects, revision, original result
and correlated business/receipt audits commit atomically. Read-only ID/key
recovery uses one indexed lookup. Exact-schema and retained validation anchor
editable seed origins, reconstruct revision/command/audit chains and reject
altered request fingerprints, results or current revision tips.

Maintenance keeps MAINT-001's fixed category vocabulary, as confirmed for this
slice. There is no Maintenance category-administration command to recover.
Issue category/detail edits already participate in the shared Issue revision,
immutable receipts and recovery delivered in Slice 11. Editable Maintenance
taxonomy would require a separately approved design change.

Focused validation: `finance/tests/test_category_command_readiness.py`,
`finance/tests/test_expenses.py` and
`operator/tests/test_endpoint_contracts.py`.

| Area | Focused proof |
| --- | --- |
| Happy paths | Category creation, patch, archive, restore and seed editing; typed original results and one revision increment per effective command |
| Invalid combinations | Required exact revision/UUID keys from API/direct calls, normalized-name uniqueness, lifecycle guards, stale current-category conflicts and changed reuse |
| Idempotency and retry | Original results after later changes; audit-free replay; no-op receipts preserve revision/time; same-key concurrency and competing revisions |
| Transaction rollback | Failed receipt or audit writes roll back category, revision and correlated audits for every command |
| Persistence/schema | Exact ledger constraints/indexes/triggers; canonical requests/results and fingerprints; registered seed origin, legal revision/audit history and tampering rejection |
| Backup/restore | Encrypted LOCAL-002 round trip preserves category identities/revisions, original results, receipts and correlated audits |
| Query budget | One indexed SELECT for ID/key recovery; no current-state reconstruction or additional transaction on replay; deterministic no-workspace OpenAPI contracts |

### Slice 29: AI configuration and draft-review recovery (delivered)

Settings, connection creation/update, destination disclosure and action-limit
overrides now require an exact owning revision and UUID key. Settings and
connections start at one; creation and absent overrides require zero. Effective
configuration changes advance the revision once; no-ops retain revision/time
and record a receipt. Draft edit/approve/dismiss require the existing positive
draft version and a UUID key. Edits increment the version; terminal decisions
preserve it and retain their lifecycle guards.

The source-owned `ai_command_operations` ledger stores canonical requests,
fingerprints, original typed results and correlated operation audits. It replaces
the settings-only ledger in the greenfield baseline. Same-key replay precedes
revision/lifecycle/source checks and returns the original result after later
changes. Changed reuse conflicts. Stale revision responses include current state
and revision. Public ID/key recovery performs one indexed read.

Approvals carry an immutable command identity through the registered owning
handler. Its transaction-bound review adapter checks replay before source
validation and official writes, then stores the complete original result and
receipt alongside the domain consequence, review decision and correlated audits.
The synthetic integration handler proves this boundary and rollback behavior.
Static production action/approval registries retain their existing gates.

Credential changes and connection probes remain explicitly gated for recoverable
UI attempts: their device/provider effects do not share SQLite atomicity. This
slice adds no OPS registrations, browser controls, new action approval modes or
domain-dismissal workflows.

Focused validation: `ai_governance/tests/test_command_readiness.py`,
`ai_governance/tests/test_governance.py`,
`ai_governance/tests/test_api_contracts.py` and
`operator/tests/test_endpoint_contracts.py`.

| Area | Focused proof |
| --- | --- |
| Happy paths | Settings, connection creation/edit, disclosure, limit overrides and draft edit/approve/dismiss through real SQLite; effective revisions and configuration no-ops |
| Invalid combinations | Required exact revision/UUID key from API and direct callers; registered connection/limit policy, terminal lifecycle, stale current-state conflicts and changed reuse |
| Idempotency and retry | Original results after later configuration/draft/source changes; audit-free replay; concurrent duplicate settings and approval submissions; competing revisions |
| Transaction rollback | Receipt and commit failures roll back configuration/draft/review/domain effects; approval stores its original result inside the owning transaction |
| Persistence/schema | Exact ledger constraints/indexes and update/delete/replace guards; canonical request/result/fingerprint, revision tips and complete correlated mutation/receipt evidence; rewritten history rejected |
| Backup/restore | Encrypted LOCAL-002 round trip compares stable receipt rows and audits plus settings, limits, run/draft/review history; credentials remain excluded |
| Query budget | One indexed SELECT for ID/key recovery, no current-result reconstruction, deterministic no-workspace OpenAPI contracts and bounded existing draft projections |

### Slice 30: Lease OPS recovery registration (delivered)

Registered the delivered LEASE-001 commands with OPS forms and Lease-owned
receipt recovery. This includes creation and draft edits, terms and participants,
renewal options, termination cases and proposals, and execute/end/terminate/void
timeline actions. OPS validates against `lease_command_operations`; it does not
dispatch the command or reconstruct its result from the current Lease.

Timeline forms carry the parent `expectedRevision` for the Lease and a separate
`expectedSpaceRevision` for the Space status change. The bound request fingerprint
uses the same canonical Lease command identity and preserves the complete
original response, including its resulting Lease revision and operation ID.
Lease creation uses revision zero and its official command validates the target
space. No browser controls are enabled by this slice.

Registered forms: `lease.create`, `lease.patch`, `lease.term.replace`,
`lease.participant.add`, `lease.participant.update`,
`lease.participant.remove`, `lease.execute`, `lease.end`, `lease.terminate`,
`lease.void`, `lease.renewal.add`, `lease.renewal.update`,
`lease.renewal.decide`, `lease.termination.create`,
`lease.termination.proposal.add`, `lease.termination.proposal.accept`,
`lease.termination.transition`, and `lease.termination.complete`.

Focused proofs cover registration completeness, form validation, Lease-owned
fingerprint parity, source-revision freshness, immutable receipt lookup, and
original operation identity. The existing Lease persistence validator continues
to validate append-only receipts and correlated audit history.

| Area | Focused proof |
| --- | --- |
| Happy paths | Lease forms are registered with their source-owned reader and typed payload schemas |
| Invalid combinations | Incomplete forms are rejected; Lease revision and Space status revision remain separate |
| Idempotency/retry | Form fingerprint matches the stored Lease request and key lookup returns its original receipt after commit |
| Rollback | Existing Lease transaction tests prove audit and commit failures roll back Lease and timeline writes |
| Persistence/schema | Existing command validator checks exact schema, immutable receipts, request/result fingerprints and audit evidence |
| Backup/restore | Existing Lease and workspace tests validate retained receipts through current-schema and archive validation |
| Query budget | Recovery reads the indexed Lease command receipt without hydrating current Lease state |

### Slice 31A: Rent expectation/receipt and prepaid-check OPS recovery (delivered)

Registered this explicitly approved bounded Finance batch against the existing
rent-ledger command receipts. The nine forms are:

- `finance.rent_expectation.void`
- `finance.rent_expectation.timeliness_review`
- `finance.rent_receipt.create`
- `finance.rent_receipt.void`
- `finance.prepaid_check.create`
- `finance.prepaid_check.deposit`
- `finance.prepaid_check.return`
- `finance.prepaid_check.void`
- `finance.prepaid_check.replace`

These forms use the owning Lease as their source and carry the rent-ledger
revision as `expectedRevision`. They reconstruct `FinanceCommandIdentity` using
the official command payload, including allocation ordering, defaults and
replacement lineage. Finance's read-only recovery reader combines Lease status
with the rent-ledger revision and reads the original `finance_command_operations`
result on the caller's connection. It does not dispatch financial mutations,
rebuild results from current records, or enable browser controls.

Slice 31A excludes generated expectation synchronization, delivered separately
in 31B. Expense, deposit-account and Owner-rent-report mutations remain in Slice
31's proposed, unapproved batches below.

| Area | Focused proof |
| --- | --- |
| Happy paths | Exact nine-form/schema/binding registration; Finance reader returns the original rent-receipt operation and ledger revision |
| Invalid combinations | Incomplete forms and malformed commands are rejected; Lease lifecycle is checked before attempt admission |
| Idempotency/retry | Fingerprints match `FinanceCommandIdentity`; receipt lookup validates action, source, and request fingerprint |
| Rollback | Existing FIN-001/FIN-007 persistence tests prove financial effects, receipts and audit events share one transaction; OPS is read-only |
| Persistence/schema | Existing Finance validators enforce immutable command receipts, revision and audit history; no schema changes |
| Backup/restore | Existing Finance encrypted archive tests retain command receipts; no new persistence added |
| Query budget | Finance receipt lookup and rent-ledger revision are indexed bounded reads; Lease status comes from its source reader on the same connection |

### Slice 31B: Generated rent-expectation synchronization (delivered)

The approved bounded batch is `finance.rent_expectation.synchronize`. Reuse the
owning Lease, rent-ledger revision, `SynchronizeExpectationsCommand`, and immutable
Finance receipt. Recovery identifies the ledger command rather than selecting a
generated expectation or regenerating its result. No browser controls are enabled.

The typed OPS form preserves Finance's canonical defaults and override semantics.
Attempt admission checks the selected term's Lease membership and the ledger
revision using source-owned readers. Recovery reads the retained command's Lease
target and original result, including empty/no-op results, on the caller's
connection. No new persistence or mutation ledger is introduced.

| Area | Focused proof |
| --- | --- |
| Happy paths | API discovery, save, preparation and reconciliation for generated and empty synchronization results; deterministic no-workspace OpenAPI contract |
| Invalid combinations | Strict revision/UUID/date/confirmation fields; missing or foreign term, stale ledger and unconfirmed responsibility override rejected |
| Idempotency/retry | Canonical Finance fingerprint parity, including defaults and normalized override reasons; original replay after later synchronization; OPS retries and changed-payload conflicts |
| Rollback | Injected audit failure rolls back expectations, ledger revision, command receipt and correlated audit rows; retry then succeeds |
| Persistence/schema | Current-schema validation checks retained Finance and OPS records; existing immutable source receipts are reused |
| Backup/restore | Encrypted LOCAL-002 round trip preserves expectations, revisions, original outcomes, OPS attempts and correlated financial/OPS audit history |
| Query budget | Outcome recovery performs one indexed SELECT independent of generated result count; source reads use the caller-owned connection without opening another connection |

Focused validation: 93 tests passed across synchronization recovery, Finance form
contracts, recovery composition and Finance command tests.

### Slice 31C: Expense and category OPS recovery (delivered)

The approved nine-form batch reuses Expense aggregate revisions and category
revisions, source command normalization, and immutable Finance/category receipts:

- **31C — Expense and category commands:** `finance.expense.{create,patch,void}`,
  `finance.expense_refund.{create,void}`, and
  `finance.expense_category.{create,patch,archive,restore}`.
Creation forms have no pre-existing source. Expense creation recovery normalizes
only the server-generated aggregate ID to the attempt key for pre-dispatch
comparison; the source receipt and financial fingerprint remain unchanged.
Patch forms preserve field presence, including explicit nulls. Refunds use their
parent Expense revision and verify child membership. Category archival and
restoration respect the current category lifecycle.

| Area | Focused proof |
| --- | --- |
| Happy paths | Typed discovery, preparation and original receipt reconciliation for Expense create/patch/refund and category create/patch/archive/restore |
| Invalid combinations | Strict revisions, identifiers, decimal amounts, confirmations and extra-field rejection; stale aggregate/category state rejected |
| Idempotency/retry | Canonical source-request parity, patch no-op and explicit-null semantics; original recovery after later refunds or category lifecycle changes; HTTP reconciliation replay |
| Rollback | Finance consumer/category tests prove source effects, revisions, immutable receipts and correlated audit rollback |
| Persistence/schema | Runtime and current-schema validation share the complete binding registry; no schema or mutation ledger added |
| Backup/restore | Encrypted round trip compares Expense/refund records, financial revisions/receipts and OPS attempts/operations; source category tests preserve category receipts |
| Query budget | Each source-owned outcome lookup is one indexed SELECT on the caller connection; no current-result reconstruction |

### Slice 31D: Security-deposit OPS recovery (delivered)

The approved eighteen-form batch reuses the account-scoped financial revision
and immutable source results:

- **Security deposits:** `finance.deposit_account.create`,
  `finance.deposit_receipt.{create,void}`,
  `finance.deposit_settlement.{create,patch,approve,complete,void}`,
  `finance.deposit_deduction.{create,update,delete}`,
  `finance.deposit_credit.{create,update,delete}`,
  `finance.deposit_deduction_source.{add,delete}`, and
  `finance.deposit_refund.{create,void}`.
Every child form selects its parent account and a typed target. Preparation
verifies account membership and the applicable settlement/receipt lifecycle.
Account creation binds the selected Lease and term while normalizing only the
server-generated account scope for pre-dispatch recovery comparison. Deleted
children recover from their immutable receipts without reloading deleted rows.

| Area | Focused proof |
| --- | --- |
| Happy paths | All eighteen exact bindings; real account/receipt/settlement/refund lifecycles, child edits/deletions and draft settlement patches |
| Invalid combinations | Strict fields, required targets, stale parent revision, missing child and settlement lifecycle guards |
| Idempotency/retry | Canonical source-request parity; recovery after child deletion, completion and settlement replacement retains original revision and target |
| Rollback | Source consumer tests prove child, account revision, receipt and audit writes roll back together |
| Persistence/schema | Existing Finance schema and immutable receipts reused; current-schema validation checks reconciled deleted-child evidence |
| Backup/restore | Encrypted round trip validates reconciled deleted-child attempts and original Deposit outcomes, comparing OPS records and source/financial/OPS audit history |
| Query budget | One indexed outcome query; bounded source/child checks use the same caller-owned connection |

### Slice 31E: Owner rent-report OPS recovery (delivered)

The approved four-form batch is `owner_rent_report.{create,patch,verify,reject}`.
It preserves the report revision and Finance receipt handoff in the owning
transaction. Verification includes the selected rent-ledger revision and exact
adoption/creation mode, allocation identities and replacement receipt. Preparation
checks both report state and ledger revision; recovery reads only the original
Owner receipt and never creates or adopts a Finance receipt itself.

| Area | Focused proof |
| --- | --- |
| Happy paths | All four exact bindings; real creation/patch/rejection receipts and OPS verification recovery for both adoption and receipt creation |
| Invalid combinations | Strict claim/confirmation/allocation fields and bounded allocations; stale rent-ledger preparation rejected |
| Idempotency/retry | Source fingerprint parity; both verification modes replay their original results without repeating financial effects |
| Rollback | Owner source tests prove failed verification rolls back report, Finance receipt/allocation, ledger revision and correlated audit effects |
| Persistence/schema | Source Owner receipts remain authoritative; current-schema validation verifies retained OPS reconciliation |
| Backup/restore | Encrypted round trip validates OPS verification recovery and original Owner outcomes, comparing OPS records and source/financial/OPS audit history; source tests preserve receipt creation history |
| Query budget | Original Owner outcome is one indexed SELECT on the caller-owned connection; ledger checking uses source-owned readers |

Brace notation enumerates separate form keys, not wildcard registrations.
Expense-category registration is allocated to 31C and must not be duplicated in
Slice 37. No consequential browser controls are enabled by these batches.

Focused validation for 31C–31E: the related regression set covers 184 tests,
including 48 in `operator/tests/test_financial_batches.py`, plus the existing
Finance forms/recovery composition/synchronization, consumer/category commands
and Owner-accounting tests. Changed-file Ruff lint/format and diff checks pass.

## Slice 32: Intake OPS recovery registration (delivered)

Delivered October 9, 2026, for the six explicitly approved local-operator forms:
`intake.source.admit`, `intake.source.import`, `intake.source.correct`,
`intake.source.supersede`, `intake.source.dismiss`, and `intake.source.reopen`.
Contracts/ports, implementation, existing persistence integration, focused tests,
and runtime/retained-validation composition are delivered. No new mutation ledger
or schema format is introduced.

- Admission and import are unbound creation forms requiring revision zero at
  attempt preparation. Import retains only an ordered, bounded manifest of roles
  and SHA-256 hashes: never attachment bytes, temporary paths, or provider locators.
  An incomplete saved manifest is not authorization to dispatch a command.
- Correction, supersession, dismissal and reopening bind the source revision and
  exact evidence-revision UUID. Attention forms also retain expected attention
  state; their reuse gate follows Intake's existing legal transitions. Correction
  preparation reads the retained manifest from the specified evidence revision
  on the caller's transaction, not from the current revision after later changes.
- Fingerprints use the same source-owned semantic request helpers as Intake
  mutations, including original occurrence-offset context and local-operator
  attribution. OPS derives the fingerprint; it does not execute Intake commands.
- Recovery reads only the original operation's non-sensitive result metadata:
  operation ID, target source ID, source revision, technical status, and evidence
  revision ID. Supersession remains bound to the predecessor while returning the
  replacement target. No evidence body is disclosed and no attachment is published
  again. Full evidence and detailed receipt disclosure retain their existing
  fail-closed Intake read audits.
- Runtime and current-schema validation use the same explicit binding registry.
  System integrity transitions, trusted-transport admission, consumer-owned review
  consequences, INGEST-002 and consequential browser controls remain unregistered
  or gated; this slice does not add automatic retries.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | All six forms save/prepare, execute through real Intake, and reconcile original source/evidence identities |
| Invalid combinations | Strict revision and aware occurrence validation; malformed/oversized manifests, duplicate hashes, paths, and stale source/evidence/attention guards reject; incomplete forms cannot prepare |
| Idempotency/retry | Unknown outcomes stay unresolved; original results recover after later corrections; different source payload under the attempt key cannot reconcile; attachment recovery never publishes |
| Rollback | Source audit failure rolls back admission and its operation; the OPS attempt remains unknown; existing Intake import commit-failure tests cover publication cleanup |
| Persistence/schema | Shared binding composition and canonical fingerprints pass full current-schema validation; rewritten prepared identity is rejected; original evidence revisions remain retained |
| Backup/restore | Encrypted LOCAL-002 round trip preserves Intake operations/revisions/attachment links and Files plus OPS recovery rows; restored receipt lookup and current-schema validation pass |
| Query budget | Original outcome lookup is one indexed SELECT using the caller's existing connection; only metadata is selected; correction preparation adds one exact-revision manifest read |

Focused validation: 22 Slice 32 tests in
`operator/tests/test_intake_recovery.py` pass, including the final HTTP
fingerprint and encrypted restore checks. The broader focused Intake/OPS
regression run passes 205 tests across Intake, command recovery, Finance forms,
recovery composition and endpoint contracts. Changed-file Ruff lint/format and
diff checks pass. The complete server suite was not run.

## Slice 33: Files OPS recovery registration (delivered)

Delivered October 9, 2026, for the two explicitly approved forms: `file.upload`
and `file.link.archive`. Contracts/ports, implementation, existing persistence
integration, focused tests and shared runtime/retained-validation composition
are delivered. The existing `file_command_operations` remains the sole Files
mutation receipt ledger; no schema format or compatibility migration is added.

- Upload is an unbound creation form requiring revision zero at preparation. It
  retains declared metadata, SHA-256 and target/purpose only, never content bytes,
  temporary paths or client-selected storage providers. Files' shared normalizers
  and semantic request helpers derive the same fingerprint as the public command.
- Link archival binds the association ID and its active revision, confirmation
  and bounded reason. OPS checks the current association and invokes the same
  owning-domain archive policy on its existing connection before preparation.
  Stale or already archived associations cannot begin a new attempt.
- Upload target/purpose and generic-upload capability are checked through the
  composed Files policy registry. Unknown targets/purposes and owning-workflow-only
  Intake/Inspection evidence fail closed. The owning Files command still rechecks
  policy and idempotency atomically; an OPS form does not authorize publication.
- An indexed metadata-only receipt projection returns the original operation ID,
  file ID, link ID, result revision and recorded status. Upload recovery still
  reports its original available/active result after archival; archive recovery
  reports its original revision 2. No content is opened or republished, no provider
  locators or archive reasons are returned by OPS reconciliation, and no result is
  reconstructed from current file storage state.
- Publication remains outside SQLite's write lock. Pre-commit failure rolls back
  publication and leaves the OPS attempt unresolved. A post-commit lease-release
  failure retains the committed receipt and can reconcile without another upload.
  Original ID/key recovery and Files' privacy-safe cleanup attention remain intact.
- Internal `link_existing_file`, system-owned storage verification and caller-owned
  Intake/Inspection attachments are not standalone Files OPS forms. Their owning
  workflows must supply recovery where applicable. Browser controls, automatic
  retries and new administrative file workflows remain gated.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real multipart upload and link archival through typed APIs; OPS preparation/reconciliation returns original file/link IDs, status and revisions |
| Invalid combinations | Strict revision/hash validation; provider/path/byte fields reject; missing/unknown targets, invalid purposes and owning-only uploads fail policy; archived/stale associations reject |
| Idempotency/retry | Same-key attempt and owning-command retries preserve original results; changed content cannot reconcile; unknown outcomes stay unresolved; recovery never republishes |
| Rollback | Real commit failure removes published content and metadata; source audit/commit rollback regression tests pass; post-commit release failure reconciles the committed result |
| Persistence/schema | Shared registry and canonical source requests pass current-schema validation; rewritten prepared fingerprints and source receipt/audit tampering reject |
| Backup/restore | Encrypted LOCAL-002 round trip preserves file/link/location history, original upload/archive receipts and both OPS recovery records; restored current-schema validation passes |
| Query budget | Original outcome is one indexed SELECT on the caller-owned connection; only receipt metadata is selected, without content access or new sessions |

Focused validation: 21 tests in `operator/tests/test_file_recovery.py` pass.
The related Files, Intake OPS recovery, shared recovery-composition and endpoint
contract regression run passes 193 tests. Changed-file Ruff lint/format and diff
checks pass. The complete server suite was not run.

## Slice 34: Inspection OPS recovery registration (delivered)

Delivered October 9, 2026, for the explicitly approved ten-form batch:

- `inspection.report.create`
- `inspection.report.patch`
- `inspection.report.areas.replace`
- `inspection.report.acknowledge`
- `inspection.report.finalize`
- `inspection.report.correct`
- `inspection.evidence.attach`
- `inspection.comparison.review`
- `inspection.template.create`
- `inspection.template.patch`

Contracts/ports: bounded, extra-forbidden incomplete forms preserve field presence
for patches and accept exact integer revisions. Attachment preparation retains
normalized metadata, size and SHA-256, never content bytes, paths or provider selection.
Lease Inspection, report, observation and template references have explicit source
kinds; their revisions are not the Lease or Space revision.

Implementation: OPS derives the owning Inspection command fingerprint and reads
the original immutable receipt. Correction binds to its finalized predecessor,
resolves immutable lease/report-kind facts and reuses `report.create`; finalization
continues to own atomic supersession. Areas include observation editing rather than
introducing a separate observation command. Draft-only editing/attachment and
independent template scopes remain enforced. OPS does not dispatch mutations.

Persistence/integration: source-owned state and receipt readers use OPS's caller
connection. One indexed metadata-only query resolves the original target,
revision, status and operation ID, with file/link IDs for evidence. No additional
ledger, schema migration, nested transaction or result reconstruction is introduced.
Existing Inspection APIs, immutable receipts and FILE-001 batches remain authoritative.
Unknown attempts stay unknown until a matching source receipt exists. No browser
control, generic retry or new Inspection lifecycle is enabled.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real HTTP commands and SQLite receipts for all ten forms, including normalized checklist/evidence metadata and explicit-null patches |
| Invalid combinations | Extra fields, paths/bytes, boolean/negative revisions; incomplete attempts, stale aggregate revisions and finalized report/observation gates |
| Idempotency/retry | Original source replay and OPS receipt matching; changed request under the attempt key stays unknown; original draft/comparison result survives later changes |
| Rollback | Required attachment audit and database commit failures roll back physical publication, metadata and Inspection receipt; OPS cannot reconcile an absent receipt; a same-key retry subsequently recovers without re-publication |
| Persistence/schema | Complete product validation accepts composed Inspection recovery records; tampered OPS fingerprint is rejected |
| Backup/restore | Encrypted LOCAL-002 round trip preserves exact Inspection command and OPS recovery/operation rows |
| Query budget | One indexed outcome SELECT on the caller connection; no nested connection or complete report/evidence reload |

Focused validation: 23 tests in `operator/tests/test_inspection_recovery.py` pass.
The related Inspection, Files OPS recovery, shared recovery-composition and endpoint
contract regression run passes 197 tests. Changed-file Ruff lint/format and diff
checks pass. The complete server suite was not run.

## Slice 35: Party and Tenant OPS recovery registration (delivered)

Delivered October 9, 2026, for the explicitly approved thirteen-form batch:

- `party.create`
- `party.patch`
- `party.archive`
- `party.restore`
- `party.contact.add`
- `party.contact.update`
- `party.contact.archive`
- `party.contact.restore`
- `tenant.create`
- `tenant.designate`
- `tenant.profile.patch`
- `tenant.archive`
- `tenant.restore`

Contracts/ports: extra-forbidden, bounded incomplete forms use strict revision and
confirmation fields, typed contact identities and at most twenty reference resolutions.
Tenant designation uses the prospective Tenant revision zero, not the Party revision.
Tenant patches preserve omitted-versus-null fields. Contact and identity normalization
reuse owning application commands before fingerprinting.

Implementation: OPS computes the existing Party/Tenant semantic fingerprint,
checks current aggregate and selected-contact ownership/lifecycle, and reads the
original immutable receipt by attempt key. Contact archival checks the declared
Tenant revision and replacement selection; the owning Party command performs
preference resolution and records the correlated Tenant consequence atomically.
Internal `resolve_contact` is not registered as a separate form.

Persistence/integration: stateless source-owned readers use the caller's existing
connection; Tenant recovery consumes the Party read contract without importing
Party persistence. Each outcome requires one indexed metadata-only query, returning
the original target, scope revision, status and operation identity without reloading
current representations. No new ledger, schema, nested transaction or mutation
dispatcher is introduced. Existing typed source commands and conflict/ID/key lookup
contracts remain authoritative; unresolved or mismatched attempts remain unknown.
Party and Tenant revisions stay independent. No consequential browser control is enabled.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Actual HTTP/SQLite receipt recovery for all thirteen forms, normalized contacts/identity, designation and explicit-null profile edits |
| Invalid combinations | Extra fields, boolean/negative revisions, contact/reference bounds, mutually exclusive resolutions, stale Tenant resolution revisions and cross-Party contact selection |
| Idempotency/retry | Same-key original HTTP replay, original OPS result after later identity/profile changes, changed-request receipts rejected; incomplete attempts cannot start |
| Rollback | A Party receipt-audit failure rolls back contact archival, Tenant preference/revision and both receipts; same-key retry commits one correlated Tenant consequence |
| Persistence/schema | Full product retained validation accepts real composed records; tampered OPS fingerprint is rejected |
| Backup/restore | Encrypted LOCAL-002 round trip preserves exact Party/Tenant records, command receipts and OPS recovery/operation rows |
| Query budget | One indexed SELECT per Party/Tenant outcome on the caller connection; no nested connection or current identity/contact/profile reload |

Focused validation: 25 tests in `operator/tests/test_identity_recovery.py` pass.
The related Party, Tenant command-readiness, Inspection OPS recovery, shared
recovery-composition and endpoint contract regression run passes 225 tests.
Changed-file Ruff lint/format and diff checks pass. The complete server suite
was not run.

## Slice 36: Provider and category OPS recovery registration (delivered)

Delivered October 9, 2026, for the explicitly approved 32-form batch:

- `provider.{create,designate,profile.patch,archive,restore}` — five forms.
- `provider.{service,area,work_history,reference,reputation_link}.{add,update,archive,restore}` — twenty forms.
- `provider.category.{create,patch,archive,restore}` — four forms.
- `provider.category_assignment.{assign,archive,restore}` — three forms.

Contracts/ports: extra-forbidden incomplete forms retain strict revisions and
confirmations, typed identifiers/dates and bounded text/collections. Complete
attempts reuse the owning Provider/category command constructors and canonical
request fingerprints, preserving omitted-versus-null patch fields, normalized
initial children and sorted category identities. Provider creation is unbound;
designation uses prospective Provider revision zero. Category creation is
unbound and later category commands use the independent category revision.

Implementation: OPS checks the shared Provider revision, profile/Party lifecycle
and selected child ownership/lifecycle. Assignment creation and restoration also
check the current category revision and active category. Existing source APIs
remain the mutation dispatch boundary; OPS does not dispatch or automatically
retry them. Unknown or mismatched receipts remain unresolved.

Persistence/integration: source-owned stateless readers consume the caller's
connection and the Party read contract. One indexed metadata-only query per
outcome returns the original aggregate, child/category target, resulting revision,
status and operation ID. No current representation reload, new ledger, schema,
nested transaction or browser control is introduced. Runtime and retained OPS
validation use the same binding composition.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Actual HTTP/SQLite execution and recovery for all 32 forms, including designation and normalized child/category patches |
| Invalid combinations | Strict revision/category-revision types, extra fields, bounded collections/text, invalid URLs, stale revisions and cross-Provider child selection |
| Idempotency/retry | Same-key original HTTP replay; original metadata after later mutations; changed-payload receipts remain unknown; incomplete forms cannot begin attempts |
| Rollback | Receipt-audit failure rolls back assignment/profile revision and receipt; the original attempt remains unknown and same-key retry recovers |
| Persistence/schema | Full product validation accepts composed records and rejects a tampered OPS fingerprint |
| Backup/restore | Encrypted LOCAL-002 round trip preserves exact Provider/category/assignment records, immutable receipts, OPS rows and correlated audit history |
| Query budget | One indexed SELECT per outcome on the caller connection, without nested connections or current-record hydration |

Focused validation: 24 tests in `operator/tests/test_provider_recovery.py` pass.
The final Provider/category/child/router focused run passes 94 tests, including
those 24. The combined recovery-composition, endpoint, Party/Tenant and Provider
command regression run passes 202 tests. Changed-file Ruff lint/format and diff
checks pass. The complete server suite was not run. Consequential browser controls
remain gated.

## Slice 37: Owner-concern OPS recovery registration (delivered)

Delivered October 9, 2026, for the explicitly approved seven-form batch:
`owner_concern.{create,patch,in_progress,open,resolved,dismissed,follow_up}`.
`open` covers returning in-progress work to open and reopening terminal work.
Expense categories and Maintenance issue editing are already registered and are
not registered again here.

Contracts/ports: extra-forbidden incomplete forms use strict concern revisions,
confirmations, UUID references, aware timestamps and bounded narratives. Creation
uses revision zero and no bound source; other commands use the shared concern
revision. Complete requests reuse the owning concern/FollowUpInput constructors
and canonical command fingerprint. Patch field presence and transition narrative
semantics match the existing HTTP dispatch boundary, including start ignoring its
optional summary. Context-dependent ownership, historical selection, duplicate
and reopen-reason policy remains with the source command.

Implementation: OPS checks the concern revision and action-specific lifecycle;
follow-ups remain available in terminal states, as the source contract permits.
Preparation never dispatches a command. Unknown or mismatched receipts stay
unknown; reconcile never repeats the concern or Task write. Existing owning APIs
provide typed results/conflicts and operation-ID/key recovery.

Persistence/integration: a source-owned stateless reader uses the caller's
connection for one indexed metadata-only receipt query. It returns the original
concern ID, revision, status and operation ID, not current concern or Task state.
The source receipt retains the full original concern and optional Task result.
Existing atomic concern/Task/link/audit writes are reused; Communications keeps
its separately registered command authority. No ledger, schema, nested transaction
or browser control is added. Runtime and retained OPS validation share composition.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real HTTP/SQLite dispatch and OPS recovery for all seven forms, creation with a Task, subsequent follow-up, return-to-open/reopen and patch no-op |
| Invalid combinations | Strict revisions/confirmations, typed UUID/timestamps, bounded text, extra fields, incomplete requests, stale revisions, terminal patch and source-owned reopen-reason rejection |
| Idempotency/retry | Original concern/Task HTTP replay and ID/key recovery after later changes; mismatched payload receipts remain unknown |
| Transaction rollback | Receipt failure after Task insertion rolls back creation/follow-up, concern revision, Task/link and audits; same-key retry recovers |
| Persistence/schema | Full product validation accepts composed records and rejects a tampered OPS fingerprint |
| Backup/restore | Encrypted LOCAL-002 round trip preserves exact concern/Task/link/receipt/OPS rows and correlated audit history |
| Query budget | One indexed receipt SELECT on the caller connection; no nested connection or current-detail reload |

Focused validation: 17 tests in `operator/tests/test_concern_recovery.py` pass.
The related regression run passes 235 tests across
`owner_management/tests/test_command_readiness.py`,
`owner_management/tests/test_owner_concerns.py`,
`operator/tests/test_recovery_composition.py`,
`operator/tests/test_endpoint_contracts.py` and
`operator/tests/test_provider_recovery.py`. Changed-file Ruff lint/format and
diff checks pass. No complete server suite or browser controls are included in
this slice.

## Slice 38: AI configuration and draft-review OPS recovery registration (delivered)

Delivered October 9, 2026, for the explicitly approved eight-form batch:
`ai.settings.update`, `ai.connection.{create,update,disclosure}`,
`ai.action_limit.update` and `ai.draft.{edit,approve,dismiss}`.
Credentials, transport probes, generation, new approval modes and browser controls
remain excluded. This registration does not add production adapters/actions or
owning-domain approval handlers to the release registries.

Contracts/ports: extra-forbidden incomplete forms use strict configuration
revisions or draft versions, bounded model/disclosure collections, bounded notes
and JSON payloads within the existing 64 KiB OPS envelope. Requests reuse
`AiCommand` fingerprints with the exact owning HTTP field-presence/default rules:
settings distinguish an omitted default connection from explicit null; disclosure
classes are deduplicated/sorted; connection creation normalizes its label while
patch requests preserve their raw supplied fields. Connection creation is unbound
at revision zero; action-limit creation uses the registered action at revision
zero. Draft commands use `version`, not an invented configuration revision.

Source identity: OPS retains the AI settings singleton `1` and canonical
registered action names for action limits. Connection/draft references and all
other existing sources remain canonical UUIDs. Typed input/result contracts and
retained validation share these explicit identity rules; no synthetic UUID or new
source-identity ledger is introduced.

Implementation: OPS checks current revisions/versions, active review status and
cloud-only disclosure. The source APIs remain the dispatch boundary and enforce
registered model/action policy and source freshness. Approval still runs through
the registered owning-domain handler with domain effects, review and original
receipt committed atomically. OPS reconciliation never calls a provider or repeats
an approval; unknown/mismatched results remain unresolved.

Persistence/integration: the AI-owned stateless reader uses the caller connection
for narrow state queries and one indexed metadata-only original-receipt query.
Result targets, revisions/versions, statuses and operation IDs come from the
recorded result, never current settings/connections/drafts. Runtime and retained
OPS validation share binding composition. Existing AI receipt-ID/key endpoints
provide the original full typed result. No schema, mutation ledger, nested
transaction, external-effect recovery or browser control is added.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Actual HTTP/SQLite dispatch and recovery for all eight forms; settings singleton/action-name identities, cloud disclosure, accepted connection no-op, draft editing, dismissal and owning Task approval |
| Invalid combinations | Strict revisions/versions, typed source identities, bounded text/collections, extra fields, incomplete requests, stale versions, terminal drafts and transaction-visible stale-source rejection |
| Idempotency/retry | Original HTTP results after later changes; omitted/null settings mismatch stays unknown; original approval replay does not repeat its Task write |
| Transaction rollback | Failure recording an approval receipt after the owning Task write rolls back Task, review, receipt and correlated audits; same-key retry recovers |
| Persistence/schema | Full product validation accepts composed AI/OPS records and rejects a tampered recovery fingerprint |
| Backup/restore | Product-valid encrypted LOCAL-002 round trip preserves settings, connections, limits, runs, drafts, reviews, all eight command receipt types, Task effects, OPS records and correlated history |
| Query budget | One indexed metadata-only original approval receipt SELECT on the caller connection; no nested connection or current-state/credential/provider reads |

Focused validation: 19 tests in `operator/tests/test_ai_recovery.py` pass.
The related regression run passes 207 tests across
`ai_governance/tests/test_command_readiness.py`,
`ai_governance/tests/test_governance.py`,
`operator/tests/test_recovery_composition.py`,
`operator/tests/test_endpoint_contracts.py` and
`operator/tests/test_concern_recovery.py`. Changed-file Ruff lint/format and diff
checks pass. Only focused tests are run; no browser controls are enabled.

## Slice 39: AI external-effect recovery (delivered)

Delivered October 9, 2026, following approval of the separate device-effect
recovery authority. The bounded batch is
`ai.connection.credential.{set,delete}` and `ai.connection.probe`.
No browser controls, automatic probes, generation forms or additional approval
modes are enabled.

Contracts/ports: credential PUT/DELETE and synthetic connection-test POST require
an exact positive connection revision and UUID attempt key. Typed responses carry
operation/key/connection identities, the committed reservation revision and
`updatedAt`, completion state/time and an immutable sanitized result. Secret-free
OPS forms retain only the expected revision; credential values belong exclusively
to the live write-only owning request, never OPS, SQLite, fingerprints or audits.
The key identifies the set intent, not the secret: replay cannot apply another
credential value. A replacement requires a new key.

Implementation: a short AI-owned intent transaction checks replay first, then
revision and any unknown attempt, advances the connection revision once, and
records correlated reservation/intent audits. Keyring and provider calls occur
outside transactions. A second transaction records the result and presence-only
credential audit together. Ambiguous failure/interruption or result-commit failure
leaves `outcome_unknown`; recovery never repeats the effect or infers replacement
success from presence. Explicit acknowledgement closes uncertainty as `abandoned`
without claiming success/failure. It cannot close an in-process operation; repair
or another probe requires a fresh key and current revision.

Persistence/integration: the current greenfield baseline adds
`ai_external_operations`, with immutable intents and one guarded result
completion. Exact schema/retained validation check its constraints, indexes,
trigger bodies, canonical request/result, timestamps, complete correlated history
and connection-revision lineage. Typed read-only ID/key endpoints and the narrow
source-owned OPS reader use original results, not current device state. Every
receipt requires device-local revalidation; Settings reads no longer initiate a
probe. Unknown OPS attempts stay unresolved until explicit acknowledgement or a
recorded completion. Encrypted restore preserves history and unknown attempts,
not secrets or current readiness.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real SQLite credential set/delete, bounded synthetic probe and owning HTTP/OPS recovery; one reservation revision increment |
| Invalid combinations | Exact revision/UUID validation, stale conflicts, extra/secret OPS fields, unknown and in-process acknowledgement guards |
| Idempotency/retry | Original result after later configuration changes; changed metadata conflicts; duplicate submissions never repeat the external call; explicit acknowledgement and fresh-key repair |
| Transaction rollback | Intent/audit failure prevents dispatch; result-write failure rolls back completion/audits and preserves the unknown intent without compensating/repeating the external effect |
| Persistence/schema | Guarded immutable intent/result, canonical sanitized payloads, correlated audit/revision reconstruction and tampered-result rejection |
| Backup/restore | Product-valid encrypted round trip preserves original external intents/results, OPS records and correlated history; recovered receipts require device-local validation |
| Query budget | One indexed original-result metadata query on the caller connection; no secret/provider reads or nested connection during recovery |

Focused tests are in `ai_governance/tests/test_external_effects.py`,
`ai_governance/tests/test_api_contracts.py` and
`operator/tests/test_ai_recovery.py`. The final focused run passes 104 tests across
all AI-governance tests and the AI OPS recovery tests. The related regression run
passes 234 tests including OPS recovery composition and endpoint contracts.
Changed-file Ruff lint/format checks and `git diff --check` pass. Only focused
tests are run; no consequential browser controls are enabled.

## Slice 41: Property/Space inventory and ownership OPS recovery registration (delivered)

Delivered October 9, 2026, for the confirmed nine forms:
`portfolio.property.{create,patch,archive,restore}`, `portfolio.ownerships.replace`
and `portfolio.space.{create,patch,archive,restore}`. The existing seven manual
status forms are unchanged. No browser controls or automatic dispatch are enabled.

Contracts/ports: explicit incomplete forms retain `expectedPropertyRevision`;
creation requires zero at preparation. Nested spaces and ownerships are bounded
to 100 entries each, with strict revision/confirmation types, bounded text and
extra-field rejection, plus the existing OPS 64 KiB payload ceiling. Initial
occupancy/availability and inline Party creation retain the owning command shapes.
Space edits/archive/restore require `spaceId` and bind to the parent Property.

Implementation: bootstrap constructs the owning Portfolio commands to obtain
their normalized canonical fingerprints. Patch fingerprints preserve supplied
field presence, including explicit nulls. Preparation checks the shared Property
revision, parent lifecycle, office-suite creation eligibility and child membership
and lifecycle. Recovery never invokes a mutation. All nine forms use the existing
Portfolio inventory ledger; no schema or additional ledger is introduced.

Persistence/integration: a source-owned reader projects original operation ID,
action, fingerprint, target ID, status and committed Property revision with one
indexed key query on the caller's connection. OPS receipt `sourceKind/sourceId`
identify the revision-owning Property; `result.targetId` identifies the original
Property or Space, including server-assigned creation IDs. Runtime and retained
OPS validation share the same nine bindings. Source effects, receipt and correlated
audits retain Slice 14's atomic transaction and immutable original-result replay.

Focused validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | All nine forms save, prepare, dispatch through real HTTP/SQLite and reconcile; nested initial status and inline owner inputs |
| Invalid combinations | Incomplete preparation, foreign child and stale revision rejected; strict types, nested limits and undeclared fields |
| Idempotency/retry | Canonical fingerprint parity through reconciliation; all nine original responses replay after later mutations; changed creation payload conflicts |
| Rollback | Required operation-audit failure rolls back Property edit/revision/receipt; unresolved OPS attempt remains recoverable and succeeds on explicit retry |
| Persistence/schema | Full current-schema validation of reconciled records; rewritten saved payload rejected; existing Slice 14 receipt/audit/trigger tampering proofs retained |
| Backup/restore | Encrypted LOCAL-002 round trip preserves complete inventory receipt, OPS record/operation rows and correlated Portfolio audits and passes full product validation |
| Query budget | One indexed receipt SELECT on the caller-owned connection, without nested connections or loading the complete stored response |

Focused tests: `operator/tests/test_inventory_recovery.py`,
`operator/tests/test_command_recovery.py`, `operator/tests/test_recovery_composition.py`,
`operator/tests/test_endpoint_contracts.py` and `portfolio/tests/test_inventory_readiness.py`.
Validation: 16 Slice 41 tests pass; 236 related focused Portfolio, OPS composition,
endpoint-contract and AI recovery tests pass. The focused command-recovery and
Slice 14 inventory checks also pass. Changed-file Ruff lint/format and diff checks
pass. No full-suite run or frontend change is included.

## Command-safety readiness inventory

This inventory is deliberately not a claim that consequential commands are all ready.
UI controls and automatic retries remain gated until their owning contracts are complete.

| Workflow | Current boundary | Remaining gate |
| --- | --- | --- |
| OPS preferences/recovery | Revision check, immutable operation receipt, same-key replay, payload conflict | Consume these contracts in the future browser transport |
| Communication create/patch/record/correct | Required revision/key, immutable typed original receipt and detailed conflict; explicit OPS form/receipt composition | Slices 10 and 19 backend contracts delivered; browser transport remains gated |
| Maintenance issue and child commands | Shared issue revision, required key, atomic effects and immutable typed receipts; explicit OPS issue/child forms | Slices 11 and 19 backend contracts delivered; browser transport remains gated |
| Task creation | Required revision zero and UUID key; immutable creation receipt, replay, payload conflict and OPS reconciliation | Backend contract delivered in slice 7; future browser transport must retain the exact command fingerprint and attempt key |
| Task waiting/follow-up | TASK-002 expected revision, idempotency and operation lookup; explicit OPS forms | Slice 19 registration delivered; browser attempt integration remains gated |
| Task start/complete/cancel/reopen and reminder add/acknowledge/dismiss | Required parent revision and UUID key; atomic immutable receipt, typed response and lookup, same-key replay; explicit OPS forms | Slices 8 and 19 delivered; browser transport/controls remain gated |
| Task editing/deletion | Required shared revision/key, immutable edit/no-op/delete receipts and retained tombstones; explicit OPS forms | Slices 9 and 19 delivered; browser transport remains gated |
| Portfolio manual status | Required revision/key, complete typed snapshots/conflicts and immutable operation/key lookup; explicit OPS forms | Slices 12 and 19 delivered; browser transport/controls remain gated |
| Lease draft/child and timeline actions | Required shared Lease revision/key, immutable original receipts and public read-only ID/key lookup; timeline actions also require the independent Space revision | Slice 13 source contracts and Slice 30 OPS recovery registration delivered; browser controls remain gated |
| Property/Space lifecycle and ownership changes | Required shared Property revision/key, atomic immutable original receipts, typed conflicts and read-only ID/global/scoped key lookup | Slice 14 source contracts and Slice 41's nine inventory OPS forms delivered; browser transport follows |
| Rent and prepaid-check commands | Shared ledger revision/key, immutable original receipts, atomic check/receipt/reminder effects and read-only key recovery; Owner receipt creation uses the same ledger contract | Slice 15 source contracts and all approved Finance OPS batches in Slices 31A–31E delivered; browser transport remains gated |
| Expense, Deposit and Owner-report commands | Required aggregate revision/key, original-result recovery, atomic child effects; Owner verification checks both report and ledger revisions | Slice 15 source contracts, Slice 28 category contracts and Slices 31C–31E OPS registration delivered; browser controls remain gated |
| Intake commands | Required source/evidence revisions, immutable original operator results and indexed recovery; consumer attention remains transaction-aware | Slice 16 source contract and Slice 32's six local-operator OPS forms delivered; system integrity remains source-owned, INGEST-002 consumer consequences belong to UI-002; browser transport follows |
| Files upload / link archival | Required UUID key; immutable original result and bounded recovery; archival requires association revision and returns a current-link conflict snapshot | Slice 17 source contract and Slice 33's two OPS forms delivered; internal reuse and system storage verification are not standalone OPS forms; browser transport follows |
| Owning attachments / inspection lifecycle | Intake and Inspection own immutable receipts and Files batches; Inspection uses a lease-scoped revision and separate template revisions | Intake source contract and import OPS recovery delivered in Slices 16 and 32; Inspection source contract and ten OPS forms delivered in Slices 18 and 34; internal attachment consequences remain owning-workflow operations, not extra Files forms; browser transport follows |
| Party identity | Required Party revision/UUID key, immutable identity receipts, detailed stale conflicts and indexed ID/global-key recovery | Slice 21 source contracts and Slice 35 OPS registration delivered; browser controls remain gated |
| Party contact methods | Required shared Party revision/UUID key, immutable contact results, atomic owning-reference coordination and shared indexed recovery; Tenant resolutions additionally require their current Tenant revision | Slice 22 source contracts and Slice 35 OPS registration delivered; internal role-reference resolution remains an atomic owning consequence; browser controls remain gated |
| Tenant creation/designation, profile/preferences, archive/restore | Required Tenant revision/UUID key, immutable original Tenant results, detailed stale conflicts and indexed ID/global-key recovery; Party identity/contact effects and preference-resolution receipts commit atomically | Slice 23 source contracts and Slice 35 OPS registration delivered; consequential browser controls remain gated |
| Provider creation/designation, profile, archive/restore | Required Provider revision/UUID key, immutable identity/profile results, current-profile stale conflicts and indexed ID/global-key recovery; initial Party/contact/child/category effects and audits commit atomically | Slice 24 source contracts and Slice 36 OPS registration delivered; browser controls remain gated |
| Provider services, areas, work history, references and reputation | Required shared Provider revision/UUID key, immutable original child results, atomic child/profile/audit effects and indexed ID/global-key recovery | Slice 25 source contracts and Slice 36 OPS registration delivered; browser controls remain gated |
| Provider categories and assignments | Required category revision/key or shared Provider revision/key; assign/restore also checks category revision; immutable typed original results and indexed recovery | Slice 26 source contracts and Slice 36 OPS registration delivered; browser controls remain gated |
| Owner concerns and follow-ups | Required shared concern revision/UUID key; immutable original concern and Task results, atomic correlated effects, detailed stale conflicts and indexed recovery; links use COM-owned receipts | Slice 27 source contracts and Slice 37 OPS registration delivered; browser controls remain gated |
| Expense categories / Maintenance taxonomy | Required category revision/UUID key, immutable original results and indexed recovery; Maintenance has a fixed vocabulary and issue-owned category-edit receipts | Slice 28 source contracts and Slice 31C Expense-category OPS forms delivered; Maintenance category editing uses the existing issue-owned form; editable Maintenance category administration is outside scope; browser transport follows |
| AI configuration and draft review | Required configuration revision or draft version and UUID key; immutable original results, detailed stale conflicts, indexed ID/key recovery; approval receipt and official effects commit in the owning transaction | Slice 29 source contracts and Slice 38 OPS registration delivered for currently registered commands; INGEST-002 approval/dismissal extensions move to UI-002; core browser controls remain gated pending transport integration |
| AI credentials and connection probes | Required connection revision/key; durable sanitized intent/result, explicit uncertainty acknowledgement, original ID/key/OPS recovery; no automatic external retries | Slice 39 delivered under its approved non-atomic recovery contract; device-local readiness and consequential browser controls remain gated |

The registry now contains 192 explicit command-form keys, including all 41
Slice 31A–31E forms, six Slice 32 forms, two Slice 33 forms, ten Slice 34 forms,
thirteen Slice 35 forms, 32 Slice 36 forms, seven Slice 37 forms, eight Slice 38 forms
and three Slice 39 forms and nine Slice 41 forms,
plus the three existing task-create, maintenance-issue-create and communication-record
schemas (195 total). Only these registered schemas can
begin recoverable attempts. An idempotency field alone does not prove readiness.
Other source-owned APIs remain available but are not thereby registered for
OPS recovery. This inventory does not authorize generic UI retries.

## Remaining backend readiness slices

Updated October 9, 2026. Slices 31A–31E are delivered for their 41 approved
rent-ledger, prepaid-check, synchronization, Expense/category, deposit and
Owner-report forms.
Slice 32 is delivered for its six approved local-operator Intake forms.
Slice 33 is delivered for public upload and link archival.
Slice 34 is delivered for its ten approved Inspection forms.
Slice 35 is delivered for its thirteen approved Party/Tenant forms.
Slice 36 is delivered for its 32 approved Provider/category forms.
Slice 37 is delivered for its seven approved Owner-concern forms.
Slice 38 is delivered for its eight approved AI configuration/review forms.
Slice 39 is delivered for its three approved secret-free AI external-effect forms.
Slice 41 is delivered for its nine approved Portfolio inventory/ownership forms.
Consuming delivered contracts in browser transport remains subsequent UI work.

Slices 9–30 delivered their selected source-owned backend and recovery contracts.
Reuse those commands when they apply to the remaining work.

### Remaining consequential workflow gates — ordered slices

All approved source-owned readiness slices through Slice 30 are delivered.
Core browser integration consumes the delivered OPS batches below. Feature-specific
INGEST-002 readiness is tracked separately under UI-002, rather than as another
UI-001 slice. Read-only directories and details may already use delivered contracts;
this inventory does not authorize additional command registrations.

Slices 37–39 completed their approved bounded OPS registration batches. Future
registrations still require exact batch approval and must reuse the owning
commands, revisions, fingerprints and immutable original receipts; do not add
another mutation ledger or reconstruct results from current state. Preserve the 64
original forms delivered in Slices 19 and 30, all 41 Slice 31A–31E forms,
the six Slice 32 forms, the two Slice 33 forms, the ten Slice 34 forms,
the thirteen Slice 35 forms, the 32 Slice 36 forms, the seven Slice 37 forms and
the eight Slice 38 forms, three Slice 39 forms and nine Slice 41 forms.
Each registration must connect typed request/result/conflict contracts, command
dispatch and source-owned ID/key recovery to OPS and prove interrupted-attempt
recovery. No slice below enables browser controls.

The former planned Slice 40 (INGEST-002 approval and domain-dismissal extensions)
is moved to [UI-002 readiness work](UI-002_DESIGN_preliminary.md#ingest-002--issue-review-readiness-and-recovery-former-slice-40).
It is not a remaining UI-001 slice. Slices 29 and 38 retain their delivered
generic AI configuration/review contracts; Slice 32 retains its six local-operator
Intake forms. Additional issue-review handlers, modes and OPS forms require
INGEST-002 readiness and UI-002 delivery registration.

### Ordered remaining UI-001 backend slices

Implement in the following order. Slice 40 remains assigned to UI-002; do not
reuse its number. Slice 41 is delivered; Slices 42–43 remain planned work.
Slice 41 closes domain/OPS readiness before React work. Slices 42–43 implement
the server portion of the UI-001 foundation; they can use HTTP/static fixtures
before a real web build exists, and require final packaged-browser validation
once the frontend is available.

1. **Slice 42: Local browser transport security.**
   Implement architecture-compliant loopback startup, allowed Host validation,
   explicit development/production Origin policy and cross-origin mutation
   protection across all mutation routes, including multipart uploads and AI
   credential/probe operations. Define and document handling of absent/null
   Origin, non-browser CLI/setup callers and preflight requests without weakening
   browser-origin checks. Keep relative API requests and the same-origin production
   contract; no application login or permissive CORS. Reject disallowed requests
   before any domain write, file publication, credential change or external call.
   Verify valid production/development requests, hostile Host/Origin combinations,
   unrelated-origin simple/multipart requests, accepted CLI/setup behavior,
   workspace-unavailable bootstrap and unchanged revision/idempotency recovery.
   Security failures must cause no domain-state, command-receipt, correlated domain-audit or external-effect mutation. No schema
   or backup format change; security configuration remains device/deployment local.
   Request checks must not add per-record queries or open extra domain snapshots.

2. **Slice 43: Packaged static serving and restricted SPA fallback.**
   After Slice 42, serve the compiled web assets on the same local FastAPI origin.
   Preserve `/api`, `/health`, `/docs`, `/redoc` and `/openapi.json`; return the SPA
   entry only for registered UI-001 browser routes with GET/HEAD and an HTML Accept
   header. Unknown API routes, missing assets, other methods and unregistered UI-002
   routes retain truthful errors. Prevent path traversal and keep workspace files
   outside static roots; FILE-001 remains their access boundary. Define safe cache
   behavior for the entry document and versioned assets, restrictive production
   CSP/security headers and explicit missing-build handling. Packaging must include
   the web build without incorporating workspace data or secrets. Use fixture
   assets for server tests; finish with an actual packaged-build smoke test when
   the web scaffold exists. Validate direct/deep-link loads, HEAD/Accept/method
   combinations, missing API/assets, traversal, security headers and a gated
   workspace bootstrap. Static fallback must not open the workspace or query its
   database. No persistence/schema or backup format change; restored workspaces
   retain the ordinary runtime readiness gate.

Internal file reuse, storage verification and system Intake transitions remain
owned by their source/consumer contracts. Their omission from standalone OPS
forms is intentional, not another UI-001 slice. If a new operator workflow is
proposed for them, define its scope separately before registration. Production
model/action availability remains capability-gated; optional AI adapters do not
block manual UI-001 workflows. DASH-001 aggregation and UI-002 issue review remain
outside these three slices.

### Completion criteria and sequencing

For each future approved slice, document its owning command contract, delivered
behavior, receipt/recovery authority and focused test locations. Mark it
delivered when the applicable proofs below pass, using the same validation
matrix as the delivered slices.

Validation matrix:

| Area | Focused proof |
| --- | --- |
| Happy paths | Real persistence-backed commands, lifecycle changes and no-ops; effective changes advance the owning revision according to its contract; original typed results are recorded before commit |
| Invalid combinations | Required revision/key validation from HTTP and direct callers; lifecycle, ownership and field-combination guards; typed stale conflicts include the current owning state |
| Idempotency/retry | Same-key replay returns the original result after later changes; changed payload reuse conflicts; concurrent duplicate submissions and competing revisions behave correctly; read-only ID/key recovery uses retained receipts |
| Rollback | Domain effects, revisions, receipts and correlated audits commit or roll back together; cross-module writes and attachment publication/cleanup participate where applicable |
| Persistence/schema | Exact current schema, constraints, indexes and immutable receipt triggers; canonical requests/fingerprints/results, legal revision history and correlated audit evidence; retained-data tampering is rejected |
| Backup/restore | Encrypted LOCAL-002 round trip preserves stable IDs, original results, revisions, lineage and correlated audit history |
| Query budget | Bounded projections and indexed recovery; no per-record recovery reads, N+1 queries or post-commit reconstruction of original mutation results |

Slices 21–30 completed contracts/ports, implementation, persistence, focused
tests and integration for their selected workflows. Reuse their delivered
contracts. Any future backend slice follows the same sequence and records its
proofs in the delivered sequence and command-safety inventory.

Slices 37–39 have proved their approved OPS batches against the delivered source
contracts, including Slice 39's explicitly approved external-effect uncertainty
contract. INGEST-002 readiness work formerly labeled Slice 40 is tracked under
UI-002 and does not block core UI implementation. Slice 41 completes the nine
Portfolio inventory registrations. The 195
registered OPS schemas stay available; browser transport integration follows
readiness for each selected workflow. Pause for any new product or lifecycle decision.

No consequential browser controls are enabled by this backend checklist. A
workflow can remain gated while independently ready workflows proceed to UI
implementation; unfinished features must not be presented as safely retryable.

## Subsequent UI slices

After Slice 41, begin React/Vite and reproducible generated contracts while
completing the server foundation in Slices 42–43. Before enabling consequential
browser workflows, verify transport security and actual packaged serving; then
complete bootstrap/workspace gate; appearance and
navigation; accessible disclosures and async states; directories/workspaces and actual
domain actions; recovery/search/coverage/waiting; AI controls; shared Home primitives;
focused browser/accessibility/packaging verification. DASH-001 aggregation stays separate.
