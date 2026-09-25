# AI-GOV-001 — Governed AI Runs and Review Foundation

## Status

Proposed backend/API design. No application code is included in this document.

This design is based on the AI-GOV-001 backlog outcome, [ARCHITECTURE.md](ARCHITECTURE.md), the accepted AI decisions in [DECISIONS.md](DECISIONS.md), the confirmed UI direction in [UI-001_DESIGN.md](UI-001_DESIGN.md), [AI_INTEGRATION_RESEARCH.md](AI_INTEGRATION_RESEARCH.md), the downstream AI/ingestion/MCP backlog, and the current server implementation.

Built-in assistance is provider-neutral. Operators may choose a registered hosted model connection (including Meta Model API or OpenAI) or a validated on-device runtime. Connected personal assistants are separate MCP-001 connections and may use a different vendor. No provider is selected merely by this design; production adapters must pass their capability and disclosure gates. This revision supersedes the former fixed Meta Muse identity.

## Outcome

AI-GOV-001 supplies a reusable governance boundary for later AI capabilities. It ensures that:

- the application never sends an unbounded or unreviewed domain record to a model provider;
- the exact bounded, redacted provider input and validated output are retained separately from the authoritative source record;
- model output remains a draft until an explicit operator decision;
- approval consequences execute in the owning domain's transaction;
- every run, edit, decision, limit change, and provider-setting change is auditable;
- provider credentials remain device-local secrets; and
- configured limits and a global kill switch fail closed.

AI-GOV-001 is infrastructure and governance, not an AI feature. It does not extract an issue, transcribe audio, diagnose a repair, rank a provider, draft a document, or expose an MCP server. Those capabilities register their own action definitions in later slices.

## Current implementation baseline

The repository already provides the foundations AI-GOV-001 must reuse:

- a single external workspace with one SQLite writer and short immediate transactions;
- exact current-schema validation and a greenfield Alembic baseline;
- append-only AUDIT-001 events with `local_operator`, `system`, `connector`, and `ai_assistant` actor kinds;
- encrypted LOCAL-002 archive validation, backup, and restore;
- FILE-001 stable file records and domain-owned link validation;
- FastAPI/Pydantic contracts that reject unknown fields; and
- an OS-keyring implementation currently specialized for automatic-backup passphrases.

The following do **not** exist yet and must not be assumed:

- an `ai_governance`, `intake`, `connectors`, `documents`, jobs, or outbox module;
- a general external-provider credential abstraction;
- a durable background worker;
- AI action, prompt, redaction-profile, or approval-handler registries;
- application-wide record-version columns; or
- any production AI capability that can create a real draft.

Consequently AI-GOV-001 uses synchronous provider execution outside database transactions, introduces the minimum provider-secret port it needs, and verifies its extension contracts with a test-only action definition. It does not invent a generic job system or production AI action.

## Scope

AI-GOV-001 includes:

- the `ai_governance` module and its exact-schema/data validator;
- a static action-definition registry composed at bootstrap;
- a provider-agnostic `AiProviderPort`;
- a versioned redaction-profile registry and deterministic redaction engine;
- governed run, draft, review-action, settings, and action-limit persistence;
- provider credential set/delete/status operations through the OS credential store;
- generic draft list/detail/edit/dismiss APIs and approval dispatch to an owning-domain handler;
- atomic limit reservation, idempotency, lifecycle, audit, and crash-recovery rules; and
- LOCAL-002 backup/export/restore and retained-data validation.

AI-GOV-001 excludes:

- production prompts or domain output schemas;
- source ingestion and source-message persistence (`INGEST-001`);
- issue extraction/matching and issue-specific approval (`ISSUE-AI-001`, `ISSUE-AI-002`, `INGEST-002`);
- a local MCP server or assistant delegation (`MCP-001`);
- voice transcription, documents, marketing, recommendations, or scheduling;
- automatic approval or any automatic domain side effect;
- domain-quality evaluation suites (owned by each capability), fine-tuning, retrieval infrastructure, or prompt marketplaces; and
- React work. UI-001 owns the eventual Settings and review surfaces.

## Architecture and ownership

| Concern | Owner |
| --- | --- |
| Authoritative source record and its lifecycle | Source domain, such as Intake or Maintenance |
| Candidate context construction | Capability-owning domain |
| Redaction profile definition | Capability-owning domain, registered with AI Governance |
| Deterministic profile execution and secret rejection | AI Governance |
| Provider invocation and provider error translation | Provider adapter behind `AiProviderPort` |
| Run, exact redacted request, draft shell, review actions, limits | AI Governance |
| Draft payload schema and edit validation | Capability-owning domain, registered as a pure validator |
| Approval eligibility and official-record consequences | Capability-owning domain |
| Atomic review completion inside the approval transaction | AI Governance transaction operations called by the owning domain |
| Source attachments | FILE-001 plus the source domain's file-link policy |

