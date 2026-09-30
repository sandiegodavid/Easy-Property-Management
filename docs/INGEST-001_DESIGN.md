# INGEST-001 — Retained Source Evidence and Provenance

## Purpose

`INGEST-001` gives the application a neutral, durable record of the evidence from which a later issue draft may be proposed. It retains a bounded source snapshot, trusted submission provenance, attachment references, source identity, technical processing state, and duplicate information without treating any extracted or assistant-supplied interpretation as fact.

The result is useful without an assistant or model. The local operator can import source evidence manually; later capabilities can read the same retained source, propose fields, compare those fields with the evidence, and require approval before Maintenance changes.

This is a backend and API slice. `UI-001` owns the eventual operator interface, `INGEST-002` owns issue-specific comparison and approval, and `MCP-001` owns connected-assistant authorization and transport.

## Scope and boundaries

INGEST-001 provides:

- one retained source per individual message, note, or transcript, with an optional conversation reference for grouping;
- a versioned canonical evidence envelope that preserves the exact bounded snapshot accepted by the application;
- source/provider identity, account-scope provenance, occurrence and receipt times, and trusted submitter provenance;
- attachment references through FILE-001, with no copied file metadata or filesystem path;
- separate technical-ingestion and operator-attention states;
- exact replay protection and account-scoped source deduplication, plus non-destructive probable-duplicate hints;
- a source projection with an opaque revision and SHA-256 fingerprint for AI-GOV-001 and INGEST-002;
- append-only correction, supersession, dismissal, and operation history; and
- exact-schema, retained-data, audit, archive, backup, and restore validation.

INGEST-001 does not provide:

- mailbox, SMS, chat, or calendar discovery; account credentials; polling; webhooks; or message sending;
- assistant authentication, grants, health, proposal receipts, or file-exchange/MCP transport;
- issue extraction, property/party matching, duplicate-issue detection, diagnosis, or provider recommendations;
- an AI draft, approval queue, or an official Maintenance issue;
- a second communication ledger or automatic COM-001 entry;
- audio recording, transcription execution, or audio deletion; or
- React screens.

An accepted source is evidence, not an assertion that an issue exists. Text in the source is untrusted data and never becomes an instruction to the application, model adapter, or connected assistant.

## Dependency alignment

| Dependency or follow-on | INGEST-001 relationship |
| --- | --- |
| AUDIT-001 | Every accepted source, revision, lifecycle decision, and sensitive read uses registered fail-closed audit policy. Audit is evidence, not idempotency storage. |
| FILE-001 | Owns immutable file metadata, content hashes, provider locations, bytes, and generic links. Intake owns whether a file link belongs to a source revision. |
| COM-001 | Remains a valid narrow dependency: INGEST-001 adds `intake_source` to COM-001's typed link vocabulary. Communications may summarize and link to a source, but neither module creates or edits the other's record. |
| AI-GOV-001 | Not a hard dependency. It later consumes a source projection and stores governed input and proposed output separately. Manual intake must work with AI disabled. |
| ISSUE-AI-001/002 | Later consumers of retained evidence. Their extraction, entity matching, and existing-issue similarity results are drafts, not source fields. |
| INGEST-002 | Owns source-versus-draft comparison, edit/link/dismiss decisions, and the atomic Maintenance consequence. It uses Intake's attention-state port. |
| MCP-001 | Authenticates an assistant, binds a verified grant/account identity, and calls Intake's internal admission port. Intake exposes no unauthenticated assistant endpoint. |
| VOICE-001 / VOICE-AI-001 | VOICE-001 owns audio capture/import. VOICE-AI-001 supplies transcript revisions. Intake owns the retained transcript and its source projection, not transcription or audio retention. |
| DASH-003 | Later composes unprocessed, failed, or low-confidence work. It must not infer these states from raw table scans. |

This division follows the modular-monolith rule in `ARCHITECTURE.md`: cross-module calls use small application protocols composed at bootstrap, caller-owned transactions where atomicity matters, and no imports of another module's SQLAlchemy models or repositories.

## Current implementation findings

