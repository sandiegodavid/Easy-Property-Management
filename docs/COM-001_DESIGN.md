# COM-001 — Manual Communication Ledger and Follow-up Context

## Purpose

`COM-001` gives the local operator an auditable timeline of communications with owners, tenants, and other saved parties. It records what the operator says occurred, preserves the relevant property, lease, rent, renewal, or task context, and can create a related follow-up task.

This is a manual local interaction ledger. An `outbound` entry means that the operator records an already-sent or already-spoken communication; it never sends email or SMS. An `inbound` entry means that the operator records a received interaction; it does not ingest an external mailbox or SMS source.

The command safety contract below is authoritative for UI-001 integration. [COM-001 Command Readiness](COM-001_COMMAND_READINESS.md) supplements it with exact trigger SQL, external caller requirements, and the validated test matrix.

## Scope and boundaries

COM-001 provides:

- Draft and recorded communication entries for any saved party, including client owners and tenants.
- One or more participant snapshots, typed context links, and an optional atomic TASK-001 follow-up.
- Immutable recorded history with explicit, reasoned corrections instead of silent edits.
- Property-local time semantics when a linked property, space, or lease determines one property time zone.
- Typed backend/API contracts, fail-closed audit events, exact current-schema validation, and encrypted backup/export/restore coverage.

COM-001 does not provide:

- Email, SMS, letter, portal, push, calendar, or any other delivery. `COM-002` later owns connected-account delivery and delivery tracking.
- Gmail, Outlook, SMS, voice-note, transcript, attachment, thread, source-message, or external-message ingestion. `INGEST-001` owns those source records and adds a typed `intake_source` link to this timeline through COM-001's owning-feature validation extension. Importing a source does not create a communication.
- File attachment upload or document storage. A later communication attachment slice must use FILE-001 through a communication-owned transaction boundary.
- Automated rent reminders, renewal notices, or dashboard prompts. The operator may create a TASK-001 follow-up manually; dashboard surfacing comes later.
- React screens. `UI-001`, immediately before `DASH-001`, owns the operator timeline, recording, correction, and follow-up workflow.
- Contact delivery preferences, expected communication methods, consent, legal notice delivery, or legally sufficient notice proof.

The current hard dependencies remain `TASK-001` and `TEN-001`. TEN-001 established the shared `parties` and `party_contact_methods` boundary used by all roles. COM-001 intentionally does not require a party to have an active tenant profile: an owner-only, provider, or future role party can participate in a communication. It does not add a hard dependency on a separate owner module.

## Core model

All IDs are UUIDs. Timestamps are timezone-aware UTC text. Dates and timestamps use the existing US-only MVP policy.

### `communications`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `direction` | Required `inbound`, `outbound`, or `internal`. `outbound` records an operator-reported completed contact; it is not a send request. |
| `channel` | Required `phone`, `email`, `sms`, `in_person`, `letter`, or `other`. |
| `subject` | Required trimmed, bounded 1–240-character operator summary. |
| `body` | Required bounded 1–10,000-character sensitive narrative. |
| `occurred_at_utc` | Required aware instant supplied by the operator. |
| `occurred_timezone` | Required IANA zone used for operator presentation and local-date rules. |
| `status` | `draft`, `recorded`, or `superseded`. Only drafts are editable. |
| `recorded_at` | Required only for `recorded` and `superseded` rows. |
| `supersedes_communication_id`, `superseded_by_communication_id` | Optional one-to-one correction lineage on recorded or superseded history. A replacement may itself be superseded while retaining its backward link and correction reason. |
| `correction_reason` | Required bounded sensitive operator reason when superseding a recorded entry. |
| `created_at`, `updated_at` | Required UTC audit timestamps. |
| `revision` | Required positive integer shared across payload, participants, links, recording, and correction. Creation starts at 1; each accepted mutation increments it once. |

### `communication_operations`

The existing domain-owned operation records retain immutable command outcomes; the audit ledger supplies correlated evidence rather than idempotency state.