Neither side imports the other's SQLAlchemy models. Cross-module calls use application protocols composed at bootstrap. AI Governance never mutates an authoritative source or result record itself.

## Static action-definition registry

Every production action type must have one immutable code definition registered at startup. Unknown or duplicate action types fail startup. An `AiActionDefinition` contains:

- `action_type` and `owning_module`;
- allowed source entity types;
- candidate-input schema;
- redaction profile name and version;
- provider-request schema and maximum serialized size;
- prompt-template identifier and version;
- draft payload schema and output-schema version;
- allowed confidence labels, their provenance fields, and whether a calibrated numeric value is permitted;
- required capabilities/input modalities, permitted execution locations, and allowed provider/model/version ceilings;
- maximum prompt and completion tokens permitted by code;
- the explicit approval effect (`create`, `update`, or `advisory_only`) and whether it requires a result reference; and
- validator/approval-handler identifiers supplied by the owning module.

The registry is code, not mutable workspace data. Operator settings may disable an action or narrow its limits/provider choices, but may never expand beyond the registered definition. Historical rows retain all version identifiers needed to interpret them after the active definition changes.

AI-GOV-001 itself registers no production action. Tests use a synthetic action to prove the framework without pretending that a later feature exists.

## Persistence model

All IDs are UUID strings. Timestamps are timezone-aware UTC text. JSON is canonical, bounded, and validated before persistence.

### `ai_settings`

One singleton row owns workspace-wide settings.

| Field | Rule |
| --- | --- |
| `singleton` | Integer primary key constrained to `1`. |
| `kill_switch` | Boolean. When enabled, no new provider call, assistant read/export, or external proposal is accepted. Recheck at dispatch and result admission. Existing drafts remain reviewable, dismissible, and explicitly approvable under current domain checks; no new AI call occurs. |
| `built_in_enabled` | Boolean, default false. Off blocks all app-initiated inference, including action-specific connection overrides, without affecting assistant grants. |
| `default_connection_id` | Nullable reference to `ai_model_connections`; null means built-in assistance is not configured. Selection never grants disclosure permission. |
| `updated_at` | UTC timestamp. |

The kill switch is not duplicated on every action-limit row.

### `ai_settings_operations`

This append-only idempotency table records a settings operation key, semantic request fingerprint, immutable response snapshot, and creation time. It prevents an older retry from overwriting newer settings. It is validated and included in encrypted backup/restore.

### `ai_model_connections`

One row per configured model connection, independent of MCP-001 assistant delegations. This is a seventh governance table.

| Field | Rule |
| --- | --- |
| `id`, `label`, `revision` | Stable UUID, bounded operator label, monotonic configuration revision. |
| `adapter_id`, `adapter_version`, `model_identifier`, `execution_location` | Registered combination only; location is `on_device` or `cloud`. Operators cannot enter arbitrary network destinations through this table. |
| `model_artifact_digest`, `quantization`, `runtime_id`, `runtime_version` | Required for a validated local configuration; null where inapplicable for hosted models. |
| `enabled` | Disabling blocks new dispatch; no automatic alternative is chosen. |
| `cloud_data_classes`, `disclosure_version`, `disclosure_accepted_at` | Explicit allowed data classes and destination-specific disclosure acknowledgement; default empty. Required for cloud transmission of each governed class, including tenant/owner message content. A destination or disclosure change clears permission. Local processing needs no cloud consent. |
| `created_at`, `updated_at` | UTC timestamps. |

Credentials, local endpoints, paths, runtime processes, downloads, and current health are device configuration, not portable row content. Readiness is derived from a device check; restoring a row cannot restore a live connection. Action overrides may select another registered connection with the same checks. The effective connection and revision are frozen when reserving a run.

### `ai_action_limits`

One optional operator override per registered action type.

| Field | Rule |
| --- | --- |
| `action_type` | Primary key; must exist in the static registry. |
| `enabled` | Boolean. |
| `connection_id` | Optional registered model connection override; null uses the workspace default. External proposals do not use it. |
| `max_runs_per_utc_day` | Positive integer no greater than the registered ceiling. It applies to both provider generations and later external proposals. |
| `max_prompt_tokens` | Positive integer no greater than the registered ceiling. |
| `max_completion_tokens` | Positive integer no greater than the registered ceiling. |
| `allowed_models` | Canonical JSON array containing a non-empty subset of the registered transport-provider-qualified model/version identifiers. |
| `updated_at` | UTC timestamp. |

