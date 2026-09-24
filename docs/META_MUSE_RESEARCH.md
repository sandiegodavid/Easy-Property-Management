# Meta Muse integration research and design proposals

September 24, 2026

## Recommendation and scope

Use app-controlled, reviewable assistance through Meta Model API and evaluate a separate, optional Muse Agent file bridge for delegated external-app work. The app retains official records, durable workflows, deadlines, validation, approvals, and audit history. Core property-management work must remain available without either integration.

This report distinguishes official documentation, capabilities reported by Muse Agent in discussions supplied by the product owner, and application recommendations. Reported capabilities have not been demonstrated in integration tests. This report does not amend confirmed implementation contracts or MVP scope.

## Product map: agent, models, and API

**Muse Code is an agent application that uses Meta Model API, not another model offered alongside Spark, Image, and Voice Transcribe.** The personal Muse Agent is a separate finished product. Access to model inference does not establish access to that personal agent's account, connected apps, memory, or tasks.

| Name | What it is | Relationship to Meta Model API | Meaning for this application |
| --- | --- | --- | --- |
| **Muse / Muse Agent** | Meta's personal AI agent, powered by Muse Spark. | A separate personal-agent product; the reviewed API docs do not document an endpoint for controlling it. | The intended assistant for external-app work and inbound evidence; requires its own verified integration. |
| **Muse Spark** | A model used for reasoning and agentic work. | Served through Model API. | The model behind app-owned summaries, extraction, and proposals. |
| **Muse Code** | A ready-made coding agent for terminal and CI. | Uses Model API and its authentication/billing. | A development tool or separately chosen agent client; not an alias for the personal agent. |
| **Muse Image** | An image generation/editing model. | Served through Model API. | A separate capability; not needed merely to connect an assistant. |
| **Muse Voice Transcribe** | A speech-to-text model. | Served through Model API. | Potential transcription capability. It does not provide speech synthesis or a speech-to-speech conversation API. |
| **Meta Model API** | Developer inference service. | Hosts the models above; Muse Code consumes it. | The app's built-in model integration, separate from personal-agent connectivity. |

