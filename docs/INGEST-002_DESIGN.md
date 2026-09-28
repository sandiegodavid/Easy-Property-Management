# INGEST-002 — Source-backed Issue Draft Review

## Status and authority

This is the confirmed backend/API and UI-handoff design for `INGEST-002`. It is based on [FEATURE_BACKLOG.md](FEATURE_BACKLOG.md), [ARCHITECTURE.md](ARCHITECTURE.md), [INGEST-001_DESIGN.md](INGEST-001_DESIGN.md), [AI-GOV-001_DESIGN.md](AI-GOV-001_DESIGN.md), [MAINT-001_DESIGN.md](MAINT-001_DESIGN.md), and [MAINT-004_DESIGN.md](MAINT-004_DESIGN.md), plus the current implementation.

The decisions under **Resolved contradictions and decisions** are authoritative for this feature and reconcile the ambiguities found during design. The required AI-GOV-001 contract changes and the INGEST-001 readiness gate are reflected in the upstream documents. No application code is included.

## Outcome

`INGEST-002` lets the local operator compare an issue proposal with the exact retained source revision on which it was based, edit the proposed issue facts, resolve authoritative property, space, and reporter context, and then choose one explicit terminal consequence:

- create one official Maintenance issue;
- link the retained source and reviewed proposal to an existing issue without changing that issue;
- apply an explicitly selected, bounded update to an existing active issue and link the source;
- dismiss the proposal and source as reviewed with no issue; or
- discard the proposal for rework while leaving the source unprocessed.

The selected consequence, AI review decision, Intake attention transition, issue-review outcome, Maintenance write where applicable, and all audit events commit atomically. No proposal becomes an official issue or changes one merely because a model or assistant supplied it.

## Scope and boundaries

INGEST-002 provides:

- the production issue-proposal payload contract registered with AI Governance;
- a source-backed review queue and detail composition;
- exact source-revision, provenance, transcript/body, attachment, governed-input, proposal, operator-edit, and optional match-candidate comparison;
- explicit operator resolution of all facts required by MAINT-001 and MAINT-004;
- create, link-only, bounded update, no-issue dismissal, and rework dispositions;
- optimistic review concurrency and command idempotency;
- one durable issue-review outcome linking source, draft, decision, and resulting issue;
- atomic coordination across Maintenance, AI Governance, Intake, and Audit;
- bounded issue lookup for manual target selection when optional matching is unavailable;
- retained-data, exact-schema, backup/restore, and audit validation; and
- the feature-specific contract consumed later by UI-001, MCP-001, ISSUE-AI-001/002, VOICE-AI-001, and DASH-003.

INGEST-002 does not provide:

- mailbox, SMS, chat, file-bridge, or MCP transport;
- message discovery, credentials, polling, or assistant grants;
- model inference, transcription, entity matching, duplicate scoring, diagnosis, or provider recommendations;
- direct email/SMS sending or automatic COM-001 communication creation;
- general issue editing, reporter correction, work-journal updates, assignments, appointments, or financial changes;
- a replacement for direct operator entry through MAINT-001; or
- React implementation before UI-001.

An operator may still record an issue directly through Maintenance when no retained source or generated proposal is involved. INGEST-002 governs source-backed proposals admitted through AI Governance. Manual issue entry remains usable when AI and assistant connections are absent, paused, or unavailable.

## Dependency and ownership alignment