An absent override uses the static definition's defaults. A UTC calendar day is used deliberately because the workspace has no single authoritative business time zone. Blocked attempts do not consume the run cap; every attempt that reaches the configured model transport or every external proposal admitted later by MCP-001 does.

### `ai_runs`

One row represents one governed provider invocation or, later, one externally produced assistant proposal admitted to the review queue.

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `execution_kind` | `provider_generation` or `external_proposal`. The latter is reserved for MCP-001 and does not trigger a second model call. |
| `action_type`, `owning_module` | Required registered codes. |
| `source_entity_type`, `source_entity_id` | Required typed source reference. No polymorphic database foreign key is claimed. |
| `source_revision`, `source_fingerprint` | Required opaque revision and SHA-256 supplied by the source-domain projection. These preserve what the run was based on without requiring a universal `record_version` column. |
| `connection_id`, `configuration_revision`, `transport_provider`, `adapter_version`, `model_identifier`, `execution_location` | Generated runs snapshot the registered model connection and actual provider/model/location. No fixed assistant name. |
| `model_artifact_digest`, `quantization`, `runtime_id`, `runtime_version` | Required provenance for local generation; absent when inapplicable. |
| `assistant_name`, `assistant_connection_id`, `delegation_id`, `reported_model_identifier` | External proposals identify the authenticated connection/grant. Display name comes from that binding, not submitted text. Model/usage are nullable and labeled reported unless verified. Generated runs need no personal-assistant identity. |
| `prompt_template_id`, `prompt_template_version`, `output_schema_version` | Registered prompt versions required for generated runs; null for external proposals whose internal prompt is unknown. Output/envelope schema version is required for both kinds. |
| `redaction_profile`, `redaction_profile_version` | Required applied profile. |
| `governed_input_json` | Exact canonical bounded content admitted by governance: the redacted provider request for `provider_generation`, or the validated proposal envelope for `external_proposal`. This is retained so the operator can see what left or entered the workspace. It never contains credentials. |
| `input_fingerprint`, `request_fingerprint` | SHA-256 digests of the canonical governed input and complete idempotent request respectively. |
| `status` | `reserved`, `running`, `succeeded`, `failed`, or `blocked`. |
| `prompt_tokens`, `completion_tokens` | Nullable provider-reported usage. |
| `provider_request_id` | Nullable bounded non-secret provider reference. |
| `error_code`, `error_detail` | Nullable bounded sanitized values; required for `failed`/`blocked`. Raw provider bodies and stack traces are forbidden. |
| `idempotency_key` | Globally unique caller-supplied UUID. |
| `correlation_id` | Required UUID shared with drafts, review actions, result writes, and audit events. |
| `started_at`, `finished_at`, `created_at` | UTC lifecycle timestamps with status-dependent constraints. |

Retaining only an input fingerprint is insufficient for the accepted redaction-visibility and audit requirements. The exact **redacted** request is therefore retained. Raw source records remain owned separately by their source module.

### `ai_drafts`

One validated draft per successful run in this slice.

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `run_id` | Required unique foreign key to `ai_runs`. |
| `entity_kind` | Registered bounded code describing the draft payload. |
| `draft_payload` | Canonical JSON validated by the registered owning-domain schema. |
| `confidence` | Nullable bounded JSON validated against the action definition's allowed labels and required provenance. A numeric value is accepted and presented as a percentage only when the action definition permits it and identifies a documented calibrated source; otherwise confidence is a named qualitative label. |
| `status` | `proposed`, `edited`, `approved`, `dismissed`, or `superseded`. |
| `supersedes_draft_id` | Nullable unique self-reference. A draft may supersede one prior draft; no branching or cycles. The prior draft becomes `superseded` in the same transaction. |
| `version` | Positive monotonic integer for optimistic review edits and decisions. |
| `terminal_at` | Required only for `approved`, `dismissed`, or `superseded`. |
| `created_at`, `updated_at` | UTC timestamps. |

The source reference is reached through the immutable `run_id`; it is not copied into the draft. Only `proposed` and `edited` drafts may be edited or decided. Terminal drafts are immutable.

### `ai_review_decisions`

This append-only table records every operator review action, including edits.

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `draft_id` | Required foreign key. |
| `decision` | `edited`, `approved`, or `dismissed`. |
| `draft_version_before`, `draft_version_after` | Required monotonic versions proving which payload was reviewed. |
| `operator_note` | Nullable bounded operator text. Domain snapshot policy determines history redaction. |
| `result_entity_type`, `result_entity_id` | Present for approval when the action definition requires a resulting record; absent for edit/dismiss and for approved advisory-only actions. |
| `correlation_id` | Required; approval uses the run correlation ID. |
| `decided_at` | UTC timestamp. |