The current application has working Audit, Files, Communications, Maintenance, and AI Governance modules, but no `intake` package, tables, migration registration, API router, bootstrap composition, audit policy, file-link validator, source reader, or retained-data validator.

The implementation must account for these existing contracts:

1. FILE-001 accepts links only for registered entity types and purposes. Intake therefore needs an `intake_source` file-link policy and validator.
2. `FileService.add_in_transaction(...)` uses the current FILE-001 adapters to publish and hash-verify content before writing file/link/audit rows on a caller-owned transaction. The returned object retains rollback ownership until the database result. Intake must hold every lease, roll all operation-owned content back on transaction failure, and create a `ready` source only in the transaction that records the complete verified attachment set.
3. COM-001 currently defers ingested-source links. Its link vocabulary, database constraint, bootstrap target validator, exact-schema validation, and tests must be extended together when INGEST-001 is implemented.
4. AI Governance already models opaque source revision and fingerprint inputs, but it has no Intake source adapter and no external-proposal workflow. INGEST-001 supplies only the source projection; it does not fill those later workflow gaps.
5. The application uses a greenfield latest-schema baseline. INGEST-001 updates that baseline, expected-table lists, current-data validation, sanitized fixtures, and archive validation; it does not add legacy compatibility aliases.
6. The application has no durable background-job system. Admission, file verification, retry, and integrity recovery must have explicit synchronous operations and restart-safe outcomes rather than depending on an invisible worker.

## Source and evidence definitions

### Source granularity

One source represents one email, SMS/chat message, operator note, or voice-note transcript. A mail thread or chat conversation is not stored as one ever-growing source. Related messages carry the same bounded `conversation_ref` and remain individually deduplicable, attributable, and reviewable.

### Meaning of “original source evidence”

For this feature, “original” means the exact canonical evidence snapshot accepted by the application, before extraction, summarization, matching, or operator edits to proposed fields. It does not mean an unlimited provider payload, arbitrary mail headers, a mailbox export, or trusted truth.

The versioned canonical envelope contains only:

- schema version and source kind;
- optional subject;
- required plain-text body or transcript;
- bounded sender/author and recipient descriptors with role, display value, and typed address where supplied;
- source occurrence time and its reported time-zone/offset context;
- optional provider, conversation, and external-source identifiers;
- attachment-link IDs, roles, and stable content hashes; and
- explicitly qualified provenance and confidence metadata allowed by that envelope version.

HTML is not rendered or stored in the envelope. An operator or adapter must supply plain text. An optional `.eml`, export, image, or other raw artifact can be retained as a FILE-001 attachment with purpose `raw_source`, but Intake never parses or executes it automatically.

Arbitrary provider JSON and arbitrary headers are rejected. Future envelope fields require a new registered schema version and retained validator.

## Persistence model

All IDs are UUIDs. Timestamps are timezone-aware UTC text. Canonical JSON uses the repository's deterministic serialization rules before hashing.

### `intake_sources`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `source_kind` | `email_message`, `sms_message`, `chat_message`, `operator_note`, or `voice_transcript`. New kinds require a schema change. |
| `channel` | `email`, `sms`, `chat`, `internal`, or `voice`; compatible with the source kind. |
| `origin_system` | Bounded normalized name such as `gmail`, `outlook`, `muse_agent`, `manual`, or `voice_workflow`; it identifies provenance, not authority. |
| `external_source_id` | Nullable bounded provider/message identifier. Required for exact provider-source deduplication. |
| `conversation_ref` | Nullable bounded opaque grouping reference; never used as the source's identity. |
| `account_scope_hash` | Nullable SHA-256 of a versioned canonical provider/account identity. It contains no credential. |
| `account_identity_state` | `transport_verified`, `operator_confirmed`, `unverified_claim`, or `not_applicable`. Only the first two permit hard account/source deduplication. |
| `account_display_hint` | Nullable bounded masked/local display value. It is not used for authorization or deduplication. |
| `submitter_kind` | `local_operator`, `assistant_connection`, or `voice_workflow`. The application supplies this from trusted context; request content cannot self-assign it. |
| `submitter_reference` | Nullable opaque reference to the authenticated connection/workflow. No secret, display claim, or mutable name is treated as identity. |
| `occurred_at_utc` | Required source-reported event time. |
| `received_at_utc` | Required application receipt time. |
| `technical_status` | `ready`, `failed`, or `superseded`. Admission is atomic; a partial source is not a lifecycle state. `failed` records a later detected integrity/unavailability failure. |
| `attention_status` | `unprocessed`, `in_review`, `resolved`, or `dismissed`. This is distinct from technical readiness. |
| `current_revision_id` | Always required; references exactly one retained revision belonging to the source. |
| `supersedes_source_id`, `superseded_by_source_id` | Nullable one-to-one non-branching lineage for replacement sources, including attachment-set corrections. |
| `failure_code` | Nullable registered non-sensitive code. Detailed external error payloads are not retained here. |
| lifecycle timestamps | Required combinations validated against both status machines. |