| Capability | Responsibility in this workflow |
| --- | --- |
| INGEST-001 / Intake | Owns retained source identity, exact evidence revisions, attachment associations, technical state, and attention state. It exposes consumer-neutral exact-revision and current-source reads plus transaction-aware attention operations. |
| AI-GOV-001 / AI Governance | Owns the run, governed input, proposal payload, operator edits, generic review decision, model/assistant provenance, confidence, and draft version. |
| MAINT-001 / Maintenance | Owns official issue creation, mutable issue facts, issue lifecycle, and issue audit history. |
| MAINT-004 / Maintenance | Owns authoritative reporter attribution and its relationship validation. Extracted reporter text is only a proposal. |
| AUDIT-001 | Records correlated review, outcome, Intake, AI, and Maintenance events according to each owner's policy. Audit is not the source-to-result link or idempotency store. |
| FILE-001 | Owns source file metadata, hashes, availability, and bytes. INGEST-002 reads source attachment projections; it does not copy file metadata or create issue file links automatically. |
| ISSUE-AI-001 | Optional producer of the issue proposal payload from retained evidence. It is not required for operator review of an external proposal. |
| ISSUE-AI-002 | Optional provider of property, space, party, and possible-existing-issue candidates. Its absence must leave manual lookup usable. |
| MCP-001 | Later authenticates and admits external proposals through the same registered payload and review contract. It never approves its own proposal. |
| UI-001 | Delivers the comparison and decision workflow after the backend contracts are complete. |
| DASH-003 | Later composes unprocessed sources, live reviews, stale proposals, and ingestion failures through bounded read contracts. |

This follows the modular-monolith rules in `ARCHITECTURE.md`: source modules expose neutral application protocols, the consuming domain owns policy, coordinated writes use one caller-owned immediate transaction, and no module imports another module's SQLAlchemy models or concrete repository.

## Review subject and proposal contract

### Review subject

One issue review is identified by an AI Governance draft whose registered action is the issue-intake action and whose source is one `intake_source` revision. The source revision and fingerprint in the run are immutable. Review detail also loads the current source projection so the operator can see whether that evidence is still current.

The proposal is not the official issue. It may contain unknown, incomplete, or incorrect facts. A base review must remain possible without ISSUE-AI-002 matches.

### Proposed issue payload

The production payload uses a versioned, closed schema. Unknown fields fail validation. The initial schema contains:

| Field | Rule |
| --- | --- |
| `summary` | Required proposed text, 1–240 characters. |
| `description` | Required proposed text, 1–8,000 characters. |
| `category`, `categoryDetail` | Nullable Maintenance category proposal using the MAINT-001 vocabulary and pairing rules. The operator must resolve a valid category before create or selected update. |
| `priority` | Nullable `low`, `normal`, `high`, or `urgent` proposal. The operator must resolve it before create or selected update. |
| `reportedAtUtc` | Nullable aware timestamp proposal. The operator must confirm the event time before create. |
| `requestedAction` | Nullable bounded source-derived context. It remains review context and is not a MAINT-001 issue field. |
| `reporterText` | Nullable bounded name/address text extracted from evidence. It is never a Party ID or authoritative identity. |
| `reporterRole` | Nullable proposed `owner`, `tenant`, `manager`, or `staff`. The operator must select a valid MAINT-004 subject and role before create. |
| `propertyText`, `spaceText` | Nullable bounded source-derived descriptors. They are not stable Portfolio IDs. |

ISSUE-AI-002 candidates remain a separate projection with candidate identity, reason, provenance, and confidence. They do not become fields in the retained source and do not silently replace operator selections.

### Resolved review input

Approval carries a complete, explicit review request rather than trusting proposal fields implicitly:

- current draft ID and expected draft version;
- expected source revision and fingerprint shown to the operator;
- decision mode;
- operator note or required reason;
- client-generated idempotency key;
- for create: complete MAINT-001 issue input, including property, optional space, valid category/priority, reported time, and complete MAINT-004 reporter attribution;
- for link: existing issue ID and expected target revision;
- for update: existing issue ID, expected target revision, and an explicit set of selected mutable fields with complete replacement values.

The server reconstructs and validates the request fingerprint. It never accepts a client-supplied result ID, source provenance, model identity, reporter display snapshot, or audit actor.

Maintenance must expose an opaque issue revision in its review projection. The current implementation may derive that revision from the issue aggregate's `updated_at`, but clients treat it as an opaque value and never construct or compare timestamps themselves.

## Decision modes

### Create issue

Create uses normal Maintenance policy inside the approval transaction. It validates active property/space context, reporter eligibility on the property-local reported date, issue taxonomy, and all MAINT-001 invariants. The result is one new `maintenance_issue` with its usual create idempotency and audit evidence.