There may be many `edited` rows but at most one terminal (`approved` or `dismissed`) row per draft. An edit is a recorded review action, not a terminal decision.

## Redaction and input controls

The owning domain prepares a typed candidate projection; it does not hand an ORM entity or arbitrary dictionary to AI Governance. AI Governance then applies the registered profile and validates the resulting provider request.

A profile is versioned code with explicit rules per field: allow, drop, mask, truncate, or transform through a named deterministic transformer. Unknown fields fail closed. Across all profiles:

- credentials, secrets, raw bank/payment data, and unredacted account identifiers are forbidden;
- free-form collections, narrative fields, and file-derived text have explicit item/character limits;
- applicant financial evidence requires the future capability's explicit consent and retention metadata;
- provider instructions and context are scanned recursively using the existing conservative audit secret patterns plus action-specific rules;
- reversible tokenization is out of scope until a design identifies where its mapping lives and how it is retained safely; and
- the exact canonical redacted request and profile version are persisted before the provider is called.

Cloud disclosure is checked against the effective connection, accepted disclosure version, and each action's data classes. Tenant/owner messages remain blocked by default; other classes do not inherit permission from them. Before sending, show the destination and what will leave the device. Changing vendors or moving a local request to cloud requires that destination's explicit permission. Redaction and minimization remain mandatory for both local and cloud inference. A local client or file bridge does not establish local processing; assistant exports require their own MCP-001 disclosure grant.

Provider output passes the registered Pydantic schema, bounded-size checks, and secret/account-identifier rejection before a draft can be stored. A malformed output fails the run and creates no draft.

## Provider adapter and credentials

`AiProviderPort` is owned by AI Governance. Its application contract is conceptually:

- `estimate_input_tokens(provider_request, model) -> int`;
- `generate(provider_request, model, max_completion_tokens, timeout) -> AiProviderResult`; and
- typed errors for unavailable credentials, timeout, rate limit, rejected input, malformed response, and provider failure.

The coordinator, not the adapter, owns action limits, persistence, idempotency, and audit. The adapter owns protocol translation, timeout enforcement, provider token counting/estimation, response-schema submission where supported, and sanitized provider errors. A provider/model that cannot enforce the registered completion ceiling is not eligible.

AI-GOV-001 adds an AI transport-credential application protocol and a keyring adapter keyed by `(workspace_id, connection_id)`. It may reuse the `keyring` library but must not reuse the backup-specific `BackupSecretStore` interface. APIs can set, replace, delete, and report credential presence for the configured transport; they never return credential values. Secrets are excluded from database rows, logs, audit snapshots, archives, exports, and migration payloads.

A static adapter registry declares supported models, execution location, credentials required, tested input modalities, schemas, and context/output ceilings. Settings selects only registered combinations; unavailable choices show a reason and cannot run. Meta Model API is one hosted adapter, not the identity of all AI output. A model's function calling is a proposed structured response, not permission to execute tools.

Local inference is introduced by AI-LOCAL-001 through the same port. Machine configuration constrains the endpoint to the approved local runtime and rejects cloud tags/fallback. Start with one local inference at a time and bounded text; timeout and explicit interruption must leave normal record workflows usable. Release concurrency capacity on every exit. No automatic installation/download or model switching occurs during an ordinary action. Weights are outside backups. Cloud credentials are optional for local adapters; check the adapter's actual requirements rather than demanding a dummy API key.

Configuration changes affect later runs only. Snapshot the chosen configuration at reservation, recheck permission/pause immediately before dispatch and result admission, and never relabel old drafts. Revoked permission or pause during a call cannot recall sent data; retain a sanitized blocked outcome and no new review draft for a late result. There is no cross-provider automatic retry.

## Run lifecycle and transaction boundaries

AI-GOV-001 does not hold a SQLite transaction open during a network call.

1. The capability-owning application service supplies a typed candidate, source revision/fingerprint, and idempotency key to the AI coordinator.
2. The coordinator resolves the registered action, applies redaction, canonicalizes the exact provider request, and computes fingerprints.
3. It checks adapter readiness and any required credential through the device/keyring ports before opening a write transaction. In one immediate transaction it then checks the kill switch, built-in enablement, connection revision and disclosure permission, action enablement, registered transport/model/capability allowlist, token estimates, UTC-day cap, source reference, and idempotency. It inserts a `reserved` run and its audit event. A missing required credential or other blocked request inserts a `blocked` run and audit event but never calls the provider.
4. A short transaction rechecks permission and pause, then changes the reserved run to `running`. The provider call then occurs with no database transaction open.
5. On success, one immediate transaction rechecks pause/disclosure eligibility and revalidates the returned payload, changes the run to `succeeded`, inserts the `proposed` draft, and writes correlated audit events.
6. On failure, one immediate transaction marks the run `failed` with a sanitized code/detail and writes its audit event. No draft is created.

