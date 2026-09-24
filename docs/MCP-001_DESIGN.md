# MCP-001 — Connected Assistants, Scoped Context, and Reviewed Proposals

## Status and purpose

Proposed implementation design, revised September 24, 2026 using [AI integration research](AI_INTEGRATION_RESEARCH.md). No live connection is implied. The stable backlog ID is retained; it defines the shared assistant contract and its MCP transport. The separate [Muse file-exchange proposal](META_MUSE_RESEARCH.md#proposed-file-exchange-adapter) reuses that application contract but is not part of the MCP protocol.

An assistant may discover messages in its separately authorized accounts, request bounded context, and submit evidence-backed proposals. The app validates and retains evidence, shows a review, and commits only after operator approval. Built-in hosted/local inference belongs to AI-GOV-001 and does not require an assistant connection. A model key never grants personal-assistant access.

Hard dependencies: AI-GOV-001 and INGEST-002. Their prerequisites supply audit, retained evidence, files, and domain review. Manual review and intake do not depend on this transport slice.

## Client compatibility and delivery scope

MCP is a protocol, not a ChatGPT-exclusive service. Documented consumers include [ChatGPT desktop/Codex](https://learn.chatgpt.com/docs/extend/mcp), [Claude Desktop](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop), [Claude Code](https://code.claude.com/docs/en/mcp), and [VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration). Local STDIO is the first transport target; exact client version, launch permissions, and tool behavior must pass an integration test. Streamable HTTP is a separate local adapter, not assumed available merely because a client supports MCP.

Hosted ChatGPT web does not inherit a desktop's local configuration. OpenAI documents [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) for private servers, but it is a remote disclosure route with separate setup and permissions. No tunnel, public endpoint, or remote access is enabled by this MVP design. Computer use and model function calling are not themselves MCP clients.

Muse Agent's supplied session reports file commands but no local MCP client, HTTP path, shell, or GUI control. Treat these as session observations to verify, not universal product claims. Its candidate transport is file exchange, with manual import as fallback. Do not advertise Muse as MCP-ready.

Deliver one tested local MCP client first, then qualify other MCP client configurations independently. File-adapter qualification is specified in the Muse note. The interface does not require every listed client to ship. Unsupported candidates appear as unavailable with a reason; they cannot grant working access.

## Shared application boundary

MCP tools call application services, never domain repositories directly. Other transports must reuse the same boundary:

1. Resolve workspace, connection, delegation, and effective scopes.
2. Check pause, expiry/revocation, disclosure permission, and bounded input.
3. Read authorized projections or admit original source evidence through Intake.
4. Validate a typed proposal, source identities/revisions, and idempotency.
5. Admit an AI-GOV run with `execution_kind=external_proposal`, without a second model call.
6. Return a durable receipt and expose subsequent review/commit outcomes.

No SQL, arbitrary filesystem access, approval tool, generic provider-run endpoint, sending, payment, signing, or unrestricted domain-write tool is exposed. Tools labeled proposal-only still mutate the review queue and must not claim to be read-only. Tool annotations describe behavior; authorization remains server-enforced.

## Connections and delegation

Settings → AI assistance → Connected assistants manages named connections independently of model providers. A connection identifies the actual product/client and transport, not just a vendor. Multiple connections can coexist; avoid scheduling duplicate mailbox discovery by default and warn about overlapping account/filter coverage. Cross-connection source deduplication remains mandatory.

A grant explicitly selects properties/units, data classes, purpose, registered read/submission scopes, expiry, and any scheduled polling expectation. No wildcard or admin scope exists. The application determines the effective principal from authenticated transport/session binding; envelope display names cannot confer identity or permissions. Reads and exports enforce both entity and field scope. Shared HOA cases disclose only authorized units; links to other units do not expand the grant.

| Persistence | Required content |
| --- | --- |
| `assistant_connections` | Stable ID, operator label, registered client/adapter/version, transport (`mcp_stdio`, `mcp_http`, `file_exchange`), desired/acknowledged configuration revisions, interactive/scheduled mode, lifecycle, and historical capability-test result. Live health is device-verified. |
| `agent_delegations` | Stable ID, connection/workspace ID, scope and entity/data-class bounds, disclosure version/acknowledgement, expiry, grant/revocation timestamps, status, and credential verifier where applicable. No usable secret. |
| `ai_agent_limits` | Connection/action admission caps and payload ceilings, no broader than the registered external-proposal limits. Unknown agent token usage is not zero. |
| `assistant_submissions` | Connection, grant, intent ID/key/fingerprint, source/run/draft references, durable receipt state, correlated audit, and timestamps. |
| `assistant_poll_reports` | Unique connection/poll ID, server receipt time, reported outcome/counts/error, acknowledged configuration, and last successful poll. Bounded report payloads and explicit retention policy consistent with governed history. |

All require exact schema, retained-data, audit, and encrypted archive validation. Ephemeral transport folders, usable credentials, local paths, and current device sessions are excluded from backups. Restore preserves history but invalidates every live delegation and requires new device authorization.

### Authentication by transport

- **STDIO:** a trusted launcher binds the process/session to a preapproved connection and grant. Resolve credentials via device-controlled bootstrap, not command-line plaintext or a secret in exported configuration. No unauthenticated launch obtains workspace access. The launcher is an adapter to the running application boundary, not a second independent database writer.
- **Local HTTP:** bind to the intended loopback interface, authenticate each call with a connection-bound credential, enforce host/origin checks and protocol/session rules. Localhost alone is not authentication. Credential rotation invalidates the previous verifier and requires verified delivery.

Model API keys and assistant credentials are distinct OS secrets keyed to workspace and connection. Grant management is an operator-only application operation, never an assistant tool. There is no assistant-to-assistant delegation.

## Read and submission tools

Each tool has bounded request/response schemas, cursor pagination, field minimization, and explicit capability/scope checks. Expose only tools whose source domains and approval contracts exist.

| Tool family | Contract |
| --- | --- |
| `properties.list/get`, `issues.list/get` | Authorized summaries with source-owned opaque revision and fingerprint. |
| `leases.get`, `rent.status` | Bounded authorized facts; never payment credentials or unrestricted applicant evidence. |
| `providers.list/get`, `tasks.list/get`, `coverage.get` | Domain-owned projections; no duplication of authority. |
| `communications.list/get` | Bounded metadata/excerpts; larger permitted content needs an explicit purpose and data-class grant. |
| `activity.since` | Scoped metadata changes only, opaque cursor, bounded page, rate limit/retry hint. Invalid/expired cursor returns an explicit resync requirement, not an empty successful result. |
| `sources.submit` | Bounded source evidence and account identity admitted through INGEST-001; attachments use FILE-001 validation. |
| `proposals.submit` | Typed external proposal admission only; returns a review-queue receipt. |
| `receipts.get` | Connection-owned submission status and permitted result reference; never another connection's queue. |
| `connection.config`, `connection.heartbeat` | Read authorized desired configuration and report a poll outcome; neither grants scope nor acknowledges an unverified schedule automatically. |

Read tools do not expose raw attachments by path or provide arbitrary access to SQLite, workspace archives, or the attachments tree. Non-MCP transports must preserve these same scope boundaries.

## Proposal and receipt contract

```json
{
  "intent_version": 1,
  "intent_id": "uuid",
  "idempotency_key": "uuid",
  "action": "maintenance.issue.create",
  "base_ref": {
    "entity_type": "intake_source",
    "entity_id": "uuid",
    "source_revision": "opaque-source-revision",
    "source_fingerprint": "sha256"
  },
  "payload": { "property_id": "uuid", "title": "Water under kitchen sink" },
  "evidence_refs": [{ "entity_type": "intake_source", "entity_id": "uuid" }],
  "rationale": "Tenant reports an active leak; review priority and response.",
  "conversation_ref": null
}
```

The example abbreviates the domain payload; registered schemas are authoritative. The app supplies authenticated connection/delegation identity. A create cites retained evidence/parent context; an update cites the current target plus supporting evidence. Missing or ambiguous property/unit matches stay unresolved in review and cannot create an official issue until selected. At least one usable evidence reference is required; a Gmail message ID without retained content is not a source comparison.

Deduplicate transport submissions by workspace/connection/idempotency key. Same key and same fingerprint returns the same receipt; changed content returns `409 assistant_idempotency_conflict`. Map admission to a stable application-generated AI-GOV UUID, so connection-scoped keys cannot collide with its globally unique run key. Separately deduplicate source messages across connections by source provider, verified/bound account identity, and message ID. Repeated interpretations of one source must be presented as revisions/duplicate candidates, never silently create two issues. Unverified source account claims retain that qualification.

Receipt states are `accepted_for_review`, `rejected`, `approved_committed`, `dismissed`, and `superseded`; approval conflicts keep the proposal awaiting review with a typed failure. A receipt includes stable submission/run/draft references, receipt version, timestamps, safe error/retry guidance, and a result reference only after the domain transaction commits. Admission is not approval and approval is not external delivery. Store the receipt state transactionally with admission/decision; transport publication can retry after a crash without repeating the domain effect.

### First action and later extensions

The first implemented action is `maintenance.issue.create` from retained evidence, with property/unit, reporter, category, priority, bounded title/description, and evidence links. INGEST-002 and Maintenance own schema, required fields, and atomic approval. This does not invoke a model API.

Updates, status transitions, assignments, task creation, documents, and reminders are separately registered extensions, not implicitly delivered by MCP-001. They must use each domain's actual lifecycle and approval rules; do not invent a simplified maintenance status sequence. Assignment never implies contacting a provider. Repair completion requires the domain's verification checks. An HOA follow-up draft cannot establish sent delivery, acknowledgement, or physical repair completion.

Opaque source revisions need not be monotonic integers. At approval, reload the source and compare its revision/fingerprint in the owning transaction. Stale input returns `409 ai_stale_draft`; require a refreshed proposal or explicit domain-supported revalidation, not a generic “approve anyway.”

## Discovery, timing, and health

The app owns no mailbox credential or poller. An assistant's separately authorized scheduler performs message discovery. Desired cadence in Settings is a request until the actual scheduler acknowledges it. Enabling a connection requires proof of the supported schedule, filters, account scope, pagination, overlap/catch-up, durable checkpoints, and per-message retry behavior; a rolling one-day query is insufficient after downtime.

MCP submission can deliver quickly, but it does not make message discovery instantaneous. Mac sleep, closed apps, failed polling, missing attachments, and unavailable networks affect coverage. Emergency workflows must not promise immediate detection; an assistant may also alert the operator after discovery, but chat is not the durable record or application approval.

A scheduled connection reports a unique poll ID, acknowledged config revision, outcome (`success`, `partial`, `failed`), bounded counts, and sanitized error. Server receipt time drives health, not an assistant-supplied timestamp. Replaying a poll ID cannot create fresh activity. Track last contact separately from last fully successful poll.

While scheduled and enabled, no valid contact for twice the acknowledged interval raises “No contact from [connection] since [time]. Check the connection or enter items manually.” Before initial acknowledgement use the requested interval and show “Not yet verified.” An unacknowledged interval edit does not postpone a stale warning. A fresh failed/partial poll clears silence but retains its own failure/incomplete warning. Interactive MCP connections show last activity and test status without missed-poll alarms. Evaluate on startup/resume; no live warning is possible while the app is closed. Reports never prove complete mailbox coverage.

## Pause, revocation, and review

Global AI pause blocks new inference, assistant reads/exports, and source/proposal admission. Connection pause affects that assistant alone; revoke invalidates its grant on the next operation. Recheck authorization before response disclosure and admission commit. In-flight disclosure cannot be recalled, and independent assistant schedules/account permissions are not revoked by the app.

Already admitted drafts remain reviewable, editable, and dismissible. Approval remains an explicit operator action with current source/domain checks and a visible paused/revoked-source notice; it does not reactivate the connection. Queued but unadmitted work has no authority. Tokens/scopes are never silently inherited by a replacement connection.

## Operator and management APIs

UI-001 owns setup, scope/disclosure review, enable/pause/revoke, synthetic tests, health details, and per-connection limits. Show transport names in advanced details, with a plain label such as “Local connection” for MCP. Do not show a universal API-key field for assistants.

Proposed operator-only APIs: `GET/POST /api/assistants/connections`, `PATCH .../{id}`, `POST .../{id}/test`, `POST .../{id}/grants`, and `POST .../{id}/pause` or `/revoke`. Read responses omit secrets. Model connections use `/api/ai/connections` separately. MCP tools call internal admission services; no unauthenticated `/api/agents/proposals` workaround is required. An HTTP transport exposes only its authenticated protocol boundary.

Audit every grant, disclosure, proposal, decision, rejection, pause, revocation, and health transition with the connection/grant and correlation ID. Record data-bearing reads/exports; only empty health polling may be sampled. Model identity supplied by an external assistant is not independently verified attribution.

## Verification and Definition of Done

- [ ] One real local MCP client completes scoped read → source retention → proposal → app review → domain commit → final receipt with synthetic data. Document client/version/transport and failed capability checks.
- [ ] Client-neutral contracts pass transport-independent service tests and MCP adapter tests; unsupported client configurations stay unavailable.
- [ ] Each supported MCP transport proves identity, bounded access, explicit disclosures, pause/revocation, and restore reauthorization.
- [ ] Duplicate same/different payloads, cross-connection source duplicates, stale sources, ambiguous units, oversized inputs, malformed evidence, and injected instructions cannot bypass review.
- [ ] Disconnects, restart after admission/before receipt, replayed heartbeats, offline/sleep recovery, and receipt retries cannot duplicate or lose an admitted proposal.
- [ ] Scheduled and interactive health have distinct semantics; last contact never means complete coverage.
- [ ] Approval/receipt outcome is atomic with domain writes; no model retry or external send occurs on proposal admission.
- [ ] Sandbox testing uses a separately authorized disposable workspace and separate credentials; an assistant cannot switch into production with a request flag.
- [ ] Backups retain provenance and history, exclude usable secrets/exports/runtime state, and restore with all connections requiring reauthorization.
- [ ] Manual intake, app-owned reminders, and ordinary property workflows remain usable with no assistant.