The source evidence remains owned by Intake. The review outcome provides the durable source-to-issue provenance. Source attachments are visible through that link and are not automatically copied into Maintenance file links. A later explicit Maintenance evidence action may create an allowed FILE-001 link when the operator needs an attachment to participate directly in the issue workflow.

### Link without changing the issue

Link validates that the selected issue exists and that the operator reviewed its current revision. It records the issue as the result of the review but does not patch the issue, change its reporter, add a communication, alter lifecycle, or add a work-journal entry.

Link is the safe default when the source reports an already-recorded issue and no official issue field needs correction. Optional duplicate suggestions may preselect a candidate visually, but only the operator's explicit request establishes the link.

### Update an existing issue

Update is limited to active `open` or `in_progress` issues and to the MAINT-001 mutable detail fields:

- `summary`;
- `description`;
- `category` plus `categoryDetail`; and
- `priority`.

The request names the fields being applied. Unselected proposal fields do not overwrite current values. Property, space, reported time, reporter attribution, status, appointments, assignments, costs, work journal, tasks, communications, and evidence links are outside this update.

Reporter correction remains the dedicated confirmed MAINT-004 command. A proposal that appears to identify a different reporter may be linked to the issue for provenance, but changing the official reporter requires that separate workflow. Terminal issue updates are rejected; their source may still be linked without mutation.

Update requires the target revision the operator compared. A changed target returns `409 issue_intake_target_stale` and leaves the draft live. The operator must review the latest issue before retrying.

### Dismiss as no issue

This decision requires a bounded reason. It terminally dismisses the proposal, records a no-issue outcome, and changes the current ready source from `in_review` or `unprocessed` to `dismissed` in the same transaction. It does not delete evidence, create a communication, or suppress a different source.

### Discard for rework

This decision requires a bounded reason. It terminally dismisses the current proposal but returns the current ready source to `unprocessed`, allowing a corrected source, a superseding proposal, or later manual review. It does not assert that the evidence contains no issue.

The product must not use one ambiguous **Dismiss** action for both meanings.

## Persistence model

INGEST-002 adds one domain-specific table. It does not copy source evidence, AI payloads, or Maintenance issue fields.

### `intake_issue_review_outcomes`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `draft_id` | Required unique AI Governance draft reference. One draft has at most one terminal issue-review outcome. |
| `source_id` | Required Intake source reference copied from the run relationship for indexed provenance lookup. |
| `source_revision_id`, `source_fingerprint` | Exact evidence revision and SHA-256 reviewed. They must match the run. |
| `draft_version`, `draft_payload_fingerprint` | Exact edited proposal version and canonical payload fingerprint reviewed. |
| `decision_mode` | `create`, `link`, `update`, `dismiss_no_issue`, or `discard_for_rework`. |
| `result_issue_id` | Required for create/link/update; null for dismissal/rework. |
| `target_revision_before` | Required for link/update; null for create and no-result decisions. |
| `result_revision_after` | Required for create/update; for link it equals the reviewed target revision. |
| `applied_fields` | Canonical closed JSON list for update; empty for every other mode. |
| `reason` | Required for dismissal/rework; optional bounded operator note for approval modes. |
| `idempotency_key`, `request_fingerprint` | Required unique command identity and canonical semantic-request fingerprint. Same-key/same-request returns the stored response; changed reuse returns `409 issue_intake_idempotency_conflict`. |
| `response_snapshot` | Bounded canonical response sufficient to replay the original terminal result after later issue changes. |
| `correlation_id` | Required correlation shared with AI, Intake, Maintenance, and Audit writes. |
| `decided_at` | UTC timestamp. |

Indexes support `(source_id, decided_at)`, `(result_issue_id, decided_at)`, and review-history reads. A partial uniqueness rule permits at most one approved issue consequence (`create`, `link`, or `update`) per source, preventing one retained message from creating or adopting multiple official issues as required by the Product Brief. Database checks enforce decision/result/revision/applied-field combinations. Retained-data validation confirms referenced run/draft/source/revision/result identities and correlated decision/audit evidence.