### `intake_evidence_revisions`

Each row is immutable once its admitting database transaction commits and contains:

- stable ID, source ID, positive monotonic revision number, and envelope schema version;
- revision kind: `submitted`, `operator_correction`, or `transcript_revision`;
- the exact bounded canonical envelope JSON;
- `content_fingerprint`, computed from a canonical hash projection of the envelope, including ordered attachment roles and content hashes but excluding application-generated source, revision, file, and link IDs;
- a bounded correction reason for non-initial revisions;
- trusted actor kind/reference and creation time; and
- optional `supersedes_revision_id` / `superseded_by_revision_id` one-to-one lineage.

The initial revision and every attachment association are written together in the admitting transaction and are never edited afterward. A correction appends a complete replacement envelope, advances `current_revision_id` once in the same transaction, and records one operation and correlated audit set. A revision cannot change provider/source identity or attachment membership. Those changes require a replacement source linked through source supersession so exact dedup history remains explainable.

### `intake_revision_file_links`

This immutable association records revision ID, FILE-001 link ID, attachment role (`source_attachment` or `raw_source`), and display order. It does not copy file name, media type, byte size, hash, provider, or storage path. Those remain FILE-001 facts.

Every referenced file link must target the same `intake_source`, use an allowed purpose, remain retained, and point to available hash-verifiable content when the source is admitted. The initial attachment set is fixed at admission and copied unchanged to later same-source revisions.

### `intake_source_operations`

Append-only operations provide idempotency and recovery independently of Audit. Each row records:

- operation ID and type (`admit`, `integrity_failed`, `integrity_restored`, `correct`, `supersede`, `attention_transition`);
- caller-supplied idempotency UUID, immutable canonical request payload, and its recomputable fingerprint;
- source ID, optional resulting revision ID, outcome, and registered error code;
- correlation ID, trusted actor context, and timestamps.

A unique idempotency key with the same request fingerprint returns the same result. Reusing it with changed content returns `409 intake_idempotency_conflict`.

### `intake_source_duplicate_candidates`

This append-only table records a candidate pair, reason (`content_fingerprint`, `conversation_similarity`, or future registered reason), confidence label/provenance, disposition (`unreviewed`, `distinct`, or `same_source`), operator decision metadata, and timestamps. It never aliases or merges source IDs automatically.

Exact source replays do not create a candidate row; they return the already-retained source. Issue similarity remains ISSUE-AI-002's responsibility and is not stored here.

## Admission, attachment, and lifecycle

### Trusted admission contexts

There are two application entry paths:

1. The operator API creates a `local_operator` admission context. It cannot claim an assistant connection or verified account.
2. A future authenticated transport calls an internal `IntakeAdmissionPort` with an application-supplied connection/grant context. MCP-001 checks grants, pause/revocation, and account binding before the call and again before its own receipt commit.

There is no public `POST /api/assistants/...` endpoint in INGEST-001. Intake validates evidence and provenance but does not authenticate an assistant.

Global AI pause does not block manual operator intake. A connected-assistant adapter enforces the pause before calling Intake. Already retained evidence remains readable and reviewable according to existing local access rules.

### Technical lifecycle

