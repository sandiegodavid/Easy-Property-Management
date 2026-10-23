# ASST-001 — Shared connected-assistant boundary

## Status and ownership

Proposed technical design, reviewed October 23, 2026, based on the [agent triage design](agent-triage-design.md). This is the application contract for qualified connected assistants. [MCP-001](MCP-001_DESIGN.md) and [ASST-FILE-001](ASST-FILE-001_DESIGN.md) are alternative transports. A model API connection remains separate under AI-GOV-001. No assistant product is presumed available or required for manual EPM use.

ASST-001 establishes the shared boundary independently of the business actions that use it. The first proposed connected action is a bounded EPM-initiated request for the registered AI-DRAFT-001 follow-up action, once that action exists. Scheduled channel discovery and retained-source issue proposals are gated behind [ASST-INTAKE-001](ASST-INTAKE-001_DESIGN.md) and INGEST-002. Either capability can qualify independently. No agent receives direct create, assignment, payment, sending, signing, or approval commands.

## Delivery boundary and dependencies

This revision specifies the shared application service and its operator UI. Existing accepted direction remains binding; the numbered recommendations at the end are proposed decisions, not newly approved product policy. Technical defaults below depend on those decisions. No application code is changed by this design.

| Dependency | What ASST-001 reuses or requires |
| --- | --- |
| AI-GOV-001 — implemented | Global pause, registered actions/redaction, governed inputs, run/draft review, audit and original-result conventions. Extend through application ports; configuration for a model is not an assistant grant. |
| AUDIT-001, LOCAL-002, OPS-001, UI-001 — implemented foundations | Correlated audit, current-schema portable validation, single writer, operator command recovery, Settings shell, generated contracts and accessible disclosure patterns. These are integration touchpoints, not new deferred UI backlogs. |
| AI-DRAFT-001 — planned action dependency | Required for the first real connected follow-up: Maintenance context/preview and action schema, selected-source manifest, advisory review/editor and manual Communication handoff. Not required to test ASST-001's transport-neutral service with synthetic fixtures. |
| MCP-001 **or** ASST-FILE-001 — later qualification | At least one is required to enable a real connection. They depend on ASST-001; ASST-001 must not depend back on them. Neither a specific product nor both transports are required. |
| INGEST-002 and ASST-INTAKE-001 — later source path | Own source-backed admission, retained evidence and official issue decisions, source scheduling/coverage and their UI. ASST-001 supplies shared authentication, grants, policy and receipt ports; it does not implement mailbox scanning or an issue proposal handler. |
| DASH-003 — separate integration | Portfolio-wide source health/queue attention. ASST-001 delivers Settings and contextual request status without making a new Home aggregation a prerequisite. |

**Completion has two distinct proofs.** ASST-001 can complete its persistence, service, Settings, recovery and contract tests against a non-production synthetic adapter; it must visibly report that no real assistant is available. The connected follow-up becomes operator-usable only when AI-DRAFT-001 and one transport pass real-client acceptance. Never register the synthetic adapter as a selectable production assistant to satisfy that acceptance.

## Current implementation assessment

Reviewed against the current checkout on October 23, 2026; these observations are not a test run.

| Existing implementation | Consequence for this design |
| --- | --- |
| [AI registries](../../application/apps/server/app/modules/ai_governance/application/registry.py) are empty. | No production action, model or connected-assistant capability is established by the current Settings UI. |
| [AI run model](../../application/apps/server/app/modules/ai_governance/infrastructure/sqlalchemy_models.py) has `external_proposal`, assistant/delegation provenance fields and one draft per run. | Reuse the run/draft authority, but add a real authenticated admission port and retained linkage validation. Nullable string fields alone do not verify a connection or grant. |
| [Generation coordinator](../../application/apps/server/app/modules/ai_governance/application/service.py) reserves a run and calls a provider synchronously outside the write transaction. | It is not an assistant request dispatcher. AI-DRAFT-001 plans asynchronous model execution; connected transport scheduling remains ASST-001's separate concern. |
| `ai_external_operations` and [external-effect validation](../../application/apps/server/app/modules/ai_governance/infrastructure/external_validation.py) cover credential set/delete and model connection probes. | Do not repurpose these records as assistant submissions or receipts. Their model-connection identity and allowed actions are incompatible. |
| [AI API](../../application/apps/server/app/modules/ai_governance/api/router.py) and [browser workflow](../../application/apps/web/src/workflows/ai-governance.tsx) provide model Settings and generic draft review. | Add separate connected-assistant contracts and Settings UI; reuse shared review rather than copy it. No current assistant-management API was found. |
| [Bootstrap](../../application/apps/server/app/bootstrap/api.py), [workspace runtime](../../application/apps/server/app/modules/workspace/application/runtime.py) and [archive service](../../application/apps/server/app/modules/workspace/application/archive_service.py) govern composition, writer ownership and portability. | Register new schema/audit validators and lifecycle hooks here. A transport process must not open another canonical database writer. File-exchange archive content remains ASST-FILE-001 work. |