The table is justified even though AI Governance has generic review decisions: it records the issue-specific effect, provides a durable source-to-issue provenance link, supports byte-equivalent retry, and lets Intake and Maintenance expose bounded history without treating Audit as operational storage.

## Lifecycle and concurrency

### Queue and review lifecycle

1. A provider generation or authenticated external proposal creates a validated AI Governance draft for the issue-intake action. INGEST-002 creates no second copy of its payload.
2. The queue composes each live issue draft with its source summary. A source with a live draft appears as one review item rather than one source item plus one draft item.
3. Opening or explicitly starting review moves a current ready source from `unprocessed` to `in_review` through Intake's reasoned transaction operation. Reopening the same review is idempotent and does not lock out a second browser tab.
4. Editing replaces the complete proposal payload through AI Governance's versioned edit operation. Source, governed input, and provenance do not change.
5. A terminal command reloads the draft, run, source, exact evidence revision, optional target issue, and any prior outcome in one immediate transaction. It rejects stale or invalid state before writes.
6. The selected domain consequence, issue-review outcome, generic AI decision, Intake attention transition, and audit set commit together.

### Staleness rules

Approval, link, update, and no-issue dismissal require:

- a `proposed` or `edited` issue-intake draft at the expected version;
- a `ready`, non-superseded Intake source;
- the run's source revision/fingerprint to remain current;
- no prior terminal issue-review outcome for the draft; and
- for link/update, the current issue revision to equal the reviewed target revision.

A source correction, source supersession, evidence-integrity failure, draft edit in another tab, or target issue change returns a typed conflict and writes no terminal decision. There is no silent rebase. Previously displayed evidence may remain visible with a stale label so the operator can understand the conflict, but a new or superseding proposal must bind to the current source revision before approval.

### Multiple proposals for one source

MVP rule: one live issue-intake draft per source. A rerun or replacement proposal must explicitly supersede the prior live draft. Historical terminal drafts remain visible. At most one approved create/link/update consequence may exist for the source. This keeps Intake's single attention state truthful and enforces the Product Brief's requirement that deduplication prevent one message from creating multiple issues.

If one message describes several distinct problems, the MVP does not split it into several source-backed issue outcomes. Supporting that case later requires an explicit split-source or per-source review-item design rather than weakening duplicate protection silently.

## Atomic transaction design

### Create, link, and update

The registered issue approval handler is Maintenance-owned because Maintenance owns the official consequence. It opens the normal Maintenance immediate transaction and receives transaction-aware operations composed at bootstrap:

- AI Governance review operations to load the exact draft/run and complete the generic approval;
- Intake exact-revision/current-source readers and reasoned attention operations;
- INGEST-002 outcome operations; and
- existing Maintenance context readers and Audit recorder.

The handler validates the complete request, performs the create/link/update consequence, inserts the immutable outcome, completes the AI approval with `result_entity_type = maintenance_issue`, changes Intake attention to `resolved`, and writes correlated audits before commit. Link-only still inserts a review outcome and approval decision even though the issue row does not change.

No network call, model call, keyring access, file-byte read, or assistant transport occurs inside this transaction.

### Dismissal and rework

An INGEST-002 review-decision service opens one immediate transaction using AI Governance, Intake, outcome, and Audit transaction operations. It inserts the issue-review outcome, terminally dismisses the AI draft, and changes Intake attention to `dismissed` or `unprocessed` according to the explicit mode.

The generic `/api/ai/drafts/{id}/dismiss` route must not bypass this source-state consequence for the registered issue-intake action. AI Governance must dispatch a registered domain dismissal handler or reject the generic route and direct callers to the INGEST-002 endpoint.

### Lost responses and retries

Every terminal request requires an idempotency key. The outcome row is checked before lifecycle guards:

- same key and request fingerprint returns the original response snapshot;
- changed content with the same key returns `409 issue_intake_idempotency_conflict`;
- a different key after the draft is terminal returns its recorded terminal outcome rather than creating another result.