Sources for product classifications: [Meta developer overview](https://dev.meta.ai/docs/overview), [Muse personal-agent introduction](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/). The application column is design interpretation, not a claim that Meta provides an Easy Property Management connector.

## What the official sources establish

### Personal Muse Agent

Meta's announcement describes a personal agent that runs in a dedicated cloud computer, Muse Secure VM, with its own browser. It can continue work after the app closes, use connected services, and request approval for sensitive actions such as email sending. Users control connected-service access. The announcement identifies Muse Spark as its underlying model. These are product statements, not a custom connector specification. [Meta announcement](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)

That announcement lists rollout on iOS, Android, and the web. The Mac download URL returned a title mentioning Mac and mobile, but no readable body in this research session. The user's Mac experience is useful context; neither that title nor a desktop client proves local-only execution, access to arbitrary local files, or a supported local MCP transport. [Announcement](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/), [download page](https://ai.meta.com/muse/download/)

### Meta Model API

The documented inference base URL is `https://api.meta.ai/v1`, with bearer-token authentication. Spark supports Responses, Chat Completions, and Messages request formats; protocol compatibility describes how an application calls a model, not how it controls the personal Muse Agent. [API overview](https://dev.meta.ai/docs/overview), [Choosing an API](https://dev.meta.ai/docs/protocols)

Image generation and speech transcription have their own documented interfaces. Do not assume every model uses every text/chat protocol. The current voice product is specifically **Muse Voice Transcribe**; the broad label “Muse Voice” should not imply a talking assistant. [API overview](https://dev.meta.ai/docs/overview)

### Muse Code and MCP

Muse Code documents MCP server configuration and both `stdio` and `streamable_http` transports, plus remote OAuth sign-in. Those capabilities belong to Muse Code. Its configuration files and commands must not be presented as installation instructions for the personal Muse Agent. [Muse Code configuration](https://dev.meta.ai/docs/muse-code/configuration), [Muse Code extensions](https://dev.meta.ai/docs/muse-code/extending)

## Personal-agent integration remains unverified

The reviewed primary sources did not establish these capabilities for the personal Muse Agent:

- Registering this application's custom MCP server, including a supported transport and authentication flow.
- Reaching this app's local loopback server from the personal agent's execution environment.
- Programmatically handing off a task through an API or deep link and receiving authenticated completion/results.
- Installing a one-approval setup bundle that changes schedules, configuration, or tokens.
- Guaranteeing scheduled Gmail ingestion, retries, source retention, or heartbeat delivery under an integration contract.
- Exposing personal-agent token accounting to this app.

These are **unverified**, not proven impossible. Muse Code's MCP support, API tool calling, and the personal agent's general ability to use connected apps do not establish them. A cloud process cannot reach this Mac's loopback address without a supported bridge; the local MVP should not silently assume a public tunnel. This connectivity conclusion is engineering analysis based on the documented cloud execution model, not a Meta connector claim.

## Personal-agent capability assessment

Muse Agent reports approximately 50 declared commands in the product owner's session, including `email.search`, `calendar.create`, `files.read`, `files.list`, `files.write`, and `files.rename`. It reports no MCP client, raw HTTP/SSE path to localhost, generic shell, or screen/mouse/keyboard automation for operating the Mac app. These are session-specific reports, not demonstrated capabilities or universal product limitations. A Mac-facing command surface does not prove local-only execution.

A suggested but unexposed “Computer Use” approval gate remains unverified and should not influence the integration contract. GUI automation is not inherently untestable or incapable of unattended operation; it is unavailable in the reported session. A structured bridge can avoid dependencies on visual layout and interactive desktop state, but still requires reliability tests.

## Proposed file exchange adapter

File exchange is the candidate transport for the personal Muse Agent because the supplied session reports file commands but no local MCP or HTTP client. It is separate from MCP. The adapter must reuse the application-owned authorization, source admission, proposal, receipt, and review contracts in [MCP-001](MCP-001_DESIGN.md#shared-application-boundary); it must not introduce another way to write official records. These are proposed requirements, not verified Muse capabilities or a delivered integration.

### Exchange directory and access

Use an operator-approved directory per connection, outside authoritative storage. Publish only bounded configuration, authorized context, and receipts. Do not grant access to SQLite, workspace archives, the attachments tree, or internal logs. The earlier `muse-bridge.json` and `.muse-bridge/heartbeat.json` examples are discussion sketches; the proposed layout is:

| Directory | Purpose |
| --- | --- |
| `config/` | Non-secret versioned descriptor, delegated scope, source filters, and requested cadence. Desired and acknowledged configuration remain distinct. |
| `context/` | Bounded exports for authorized properties, units, and cases. |
| `inbox/` | Completed source/proposal submissions; temporary files are ignored. |
| `receipts/` | Versioned admission/rejection and final review/commit outcomes, separate from the watched inbox. |
| `health/` | Structured poll reports with unique IDs, acknowledged configuration, outcome, and sanitized errors. |
| `processed/`, `error/` | Transport recovery copies governed by an explicit cleanup policy, not the authoritative review history. |

A writable folder, filename, claimed agent name, or content hash does not authenticate Muse. Verify OS read/write isolation and trustworthy writer attribution before enabling automatic admission. Broad workspace permissions defeat scoped exports. If the actual assistant cannot be confined to the exchange, use explicit manual export/import and label attribution unverified. Never place reusable bearer secrets in JSON files as a substitute for authentication.

### Publication, admission, and receipts

1. Muse reads the current configuration and permitted context, discovers a relevant message through its independently authorized account, and prepares bounded evidence and a typed proposal. Reading a changed interval does not prove that its scheduler changed.
2. Muse writes a temporary file on the inbox filesystem, then atomically renames it to a final JSON filename. Verify the actual command and rename semantics. If unsupported, use a tested completion manifest with digest/length validation or manual import; stable mtime alone does not prove completeness.
3. A directory watcher prompts a scan. Startup, resume, and periodic scans recover missed events. Enforce byte/count limits, allowed filenames, regular-file checks, strict schemas, and rejection of traversal or symlink escapes. Treat submitted text as evidence, never instructions to expand authority.
4. The shared admission service checks the current grant, data/property scope, pause state, evidence, source revisions, payload bounds, and idempotency. Intake retains original evidence separately from the interpretation; AI Governance admits an external proposal without another model call. Recheck authorization at commit time.
5. Persist the outcome before moving the file to processed/error. Publish a versioned receipt atomically in `receipts/`. Durable identity and fingerprints—not folder position—govern recovery after a crash or failed move. Same-key retries return the existing outcome; changed payloads conflict. Separate account/message deduplication prevents two assistant connections from creating duplicate source records.
6. Muse reads the receipt and retries only retryable failures. Missing receipt means unknown delivery, not success. Do not delete an unacknowledged submission or advance a mailbox checkpoint past it.
7. The operator reviews in the app. A receipt distinguishes admission for review from rejection, dismissal, supersession, and approved commitment. Publish the final result only after the owning domain commits. Approval never means that a message was sent or a repair completed.

A file arriving while paused is held without admission and checked against the current grant after resume. Files bound to a revoked grant are rejected rather than replayed under a new grant. Changed permissions or records can change the outcome; identical input does not guarantee identical results regardless of application state.

### Proposal content and source evidence

Use the shared versioned proposal envelope, stable submission/idempotency identities, registered action/payload schemas, source references, and bounded rationale. Connection identity comes from the verified transport binding, not submitted text. File serialization and publication must be tested against those schemas before implementation enablement.

For a maintenance email, retain the relevant content and provenance plus attachments relied on by the proposal. A Gmail message ID alone cannot support source comparison. An address is a matching hint: resolve it to an authoritative property/unit record or require operator selection. Urgency and category remain proposed values. Chat approval cannot replace application review or bypass pause/revocation.

### Timing, health, and fallback

File arrival is the local notification mechanism; the app does not poll Muse over a network, but reconciles its own inbox. Muse suggested discovery every 15–30 minutes; that cadence and scheduler support remain unverified. Measure discovery, handoff, and review delay separately. Fast handoff does not establish timely discovery during Mac sleep, app downtime, failed polling, or missing attachment access.

Each attempted poll should report a unique poll ID, acknowledged configuration, outcome, bounded counts, and sanitized errors, including empty or failed polls. App receipt time drives freshness. Touching a file or replaying an old report must not count as fresh contact. Track last contact separately from last successful poll and apply the shared scheduled-connection warning rules; neither heartbeat nor reported success proves complete mailbox coverage.

For urgent or ambiguous items, Muse may also notify the operator after discovery. Chat is an additional alert, not an immediate emergency-response guarantee or the durable record. Manual entry and explicit context export/result import remain available when automation is unavailable.

### Revocation, privacy, and recovery

Revocation stops new app exports and admission, but cannot stop Muse's independent schedule, revoke its mailbox access, or retract copies already read. Remove app-owned exported context where possible. Existing admitted drafts remain available under the shared review rules.

Retained evidence, submission outcomes, receipts, and review history belong in the normal encrypted workspace backup. Live exchange folders, cached exports, device paths, and usable authorization do not. Restore requires a fresh grant and exchange-directory validation; never replay old files as newly authorized work. Define cleanup only after durable retention and receipt recovery are established.

Local file handoff does not establish local inference: Muse's discovery and processing may still use cloud services. Apply the connection's data-disclosure permission before publishing context.

### Validation before enablement

Use synthetic data to verify bounded configuration/context reads, temporary-file publication, admission, receipt reading, app review, and the final committed outcome. Test:

- Actual file-command capabilities, same-filesystem publication, incomplete files, size limits, and traversal/symlink rejection.
- Writer attribution and scope isolation; failed isolation must disable automatic ingestion.
- Duplicate and changed-payload retries, cross-connection source duplicates, stale records, and ambiguous unit matches.
- Missed watcher events, restart after admission but before receipt publication, failed moves, and retryable versus terminal errors.
- Scheduled polling, catch-up, app closure, Mac sleep, repeated heartbeats, and discovery delay separately from handoff delay.
- Pause, queued submissions, revocation, backup/restore, and preservation of existing review drafts.

No successful end-to-end file exchange has yet been demonstrated. Enable the Muse bridge only after these checks pass; otherwise preserve manual import. A future verified Muse MCP client would be a different transport qualification, not evidence that files implement MCP. Meta Model API remains an independent model-inference option.

## Built-in model assistance

### Capabilities and responsibility

Meta documents tool calling, multi-step workflows, reasoning replay, and optional server-managed conversation state. Bounded requests are an application design choice, not an API limitation. Conversation state does not imply access to the personal agent's memory or accounts. [Choosing an API](https://dev.meta.ai/docs/protocols)

An embeddings endpoint was not established by the reviewed documentation. Duplicate detection can instead retrieve candidates using property, dates, and text search, then request a model comparison. This is an application recommendation. Pricing is capability-specific, including token, image, and audio units; use the applicable current pricing. [API overview](https://dev.meta.ai/docs/overview)

The app owns durable workflow state, deadlines, validation, approvals, and audit records. Muse Agent can handle delegated discovery and submit proposals through a validated bridge. Sharing a Mac adds no special API connection: built-in model assistance and the personal-agent session remain independent integrations.

### Recommended application priorities

The following ordering is a design recommendation, not a change to MVP scope or confirmed delivery order:

| Priority | Candidate use case | Recommended operator experience |
| --- | --- | --- |
| 1 | Lease/document extraction | Review proposed rent, dates, tenant details, and clauses alongside supporting passages before saving. Validate document input support and extraction quality before adopting it. |
| 2 | Message or voice-note extraction | Review a concise issue draft with source evidence. Transcription and subsequent summary/extraction are distinct steps. |
| 3 | Follow-up drafting | Generate an editable draft from the selected case and its relevant history. Draft approval does not establish that a message was sent. |
| 4 | Duplicate suggestions | Explain possible matches among retrieved candidates; the operator decides whether to link records. |
| 5 | Advisory analysis | Label suggested cause, urgency, and provider category as advisory, expose uncertainty, and preserve operator judgment. |

Muse associated these ideas with FILE-001, ISSUE-AI-002, VOICE-AI-001, ISSUE-AI-003, and COM-002. Those associations are discussion references, not confirmation that each feature's current contract includes this capability. In-app questions over local records are another candidate; answers should be grounded in explicitly selected or retrieved records with source references.

### Data controls and independence

Prefer app-controlled, bounded requests that disclose only the context needed for the task. Apply the app's disclosure and redaction controls and check **Pause all AI assistance** before dispatch. Remote model requests send the supplied context to Meta's service; running the property-management app locally does not make those calls local inference. [API overview](https://dev.meta.ai/docs/overview)

Use assistance on demand or at explicit workflow triggers, with usage limits and suitable reuse of prior results. Cached suggestions should retain their source-record versions so a changed lease or issue invalidates stale advice. Extracted fields and recommendations still pass through app validation and operator review before becoming official records.

The recommended architecture is **app-controlled, reviewable model assistance plus an optional Muse Agent bridge**. Neither integration should be required for core property-management work. This section records recommendations only; it does not amend UI-001, AI-GOV-001, MCP-001, or feature delivery scope.

## Relationship to the current repository decisions

[UI-001 D46](UI-001_DESIGN.md), [AI-GOV-001](AI-GOV-001_DESIGN.md), and [MCP-001](MCP-001_DESIGN.md) define this application's intended behavior. Meta Model API is one registered-provider candidate; personal-agent access is independent and capability-gated. The app’s decision to use authorized assistants or manual entry for inbound evidence, retain submitted evidence, monitor heartbeats, and leave outbound sending manual is a **repository decision**, not independently verified Meta product support. Likewise, proposed setup bundles, ingestion schedules, token rotation, and retry behavior remain application integration requirements until proven against a supported personal-agent interface.

## Proposed operator experience

1. Name the section **Settings → AI assistance**. Separate **Personal assistant — Muse Agent** from **Built-in AI — Muse Spark via Meta Model API**. Keep Settings as the overall destination. An API key verifies model access; show personal-agent connection status only after its own connection test. The current contracts select Meta for built-in AI; these labels do not propose a provider switch.
2. For agent access show workspace, permitted properties and record types, ability to read/propose, last successful connection, recent activity, test connection, and disconnect. Reveal only verified capabilities; distinguish unavailable, disconnected, and limited operation.
3. Place contextual **Prepare with Muse** actions inside expanded records, preserving D35's non-editable summary bar. Examples include case summaries, HOA follow-up drafts, owner updates, and document comparisons.
4. Show a preview of the context being shared, record references and freshness, then return proposals to the app's review flow. If supported handoff is unavailable, offer an explicitly manual copy/export workflow and manual result import without implying a live connection.
5. Home shows a compact draft-review entry when actionable work exists. The app remains authoritative for obligations and reminders. Agent work status (preparing, awaiting review, failed, cancelled) stays separate from repair/task/payment status.
6. Label revocation **Pause assistant access to this workspace**. It blocks app-mediated access and proposals; it cannot retract already shared context or stop independent activity inside Muse. Model-call limits apply to app-owned API requests; desktop-agent token use is unknown unless the integration reports it.
7. For the HOA regulator case, share the selected contact history, responsibility evidence and outstanding request. Muse prepares the next follow-up; sending and confirmed sent evidence are separate from drafting. Scheduling or an HOA acknowledgement never closes the repair.
8. Put token budgets, redaction-profile versions, and transport configuration under **Advanced**. Keep plain-language connection status, data access, permitted actions, activity, and pause/disconnect controls prominent.

## Adoption and implementation boundaries

Keep the API adapter and personal-agent adapter distinct in implementation, status, credentials, usage reporting, and revocation. `MCP-001_DESIGN.md` proposes delegated reads and reviewed writes; its shared application contract is reused by the separately proposed file adapter above, whose Muse capabilities still require verification. An external agent's proposal need not trigger another model call merely to enter the review queue. Muse Code could be evaluated as a separate MCP client, but substituting it for the requested personal agent would be a new product decision.

Recommended first milestone: evaluate the session-proposed file bridge using the synthetic-data checks above, including one bounded case read, one proposal returned for operator review, and successful denial after revocation. Then implement connection controls and contextual actions for the proven transport. Preserve the manual copy/export fallback if automated file exchange or another supported transport is unavailable.

## Evidence limitations

The developer overview, protocol documentation, Muse Code documentation, and Newsroom announcement were readable during research. The [AI-agents explainer](https://ai.meta.com/learn/agentic-ai/what-are-ai-agents/), [Muse product page](https://ai.meta.com/muse/), and [Mac download page](https://ai.meta.com/muse/download/) returned titles without readable bodies; they do not establish detailed capabilities in this report.

Personal-agent command availability, scheduling, and file exchange remain session reports pending validation. Official product capabilities, these reports, and the proposed application contract must remain distinct evidence categories.