The active UI-001 design has been consolidated/archived. Current [frontend architecture](../ui/frontend-architecture.md) and [operator experience](../ui/operator-experience.md) govern implementation; the [archived design](../archive/designs/UI-001_DESIGN.md) supplies historical decisions.

## Technical ownership and application ports

Propose a new `assistants` module following the architecture's domain/application/infrastructure/api structure. It owns connection identity, grants, capability qualification, transport requests, submission/receipt identity and contact health. AI Governance continues to own action registration, governed run/draft/decision state and global AI policy. Maintenance owns follow-up context and source validity. Intake owns canonical message evidence. Operator composes Settings and recoverable commands. Adapters never import another module's ORM or write its tables.

Bootstrap injects these small application contracts:

- **Assistant principal resolver:** supplies workspace, connection, authenticated session/device epoch and adapter identity from a verified transport. Caller-supplied connection labels are never principals. An in-process port is not itself a network authentication mechanism; the transport must authenticate its local IPC or launch boundary.
- **Action policy/context port:** validates registration, permitted execution kind, exact selected entities and data classes, source manifest and governed context using owning-domain reads. The first action uses AI-DRAFT-001's Maintenance projection; no general database/query or file-path capability is included.
- **Governed external-result admission port:** inserts an external run and one draft using a caller-owned transaction, without invoking a model. It validates the same closed output schema and provenance rules as the registered action. The assistant request points to that run; it is not a second editable draft.
- **Policy snapshot port:** reads the AI global pause/revision together with assistant grant/connection state within the writer transaction. Pause must take effect without a cached UI flag or a cross-service time-of-check gap.
- **Transport projection port:** exposes bounded assigned requests and versioned receipt projections after commit. Network, keyring and file I/O occur outside writer transactions. Reconciliation republishes committed identity; it never creates a new request or claims exactly-once execution by the assistant.
- **Decision receipt port:** AI Governance or the later source-owning decision handler records the resulting assistant receipt in the same transaction as the decision. There is no second approval command.

Use the existing single-writer unit-of-work conventions and explicit transaction-aware ports. For result admission, request transition, external run/draft, durable receipt and audit either all commit or all roll back. Inject persistence operations through ports rather than calling a service that opens a nested transaction.

## Connection, grant and action contract

A connection identifies its actual product/client, adapter, version, transport and demonstrated capabilities. An operator grant binds workspace and connection identity to purpose, role, selected entities/data classes, registered actions, disclosure, expiry and limits. EPM verifies effective writer/session identity at the transport boundary; an envelope's `agent_id` or filename is not authentication. Every read, export, request, submission and result rechecks pause, revocation, scope, bounds and current action registration. Grants do not transfer to replacement agents or restored devices. Assistant account permissions are separately managed by the assistant platform and are not implied by an EPM grant.

Store connection/grant history, bounded work requests and their state versions, accepted terminal results, submission keys/fingerprints, durable receipts, capability-test results, audit and health observations in application-owned persistence. Usable transport secrets remain outside portable data. Database receipts are authoritative; file or MCP responses are projections. One transaction owns an accepted result and correlated audit. EPM's operator-only Settings controls grant, limits, pause and revoke; a connected assistant cannot change them.

| Application-owned record | Required facts |
| --- | --- |
| `assistant_connections` | Stable ID, operator label, actual client/adapter/version, transport, requested/acknowledged configuration, interactive/scheduled mode, lifecycle and capability-test history. |
| `agent_delegations` | Workspace/connection, selected entity and data-class scope, purpose/role, disclosure acknowledgement, expiry, status and revocation history; no usable secret. |
| `assistant_work_requests` and immutable results | Registered action/version, bound issue/source revision, bounded disclosed context, connection/grant, state/version, expiry, cancellation, response key/fingerprint and immutable terminal result. |
| `assistant_submissions` and receipts | Connection/grant, intent and idempotency key/fingerprint, retained source/run/draft references when applicable, versioned admission and decision result, audit correlation. |
| `assistant_poll_reports` — ASST-INTAKE-001 extension | Unique connection/poll ID, server receipt time, effective source/configuration, success/partial/failure counts, checkpoint range and unresolved intervals. Populated only for qualified scheduled discovery. |

Retained validation binds these records to exact schemas, source identities and audit evidence. Encrypted backup retains history, but not usable credentials, active session authorization or device paths. Connection/action admission caps and payload ceilings are separate from measured model token limits; unreported assistant token use is Unknown, never zero.

### Persisted identity and authorization rules

Use stable UUIDs, UTC event instants, aggregate revisions and canonical fingerprints. A grant revision is immutable historical scope; an amendment creates a replacement revision and invalidates pending work tied to the old authorization. Preserve old scope for provenance without treating it as live permission. Use explicit selected IDs rather than an implicit “all future properties” wildcard. Data classes are release-owned registered codes; action/role selection is an intersection of permission, not a way to bypass data-class limits. If an entity is archived, detached or no longer eligible, the owning reader denies new disclosure.