| Field | Rule |
| --- | --- |
| `id` | Stable operation UUID, returned as `operationId` and used for receipt lookup. |
| `idempotency_key` | Required globally unique client UUID. |
| `action` | `created`, `patched`, `recorded`, or `corrected`. |
| `target_communication_id`, `result_communication_id` | Create has no target; patch/record target and result are the same communication; correction targets the source and returns its replacement. |
| `expected_revision` | Required nonnegative integer. Create requires 0; all other actions require at least 1 and check the target's current revision. |
| `result_revision` | Required positive integer matching the original response's result communication revision. Correction returns replacement revision 1 while advancing the source separately. |
| `outcome` | `applied` or `no_op`; only a patch may be `no_op`. |
| `request_json`, `request_fingerprint` | Canonical typed request including action, target, payload, and expected revision, plus its SHA-256 fingerprint. |
| `response_json` | Canonical immutable original command response, including `operationId`, `revision`, `outcome`, participants, links/context, and follow-up projections captured at acceptance. |
| `correlation_id`, `created_at` | Required correlation UUID and UTC operation timestamp. |
| `follow_up_task_id` | Optional retained task UUID for atomic follow-up/audit validation. |

All added fields are non-null except the documented target and follow-up references; no compatibility defaults or legacy schema are supported. Exact schema validation requires the owning model's revision, action, outcome, and create/non-create expectation checks. Update, delete, and conflicting insert/replace guards prevent receipt rewriting, including SQLite `INSERT OR REPLACE` with recursive triggers disabled.

Each communication has one or more `communication_participants`. A participant stores a required `party_id`, optional `party_contact_method_id`, required role (`sender`, `recipient`, `reporter`, or `other`), and immutable display snapshots for the party and selected contact method. A selected contact method must belong to the selected party. New recordings select an active party and, if supplied, an active contact method. Archived facts remain readable through snapshots; later lifecycle changes do not rewrite history.

Each communication has zero or more `communication_links`, each with a stable UUID, its communication ID, a typed `entity_type`, and a target UUID. Property-derived links additionally retain a nullable `property_timezone_snapshot`: it is the canonical IANA zone resolved when the draft link was last validated. It is returned as `propertyTimezoneSnapshot` in the link response so callers can explain the preserved local context. COM-001 accepts these typed links, with owning feature slices adding target validation when their aggregate becomes current:

- `party`, `property`, `space`, `lease`, `rent_expectation`, `rent_receipt`, `renewal_option`, `task`, `maintenance_issue`, `owner_concern`, and `intake_source`.

The owning application module validates every link target in the same immediate transaction. Unknown, misspelled, nonexistent, or unsupported target types are rejected; link validation is never fail-open. MAINT-004 supplies `maintenance_issue` target validation, OWNER-004 supplies `owner_concern` target validation, and INGEST-001 supplies `intake_source` target validation. The `intake_source` database vocabulary and validator are activated with INGEST-001, not before a retained-source table exists. Leads and applications remain deferred to their owning feature slices and require an explicit current-schema extension.

An `intake_source` link points to retained evidence; it does not make Communications a second evidence store. COM-001 retains only its operator-authored subject/body and ordinary participant snapshots. It does not copy source bodies, attachments, external message IDs, account identity, provenance, revisions, or fingerprints. Recording or correcting a communication never changes the source, and correcting or superseding a source never rewrites a recorded communication.

A new link requires a current retained `ready` source. Once a communication is recorded, later source correction or supersession does not invalidate its historical link: detail views resolve the exact retained source ID and visibly identify its current/superseded state. A new communication that should cite the replacement selects that replacement explicitly; COM-001 never follows supersession automatically.

## Recording, correction, and time rules

Drafts may be created and patched. A patch uses unset-field tracking: omitted fields remain unchanged, while explicitly clearing a required payload, participant, or link field is rejected. Every command requires a UUID key and an integer expected revision at both the HTTP and application boundary; revision values cannot be booleans, negative, omitted, or coerced from strings. Create uses expected revision 0. New patch, record, and correction commands use the target revision from a fresh detail read.

Within the existing immediate transaction, operation-key lookup precedes revision, lifecycle, and mutable participant/link eligibility checks. Matching requests replay their immutable original receipt even after later mutations. A retained key with changed payload, action, target, or expected revision produces typed `idempotency_conflict`; a new key with a stale expectation produces typed `stale_revision` including `currentRevision`. Neither rejection writes an operation. The public application helper `command_fingerprint(action, target, command, expected_revision)` supplies the same canonical fingerprint to recovery consumers.