1. **Prepare:** validate the bounded envelope, trusted context, identity shape, idempotency, complete attachment manifest, limits, and duplicate attachment hashes before acquiring file leases. No database source exists yet.
2. **Admit:** open one immediate transaction and recheck identity/idempotency. For each attachment, FILE-001 publishes and verifies the bytes, writes its file/link rows on the caller-owned connection, and returns a rollback lease. On that same connection Intake allocates the `ready` source, complete initial revision, immutable revision/file associations, operation, and correlated audit rows. Attachment identities and hashes are therefore part of the revision at its first committed state.
3. **Release or roll back:** after database commit, release every content lease. If preparation or the transaction fails, roll leases back in reverse order. A hard stop before metadata commit may leave orphaned content for FILE-001 verification/reconciliation, but it cannot leave a committed source that falsely claims missing unpublished attachments.
4. **Fail/retry:** a rejected admission records no partial source. A transport with a durable pre-admission receipt owns that failure outcome; a later retry uses the same Intake idempotency/fingerprint rules. If a later integrity check finds retained source content missing or mismatched, a reasoned operation changes the source to `failed`; a verified restoration returns it to `ready` without changing its evidence revision.
5. **Correct:** append a full evidence revision with a reason. The source remains the same and its opaque revision/fingerprint changes. Existing AI drafts become stale through their normal source-revision check.
6. **Supersede:** replace a source only when identity or attachment membership was wrong. Both source records remain retained; lineage cannot branch or cycle.

Text-only and multipart operator intake each complete as one service operation. A future chunked or asynchronous transport needs its own durable reservation/session contract; it cannot expose a partially assembled source as ready.

### Attention lifecycle

- A ready source begins `unprocessed`.
- INGEST-002 or another registered consumer moves it to `in_review` through a transaction-aware application port when a live review is admitted.
- The owning review transaction moves it to `resolved` only after an approved link/create/update consequence commits, or to `dismissed` with an operator reason when the source requires no action.
- A source may be dismissed directly before a draft exists, with explicit confirmation and a reason. Dismissal does not delete evidence and can be reopened to `unprocessed` with a new reasoned operation.
- Technical failure never masquerades as dismissal or resolution. A superseded source is terminal for new processing, while historical reviews remain readable.

Downstream consumers do not write Intake tables directly. Intake exposes transaction-aware attention operations so a review decision and attention transition can share one SQLite transaction and correlation ID.

## Deduplication and identity rules

INGEST-001 uses three deliberately different mechanisms:

1. **Operation replay:** workspace plus idempotency key and request fingerprint. This protects retries of an admission command.
2. **Exact external-source replay:** `origin_system`, trusted `account_scope_hash`, `source_kind`, and `external_source_id`. This unique identity is connection-neutral, so the same Gmail message submitted by two assistant connections returns one source.
3. **Probable duplicate:** matching content fingerprints or future registered similarity logic. This creates a reviewable candidate and never silently collapses two records.

An `unverified_claim` cannot participate in hard cross-connection deduplication. It is retained visibly as unverified and may generate a probable duplicate candidate. A later transport cannot silently upgrade the claim; it appends a reasoned provenance operation or submits a verified exact identity that an operator explicitly reconciles.

The canonical account-scope algorithm is versioned by provider. It uses a stable provider account/tenant identifier when the transport can prove one; otherwise it uses a normalized operator-confirmed account locator. Connection ID, assistant name, mutable display label, and filesystem folder are forbidden inputs because they would defeat cross-connection deduplication.

Manual notes and voice transcripts normally have `not_applicable` account identity. Their exact replay protection comes from idempotency; equal text is only a probable duplicate.

## Limits and validation

MVP bounds are:

- subject: 0–500 Unicode characters;
- body or transcript: 1–131,072 UTF-8 bytes after newline normalization;
- participants: at most 50, each display/address value at most 500 characters;
- identifiers and conversation reference: at most 500 characters each;
- attachments: at most 20, each still governed by FILE-001's 50 MiB limit, with 100 MiB aggregate per source;
- duplicate attachment content hashes within one source are rejected as a redundant/ambiguous manifest;
- correction/dismissal reason: 1–1,000 characters; and
- list page: default 50 and maximum 200.

