# COM-001 — Manual Communication Ledger and Follow-up Context

## Purpose

`COM-001` gives the local operator an auditable timeline of communications with owners, tenants, and other saved parties. It records what the operator says occurred, preserves the relevant property, lease, rent, renewal, or task context, and can create a related follow-up task.

This is a manual local interaction ledger. An `outbound` entry means that the operator records an already-sent or already-spoken communication; it never sends email or SMS. An `inbound` entry means that the operator records a received interaction; it does not ingest an external mailbox or SMS source.

## Scope and boundaries

COM-001 provides:

- Draft and recorded communication entries for any saved party, including client owners and tenants.
- One or more participant snapshots, typed context links, and an optional atomic TASK-001 follow-up.
- Immutable recorded history with explicit, reasoned corrections instead of silent edits.
- Property-local time semantics when a linked property, space, or lease determines one property time zone.
- Typed backend/API contracts, fail-closed audit events, exact current-schema validation, and encrypted backup/export/restore coverage.

COM-001 does not provide:

- Email, SMS, letter, portal, push, calendar, or any other delivery. `COM-002` later owns connected-account delivery and delivery tracking.
- Gmail, Outlook, SMS, voice-note, transcript, attachment, thread, source-message, or external-message ingestion. `INGEST-001` later owns those source records and may add a typed source link to this timeline.
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
| `supersedes_communication_id`, `superseded_by_communication_id` | Optional one-to-one correction lineage; only recorded rows may participate. |
| `correction_reason` | Required bounded sensitive operator reason when superseding a recorded entry. |
| `created_at`, `updated_at` | Required UTC audit timestamps. |

Each communication has one or more `communication_participants`. A participant stores a required `party_id`, optional `party_contact_method_id`, required role (`sender`, `recipient`, `reporter`, or `other`), and immutable display snapshots for the party and selected contact method. A selected contact method must belong to the selected party. New recordings select an active party and, if supplied, an active contact method. Archived facts remain readable through snapshots; later lifecycle changes do not rewrite history.

Each communication has zero or more `communication_links`, each with a stable UUID, its communication ID, a typed `entity_type`, and a target UUID. Property-derived links additionally retain a nullable `property_timezone_snapshot`: it is the canonical IANA zone resolved when the draft link was last validated. It is returned as `propertyTimezoneSnapshot` in the link response so callers can explain the preserved local context. COM-001 accepts these typed links, with owning feature slices adding target validation when their aggregate becomes current:

- `party`, `property`, `space`, `lease`, `rent_expectation`, `rent_receipt`, `renewal_option`, `task`, `maintenance_issue`, and `owner_concern`.

The owning application module validates every link target in the same immediate transaction. Unknown, misspelled, nonexistent, or unsupported target types are rejected; link validation is never fail-open. MAINT-004 supplies `maintenance_issue` target validation and OWNER-004 supplies `owner_concern` target validation. Leads, applications, and ingested-source links remain deferred to their owning feature slices and require an explicit current-schema extension.

## Recording, correction, and time rules

Drafts may be created and patched. A patch uses unset-field tracking: omitted fields remain unchanged, while an explicitly supplied nullable field follows its documented clear rule. An empty patch is a no-op: it does not update timestamps or append an audit event.

Recording a draft validates its participants, selected contact methods, links, direction/channel, and time-zone context within one immediate transaction and changes it to `recorded`. Every draft link revalidation refreshes its property-timezone snapshot before the occurrence-zone comparison; once recorded, the snapshot is immutable and validation never compares it with a property's later mutable address or zone. A recorded communication is immutable. To correct it, the operator creates a new recorded communication with a required correction reason and a `supersedesCommunicationId`; the transaction marks the source `superseded`, sets both lineage links, and records correlated audit events for source and replacement. Corrections cannot branch or cycle, and a superseded communication cannot be corrected again.