This is required because the current generic AI approval endpoint is version-checked but not retry-safe after an unknown response.

## Read and API contracts

All models reject unknown fields. Pages use stable ordering, opaque cursors, and a maximum page size. The required endpoints are:

| Method | Path | Intent |
| --- | --- | --- |
| `GET` | `/api/intake/issue-reviews` | Return a bounded queue filtered by live/terminal/stale state, proposal origin, source channel, or decision mode. |
| `GET` | `/api/intake/issue-reviews/{draftId}` | Return the exact source comparison, current-source state, governed input, proposal/edit history, confidence/provenance, optional candidates, current outcome, and available actions. |
| `POST` | `/api/intake/issue-reviews/{draftId}/begin` | Idempotently mark a current source in review. |
| `PATCH` | `/api/intake/issue-reviews/{draftId}` | Validate and record a complete proposal edit through AI Governance using expected draft version. |
| `POST` | `/api/intake/issue-reviews/{draftId}/approve` | Commit create/link/update using the explicit decision request and idempotency key. |
| `POST` | `/api/intake/issue-reviews/{draftId}/dismiss` | Commit `dismiss_no_issue` or `discard_for_rework` with reason and idempotency key. |
| `GET` | `/api/maintenance-issues/{issueId}/intake-sources` | Return bounded approved source/review provenance through an Intake-owned neutral reader. |

The review detail separates:

1. exact retained source evidence and provenance;
2. exact governed input supplied to the model or admitted from an assistant;
3. original proposal and confidence;
4. operator edits;
5. authoritative selected property, space, reporter, and target issue; and
6. the final official consequence, when present.

The API never labels assistant-reported model identity as verified, never renders source HTML, and never turns missing evidence or target data into an empty successful state.

Typed conflicts include:

- `issue_intake_draft_stale`;
- `issue_intake_source_stale`;
- `issue_intake_source_unavailable`;
- `issue_intake_target_stale`;
- `issue_intake_target_terminal`;
- `issue_intake_live_sibling`;
- `issue_intake_terminal`;
- `issue_intake_idempotency_conflict`; and
- the existing Maintenance validation, reporter-eligibility, and context errors.

## UI-001 handoff

UI-001 renders INGEST-002 as a substantial review page, not a compact inline commit form. The page should:

- show source evidence beside the editable proposal, with attachments and transcript/body clearly identified;
- show provider/model or assistant-connection provenance accurately;
- distinguish source text, governed input, generated proposal, operator edits, and official current issue values;
- allow manual property, space, reporter, and existing-issue lookup even when optional matching is unavailable;
- present optional candidates as suggestions with reasons, never preapproved identities;
- require the operator to select Create, Link only, or Update selected fields before approval;
- preview the exact existing-issue fields that an update would replace;
- distinguish Dismiss as no issue from Discard and rework;
- preserve edits and explain stale evidence/target conflicts without discarding input; and
- show the committed issue link and retained source history after success.

The full-summary-bar disclosure behavior from UI-001 may be used for queue items, but the comparison and terminal decision occur on the dedicated review route. No UI is built in INGEST-002.

## Audit, privacy, retention, and portability

- General activity may show bounded state and decision labels but redacts source body, governed input, draft narrative, reporter text, operator reason, and issue description.
- Contextual review history may show the source, edited proposal, selected mode, before/after issue facts, reason, provenance, and confidence according to the owning policies.
- The same correlation ID joins the issue-review outcome, AI decision, Intake transition, Maintenance mutation where present, and audit records.
- No credential, delegation secret, raw provider payload, arbitrary mail header, filesystem path, or unredacted account identity enters the outcome table or audit snapshots.
- Sources, drafts, outcomes, decisions, links, and audit history are retained indefinitely in the encrypted MVP workspace. Dismissal is not deletion.
- Exact schema and retained-data validation verify canonical JSON/fingerprints, legal state combinations, one terminal outcome per draft, matching run/source/revision facts, result existence, applied-field legality, request replay identity, and correlated domain/AI/Intake audit evidence.
- Encrypted backup/restore and future SaaS migration preserve stable IDs and history. External credentials and model runtime state remain excluded.