The daily cap counts provider runs that reached `running`, including provider failures, and external proposals successfully admitted by MCP-001. Input tokens are conservatively estimated before a provider call; `max_completion_tokens` is passed to the provider. Reported actual usage is retained but does not retroactively invalidate a completed draft. Credential changes affect later reservations and do not cancel a provider call already in flight.

Automatic retries are excluded from this slice because provider idempotency semantics are not uniform. An explicit retry uses a new idempotency key and, if successful, supersedes the prior draft explicitly. Reusing an idempotency key with the same request fingerprint returns the original run/draft; reusing it with different content returns `409 ai_idempotency_conflict`.

Because there is no durable job runner, provider execution is synchronous in AI-GOV-001. On workspace startup, any `reserved` or `running` row left by a prior process is marked `failed` with `ai_run_interrupted` and a system audit event. A later jobs/outbox feature may add queued/cancelled states without changing draft or review semantics.

## Draft review and atomic approval

List, detail, edit, and dismiss are generic governance operations. Approval is domain-owned.

- `PATCH` requires the current draft `version`, validates the entire replacement payload with the registered domain schema, increments the version, writes an `edited` review row, and audits the before/after payload through the AI-specific snapshot policy.
- Dismiss requires the current version, moves the draft to `dismissed`, inserts the terminal review row, and audits the decision in one AI Governance transaction.
- Approve resolves the registered owning-domain handler. That handler opens its normal immediate transaction, reloads the draft through transaction-aware `AiReviewOperations`, verifies status/version and the current source revision, performs the official domain consequence, then calls `AiReviewOperations.complete_approval(...)` on the **same connection** to insert the decision and make the draft terminal. All domain and AI audit events share the run's correlation ID.
- A source revision mismatch returns `409 ai_stale_draft`. The draft remains reviewable; there is no automatic rebase. The operator may explicitly rerun or dismiss it.
- Approval never sends a message, signs a document, initiates a payment, contacts a provider, or silently changes lease, occupancy, financial, assignment, or communication-delivery state. A later owning-domain design must name the exact approved consequence.

AI Governance exposes transaction operations, not another module's repository. Owning modules expose pure validators and approval handlers, not their persistence models.

## Read and API contracts

All request models reject unknown fields. Pages use bounded cursor pagination.

- `GET /api/ai/settings` returns kill-switch state, default model connection, registered choices/capabilities, destination-bound disclosures, derived readiness, and action summaries. Assistant connection state is read separately from MCP-001.
- `PUT /api/ai/settings` changes the kill switch, built-in enablement, or default connection with idempotency and audit. It cannot implicitly consent to disclosure.
- `GET/POST /api/ai/connections` and `PATCH /api/ai/connections/{id}` list/create/update registered model configurations with revision checks; `POST .../{id}/test` checks readiness using synthetic content; `PUT .../{id}/disclosure` records explicit destination/data-class consent.
- `PUT /api/ai/connections/{id}/credential` stores/replaces that connection's write-only credential; `DELETE` removes it. Read APIs report presence only. No arbitrary URL/provider proxy is exposed.
- `GET /api/ai/limits` and `PUT /api/ai/limits/{actionType}` read or narrow operator overrides.
- `GET /api/ai/redaction-profiles` returns profile name, version, action binding, and a human-readable field-handling summary—not executable rules or secret values.
- `GET /api/ai/drafts` returns a bounded page filtered by status, owning module, entity kind, action type, or source reference.
- `GET /api/ai/drafts/{draftId}` returns run metadata, exact governed input, current draft payload, confidence, source reference/revision, review history, and source-comparison availability.
- `PATCH /api/ai/drafts/{draftId}` records an operator edit.
- `POST /api/ai/drafts/{draftId}/approve` dispatches to the registered owning-domain approval handler.
- `POST /api/ai/drafts/{draftId}/dismiss` records an explicit dismissal.

There is deliberately no generic public `POST /api/ai/runs`. A public arbitrary-action endpoint would let clients bypass the owning domain's source projection and redaction preparation. Later capability endpoints invoke the coordinator through an application port. MCP-001 may add an authenticated external-proposal admission port, not a provider-generation endpoint.

Malformed requests return `422`; missing resources `404`; provider transport failures `502`/`503`; and lifecycle, source-staleness, idempotency, disabled-action, limit, and kill-switch conflicts return typed `409` responses with stable codes.