If a communication has a property, space, or lease link, COM-001 resolves the linked property time zone through an application-level portfolio/lease read port. More than one linked property context is allowed only when all resolved IANA zones agree; otherwise the command is rejected as ambiguous. The stored `occurred_timezone` must equal that resolved zone. Without a property-derived context, the operator supplies a valid IANA zone with the aware occurrence timestamp. This preserves the original local context without guessing.

## TASK-001 follow-up

The operator may request one follow-up while creating or recording a communication. COM-001 creates the TASK-001 task in the same immediate transaction, gives it a typed `communication` related-record reference, and uses the same correlation ID for the communication, task, and audit events. Task title, due time, and all task lifecycle rules remain owned by TASK-001.

A communication can have more than one related task over its life when a later workflow creates one, but COM-001 never treats task completion as a mutation of the communication. Read views project linked task status and due context; TASK-001 owns completion, reminder, dismissal, and transition history.

## API and read contracts

The backend exposes typed, unknown-field-forbidding API contracts:

- `POST /api/communications` creates a draft or immediately records an interaction, optionally with one follow-up task.
- `GET /api/communications` returns a bounded cursor page, ordered by occurrence time and ID, with filters for party, property, space, lease, typed link, direction, channel, status, local date range, and linked-task status.
- `GET /api/communications/{communicationId}` returns the complete timeline entry, participant snapshots, links, correction lineage, and follow-up-task projection.
- `PATCH /api/communications/{communicationId}` changes only a draft.
- `POST /api/communications/{communicationId}/record` records a valid draft.
- `POST /api/communications/{communicationId}/correct` records an explicit replacement for a current recorded entry.

All mutating requests carry a client-generated idempotency UUID. COM-001 stores Finance-style domain-owned operation fingerprints or an equivalent communications-owned immutable operation record; the audit ledger is evidence, not idempotency state. A follow-up-producing operation retains its `follow_up_task_id`, allowing startup and restore validation to require exactly one correlated task-created audit and one parent `follow_up_created` audit even if an archive was tampered with. SQLite update/delete triggers make operation records append-only. Responses use explicit nested participant, contact snapshot, context-link, follow-up, and correction-lineage models. Malformed values and invalid commands return `422`; missing resources return `404`; stale lifecycle, conflicting context, duplicate idempotency payload, correction, and concurrent conflicts return typed `409` with machine-readable codes.

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

The `communications` application service depends only on application-level transaction-aware ports for parties/contact methods, portfolio/lease time-zone and context validation, finance link validation, renewal options, and TASK-001 creation/read projection. Bootstrap composes SQLite implementations against the shared transaction connection. Communications must not import other modules' SQLAlchemy models or persistence adapters, and the dependent modules must not import communications persistence.

OWNER-004 may project bounded communication summaries and validate one optional originating recorded communication through consumer-neutral Communications readers. A communication-linked `owner_concern` remains owned by owner-management; participant role `reporter` is local to the communication and does not establish or change the concern's raising owner. Communication correction never rewrites concern attribution, context, or lifecycle.

The greenfield baseline adds communication tables, exact schema validation, current expected-table registration, current data-integrity validation, archive validation, backup/export/restore coverage, and operation/idempotency records. It adds no migration compatibility, adoption path, compatibility aliases, or legacy tables. Every retained communication, participant snapshot, link, follow-up task reference, correction lineage, and correlated audit event survives encrypted backup/restore.

## UI-001 scope and acceptance criteria

`UI-001` delivers the deferred operator experience before `DASH-001`:

- property, lease, tenant, owner, and task-context timeline views;
- manual inbound/outbound/internal recording with participant/contact selection;
- draft, record, correction, and task-follow-up actions with explicit sensitive-data cues;
- local-time display and structured filters; and
- end-to-end tests for lifecycle, correction, follow-up, privacy, and error states.

COM-001 backend acceptance coverage includes role-neutral party participation; active participant/contact validation; typed context validation; property-time-zone ambiguity; draft immutability boundaries; correction lineage; atomic follow-up creation; idempotency; generalized/contextual audit redaction; exact-schema/data rejection; typed HTTP errors; bounded reads; and encrypted backup/export/restore. UI acceptance remains pending until UI-001 completes.