Normalize Unicode to NFC, convert CRLF/CR to LF, preserve meaningful whitespace within the body, trim envelope scalar fields, and reject NUL/control characters except tab and newline. Address normalization is channel-specific and is not proof of party identity. Intake does not resolve a sender to a Party, property, space, lease, reporter, or issue.

The source fingerprint covers only the canonical retained evidence and stable attachment roles/content hashes. It excludes application-generated IDs as well as mutable attention state, technical state, display hints, audit metadata, and downstream drafts. The same evidence admitted independently can therefore compare equal across assistant connections even though its local link IDs would differ.

## Application ports and module structure

The implementation follows the existing module layout under `application/apps/server/app/modules/intake/` with domain models/policies, application service/ports, infrastructure repositories/unit of work, and API contracts/router.

Required consumer-neutral ports are:

- `IntakeAdmissionPort` — trusted atomic source admission with its complete attachment set;
- `IntakeSourceReader` — current projection, exact revision, bounded evidence detail, and batched summary reads;
- `IntakeAttentionOperations` — transaction-aware attention transitions for INGEST-002;
- `IntakeSourceLinkValidator` — validates COM-001 `intake_source` links;
- `IntakeFileLinkValidator` — fails closed for direct generic File API create/archive operations because a valid Intake attachment also needs an immutable revision association. Intake alone writes the file, link, and association together through FILE-001's caller-owned transaction API; and
- `IntakeRetentionValidator` — contributes exact-schema and cross-table/source-file integrity checks.

The current source projection returns source ID, kind/channel, current opaque revision, fingerprint, technical and attention states, occurred/received times, bounded provenance summary, attachment count, and comparison availability. List projections omit the full body, participant addresses, raw artifacts, and file paths.

Opaque revision values are application-generated and must change whenever the canonical evidence revision changes. Consumers compare them inside the owning transaction; they do not assume that the value is an integer.

## Operator API contracts

All contracts forbid unknown fields and return stable typed errors.

- `POST /api/intake/sources` atomically admits a bounded text-only operator source. A client-generated idempotency UUID is required.
- `POST /api/intake/sources/import` accepts one bounded metadata part and zero to twenty files, using the same admission lifecycle. It is operator-only and cannot self-claim assistant provenance.
- `GET /api/intake/sources` returns a cursor page filtered by source kind, channel, technical status, attention status, trusted/unverified provenance, received range, or duplicate-candidate state.
- `GET /api/intake/sources/{sourceId}` returns canonical current evidence, revision lineage, attachment metadata through FILE-001 projections, provenance qualifications, lifecycle history, and duplicate candidates.
- `POST /api/intake/sources/{sourceId}/correct` appends a complete corrected envelope and reason; it never patches the original row.
- `POST /api/intake/sources/{sourceId}/dismiss` and `/reopen` perform confirmed reasoned attention transitions when no conflicting review transition exists.
- `POST /api/intake/sources/{sourceId}/supersede` admits or selects a replacement source and records non-branching lineage.

Attachment acquisition and integrity recovery are owning-service operations rather than general browser APIs. Future transports submit one complete admission command or introduce a separately designed durable import-session contract; they do not assemble a partially visible source through generic file routes.

Malformed or oversized input returns `422`; missing records return `404`; idempotency reuse, exact-identity payload mismatch, illegal lifecycle transition, stale revision, and correction/supersession conflicts return typed `409` responses. Storage or verification failures use registered retryable `5xx` errors without exposing local paths.

## Audit, privacy, and security

Audit records source/revision admission, correction, supersession, integrity transitions, attention decisions, duplicate dispositions, attachment association, and full-evidence reads. General activity shows source kind, qualified provenance category, status, and safe timestamps; it redacts subject/body/transcript, addresses, account hints/hashes, external IDs, conversation references, attachment names/hashes, correction reasons, idempotency values, and connection references.

Contextual Intake detail may show retained evidence to the local operator. Raw artifacts are downloaded through FILE-001's content endpoint and are never exposed as local filesystem paths. Responses set safe content handling; HTML or active files are not rendered inline merely because their extension suggests a viewable format.