## Audit, privacy, and retained-data validation

AI-GOV-001 registers dedicated snapshot and activity policies for `ai_run`, `ai_draft`, `ai_review_decision`, `ai_settings`, `ai_action_limit`, and `ai_model_connection`.

- Operator request/configuration/review events use `local_operator`.
- Provider-produced output events use the existing `ai_assistant` actor kind with provider/model in bounded snapshot fields or `actor_reference`.
- Startup interruption recovery uses `system`.
- General activity hides provider-input and draft bodies while record history may show domain-redacted values.
- Audit snapshots never contain provider credentials or raw provider error bodies.

Workspace-open and restore validation checks more than table shape. It verifies status/timestamp combinations, registered action/version references, canonical JSON and fingerprints, run-to-draft cardinality, legal draft transitions reconstructed from audit/review rows, monotonic draft versions, a single terminal decision, acyclic non-branching supersession, result-reference requirements, idempotency/request-fingerprint consistency, and correlated approval/domain audit evidence where the owning module has registered a validator. Unknown action/profile/schema versions fail closed rather than rendering ungoverned historical data.

The source domain must retain the referenced source or an explicit tombstone. AI Governance does not cascade-delete source records or drafts. Automatic AI-history deletion is out of scope; the MVP retains runs, redacted inputs, drafts, decisions, and audit history in the workspace.

AI-GOV-001 stores token usage when the provider reports it. It stores no cost estimate. A future cost field requires provider, currency, pricing snapshot/version, and an explicitly non-financial estimate label.

## Backup, export, and restore

All seven tables participate in the encrypted LOCAL-002 database snapshot and exact archive validation. Stable IDs, versions, source/result references, lineage, review history, and correlation IDs survive restore. Static action/profile definitions are application code; historical rows carry their identifiers and versions so the current application can validate them. Supported application releases must retain validators and presentation policies for every historical version they claim to restore.

Provider credentials are not workspace content and never enter the archive. After restore, configured connections remain visible but unavailable until credentials or local runtime readiness and disclosure settings are revalidated on the new device. Model weights, runtime endpoints, and secrets are excluded. If the restored application does not recognize a retained action/profile/schema version, restore validation fails before activation.

## UI-001 contract

AI-GOV-001 delivers backend/API behavior only. UI-001 must provide:

- Settings → AI assistance with separate Built-in AI and Connected assistants cards, registered cloud/on-device selections, capability-aware readiness, a global pause, write-only credential controls, per-action limits, redaction visibility, and per-destination disclosure controls that cannot disable mandatory redaction;
- a review queue that distinguishes source content, exact governed/redacted input, AI output, operator edits, confidence labels, and stale-source warnings;
- approve/edit/dismiss controls only when a registered owning-domain handler exists; and
- explicit unavailable states for missing credentials, unsupported providers, unregistered historical versions, and missing sources.

AI-GOV-001 should be marked backend-complete but operator-workflow-in-progress until UI-001 delivers these surfaces, consistent with other pre-UI features.

## Query and performance bounds

- Draft list uses one bounded page query plus bounded set-based metadata reads; it never loads full source records.
- Draft detail may resolve exactly one source projection through its registered owner reader.
- Limits are reserved in one immediate transaction using indexed action/status/start-time fields.
- No provider call, keyring prompt, or file read occurs while a database transaction is open.
- Provider input and draft JSON have action-specific byte ceilings; large documents/audio remain FILE-001 content processed by later capability-specific bounded extraction, not database blobs.

## Acceptance criteria

- Exact-schema and retained-data validation cover all seven tables and their lifecycle/correlation invariants.
- A synthetic registered action proves redaction, exact provider-input retention, output validation, draft creation, editing, dismissal, approval handoff, audit history, and backup/restore without creating a production AI feature.
- Unknown actions, provider/model/profile versions, extra fields, secrets, oversized context, and malformed outputs fail closed.
- Kill switch, destination-bound disclosure permission, disabled action, UTC-day cap, prompt cap, completion cap, registered adapter, and action/model capability allowlist are enforced atomically before provider access.
- Concurrent duplicate submissions make at most one provider call; same-key/different-request conflicts are stable and typed.
- Provider calls occur outside SQLite transactions; interruption recovery leaves no indefinitely running row.
- Terminal drafts are immutable; supersession is acyclic and non-branching; stale-source approval cannot create an official record.
- Approval writes the official record, review decision, terminal draft state, and all correlated audit events in one owning-domain transaction.
- Credential values are absent from SQLite, audit snapshots, logs, API responses, backups, exports, and restored workspaces.
- Backup/restore preserves stable IDs, exact redacted inputs, payloads, history, lineage, settings, and limits.