Payload, participant-only, and link-only changes advance the same revision once. Empty and semantically unchanged patches retain an explicit `no_op` operation receipt without incrementing revision, changing timestamps, or appending change audits. Their key remains bound to the original request and their receipt remains replayable after the draft is recorded.

Recording a draft validates its participants, selected contact methods, links, direction/channel, and time-zone context within one immediate transaction and changes it to `recorded`. Every draft link revalidation refreshes its property-timezone snapshot before the occurrence-zone comparison; once recorded, the snapshot is immutable and validation never compares it with a property's later mutable address or zone. A recorded communication is immutable. To correct it, the operator creates a new recorded communication with a required correction reason and a `supersedesCommunicationId`; the transaction marks the source `superseded`, sets both lineage links, and records correlated audit events for source and replacement. Corrections cannot branch or cycle, and a superseded communication cannot be corrected again.

Recording increments the draft revision once. Correction increments the source revision once and starts the replacement at revision 1. A current recorded replacement may subsequently be corrected, preserving its original backward link and correction reason when it becomes superseded. Receipt creation, follow-up insertion, and all associated audits share the same transaction and connection; any failure rolls back the entire command, allowing the same key to be retried without nested transactions or separate repositories.

If a communication has a property, space, or lease link, COM-001 resolves the linked property time zone through an application-level portfolio/lease read port. More than one linked property context is allowed only when all resolved IANA zones agree; otherwise the command is rejected as ambiguous. The stored `occurred_timezone` must equal that resolved zone. Without a property-derived context, the operator supplies a valid IANA zone with the aware occurrence timestamp. This preserves the original local context without guessing.

## TASK-001 follow-up

The operator may request one follow-up while creating or recording a communication. COM-001 creates the TASK-001 task in the same immediate transaction, gives it a typed `communication` related-record reference, and uses the same correlation ID for the communication, task, and audit events. Task title, due time, and all task lifecycle rules remain owned by TASK-001.

A communication can have more than one related task over its life when a later workflow creates one, but COM-001 never treats task completion as a mutation of the communication. Read views project linked task status and due context; TASK-001 owns completion, reminder, dismissal, and transition history.

## API and read contracts

The backend exposes typed, unknown-field-forbidding API contracts:

- `POST /api/communications` creates a draft or immediately records an interaction, optionally with one follow-up task.
- `GET /api/communications` returns a bounded cursor page, ordered by occurrence time and ID, with filters for party, property, space, lease, typed link, direction, channel, status, local date range, and linked-task status.
- `GET /api/communications/{communicationId}` returns fresh detail: current revision, complete timeline entry, participant snapshots, links, correction lineage, and live follow-up-task projection.
- `GET /api/communications/operations/{operationId}` returns the immutable original command receipt under its stable operation UUID, or `404` for an unknown operation.
- `PATCH /api/communications/{communicationId}` changes only a draft.
- `POST /api/communications/{communicationId}/record` records a valid draft.
- `POST /api/communications/{communicationId}/correct` records an explicit replacement for a current recorded entry.

All four mutating HTTP inputs require `idempotencyKey: UUID` and `expectedRevision: integer`, including create expectation 0. Command responses and receipt lookup use the typed original-detail receipt with required `operationId`, `revision`, and `outcome`; ordinary detail/list responses expose current revision without operation metadata. Retrying a command or looking up its receipt does not rebuild live detail. Receipt revision is historical proof of acceptance, not a current-state expectation: refresh detail before composing a new command. Later corrections, task transitions/tombstones, or context changes do not rewrite receipts; fresh task projections hide tombstones while retained task references remain valid.

A follow-up-producing operation retains its `follow_up_task_id`, allowing startup and restore validation to require exactly one correlated task-created audit and one parent `follow_up_created` audit even if an archive was tampered with. Responses use explicit nested participant, contact snapshot, context-link, follow-up, and correction-lineage models. Malformed values and invalid commands return `422`; oversized request content returns `413`; missing resources return `404`; lifecycle, context, correction, changed-key, and stale-revision conflicts return typed `409` with machine-readable codes. OpenAPI discriminates `stale_revision` with required `currentRevision` from `idempotency_conflict` and the other domain conflicts.

