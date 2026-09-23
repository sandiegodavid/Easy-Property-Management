# MCP-001 — Muse as Consumer: Agent Delegation and Write-Intent Design

## Status

Proposed design; no bridge implementation or verified personal-agent bootstrap is implied. The bridge section below supersedes the earlier setup-bundle proposal. Model inference is verified separately through [Meta Model API](https://dev.meta.ai/docs/overview). Muse personal-agent connector registration, local reachability, scheduling, and secure credential delivery remain integration gates.

## Purpose

`MCP-001` covers both directions of Muse integration. The application-using-Muse direction (ingest, transcription, drafting) is governed by `AI-GOV-001` and implemented by domain slices. This document specifies the reverse direction: **Muse as a consumer of the application** — an agent that reads workspace records and proposes property-management work on the operator's behalf.

The core principle is unchanged: the agent never writes official records directly. It reads through bounded, redacted projections and submits typed write *intents*; intents become `ai_drafts` through the standard `mcp_proposal` run flow and only take effect when the operator approves them in the review queue.

## Scope and boundaries

MCP-001 provides:

- The local MCP server: read/query tools with declared projection schemas over workspace records.
- Agent identity and delegated authorization: scoped, revocable grants for named agents (Muse first), with tokens in the OS credential store.
- The write-intent envelope and the first fully-specified intent slice (maintenance issues); later workflows extend the catalog.
- Source-owned opaque revisions and content fingerprints so proposals are evaluated against the source projection they were based on.
- Sandbox mode for exercising tools against disposable data.
- The change-notification polling contract (`activity.since`).
- Per-agent limits and accounting, reusing the `ai_action_limits` machinery.
- Audit events attributing agent reads, proposals, and decisions.

MCP-001 does not provide:

- Any AI capability itself (extraction, transcription, drafting) — domain slices own those.
- The operator review UI — `UI-001` owns review-queue rendering and the "proposed by Muse" attribution.
- Remote/cloud access to the workspace; the MCP server is local to the operator's machine.
- Autonomous side effects: no intent executes without operator approval, ever.

Hard dependencies: `AI-GOV-001` and `INGEST-002`, matching the backlog; their prerequisites provide audit, local workspace, retained sources, and issue review.

## Agent identity and delegated authorization

Muse acts as a distinct principal, delegated by the operator — never as the operator, and never with the operator's credentials.

- A **delegation grant** names the agent (`muse`), lists granted **scopes**, and is created explicitly by the operator in Settings → AI & Muse → Agent access (UI-001 follow-up to D46). Granting writes an audit event.
- Scopes are fine-grained verbs over entity kinds, e.g. `issues:read`, `issues:propose`, `properties:read`, `communications:read`, `documents:propose`. There is no wildcard scope; `admin` does not exist.
- The grant issues a **token** shown once at creation. The token is stored in the OS credential store keyed to the workspace ID, alongside provider API keys. Only a token *fingerprint* is persisted server-side, in the new `agent_delegations` table — never the token.
- Every MCP tool call authenticates with the token. Unknown, expired, or revoked tokens fail closed with a typed `401`/`403`; the failure is audit-logged.
- **Revocation** is immediate: the token stops working on the next call. In-flight runs finish; pending proposals already in the review queue stay there for the operator to approve or dismiss — revocation never silently deletes operator-visible work.
- Delegation is per workspace. Backup/export/restore and SaaS migration exclude tokens; a restored workspace requires re-grant before the agent can connect.

### `agent_delegations`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `agent_name` | Required, e.g. `muse`. One active grant per agent per workspace. |
| `scopes` | Required JSON list of granted scope strings; validated against the registered scope catalog. |
| `token_fingerprint` | Required SHA-256 of the token; used to identify the token, never to recover it. |
| `granted_at`, `revoked_at` | Required UTC; `revoked_at` null while active. |
| `last_used_at` | Nullable UTC; updated on authenticated calls (sampled, not per-call, to avoid write amplification). |
| `status` | `active`, `revoked`, or `expired`. |

## Read tool catalog

The MCP server exposes read/query tools only. Each tool declares its projection schema; responses are bounded pages of redacted projections, never full domain records.

| Tool | Returns |
| --- | --- |
| `properties.list` / `properties.get` | Property summaries: id, name, type, occupancy, availability, opaque source revision, and content fingerprint. No owner PII beyond masked references. |
| `issues.list` / `issues.get` | Issue summaries: id, property, category, priority, status, attention reason, opaque source revision, and content fingerprint. Narrative bodies are bounded by the tool contract. |
| `leases.get` | Lease terms for a property: parties (masked), dates, rent amount, opaque source revision, and content fingerprint. No bank or payment credential data, ever. |
| `rent.status` | Rent tracking state per property/lease with opaque source revision and content fingerprint. |
| `providers.list` / `providers.get` | Provider directory entries the operator maintains; no private contact details beyond what the operator's redaction profile allows. |
| `communications.list` / `communications.get` | Message metadata with bounded excerpts; full bodies only through explicit, purpose-declared parameters. |
| `tasks.list` / `tasks.get` | Tasks and reminders with due dates, statuses, related records. |
| `coverage.get` | A property's coverage states (Recorded / Needs review / Missing / Not applicable) per responsibility area. |
| `activity.since` | Change-notification cursor feed (see below). |

Conventions: cursor pagination with bounded page sizes; unknown fields forbidden in requests; every projection includes a source-owned opaque `source_revision` and canonical content fingerprint for concurrency; sensitive identifiers are masked per the owning module's redaction profile; empty results are explicit, never errors. No universal database version column is assumed.

## Write-intent envelope

A write intent is the only way the agent proposes a change. The envelope is uniform; the payload schema is per intent action, owned and validated by the domain module.

```json
{
  "intent_id": "uuid",
  "idempotency_key": "uuid",
  "agent_name": "muse",
  "action": "maintenance.issue.create",
  "base_ref": { "entity_type": "issue", "entity_id": "uuid-or-null", "source_revision": "opaque-source-revision", "source_fingerprint": "sha256" },
  "payload": { "...per-action schema..." },
  "rationale": "bounded operator-readable text, max 500 chars",
  "conversation_ref": "optional correlation id"
}
```

Rules:

- `action` is a namespaced code registered in config; unknown actions are rejected with a typed error.
- `base_ref.source_revision` is the version the agent based the proposal on (from a read tool). For creates, `entity_id` is null and the version refers to the parent/evidence record.
- The intent is submitted to the proposed authenticated `POST /api/agents/proposals` endpoint. The registered domain action validates source references, schema, scope, limits, and redaction, then admits an AI-GOV run with `execution_kind=external_proposal`. No second provider call occurs. Audit uses `actor_kind=ai_assistant` with the delegation reference; approval remains attributed to the operator.
- Duplicate `idempotency_key` returns the original run/draft; retries never double-propose.
- `rationale` is shown to the operator in the review queue next to the draft. It must be a plain-language reason, never a dump of record contents.

## Intent catalog — first slice: maintenance issues

The maintenance module owns these intent actions, their payload schemas, and their approval consequences.

### `maintenance.issue.create`

Draft a new issue from evidence (an ingested message, photo, or voice note).

Payload: `property_id`, `category` (bounded code), `priority` (bounded code), `title` (bounded), `description` (bounded, redacted input), `evidence_refs` (typed refs to messages/files the claim rests on; at least one required). Approval creates the official issue record linked to its evidence.

### `maintenance.issue.update`

Propose field updates to an existing issue: `category`, `priority`, `notes` (append-only; prior notes are never rewritten). `base_ref` must name the issue and its version. Approval applies the update in the owning module's transaction; if the version moved since, the draft is flagged stale and approval requires operator confirmation.

### `maintenance.issue.status`

Propose a status transition along the allowed path (`open` → `in_progress` → `resolved`; `resolved` → `open` for reopen). Payload: `to_status`, `note`. Terminal transitions are never implied — the agent must name the target status.

### `maintenance.issue.assign`

Propose assigning a provider to an issue. Payload: `provider_id`, `note`. Assignment is on the never-autonomous list: the intent only ever creates a draft; the provider is contacted only by the operator's explicit approval action, never by the agent or by approval alone without the module's contact step.

Later slices (rent reminders, document drafts, task creation, lease workflows) extend this catalog with the same envelope; each slice's design specifies its payload schema and approval consequences.

## Concurrency

- Every official record carries a monotonically increasing `source_revision`, already returned by read tools.
- A proposal is evaluated against `base_ref.source_revision` at review time. If the record changed since, the review queue marks the draft **stale**: the operator sees what changed and confirms or dismisses. Stale drafts are never auto-approved and never auto-rebased.
- Approval executes in the owning module's transaction with an optimistic-version check; a version mismatch inside the transaction aborts approval with a typed `409` (`ai_stale_draft`), leaving the draft proposed.

## Direct-vs-proposal boundary

The agent may write directly **only** to agent-scoped scratch: its own conversation checkpoints, read cursors, and working notes. These are never official records, never surfaced as operator data, and never backed up as workspace content.

Everything affecting official records — creates, updates, status changes, assignments — goes through write intents and the review queue. The AI-GOV-001 never-autonomous list (no sending messages, signing documents, payments, contacting or assigning providers, or changing lease/occupancy/money state except inside an operator-approved transaction) applies to the agent direction without exception.

## Sandbox mode

A `sandbox` flag on the MCP session routes all intents against a disposable copy of the workspace. Intents run full validation and dry-run approval consequences; no drafts enter the real review queue and no real records are touched. Sandbox sessions are labeled in every audit event. The sandbox is the expected way to exercise a new intent slice before granting its scope on the real workspace.

## Change notification

v1 is a polling contract, not a push channel:

- `activity.since(cursor, entity_kinds)` returns a bounded page of change metadata: entity type, entity id, change kind (`created`/`updated`/`status_changed`), timestamp, and the new `source_revision`. Bodies and narrative content are excluded; the agent follows up with read tools if it needs detail.
- Cursors are opaque and stable; polling more often than the documented minimum interval returns `429` with a retry hint.
- The feed respects scopes: the agent only sees change metadata for entity kinds it may read.

## Limits and accounting

- External proposals consume registered action admission caps and obey action enablement and the kill switch. App-side payload size limits apply. The app cannot enforce or measure the personal agent's model token budget unless supported usage data is reported.
- A new `ai_agent_limits` table holds measurable per-agent admission overrides keyed by (`agent_name`, `action_type`): enabled state, maximum proposals per UTC day, and maximum canonical payload bytes, each no broader than the registered action ceiling. It does not mirror prompt/completion token limits. Absent an override, the registered external-proposal defaults apply. Overrides are operator-editable in Settings and audit-logged.
- Reported agent model usage is optional provenance. Missing usage stays unknown; it is never reported as zero or inferred from proposal size.

## Audit and privacy

- Agent-authenticated reads are audit-logged at the tool-call level (tool name, entity refs, timestamp) with `actor_kind=ai_assistant`, `agent_name`, and the delegation id. High-volume polling reads may be sampled per config; proposals, approvals, and revocations are never sampled.
- One correlation id spans the intent, its run, its draft, the review decision, and the resulting official record.
- Audit snapshots apply the owning module's redaction policy; agent scratch is excluded from operator-visible snapshots.
- Delegation grants, scope changes, and revocations are configuration changes with audit events.

## API contracts

MCP tools are exposed over the local MCP transport with JSON schemas per tool; the REST surface manages delegation and introspection:

- `POST /api/agents/delegations` creates a grant (operator action, returns the one-time token).
- `GET /api/agents/delegations` lists grants with fingerprints, scopes, status, and last-used timestamps — never tokens.
- `POST /api/agents/delegations/{id}/revoke` revokes immediately.
- `GET /api/agents/scopes` returns the registered scope catalog.
- `POST /api/agents/proposals` accepts authenticated external intents through AI-GOV's admission port, with typed `409`s for stale revisions, limit violations, disabled actions, and kill-switch blocks. It exposes no generic provider-run operation.

Malformed values return `422`; unknown entities `404`; authentication failures `401`/`403` with no detail leakage.

## UI-001 scope pointer

UI-001 owns the operator-visible surface, as a follow-up to D46:

- Settings → AI & Muse → Agent access: grant/revoke delegation, scope checklist, token fingerprint and last-used display, per-agent limit overrides.
- Review queue: "Proposed by Muse" attribution with model, run id, rationale, and stale-version warnings on every agent-originated draft.
- Activity views: agent proposals and decisions attributed to Muse, distinct from operator actions.

## Acceptance criteria

- Delegation grant → token → authenticated read tools → write intent → draft in review queue → operator approval creates the official record, end to end, with audit events at each step carrying `actor_kind=ai_assistant`.
- Revoked token fails closed on the next call; pending drafts remain for operator decision.
- Unknown action codes, malformed payloads, and missing evidence refs are rejected with typed errors before any draft is created.
- Stale base versions flag drafts and abort approval transactions with `ai_stale_draft`.
- Sandbox intents never touch real records or the real queue.
- Idempotent intent resubmission returns the original run/draft.
- Secrets (tokens, API keys) proven absent from the database, snapshots, backups, exports, and logs.
- `activity.since` polling respects scopes and rate limits.

## Non-goals

- Remote or multi-user agent access; the MCP server is local and single-operator.
- Push notifications or subscriptions; polling is the v1 contract.
- Agent-to-agent delegation or sub-delegation.
- Automatic approval, auto-send, auto-sign, auto-pay, or any autonomous side effect.
- Model evaluation or fine-tuning on workspace data.

## Bridge bootstrap protocol — agent or manual intake

The product decision is inbound via Muse Agent or manual operator entry, with no app-held Gmail, Outlook, or SMS credentials and no app mail polling. Muse performs extraction using its own authorized connections. The app retains submitted evidence, proposed fields, review decisions, and audit history. Outbound drafts are sent manually by the operator; the bridge receives no sending authority.

### Connection and setup

Personal-agent connector registration, secure credential delivery, local API reachability, and schedule management remain verification gates. A cloud agent cannot inherently reach a loopback URL. No implicit tunnel is authorized. Manual intake remains available while agent access is unavailable.

Settings owns enable/pause, Gmail filter, optional sender filters, desired poll interval, registered scopes, review requirement, last contact, last successful poll, sanitized failures, and proposal counts. Sender filters never confer authority. Desired and acknowledged configuration versions are distinct; reading a changed interval does not automatically reschedule the agent.

Generate a non-secret versioned descriptor with workspace ID, verified address, supported endpoint paths, and approved scopes. Setup secrets never enter workspace files, backups, exports, logs, or audit snapshots. If the verified authorization protocol uses a one-time app token, it has 256 bits of randomness, a 15-minute expiry, atomic single consumption, and only a stored verifier. Exchange it through a dedicated setup operation bound to the preapproved grant; the agent cannot grant itself privileges through an operator endpoint. Initial scopes cover source submission, issue proposals, config/heartbeat, and required bounded context reads only. Tasks/documents require separately registered actions and grants.

After the required user approval, securely exchange credentials, establish a supported schedule, acknowledge configuration, and prove the connection with synthetic data. One-step setup and unattended rotation remain intended UX until the actual integration supports them.

### Poll and admission

1. Fetch authenticated, delegation-scoped `GET /api/bridge/config`. Disabled, revoked, or paused bridges cannot submit even with stale cached configuration. The AI kill switch belongs to `/api/ai/settings`.
2. Muse reads its authorized mailbox using the configured filters and durable continuation state. App permission does not grant or revoke Muse's independent mailbox access.
3. Submit bounded original source evidence and provenance through Intake's authenticated source-admission boundary. Preserve source content separately from the proposed interpretation, with authorized attachments through FILE-001. Missing source content is explicitly marked incomplete; a message ID alone cannot support a source comparison.
4. Submit the draft through `POST /api/agents/proposals`, referencing retained evidence. AI-GOV admits an `external_proposal` without a second model call. No generic `/api/ai/runs` endpoint is exposed.
5. Deduplicate sources by workspace, provider, mailbox/account identity, and provider message ID. Validate identity against the authorized bridge binding; treat agent-supplied provenance as agent-reported unless independently verified. Use a separate stable UUID request idempotency key. Intake defines duplicate candidate handling so retries do not create additional drafts.
6. Retain per-message success/retry state and advance checkpoints only for acknowledged or explicitly skipped items. Timestamp-only cursors and rolling one-day queries are insufficient after downtime; define overlap, pagination, catch-up, and failure retries before enablement.
7. Submit an authenticated heartbeat after each attempted poll, including empty and failed polls when the app is reachable. Include a unique poll ID, acknowledged config version, outcome, bounded counts, and sanitized error codes. Agent timestamps are diagnostic; server receipt time drives freshness.

### Heartbeat monitoring

The app retains bridge enable time, last server-received heartbeat, last successful poll, reported poll outcome, and acknowledged interval/configuration. These belong to MCP bridge state and require schema, audit, and restore coverage. A repeated poll ID is idempotent and cannot fabricate new activity.

While enabled and expected to run, no heartbeat for twice the acknowledged poll interval triggers a persistent Settings/DASH-003 warning: “No Muse bridge contact since <time>. Check the connection or enter issues manually.” Before the first heartbeat, measure from enable time and show “No bridge contact yet.” Use the configured interval until the initial acknowledgement arrives; unacknowledged interval edits do not hide an existing stale warning.

A heartbeat clears the contact warning but a failed poll keeps a separate failure warning until a successful poll is reported. Neither heartbeat nor success report proves complete mailbox coverage: the app cannot independently detect messages the agent never reported. Health is evaluated from persisted timestamps on app startup/resume as well as while running; a closed local app cannot display a live warning. Expected paused/revoked states do not generate stale alerts. Audit health transitions once rather than every dashboard read.

### Revocation, rotation, and restore

Recheck grants and pause state before committing admission. Revocation rejects the next app request; it cannot stop an external schedule or revoke Muse's Gmail permission. Keep existing drafts reviewable. Rotation needs verified secure delivery, acknowledgement, retry behavior, and revocation precedence before unattended rotation is promised. Restore invalidates usable delegations, including retained verifiers, and requires fresh authorization. Prior health history is retained as history, never presented as a live restored connection.

## Definition of Done

- [ ] Delegation persistence, expiry, restore invalidation, scope validation, and audit history have exact-schema and retained-data validation.
- [ ] Read projections are bounded and redacted, with source-owned opaque revisions/fingerprints rather than assumed universal version columns.
- [ ] External proposals enter AI-GOV without a second model call and are approved atomically through the owning domain.
- [ ] Revocation, pause, idempotency, source staleness, limits, and secret exclusion have regression coverage.
- [ ] Optional bridge transport, individual approval, secure credential delivery, and scheduler capabilities are verified against the personal agent.
- [ ] Setup secrets are absent from the workspace, archives, logs, and non-secret descriptors.
- [ ] Intake retains original sources and attachments separately from drafts, with account-scoped source deduplication and reliable retry/catch-up.
- [ ] Desired and acknowledged configuration are distinguishable; schedule changes are not inferred from config reads.
- [ ] A synthetic end-to-end test proves read, source admission, draft review, and denial after revocation.
- [ ] Operator surfaces remain UI-001 work; neither this design nor a generated descriptor proves that a live bridge exists.
- [ ] Setup bundle generation, one-time token exchange, and the agent poll runbook end to end (Gmail to intents to review queue, Gmail message IDs as idempotency keys).
- [ ] Config propagation (app settings edits take effect on the next poll with no agent-side update) and heartbeat: a missed heartbeat surfaces a persistent "bridge silent" banner within 2x the poll interval.