## Implementation sequence

1. Define the neutral adapter registry and connection/disclosure schema. Qualify one hosted candidate with synthetic data before production enablement; Meta and OpenAI are candidates, not mandatory defaults. AI-LOCAL-001 qualifies local inference separately.
2. Add AI domain values, action/profile registries, pure redaction, lifecycle, and limit policies with unit tests.
3. Add the seven tables to the current baseline, exact schema/data validation, audit policies, and LOCAL-002 coverage.
4. Add provider and credential ports plus a deterministic fake adapter; do not claim a production provider until its official protocol is selected.
5. Add the coordinator with short transaction phases, idempotency, concurrency, limit reservation, and interruption recovery.
6. Add draft read/edit/dismiss APIs, approval dispatch contracts, and a test-only owning-domain handler proving atomicity.
7. Add provider credential/settings APIs and secret-exclusion tests.
8. INGEST-002 registers issue review/approval contracts for retained sources; MCP-001 admits agent-produced proposals through them. Later model capabilities register their own actions. React remains UI-001 work.

## Phased AI delivery roadmap

The cross-feature delivery plan is:

1. **Phase 0 — Governance and adapters:** design and deliver AI-GOV-001, including governed draft/review state, exact redacted-input retention, confidence provenance, audit events, action limits, the provider adapter, configured transport credentials, and the fail-closed cloud-message-content permission and disclosure policy.
2. **Phase 1 — Source intake and review:** INGEST-001 retains evidence submitted by an authorized assistant or the operator and local voice transcripts. INGEST-002 owns issue-draft review and approval without depending on bridge transport or optional matching. No native mail fetching or sending is built.
3. **Phase 2 — Bridge and intelligence:** MCP-001 adds authenticated source/proposal admission and heartbeat monitoring. ISSUE-AI-001 supplies optional built-in extraction over retained evidence; external proposals need no second inference. ISSUE-AI-002 remains optional matching assistance; diagnosis, provider suggestions, and voice capabilities follow their active dependencies. Manual entry works without an agent.
4. **Phase 3 — Documents and marketing:** deliver DOC-001 before DOC-AI-001/002/003, and LIST-001 before MKT-AI-001. Generated material is reviewed; the operator sends manually and records the outcome.
5. **Phase 4 — Operator surfaces:** UI-001 renders Settings and review; DASH-003 displays pending work, failed polls, and stale bridge contact. CONN-001 remains limited to read-only Sheets authorization.

These phases are delivery gates, not permission to collapse ownership boundaries or build React before UI-001. A feature may be designed earlier, but implementation readiness follows its hard dependencies and Definition of Done.

## Backlog dependencies and downstream contracts

AUDIT-001 is AI-GOV-001's only hard prerequisite. FILE-001 remains a dependency of file-consuming capabilities such as ingestion, document analysis, and voice/file workflows; AI Governance itself owns no files or file links.

Hard dependencies take precedence over sequence labels; the optional local pilot runs only after its evidence and extraction contracts exist:

- INGEST-001 owns retained messages/transcripts and source identity.
- ISSUE-AI-001 supplies optional built-in extraction; INGEST-002 registers the issue-draft contract and ISSUE-AI-002 may add matching assistance.
- INGEST-002 owns issue-specific source comparison, link/create/update decisions, and Maintenance approval consequences.
- MCP-001 admits authenticated external proposals to the same queue without forcing another provider call.
- VOICE-AI-001, DOC-AI items, marketing, recommendations, and scheduling register their own bounded actions later.
- UI-001 renders Settings and review; DASH-003 later surfaces outstanding AI/ingestion attention on Home.

## Resolved design decisions

These decisions summarize the implementation boundaries established above. They are grouped by responsibility; all have the same status.

### Integration and domain ownership

- **Model inference and assistant access are independent.** Registered hosted or local adapters generate bounded drafts. MCP/file connections admit external proposals. Neither connection authorizes the other's accounts, credentials, or schedules. Provenance identifies the actual provider or submitting connection.
- **Domains control generation and approval effects.** Capability-owned endpoints prepare bounded context and invoke the coordinator internally; there is no generic public `POST /api/ai/runs`. Each action declares `create`, `update`, or `advisory_only` and whether approval requires a result reference. Approval and retained-data validation enforce that declaration; “Approved” never implies an unspecified domain mutation.
- **External proposals use a separate admission path.** Runs distinguish `provider_generation` from `external_proposal`; admitting an assistant proposal does not call a model again. External activity uses the existing `ai_assistant` audit actor kind with connection/delegation metadata.
- **Intake and sending remain application-controlled.** Authorized assistants or manual entry supply evidence; the app does not fetch mail. INGEST-001 retains that evidence and INGEST-002 owns source comparison and approval. COM-002 prepares drafts for manual sending. A heartbeat establishes contact, not complete message coverage; calendar synchronization requires its own capability and authority contract.