List and detail read models keep full body and participant-contact values out of generalized activity, but display the operator-authorized contextual timeline. Full-text search across subject/body is deliberately deferred: COM-001 supports bounded structured filtering only, until a privacy-preserving local search design specifies indexing, retention, and redaction behavior.

## Audit and privacy

Every required communication, participant, link, task-follow-up, record, and correction change is fail-closed on its required AUDIT-001 event. A correction shares one correlation ID across the superseded source, new entry, participant/link changes, and any new task.

General activity must redact:

- communication `subject`, `body`, and `correction_reason`;
- party and contact-method identifiers and participant display/contact snapshots;
- task-follow-up notes, task IDs, and detailed link identifiers; and
- idempotency keys and operator-only reasons.

Contextual communication history may display the recorded subject, body, participant snapshots, links, and correction reason to the local operator. Audit policies are schema-versioned and fail closed for an unregistered communication entity/version. Audit reasons themselves must remain concise non-sensitive action labels rather than copy sensitive narrative text.

## Architecture and persistence boundaries

The `communications` application service depends only on application-level transaction-aware ports for parties/contact methods, portfolio/lease time-zone and context validation, finance link validation, renewal options, Intake source validation when INGEST-001 is installed, and TASK-001 creation/read projection. Bootstrap composes SQLite implementations against the shared transaction connection. Communications must not import other modules' SQLAlchemy models or persistence adapters, and the dependent modules must not import communications persistence.

OWNER-004 may project bounded communication summaries and validate one optional originating recorded communication through consumer-neutral Communications readers. A communication-linked `owner_concern` remains owned by owner-management; participant role `reporter` is local to the communication and does not establish or change the concern's raising owner. Communication correction never rewrites concern attribution, context, or lifecycle.

The greenfield baseline adds communication tables, exact schema validation, current expected-table registration, current data-integrity validation, archive validation, backup/export/restore coverage, and operation/idempotency records. It adds no migration compatibility, adoption path, compatibility aliases, or legacy tables. Every retained communication, participant snapshot, link, follow-up task reference, correction lineage, and correlated audit event survives encrypted backup/restore.

Retained validation reconstructs typed canonical requests, verifies fingerprints and request/result agreement, correlates original result and source revisions with audit snapshots, checks historical child/task snapshots and no-op agreement with prior history, and requires contiguous revision history and current-state/audit agreement. Validation and restore never rewrite receipts. Encrypted restore preserves stable operation IDs and exact replay responses even when newer communication mutations are included in the backup.

## UI-001 scope and acceptance criteria

`UI-001` delivers the deferred operator experience before `DASH-001`:

- property, lease, tenant, owner, and task-context timeline views;
- manual inbound/outbound/internal recording with participant/contact selection;
- draft, record, correction, and task-follow-up actions with explicit sensitive-data cues;
- local-time display and structured filters; and
- end-to-end tests for lifecycle, correction, follow-up, privacy, and error states.

COM-001 backend acceptance coverage includes role-neutral party participation; active participant/contact validation; typed context validation; property-time-zone ambiguity; draft immutability boundaries; correction lineage; atomic follow-up creation; idempotency; generalized/contextual audit redaction; exact-schema/data rejection; typed HTTP errors; bounded reads; and encrypted backup/export/restore. INGEST-001 additionally verifies that a missing, malformed, non-ready, or already-superseded target fails closed for a new link; an existing link to a later-superseded retained source remains readable; source import creates no communication; and neither correction path mutates the other module. UI acceptance remains pending until UI-001 completes.

The command-readiness [validation matrix](COM-001_COMMAND_READINESS.md#validation-matrix) covers happy paths, invalid metadata/combinations, every command's replay after later mutation, changed-key and stale conflicts, no-op outcomes, atomic follow-up rollback/retry, receipt tampering and replacement guards, HTTP/OpenAPI, encrypted restore/replay, and one-SELECT replay/receipt query budgets. The focused backend proof is 30 passing tests and 18 passing subtests, with Ruff check and format check passing; it does not imply UI screen acceptance.