No source content is sent to a model by this feature. ISSUE-AI-001 must prepare a bounded candidate and AI-GOV-001 must apply its registered redaction/disclosure rules. A source's account identity, sender address, or attachment does not become model input by implication.

There is no hard delete in INGEST-001. The MVP retains evidence and tombstones for audit, draft-source integrity, encrypted backup, restore, and later SaaS migration. A future retention/deletion feature must coordinate source revisions, file bytes, AI history, communications, official issues, and legal holds rather than deleting one table independently.

## Recovery, schema validation, and performance

Startup and restore validation verifies:

- exact tables, columns, indexes, checks, and triggers;
- legal technical/attention status and timestamp combinations;
- exactly one current revision per source, monotonic non-branching revision lineage, and matching source ownership;
- canonical envelope version/serialization and recomputed fingerprints;
- legal source supersession without cycles or branches;
- immutable operation/idempotency consistency;
- exact dedup uniqueness for trusted identities;
- revision/file-link ownership, allowed purposes, declared counts, and retained FILE-001 records;
- duplicate candidate pair ordering and valid dispositions;
- COM-001 links resolving to retained sources; and
- required correlated audit evidence.

An unavailable attachment prevents admission as `ready`; it does not produce a reassuring evidence-complete source. Workspace verification reports missing/mismatched referenced content and unexpected orphaned managed content. A later loss moves the retained source to `failed` through a reasoned integrity operation when the workspace remains recoverable. INGEST-001 does not fabricate missing bytes or silently drop declared attachments.

List queries use one bounded source page plus bounded set-based counts/provenance reads. Detail resolves one source, its revision lineage, file metadata, operations, and duplicate candidates with a fixed query budget. Full-text search and semantic indexing are deferred until OPS-001 or a later privacy-specific search design.

All Intake tables and referenced managed files participate in LOCAL-002 backup/export/restore. Stable IDs, source/revision lineage, fingerprints, provenance qualifications, statuses, operations, audit history, and COM links survive restore. Usable external credentials and transient import files do not enter the archive.

## Implementation sequence

1. Add domain types, canonical envelope version 1, limits, state machines, fingerprints, and audit snapshot policy.
2. Extend the greenfield SQLite baseline, expected-table registration, exact schema checks, cross-row validation, backup/archive validation, and sanitized fixtures.
3. Implement the Intake unit of work, operation/idempotency records, trusted admission service, exact dedup, revision/supersession rules, and source reader.
4. Compose FILE-001 attachment operations and validators; verify multi-lease rollback, transaction failure, hard-stop orphan detection, missing/mismatched content, and idempotent retry.
5. Extend COM-001's typed link vocabulary and validator composition for `intake_source`, without automatic communication creation.
6. Add operator APIs, typed errors, bounded cursor reads, audit redaction, and unavailable/recovery responses.
7. Add the source projection and attention operations that INGEST-002, AI-GOV-001, VOICE-AI-001, and MCP-001 will consume later.
8. Run focused module, schema-tamper, archive/restore, cross-module contract, and full regression tests. No React work is included.

## Acceptance criteria

1. The operator can retain a bounded message, note, or transcript with qualified provenance and optional FILE-001 attachments without configuring AI or an assistant.
2. The initial accepted envelope and every correction remain immutable and distinguishable from extracted, proposed, or official issue fields.
3. Exact idempotent replay returns the same result; changed payload reuse fails; a trusted account/source replay across connection contexts resolves to one source.
4. Unverified identity or matching content never silently merges sources and instead remains qualified or creates a reviewable duplicate candidate.
5. A source cannot become `ready` while declared attachment content is unavailable, mismatched, over limit, or linked to another entity.
6. Corrections change the source revision/fingerprint and make any earlier AI draft stale; original evidence remains readable.
7. Technical failure, unprocessed evidence, active review, resolution, and dismissal remain distinct states with legal reasoned transitions.
8. A communication can link to a retained source, but importing evidence creates no communication and changing either record never rewrites the other.
9. No public request can claim assistant identity, verified account provenance, or permission; future assistant transports use the trusted internal admission boundary.
10. General activity and list responses redact sensitive evidence while contextual detail remains useful to the local operator.
11. Exact schema/data validation, encrypted backup/restore, and future SaaS export preserve source, revision, attachment-reference, dedup, operation, and audit integrity.
12. Invalid, oversized, duplicate, stale, interrupted, and restart-recovery cases have typed outcomes and cannot create an official issue.