### Execution and controls

- **Global settings and action overrides have distinct scope.** One `ai_settings` singleton owns the global kill switch and default model selection. Action settings can narrow limits or select an eligible connection; assistant grants remain independent. Built-in Off blocks generated runs even when an action has a connection override.
- **The coordinator enforces application policy.** It checks permissions and limits, reserves capacity, and owns persistence, idempotency, and audit. Provider adapters translate protocols, count or estimate tokens, enforce request ceilings/timeouts, and sanitize errors.
- **Execution is synchronous outside database transactions.** Use `reserved`/`running` with startup interruption recovery. Durable queuing and persisted cancellation states require a later jobs/outbox design; they are not assumed by this slice.

### Evidence, review, and retention

- **Retain the exact governed input.** Store the bounded canonical redacted request and its fingerprint, not an unredacted duplicate or a fingerprint alone. External proposals retain their validated envelope so reviewers can distinguish source evidence, submitted interpretation, and operator edits.
- **Sources own revision and retention semantics.** Source adapters return opaque revisions and content fingerprints; no universal database version column is required. The source module retains the referenced record or an explicit tombstone. Source deletion never cascades into runs, drafts, or decisions.
- **Edits and approval are different review actions.** Review rows are append-only. An edit creates no official result; only a terminal approval can require a result reference, according to the action definition. Official-record consequences remain atomic with the owning domain's review completion.
- **Governed history is retained for the local MVP.** Runs, exact redacted inputs, drafts, decisions, lineage, and audit history remain in the workspace and portable archives until a dedicated retention design defines deletion/redaction and referential behavior.
- **Confidence and usage must have provenance.** Each action declares allowed confidence labels and their provenance. Percentages require a documented calibrated value permitted by that action; missing confidence or usage remains unknown. Retain provider-reported token usage, but omit cost estimates until a design supplies provider, currency, pricing snapshot/version, and an explicitly non-financial estimate label.

### Delivery dependencies

- **Governance does not own files.** FILE-001 is not an AI-GOV-001 hard dependency: governance stores bounded JSON and typed references, without an AI-owned file table or generic file links. File-consuming capabilities retain their own FILE-001 dependency.
- **Review precedes assistant transport.** INGEST-002 accepts validated submissions independently of MCP-001; MCP-001 then adds delegation and transport admission. Optional matching and built-in extraction do not gate external-proposal review. ISSUE-AI-001 provides optional built-in extraction; GMAIL-001, OUTLOOK-001, and SMS-001 remain superseded by assistant/manual intake. CONN-001 remains Sheets-only.
- **UI-001 requires working governance, review, and assistant contracts.** AI-GOV-001 supplies model settings, controls, and generic review; INGEST-002 supplies source comparison and issue approval; MCP-001 supplies assistant setup and status. All three are hard dependencies. An empty review shell or provider selector alone does not fulfill the operator workflow.

## Definition of Done

- [ ] Built-in model connections and assistant grants are independent; at least two fake adapters prove provider switching, truthful provenance, destination-specific permission, and no implicit fallback.
- [ ] The static action/profile registries and all seven persistence tables have exact current-schema and retained-data validation.
- [ ] Redaction is deterministic, versioned, bounded, secret-rejecting, and retains the exact redacted request.
- [ ] Tenant/owner message content is never sent to a cloud model unless the destination-specific permission and disclosure version are recorded; the permission cannot disable mandatory redaction or minimization.
- [ ] Limits, kill switch, registered connection selection, transport-qualified model allowlists, idempotency, transaction phases, and interruption recovery behave as specified.
- [ ] Draft edit/dismiss and owning-domain atomic approval contracts are verified with a synthetic capability.
- [ ] Source revisions/fingerprints, tombstones, indefinite MVP retention, confidence provenance, and declared approval effects are enforced and validated on workspace open and restore.
- [ ] AI-GOV-001 persists no file links and no cost estimate; provider-reported token usage remains available.
- [ ] AI-specific audit presentation is registered and correlation chains validate on workspace open and restore.
- [ ] Provider credentials are write-only OS secrets and pass database/log/archive exclusion tests.
- [ ] LOCAL-002 round trips every governed record and stable relationship.
- [ ] No production AI capability, MCP server, ingestion workflow, or React screen is falsely delivered by this slice.
- [ ] Backlog dependencies and UI/MCP contracts remain consistent with these decisions before dependent implementation begins.
