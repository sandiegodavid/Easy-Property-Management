# ASST-001 — Shared connected-assistant boundary

## Status and ownership

Proposed feature design, October 20, 2026, based on the [agent triage design](agent-triage-design.md). This is the application contract for qualified connected assistants. [MCP-001](MCP-001_DESIGN.md) and [ASST-FILE-001](ASST-FILE-001_DESIGN.md) are alternative transports. A model API connection remains separate under AI-GOV-001. No assistant product is presumed available or required for manual EPM use.

ASST-001 establishes the shared boundary independently of the business actions that use it. The first proposed connected action is a bounded EPM-initiated request for the registered AI-DRAFT-001 follow-up action, once that action exists. Scheduled channel discovery and retained-source issue proposals are gated behind [ASST-INTAKE-001](ASST-INTAKE-001_DESIGN.md) and INGEST-002. Either capability can qualify independently. No agent receives direct create, assignment, payment, sending, signing, or approval commands.

## Connection, grant and action contract

A connection identifies its actual product/client, adapter, version, transport and demonstrated capabilities. An operator grant binds workspace and connection identity to purpose, role, selected entities/data classes, registered actions, disclosure, expiry and limits. EPM verifies effective writer/session identity at the transport boundary; an envelope's `agent_id` or filename is not authentication. Every read, export, request, submission and result rechecks pause, revocation, scope, bounds and current action registration. Grants do not transfer to replacement agents or restored devices. Assistant account permissions are separately managed by the assistant platform and are not implied by an EPM grant.

Store connection/grant history, bounded work requests and their state versions, accepted terminal results, submission keys/fingerprints, durable receipts, capability-test results, audit and health observations in application-owned persistence. Usable transport secrets remain outside portable data. Database receipts are authoritative; file or MCP responses are projections. One transaction owns an accepted result and correlated audit. EPM's operator-only Settings controls grant, limits, pause and revoke; a connected assistant cannot change them.

| Application-owned record | Required facts |
| --- | --- |
| `assistant_connections` | Stable ID, operator label, actual client/adapter/version, transport, requested/acknowledged configuration, interactive/scheduled mode, lifecycle and capability-test history. |
| `agent_delegations` | Workspace/connection, selected entity and data-class scope, purpose/role, disclosure acknowledgement, expiry, status and revocation history; no usable secret. |
| `assistant_work_requests` and results | Registered action/version, bound issue/source revision, bounded disclosed context, connection/grant, state/version, expiry, cancellation, response key/fingerprint and immutable terminal result. |
| `assistant_submissions` and receipts | Connection/grant, intent and idempotency key/fingerprint, retained source/run/draft references when applicable, versioned admission and decision result, audit correlation. |
| `assistant_poll_reports` | Unique connection/poll ID, server receipt time, effective source/configuration, success/partial/failure counts, checkpoint range and unresolved intervals. Populated only for qualified scheduled discovery. |

Retained validation binds these records to exact schemas, source identities and audit evidence. Encrypted backup retains history, but not usable credentials, active session authorization or device paths. Connection/action admission caps and payload ceilings are separate from measured model token limits; unreported assistant token use is Unknown, never zero.

## First work request

The accepted [AI-DRAFT-001 contract](AI-DRAFT-001_DESIGN.md#resolved-design-decisions) owns the business action, closed schemas, selected-source revision manifest, advisory approval and contextual UI. ASST-001 adds connection/grant and transport request identity; it must not create a second draft-review ledger or relax that action contract. Reuse the governed lifecycle extensions delivered by AI-DRAFT-001 where applicable, while keeping assistant transport receipts distinct from model execution. The shared boundary can be built independently; qualifying this connected action requires AI-DRAFT-001.

For `maintenance.follow_up_draft`, EPM records request ID, connection/grant, issue ID and captured revision plus the complete selected-source revision/fingerprint manifest, bounded context and disclosure, action version, created/expiry time and state version before publishing. The assistant returns a draft or typed error with a stable connection/request key. Exact response replay returns the terminal receipt; changed content under the same key conflicts. EPM accepts at most one terminal response for the current request version. Cancellation is a durable versioned state/tombstone; a late answer cannot revive it. A timeout offers the operator manual drafting or a new request ID. The draft remains an AI Governance suggestion for operator review; COM-001 does not send.

The chosen transport publishes request, response and receipt under this same contract. Restore invalidates live grants and reconciles pending requests from durable state rather than blindly reissuing them. Revocation blocks new disclosures/admission but cannot retract already disclosed context or stop the assistant's independent activity.

The operator-only management API provides typed connection list/create/update, test, grant, pause and revoke operations; responses omit secrets. Model-provider connections remain on AI Governance's separate API. Adapters use internal application ports, not an unauthenticated `/api/agents/proposals` route. Audit each grant, data-bearing read/export, request, submission, decision, rejection, pause and revocation with connection/grant and correlation ID; only empty health checks may be sampled. Assistant-reported model identity is labeled unverified unless independently attested.

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