The backend can be marked complete when these criteria pass. The feature remains pending operator UI until UI-001, and issue conversion remains unavailable until INGEST-002.

## Contradictions and missing decisions found

### 1. COM-001 is listed as a dependency even though Intake must not become a communication ledger

The dependency is coherent only as a typed-link integration. Decision: retain COM-001 as a hard dependency, add `intake_source` to its link contract, and prohibit automatic communication creation or body synchronization. If the product does not want source-linked communications, remove COM-001 from the backlog dependency instead of inventing another coupling.

### 2. “Original source evidence” could imply unlimited raw provider payload retention

That would conflict with the backlog's bounded requirement, privacy controls, safe rendering, and the application's lack of mailbox ownership. Decision: the canonical accepted envelope is authoritative for Intake; optional raw exports are inert FILE-001 attachments. Arbitrary headers/provider JSON are out of scope.

### 3. Account-scoped deduplication has no current account registry

The application intentionally holds no mail credentials, CONN-001 no longer owns mail accounts, and MCP-001 is later. Decision: INGEST-001 stores a versioned opaque account-scope hash plus an identity trust state. Manual intake can use operator-confirmed scope; future transports must supply a stable verified provider/account identity through trusted context. MCP-001 must define each qualified adapter's canonical mapping before claiming cross-connection deduplication.

### 4. Content deduplication could discard two legitimate identical messages

Decision: only idempotency or trusted provider/account/external-source identity performs hard deduplication. Content fingerprints create candidates only. Duplicate issue detection remains ISSUE-AI-002 work.

### 5. Voice dependencies appear circular

INGEST-001 mentions transcripts, while VOICE-001 depends on it and VOICE-AI-001 performs transcription later. Decision: Intake defines and retains the `voice_transcript` source kind and revision contract now. VOICE-001 later owns audio capture/import; VOICE-AI-001 writes transcript revisions through Intake. INGEST-001 performs no transcription and requires no audio.

### 6. FILE-001 has no physical-delete contract, but voice audio need not be retained permanently

Decision: disposable audio remains in a VOICE-001-owned private temporary store with restart-safe cleanup and is outside Intake and FILE-001. Only an explicit operator choice promotes audio to retained FILE-001 evidence; promoted audio is then retained under ordinary managed-file rules. The backlog now records this boundary, so VOICE-AI-001 can verify temporary-audio disposal without implying deletion of a managed business file.

### 7. FILE-001 publication order was easy to misread

The current local and S3 adapters publish and verify content before the metadata transaction commits; the returned object's `commit()` releases rollback ownership rather than publishing bytes. Decision: Intake retains all leases until its one admitting transaction succeeds and rolls them back on failure. A hard stop before metadata commit may leave orphaned content, so FILE-001 verification/reconciliation owns that case. A future truly post-metadata adapter must use `pending` plus a durable recovery identity and cannot expose an Intake source as ready until verification completes.

### 8. “Processing state” was overloaded

One state cannot truthfully represent upload health, unreviewed evidence, an active draft, and final disposition. Decision: retain separate `technical_status` and `attention_status`; later dashboards compose both explicitly.

### 9. AI pause and manual intake were ambiguous

Decision: manual operator intake remains available while AI is paused. Connected-assistant admission is blocked by its transport/governance boundary. Retained evidence and existing drafts remain reviewable; Intake does not import AI settings merely to make this distinction.

### 10. Retention duration is not specified

Decision for MVP: retain sources, revisions, operations, tombstones, and linked files indefinitely in the encrypted workspace, with no hard-delete API. A later retention feature must make legal-hold, downstream-reference, file-byte, AI-history, and SaaS-migration decisions together. The UI must not claim that dismissal deletes evidence.