Connection lifecycle is `setup_required`, `enabled`, `paused`, `revoked`; grant expiry is derived from the captured clock. Capability readiness is separate from lifecycle and records action/version, adapter/client version, contract-pack digest, test outcome and observation time. A successful draft test cannot enable source scanning. Revoked identity is terminal; reconnecting a revoked client creates a fresh grant and verified session, preserving its history. Material identity/version/scope changes invalidate affected qualification and pending requests.

Proposed first-release limits: 10 configured connections, 10 pending requests per connection and 50 per workspace; 100 newly admitted requests per connection per UTC day; collection pages default 25, maximum 100. The request ceiling includes canceled/failed requests so retries cannot evade it. Exact replay does not consume new capacity. Action payload limits remain those of AI-DRAFT-001 (32 KiB input, 8 KiB output, ten context records); a 64 KiB envelope bound includes metadata. These are configurable downward by the operator; raising release ceilings requires explicit qualification. Assistant token/cost use stays Unknown unless reported with its assurance level.

Retain business-linked requests, canonical results, grants, receipts and their fingerprints with the workspace history; no automatic deletion of replay protection. Retain bounded diagnostic summaries rather than raw rejected hostile payloads. Rejected authenticated attempts have typed reason/fingerprint/correlation metadata; unauthenticated requests cannot create arbitrary connection records. Payloads never enter logs or generic form recovery. Diagnostic retention and sustained rejection throttling are called out as a decision below.

## First work request