## Query and performance bounds

- Queue pages use one bounded AI draft/outcome query and set-based source-summary reads; they do not load full evidence bodies.
- Detail loads one draft/run, one exact source revision, one current source projection, a bounded attachment projection, optional bounded candidates, and at most one selected issue detail.
- Issue provenance uses one batch reader keyed by issue IDs; Maintenance does not query Intake or AI tables per list row.
- Existing-issue selection uses Maintenance's indexed bounded list/search contract. ISSUE-AI-002 is an optional ranking aid, not a query requirement.
- No provider call, file-byte read, or external connection occurs inside write transactions.

## Current implementation findings and readiness gaps

The current code supplies most individual records but not the INGEST-002 orchestration:

1. AI Governance has generic draft list/detail/edit/approve/dismiss APIs and transaction-aware approval completion, but its production action registry, approval-handler registry, source validators, and source projections are empty.
2. AI Governance currently permits only one static approval effect (`create`, `update`, or `advisory_only`) per action. It cannot truthfully represent an operator choosing create, link-only, or update for one proposal.
3. Generic AI approval/dismiss commands have no idempotency key or domain-specific terminal response replay.
4. Intake exposes a current source projection and a nominal attention port, but it lacks the required exact-revision, bounded evidence-detail, and batch summary readers.
5. The implemented Intake attention transaction method updates only the source row; it does not yet write the required operation and audit evidence or implement the composed connection-aware adapter contract.
6. FILE-001 verification is not yet wired to move affected Intake sources to failed/restored technical state, so a review could otherwise present missing evidence as ready.
7. Intake detail currently imports FILE persistence models directly instead of using a FILE-owned neutral metadata reader.
8. Maintenance can create attributed issues and patch mutable details, but its public service opens its own transaction. It has no INGEST-002 approval handler that can share one transaction with AI and Intake operations.
9. Maintenance `patch_issue` has neither expected-revision checking nor command idempotency. It is unsafe as the update consequence for a reviewed proposal.
10. There is no durable issue-review outcome/source-to-issue provenance table, queue composition, API, audit policy, schema validation, or bootstrap wiring.

The unresolved INGEST-001 implementation review findings are mandatory readiness gates for INGEST-002, even though most INGEST-001 API work exists. They must be resolved and verified before INGEST-002 implementation begins; INGEST-002 must not work around them through raw Intake or FILE table access.

## Implementation sequence

Implementation starts only after the INGEST-001 readiness gate above is complete. Then:

1. Implement AI-GOV-001's selected approval-mode and domain-dismissal contracts for the create/link/update design.
2. Complete the INGEST-001 transaction-aware attention adapter, exact-revision/bounded/batch readers, FILE metadata boundary, and integrity propagation.
3. Define the versioned issue proposal validator, redaction binding, source validator/projection, action registration, and one-live-draft rule.
4. Add `intake_issue_review_outcomes`, constraints, indexes, audit policy, exact-schema/data validation, archive validation, and backup/restore coverage.
5. Add transaction-aware outcome operations and the composed review read model without cross-module ORM imports or per-row queries.
6. Refactor Maintenance policy behind an internal transaction-aware issue-review approval handler; keep the existing public Maintenance API behavior unchanged.
7. Add domain-specific begin/edit/approve/dismiss endpoints, typed errors, idempotent response replay, and safe target lookup.
8. Test create, link, selected update, no-issue dismissal, rework, stale source, integrity failure, stale target, two-tab edits, sibling drafts, lost responses, rollback at each write boundary, audit correlation, exact-schema tampering, and backup/restore.
9. Run the full backend suite. React work remains deferred to UI-001.

## Validation test matrix