The accepted [AI-DRAFT-001 contract](AI-DRAFT-001_DESIGN.md#resolved-design-decisions) owns the business action, closed schemas, selected-source revision manifest, advisory approval and contextual UI. ASST-001 adds connection/grant and transport request identity; it must not create a second draft-review ledger or relax that action contract. Reuse the governed lifecycle extensions delivered by AI-DRAFT-001 where applicable, while keeping assistant transport receipts distinct from model execution. The shared boundary can be built independently; qualifying this connected action requires AI-DRAFT-001.

For `maintenance.follow_up_draft`, EPM records request ID, connection/grant, issue ID and captured revision plus the complete selected-source revision/fingerprint manifest, bounded context and disclosure, action version, created/expiry time and state version before publishing. The assistant returns a draft or typed error with a stable connection/request key. Exact response replay returns the terminal receipt; changed content under the same key conflicts. EPM accepts at most one terminal response for the current request version. Cancellation is a durable versioned state/tombstone; a late answer cannot revive it. A timeout offers the operator manual drafting or a new request ID. The draft remains an AI Governance suggestion for operator review; COM-001 does not send.

The chosen transport publishes request, response and receipt under this same contract. Restore invalidates live grants and reconciles pending requests from durable state rather than blindly reissuing them. Revocation blocks new disclosures/admission but cannot retract already disclosed context or stop the assistant's independent activity.

The operator-only management API provides typed connection list/create/update, test, grant, pause and revoke operations; responses omit secrets. Model-provider connections remain on AI Governance's separate API. Adapters use internal application ports, not an unauthenticated `/api/agents/proposals` route. Audit each grant, data-bearing read/export, request, submission, decision, rejection, pause and revocation with connection/grant and correlation ID; only empty health checks may be sampled. Assistant-reported model identity is labeled unverified unless independently attested.

### Request lifecycle, disclosure and races

The connected request is a transport envelope pointing to an immutable governed context snapshot and, after admission, an AI Governance run. The model path continues to use AI Governance's own execution state; do not force a provider-generated run into a fictional assistant connection.

| Request state | Meaning and allowed next step |
| --- | --- |
| `pending` | Persisted, eligible for delivery while scope/source/policy remain valid. Repeated publication retains ID/version. |
| `awaiting_result` | Context was made available through an authorized transport; this is not proof the assistant started or finished. |
| `completed` | One validated draft and its review reference were committed atomically. Review status is separate. |
| `failed` | Assistant returned a valid typed error; immutable terminal receipt, with manual/new-request recovery. |
| `canceled` / `timed_out` | Cancellation or deadline won; late responses cannot create a run/draft. |
| `invalidated` | Scope/configuration/source change made this request unusable. Preserve reason and offer a new preview. |
| `interrupted` | Restart/restore cannot safely establish continuation; operator reconciliation or a new request is required. |

`expectedRequestVersion` refers to the version of the published contract, not incidental delivery-attempt counters. Retransmission does not change it. Cancellation or invalidation advances state/version. Distinct delivery attempts are diagnostic records, not new work requests. Terminal states cannot be overwritten.

Propose a 60-minute connected-request deadline (operator may choose 5–60 minutes within the adapter's qualified bounds), distinct from the model path's 60-second execution timeout. Source preview still expires after 15 minutes before initial admission. Revalidate the entire source manifest at context release and response admission, even after that initial preview check. A source change requires a new preview/request; do not silently replace the facts already sent.

Before releasing data, durably record the authorized disclosure attempt and exact content fingerprint; if that audit fails, return no content. The receipt records that data was made available, not proof of external consumption. A pause racing after release cannot retract those bytes. A local projection that has not yet been published must recheck policy; file adapters remove/restrict stale projections best-effort under their own contract without claiming retraction.

Cancellation, expiry, revocation and result admission serialize in the writer transaction. The first committed terminal transition wins; a late result receives a typed rejection/current terminal receipt. A global pause is checked immediately on every access; pending work becomes canceled through the shared lifecycle hook or bounded reconciliation, with a read projection showing it blocked immediately. Clearing pause does not resume canceled work. Already admitted drafts remain reviewable under AI Governance's own decision policy.

On ordinary restart, retain verified connection configuration but require fresh transport session establishment. Mark nonterminal requests interrupted before any re-publication; provide status/receipt reconciliation, never automatic re-execution. On restore, preserve historical grant rows but invalidate all live device/session authorization; connections become Setup required, and pending work cannot resume under a replacement grant. A new runtime epoch fences stale sessions; it is not by itself proof that portable grants should be trusted.

### Idempotency and receipt contract

Every operator mutation has a UUID key, canonical request fingerprint and durable original result. Namespace transport submissions by `(workspace, connection, operation kind, idempotency key)` and bind responses additionally to request ID/version. Fingerprints include the action/version, immutable grant revision, source manifest and canonical content; transport filenames/timestamps do not alter business identity. Same key with changed content is 409. A second key cannot create another terminal result for the same request/version.

Authentication and current read/disclosure authorization precede replay lookup. A revoked caller cannot recover sensitive content merely by knowing an old key. An authorized exact replay returns the original receipt without another action or budget charge. Operator-only history remains available after revocation. Separate immutable admission receipt from current decision status: `accepted_for_review` does not become a mutable “original result.” Later decision receipts append a version and point to the original submission and AI draft. For the advisory draft, `approved_committed` means the review decision committed and has **no issue/Communication/payment result**; the UI must say “Draft accepted,” not “Message sent.”

## API contracts and read models

Proposed operator API namespace: `/api/assistants`. Use the existing local browser transport policy; “operator-only” means the local application boundary, not newly implemented multi-user authentication. Assistant adapters cannot invoke these management routes using their scoped session.

| Operation | Required contract |
| --- | --- |
| List/detail connections and capability readiness | Bounded safe metadata, lifecycle/revision, qualification reasons, contact time, pending count and supported actions. Never return secrets or full context in collections. |
| Create/update connection; grant/replace scope; pause/resume/revoke | Expected revision, original key, explicit disclosure and correlation; return durable command result. A grant change must show affected pending work. Resume rechecks readiness and does not restore canceled requests. |
| Prepare/test capability | Preflight without domain effects; bounded asynchronous synthetic round trip. Return test ID/status and stage-specific failure; no production draft or source ingestion. Test sessions permit only synthetic fixtures. |
| Preview/start follow-up | Maintenance-owned issue endpoint selects connected execution, connection and grant. Preview binds governed data, destination, source manifest and expiry. Start returns 202 with request ID and original-result location. No browser-supplied “authoritative context.” |
| Request detail/cancel/original-key lookup | Metadata plus authorized contextual draft link, version/deadline, safe terminal reason. Lookup never dispatches. Cancellation uses expected revision/key. |
| Scope/activity/receipt pages | Exact bounded counts, stable ordering/cursor, safe event summaries and explicit current vs original outcome. Full context is a deliberate audited detail read. |

Internal adapter operations are `read_assigned_requests`, `read_request_context`, `submit_result`, `read_receipts` and `record_contact`; future source ports stay unregistered until their owning feature is delivered. Resolve authenticated principal outside the supplied payload, and enforce entity scope within every paginated query before counts/hydration. There is no generic HTTP proposal endpoint, arbitrary field-selection reader or arbitrary URL/file fetch.

Use shared API errors: 413 for bounds, 422 for malformed/unsupported combinations, 404 for absent or inaccessible resources, 409 for revision/lifecycle/source/key conflicts, 503 for unavailable workspace/capability. At a transport authentication boundary, use the protocol's unauthenticated/forbidden result (HTTP 401/403 if that transport is qualified). Quota exhaustion is a typed policy block with reset/retry information, not a generic internal error. Never rely on error-message parsing. Generate browser contracts from implemented API models.

Paginated read targets: maximum eight SELECTs for a connection/activity/request collection and twelve for a scoped follow-up preview, independent of page size; no per-row source or evidence hydration. Capture membership/counts in one bounded read snapshot. Cursor identity includes workspace/runtime/filter/order and invalidates safely on changes. Use indexed connection/state/time and unique replay/request keys; demonstrate the budget in SQL-count tests.

## Later source admission and health

ASST-INTAKE-001 may register a source-backed proposal action only after INGEST-002 owns its review and atomic consequence. The shared service then validates connection-scoped idempotency, canonical fingerprint, verified provider/account/message identity, retained evidence, action schema and current scope before admitting through Intake and AI Governance. An exact replay returns its stored receipt; changed payload under the same key conflicts. The first receipt means accepted for review, not an official issue; the later receipt reports the operator/domain outcome. Cross-connection source deduplication uses verified account identity and provider message ID; uncertain matches remain visible hints.

Receipt states are `accepted_for_review`, `rejected`, `approved_committed`, `dismissed` and `superseded`, plus typed retry guidance where applicable. The first receipt includes stable submission/run/draft references but no claimed domain effect; only a committed operator decision may add a result reference. Admission and operator decision each persist their durable result before transport publication. A stale source revision/fingerprint or target revision returns to review rather than being approved through a generic bypass. The registered action and INGEST-002 determine create/link/update/dismiss semantics, never the assistant's desired effect alone.

Interactive contact, scheduled poll report, last fully successful source scan, pending submissions and coverage gaps are distinct. A heartbeat is not proof that a mailbox was scanned. Timeouts and warnings use server-observed contact and acknowledged schedule; source coverage requires per-source checkpoints, counts, failures and verified intervals. EPM owns real-world Tasks/deadlines and manual fallback.

For a qualified scheduled connection, a suggested warning baseline is no valid contact for twice the acknowledged interval, evaluated on app startup/resume. Before schedule acknowledgement, show **Not yet verified** against the requested interval. A fresh failed or partial poll clears a silence warning but retains its own source failure warning. Interactive connections show last activity and test status without missed-poll alarms. The app cannot raise a live warning while closed, and no contact threshold proves complete source coverage.

## Delivery and validation

Ship a versioned assistant-neutral contract pack and capability manifest, with transport-specific instructions. A connection is enabled for only the actions demonstrated in a synthetic round trip. ASST-001 owns task-based setup, disclosure, test diagnostics, status, pause/revoke and recovery; it must not present source coverage before ASST-INTAKE-001 qualifies it. ASST-001 exposes typed operator APIs and internal adapter ports, not a public unauthenticated proposal route.

| Area | Cases |
| --- | --- |
| Happy paths | One bounded follow-up request → draft/error → operator review → durable result and receipt; later source proposal only after its separate qualification. |
| Invalid combinations | Wrong writer/connection, expired/paused grant, out-of-scope entity/data class, unregistered action, stale issue, oversized payload, forged identity or unsupported client. |
| Idempotency/retry | Exact request/result/submission replay, changed-key conflict, missed receipt, timeout/cancel race and cross-connection source duplicate. |
| Transaction rollback | No accepted result, proposal or official domain effect without its durable receipt and correlated audit. |
| Persistence/schema | Closed action, grant, result and receipt versions; retained identity and scope consistency; bounded history and audit validation. |
| Backup/restore | Retain history and pending status; invalidate usable grants/sessions; require fresh authorization and reconcile uncertain work. |
| Query budget | Bounded scoped reads, request lists, receipts and health without per-row source or evidence reads. |

## Included operator interface delivery

This UI is part of this functional backlog and its completion criteria. Reuse the delivered UI-001 shell, generated contracts, source-owned commands, Light/Dark themes, keyboard/focus behavior and recovery patterns. Validate real temporary-workspace reads/writes, stale revisions, lost responses, restart/restore and bounded queries; backend-only delivery is incomplete.

### Shared setup flow

The entry question is **What would you like help with?** Offer bounded jobs such as drafting on an existing issue or watching a selected source. Show only the technical prerequisites of the chosen job: drafting does not request mailbox access; source watching does. Operators can use manual EPM workflows or choose any qualified capability without first enabling an unrelated tier. No channel access is default-on. An unqualified product/client/capability is unavailable with a reason and manual alternative, not silently substituted.

Setup stays in Settings → AI assistance → Connected assistants, beside the independent Built-in AI card. It is task-specific:

1. Choose actual assistant/client, transport and job; preview exact property/unit, data-class, source-account and action scope, disclosure and expiry.
2. Preflight EPM's workspace, managed exchange when relevant, contract/action version, and proposed grant before switching apps. Show the single concrete assistant-side folder/account permission step, then return to EPM.
3. Run a synthetic request/proposal and receipt round trip with no official business record. Show which stage failed—assistant unavailable, permission/isolation, grant, version, submission or receipt—and a specific **Retry test** action. A heartbeat or test file does not prove source scanning or filesystem isolation.
4. Enable only the demonstrated capability. Source discovery separately verifies account/filter, schedule, catch-up and per-source reports under ASST-INTAKE-001. A draft test cannot label a mailbox “watched.”

The normal issue page hosts connected draft requests, pending/error/timeout states and review. INGEST-002's normal queue hosts source-backed suggestions; there is no second agent approval queue. Paused/revoked connections leave already admitted drafts visible with provenance and current-source warnings. A model-generated draft labels its verified model/runtime and device/cloud destination; an assistant-proposed draft labels verified connection/transport separately from assistant-claimed model details. The operator sends externally and records any Communication separately.

### Shared health and recovery

Settings shows a plain-language **What this assistant can see now** receipt: granted entities, sources, roles, data classes, expiry, recent EPM-mediated exports/submissions/decisions, and pause/revoke. This does not claim to list everything the assistant can see through its independent channel accounts. Connection detail separates last authenticated contact, pack compatibility, pending submissions, oldest unacknowledged item and admission-receipt delay. Scheduled source detail additionally separates last fully successful scan, partial/failed polls, requested versus acknowledged cadence, unknown intervals and provider-retention catch-up limits. Interactive clients have no fabricated missed-poll alarm.

A degraded/offline banner names the affected capability, last verified scan, and manual or reconnect path without promising unseen messages will later be found. **Reconnect source** opens product-specific permission guidance; **Update adapter** identifies the required version; **Retry test** checks the repair. EPM may republish a missing receipt or refresh a bounded export from durable state. It does not widen scope, repeat uncertain outbound work, or treat a fresh heartbeat as a completed scan. Restore marks connections Setup required; pending files cannot be admitted under a new grant automatically.

Invitations to add assistance appear at moments of relevant work, can be dismissed with **Don't suggest this again** for that invitation type, and never block manual tasks. Early suggestions may need corrections; any accuracy/time-saved report card uses measured observations and never promises automatic learning. Technical JSON/path details belong only in advanced setup or diagnostics. Mobile review, keyboard/focus behavior, light/dark themes and UI-001's full-summary-bar disclosure remain intact.

ASST-001 owns the shared Settings shell, grants/disclosure, capability inventory, scoped activity, pause/revoke, setup-required restore state and contextual connected-work-request controls. Source-specific selection/cadence/coverage and reconnect flows described above are delivered by ASST-INTAKE-001. MCP-001 and ASST-FILE-001 each supply their own permission handoff, diagnostics and round-trip qualification inside this shell; neither transport is a prerequisite for implementing the shell. A working connected capability requires at least one qualified transport. AI-DRAFT-001 supplies the shared draft editor and advisory review; qualifying the connected follow-up action requires it. Test manual-only operation, invalid grants, lost receipts, pause/revoke and restored setup state.

### Concrete UI states and acceptance

Keep Settings → AI assistance → Connected assistants alongside Built-in AI. The connection detail has Scope, Capabilities, Activity and Troubleshooting sections rather than another permanent destination. A connection summary bar only expands/collapses; edits, tests and pause/revoke buttons belong inside it. Show loading, unavailable, successful empty and stale data separately; a failed health query never becomes “No problems.”

| State | Operator presentation and permitted action |
| --- | --- |
| No qualified transport | “No connected assistant available.” Explain the missing capability; manual work and qualified built-in drafting remain usable. |
| Setup required / test running | Show the current setup stage and bounded progress, preserve choices, allow cancel/retry. Do not display Ready until the relevant round trip passes. |
| Enabled | Show the actual client/transport, qualified jobs, current scope/expiry and last authenticated contact. Interactive mode makes no scanning promise. |
| Paused / expired / revoked | Name the reason; prevent new disclosure/request actions. Preserve admitted drafts and history. Resume/reauthorize is explicit and never republishes old work automatically. |
| Pending request | Show deadline and “Waiting for assistant,” Cancel, and manual alternative. The page and other workflows remain usable. Navigation does not cancel. |
| Unknown start/cancel outcome | Disable a duplicate attempt and reconcile by original key. Retain selected context and operator text. |
| Completed | Link to the shared AI-DRAFT editor with connection provenance and source warnings. Approval, copy, external send and Communication recording remain distinct. |
| Failed / interrupted / timed out / invalidated | Show a safe reason and new-preview/new-request or manual action; retain edits and original receipt. Never automatically submit with a fresh key. |

Poll only visible active request/test views, initially every two seconds with backoff to fifteen seconds; stop on terminal state, hidden view or workspace change. Server deadline checks apply independently of polling. Reopening uses persisted state. Refresh must not overwrite dirty edits. Use existing query cancellation/runtime fencing and OPS original-key recovery; do not store exported context or secrets in browser storage or generic recovery payloads. Register each recoverable command and result reader explicitly.

Browser acceptance includes manual-only operation, grant scope preview/amendment, failed qualification and retest, contextual request and shared review, pause/revoke while waiting, expired preview, lost start/cancel response, stale selected source, page navigation, server restart and restored Setup required. Verify keyboard/focus and status announcements, narrow layouts, both themes, permission-denied and unavailable states. Synthetic acceptance proves shared mechanics; real-client acceptance remains in the selected transport feature.

## File-adapter implementation handoff

[ASST-FILE-001](ASST-FILE-001_DESIGN.md) now specifies its proposed publication/capture, bounded worker, archive cutoff and operator diagnostics. Shared request/receipt authority stays here. Its file publication port must serialize publication with pause/revoke and runtime fencing, commit disclosure audit before release, and preserve an honest uncertain-publication result on failure. Already-published bytes cannot provide authorization on every subsequent read; revoke removes projections/permissions where possible but cannot retract copies. Real identity/confinement remains a transport qualification gate, not a property supplied by this service.

The file trial initially enables only the bounded follow-up result contract. It reserves source/state kinds for ASST-INTAKE-001 without enabling arbitrary attachments or opaque checkpoints. Workspace capture includes pending complete files at an explicit cutoff and restores them privately without live authority. File-specific limits and twelve decisions remain proposed; they do not silently resolve this document's shared decisions.

## Contradictions and missing decisions

The accepted direction settles operator approval, transport independence, workspace-contained file exchange and no automatic sending. The following implementation decisions remain open. Recommendations below are reflected in the proposed technical sections; they require confirmation before implementation.

1. **Module ownership is unnamed.** Architecture has no assistant package, while the earlier design lists new records without their owner. Recommendation: add `assistants` for connection/grant/transport request/receipt policy; retain AI Governance run/draft ownership and Maintenance context ownership. Do not make Operator or an MCP server the business authority.

2. **Shared completion versus a usable client is ambiguous.** ASST-001 depends only on AI-GOV-001, while its original acceptance requires a real connected AI-DRAFT action; the transports themselves depend on ASST-001. Recommendation: complete shared services and UI with non-production fixtures, then qualify the real workflow under AI-DRAFT-001 plus either transport. Explicitly show unavailable capabilities until qualification; do not create a dependency cycle.

3. **External provenance fields are not an admission implementation.** Current AI runs have external fields, but no assistant grant registry/admission service; existing `ai_external_operations` is unrelated model credential work. Recommendation: add a transaction-aware external-run/draft admission port and retained provenance validation in AI Governance as part of ASST-001. Keep source-evidence admission/decision extensions in ASST-INTAKE-001/INGEST-002. No fake model connection or provider call for an external result.

4. **Work-request state risks duplicating the draft lifecycle.** AI-DRAFT-001 owns governed model execution; the older ASST text says to reuse it “where applicable” without defining that boundary. Recommendation: assistant requests own delivery/cancel/deadline, reference one admitted external AI run, and never own editable draft/approval state. Result admission atomically commits the transport terminal result, run/draft, receipt and audit.

5. **Grant changes, expiry and defaults are unspecified.** Recommendation: immutable grant revisions, explicit entities/data classes/actions, no future-entity wildcard, default 30-day grant expiry with an operator-selected shorter period; no indefinite grant in the first release. Scope/client identity changes invalidate affected pending work and qualification. Scope expansion requires a new disclosure confirmation. An authorized reconnect must not reactivate requests created under the prior grant.

6. **Pause semantics conflict with preserving pending work.** Agent triage says disabling assistance cancels pending work, but the earlier shared boundary describes pause mainly as admission gating. Recommendation: global pause, connection pause/revoke, grant expiry and disabling lifecycle assistance block immediately and cancel pending requests durably. Resuming never resumes those requests; retain admitted drafts under the existing review policy. Document that external activity and prior disclosure cannot be undone.

7. **Model and assistant deadlines differ.** AI-DRAFT-001 uses 60 seconds; triage gives a one-hour example. Recommendation: a separate connected deadline, default 60 minutes and selectable 5–60 minutes within adapter qualification. Keep the 15-minute pre-admission preview expiry and revalidate source manifests on release/result/approval. No inherited model timeout or automatic request renewal.

8. **Replay after revocation could redisclose sensitive data.** Original-result replay and current authorization checks need an explicit ordering. Recommendation: authenticate and authorize reads first; replay only an authorized immutable receipt, without fresh effects or quota charges. Revoked assistants receive no historical content; local operator history remains available. Different keys cannot bypass one-result-per-request uniqueness.

9. **Restart and restore authorization are not the same.** Recommendation: ordinary restart requires a fresh authenticated transport session and marks unresolved requests interrupted; no automatic redispatch. Restore additionally invalidates all live device/grant authorization, quarantines transport files through ASST-FILE-001 and requires explicit reauthorization. Preserve historical grant facts. Use device/session epochs outside portable authorization so a copied database cannot authorize a replacement host.

10. **Admission limits and retained diagnostics are unspecified.** Recommendation: the proposed connection/request/page/payload caps above, 100 admissions per connection per UTC day, and a 30-day diagnostic-summary window. Keep business receipts and replay fingerprints indefinitely with workspace history. Rate-limit repeated rejected submissions per connection to 60/minute and keep one aggregate audit summary for suppressed repeats; every accepted disclosure/admission/decision remains individually audited. A failed mandatory audit blocks its action. Do not retain malicious raw payloads or pretend unknown token use is zero.

11. **Qualification and assistant scheduling are not guaranteed by a protocol.** A client supporting MCP or files may only work interactively and may not wake for an EPM request. Recommendation: record interactive versus unattended capability separately, version-bound to a tested client/adapter/pack. Interactive setup gives the exact “Open your assistant to process this request” step. Keep Muse as the first file trial and Dot as a later candidate per triage; choose the first MCP client during MCP-001 qualification. No product claim or automatic schedule in ASST-001.

12. **Shared health overlaps source discovery.** The existing document includes poll/coverage records and mailbox reconnect UI. Recommendation: ASST-001 owns authenticated contact, compatibility, request age and receipt delay only; poll records, acknowledged schedules, source verification/coverage and source reconnect belong to ASST-INTAKE-001. DASH-003 owns the broader Home composition. Keep those fields unavailable, not zero, until qualified.

13. **“Approved committed” can imply a business effect.** Recommendation: preserve a common receipt structure but identify the outcome kind. Advisory approval points to the reviewed draft only and displays “Draft accepted”; source-backed approval may point to an official issue only after its owning transaction commits. Admission and final decision receipts are separate immutable versions. No send, Communication or money effect is inferred.

14. **Top-level scope documents retain older integration assumptions.** Product Brief still describes native mailbox/SMS connectivity and voice in MVP; Decisions includes older assistant-grant credential wording. The accepted triage/backlog supersedes native connector assumptions for this feature. Recommendation: follow that accepted direction, keep non-secret grant history portable and usable authorization outside backups, and reconcile those broad documents in a separately authorized consistency pass. Do not broaden ASST-001 to implement their stale scope.

## Ordered implementation slices

Each slice includes focused validation and any UI needed to use it; these are sequential implementation steps, not new backlog items. Resolve the decisions above before starting. Maintain one current greenfield schema; no legacy migration/compatibility effort.

1. **Contracts and ownership.** Define the `assistants` application ports, closed schemas, capability manifest, policy/error taxonomy and synthetic adapter harness. Agree the AI Governance transaction port and future Intake extension boundary. Produce contract tests; no production capability is exposed.
2. **Persistence and portable invariants.** Add connections, immutable grants, requests, submissions/receipts, qualifications and correlated audit with replay/uniqueness constraints. Register schema and retained-history validation, backup/restore invalidation and lifecycle fences. Test atomic rollback and corrupted histories.
3. **Connection Settings and scope.** Deliver typed list/detail/create/amend/grant/pause/revoke and original-result APIs, OPS recovery registration and task-based Settings. Include disclosure preview, scope receipt, limits, unavailable/expired states and fixture-driven qualification UI. Manual workflows stay functional.
4. **Bounded context and request admission.** Integrate AI-DRAFT-001's Maintenance preview/action when available; otherwise validate ports only with fixtures. Persist immutable context/manifest, policy snapshot and request before publication. Add contextual connected selection/start/status/cancel and lost-response handling. The real action remains gated until AI-DRAFT-001 exists.
5. **Result admission and review handoff.** Add governed external run/draft admission and immutable receipt projection. Validate source references, scope and complete source manifest. Deliver the shared editor handoff, advisory outcome labels and atomic final decision receipt; test duplicate keys and races. Do not add a second queue.
6. **Qualification, lifecycle and recovery.** Finish version-bound test runs, authenticated contact/activity UI, bounded publication/reconciliation ports, pause fan-out, deadline expiry, restart/restore and denial diagnostics. Transport-specific IPC/file operations and real-client instructions remain in their own features.
7. **End-to-end acceptance and handoff.** Prove shared services/UI in temporary workspaces, query budgets, generated contracts and packaged browser operation. Publish the versioned contract pack and adapter conformance scenarios. Record shared completion separately from real transport/action qualification, and update current module/UI guides only for behavior actually implemented.

## Detailed validation matrix

| Area | Required evidence |
| --- | --- |
| Happy paths | Setup → scoped grant → synthetic qualification; real action only when qualified → preview → durable request → result/draft → edited advisory decision → receipt. No implicit Communication, Task, send or domain write. |
| Invalid combinations | Wrong workspace/session/connection, unsupported action/version, expired/replaced grant, unselected entity, data-class mismatch, source reference outside manifest, unverified client, archive/detachment, malformed output and every size/count ceiling. |
| Idempotency and retry | Lost operator response, identical/changed key, different response keys for one request, repeated publication, missed admission/final receipt and replay after pause/revoke. Assert one authoritative result and no extra admission charge. |
| Concurrency and rollback | Cancel/result, expiry/result, pause/export, grant amendment/admission and source edit/result races. Inject audit/run/draft/receipt failures: no partial acceptance, no leaked context after failed disclosure audit and no nested write transaction. |
| Persistence/schema | Closed versions, valid grant/request/run linkage, canonical fingerprints, source manifest consistency, unique terminal results, immutable receipts and prohibition of assistant approval actors. Reject tampered backup rows. |
| Backup/restore | Preserve histories and draft edits; exclude usable authorization; fresh runtime fences old sessions; pending requests interrupted and not reissued. File quarantine/archive content is verified by ASST-FILE-001, not falsely claimed here. |
| Query budget | Eight-SELECT list/detail composition target and twelve-SELECT preview ceiling, tested at maximum page/context counts and multiple connections. No per-row hydration, unscoped totals or all-page client aggregation. |
| UI and recovery | Narrow/desktop layouts, Light/Dark, keyboard/focus/status announcements, staged setup failure, manual-only mode, dirty edits, unknown outcomes, visibility-aware polling, restart and restored Setup required. Verify real persistence, not only mocked UI. |
| Transport conformance handoff | A fake adapter proves service contracts only. Each selected real adapter must additionally prove bound identity, scoped access, delivery/receipt recovery and interactive/unattended claims before its capability is enabled. |

No implementation tests were run for this documentation-only design. Existing code references are design-time evidence, not proof that the proposed assistant feature already works.