| Area | Required coverage |
| --- | --- |
| Happy paths | Edit and approve a valid proposal through create, link-only, and selected-field update; dismiss as no issue; discard for rework; reopen a saved review; read source provenance from the resulting issue. |
| Invalid combinations | Reject unknown payload fields, incomplete category pairing, unresolved/invalid reporter attribution, incompatible property/space, forbidden update fields, update of a terminal issue, result fields on dismissal, applied fields on link, and a second approved issue consequence for one source. |
| Idempotency and retry | Replay each terminal mode with the same key/request after later issue changes; reject changed-payload key reuse; reconcile a lost response without a duplicate issue, decision, outcome, attention transition, or audit event. |
| Concurrency and staleness | Reject changed source revision/fingerprint, failed evidence integrity, changed draft version, changed target revision, a live sibling proposal, source supersession, and simultaneous terminal decisions from two tabs. |
| Transaction rollback | Inject failure after each Maintenance, outcome, AI decision, Intake transition, and audit write; verify the whole consequence rolls back and a safe retry remains possible. |
| Persistence and schema validation | Tamper with decision/result pairings, fingerprints, canonical payloads, applied-field lists, response snapshots, references, unique approved outcomes, idempotency records, and correlated audit evidence; workspace validation must fail closed. |
| Backup and restore | Preserve stable source/draft/outcome/issue IDs, exact revisions, response replay, decision history, provenance, and audit correlation; exclude credentials and runtime-only state. |
| Query budget and N+1 | Hold queue-page queries constant as page size and attachment/candidate counts grow; batch issue provenance for list/detail consumers; bound evidence detail and candidate reads. |
| Privacy and boundary checks | Prove that general activity redacts evidence/proposal/reasons, source HTML is never rendered, file paths and credentials never enter responses, and no module imports another module's persistence to compose the workflow. |

## Backend acceptance criteria

INGEST-002 backend/API scope is complete when:

1. Every review shows the exact retained source revision, provenance, attachment state, governed input, proposal, and operator edits as distinct facts.
2. Optional extraction and matching can be absent without blocking manual issue entry or manual target/context selection.
3. No source, proposal, match, or confidence value becomes an official Maintenance fact without an explicit operator terminal command.
4. Create produces one valid attributed Maintenance issue; link changes no issue facts; update changes only explicitly selected allowed fields.
5. Reporter text never substitutes for a valid MAINT-004 subject and role.
6. Stale source evidence, failed evidence integrity, changed draft version, changed target issue, terminal target, or conflicting live proposal cannot commit.
7. The selected consequence, issue-review outcome, AI decision, Intake attention state, and audit set either all commit or all roll back.
8. Lost-response retries return the original result and cannot create a second issue or apply an update twice.
9. Dismiss as no issue and discard for rework produce different durable source states and both retain evidence/history.
10. Source attachments remain FILE-001 records and are not copied or auto-linked into Maintenance.
11. Review queues and issue provenance use bounded, set-based reads with fixed query budgets.
12. Exact-schema/data validation and encrypted backup/restore preserve complete review and source-to-issue history with stable IDs.

The overall operator workflow remains pending until UI-001 delivers the comparison and decision page. MCP-001 and ISSUE-AI-001 may then submit compatible proposals without changing approval semantics.

## Resolved contradictions and decisions

### 1. The implemented AI-GOV-001 baseline allows one static approval effect

One issue proposal cannot currently be registered honestly as create, update, and link-capable. Treating every result as `update` would make AI provenance and retained validation misleading; letting the assistant choose the effect would violate operator control.

**Decision:** extend the AI action definition to declare a closed set of operator-selectable approval modes and record the selected mode in the generic decision and the registered domain outcome. Add `link` as a distinct mode. INGEST-002's outcome row records the exact mode, and AI retained-data validation delegates domain-effect validation to the owning domain.

### 2. “Submitted draft” has no producer in INGEST-002's hard dependency set

AI-GOV-001 intentionally registers no production action. ISSUE-AI-001 is optional and MCP-001 follows INGEST-002. Therefore INGEST-002 can register and review the schema but cannot receive a production proposal until a later producer is enabled.

**Decision:** keep direct MAINT-001 operator entry as the no-AI path; a manually authored source-backed draft is not part of INGEST-002 and must not be represented as an AI run. Implement INGEST-002 with deterministic contract tests and enable its queue only when a registered producer exists. UI-001 must show a truthful unavailable or empty state rather than implying extraction is active. If a neutral source-backed manual-draft workflow is needed later, it requires its own domain owner and design.

### 3. Link and update semantics are undefined

The backlog does not say whether link mutates an issue, which fields update may change, or whether reporter/property/lifecycle may be replaced.

**Decision:** link is provenance-only; update applies only selected mutable issue detail fields to an active issue; reporter correction and all other lifecycles remain separate commands.

### 4. No module currently owns durable source-to-issue review provenance

AI decisions point to a result but do not record the domain-specific effect, retry response, applied fields, or an Intake-facing issue link. Audit cannot serve as operational linkage.

**Decision:** add `intake_issue_review_outcomes` under INGEST-002. Intake owns the source/review provenance; Maintenance remains the issue authority; AI Governance remains the draft authority.

### 5. Atomic approval is promised but the implemented services cannot yet share it

Current Maintenance create/patch services and generic AI review services open their own units of work. The implemented Intake attention operation also lacks its required operation/audit writes.

**Decision:** add transaction-aware operations and a Maintenance-owned approval handler using one immediate connection. Do not coordinate by sequential API calls or compensate after partial commits.

### 6. Update concurrency and lost-response behavior are unspecified

Maintenance patching has no expected revision or idempotency, while UI-001 requires stale-edit protection and outcome reconciliation.

**Decision:** require the reviewed target revision and an INGEST-002 terminal idempotency key. Store an immutable response snapshot in the outcome row. Do not broaden the ordinary patch endpoint merely to hide this workflow's stronger contract.

### 7. Generic AI dismissal conflicts with Intake attention state

The existing generic dismiss endpoint terminally dismisses a draft but cannot decide whether its source means no issue or should return for rework. It may leave a source incorrectly `in_review`.

**Decision:** require the two explicit domain dismissal modes and route issue-intake dismissals through INGEST-002's atomic handler. Prevent the generic route from bypassing registered domain consequences.

### 8. Multiple live proposals conflict with Intake's single attention state

AI Governance permits multiple drafts while Intake has one attention state. Without an issue-specific rule, simultaneous drafts could race and create duplicate issues from the same retained message. The Product Brief already requires deduplication to prevent one message from creating multiple issues.

**Decision for MVP:** enforce one live issue-intake proposal and at most one approved issue consequence per source; require explicit supersession for reruns. Multi-issue splitting remains unsupported until a separate source-splitting or review-item contract is designed.

This follows the current Product Brief. A change to support several issues from one source would require an explicit product and data-model revision.

### 9. Reporter extraction cannot satisfy MAINT-004 identity requirements

Reporter text and role from a source do not prove a Party, local-operator subject, property relationship, or historical eligibility.

**Decision:** require explicit operator selection of the MAINT-004 reporter subject and role for create. Optional matching may suggest a subject, but anonymous or unresolved proposals cannot commit. Link/update never change the existing reporter implicitly.

### 10. Attachment treatment is unspecified

Comparing evidence does not say whether source attachments become issue evidence. Automatically creating a second file link can imply operator endorsement and complicate later archival.

**Decision:** retain attachments under the Intake source and expose them through source-to-issue provenance. Create a Maintenance file link only through a separate explicit evidence action.

### 11. INGEST-001 consumer contracts remain incomplete

The [pending implementation review](pending_code_review_comments/INGEST-001_COM-001_REVIEW_COMMENTS.txt) identifies missing exact-revision/batch readers, unaudited attention transitions, absent file-integrity propagation, and a FILE persistence-boundary violation. INGEST-002 depends directly on those paths.

**Decision:** these findings are mandatory readiness gates. Resolve and verify them before INGEST-002 implementation begins; do not implement review orchestration against raw Intake or FILE tables.
