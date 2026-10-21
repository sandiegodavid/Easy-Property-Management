# ASST-001 — Shared connected-assistant boundary

## Status and ownership

Proposed feature design, October 20, 2026, based on [agent triage research](../research/agent-triage-design.md). This is the application contract for qualified connected assistants. [MCP-001](MCP-001_DESIGN.md) and [ASST-FILE-001](ASST-FILE-001_DESIGN.md) are alternative transports. A model API connection remains separate under AI-GOV-001. No assistant product is presumed available or required for manual EPM use.

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

For `maintenance.follow_up_draft`, EPM records request ID, connection/grant, issue ID and captured revision, bounded context and disclosure, action version, created/expiry time and state version before publishing. The assistant returns a draft or typed error with a stable connection/request key. Exact response replay returns the terminal receipt; changed content under the same key conflicts. EPM accepts at most one terminal response for the current request version. Cancellation is a durable versioned state/tombstone; a late answer cannot revive it. A timeout offers the operator manual drafting or a new request ID. The draft remains an AI Governance suggestion for operator review; COM-001 does not send.

The chosen transport publishes request, response and receipt under this same contract. Restore invalidates live grants and reconciles pending requests from durable state rather than blindly reissuing them. Revocation blocks new disclosures/admission but cannot retract already disclosed context or stop the assistant's independent activity.

The operator-only management API provides typed connection list/create/update, test, grant, pause and revoke operations; responses omit secrets. Model-provider connections remain on AI Governance's separate API. Adapters use internal application ports, not an unauthenticated `/api/agents/proposals` route. Audit each grant, data-bearing read/export, request, submission, decision, rejection, pause and revocation with connection/grant and correlation ID; only empty health checks may be sampled. Assistant-reported model identity is labeled unverified unless independently attested.

## Later source admission and health

ASST-INTAKE-001 may register a source-backed proposal action only after INGEST-002 owns its review and atomic consequence. The shared service then validates connection-scoped idempotency, canonical fingerprint, verified provider/account/message identity, retained evidence, action schema and current scope before admitting through Intake and AI Governance. An exact replay returns its stored receipt; changed payload under the same key conflicts. The first receipt means accepted for review, not an official issue; the later receipt reports the operator/domain outcome. Cross-connection source deduplication uses verified account identity and provider message ID; uncertain matches remain visible hints.

Receipt states are `accepted_for_review`, `rejected`, `approved_committed`, `dismissed` and `superseded`, plus typed retry guidance where applicable. The first receipt includes stable submission/run/draft references but no claimed domain effect; only a committed operator decision may add a result reference. Admission and operator decision each persist their durable result before transport publication. A stale source revision/fingerprint or target revision returns to review rather than being approved through a generic bypass. The registered action and INGEST-002 determine create/link/update/dismiss semantics, never the assistant's desired effect alone.

Interactive contact, scheduled poll report, last fully successful source scan, pending submissions and coverage gaps are distinct. A heartbeat is not proof that a mailbox was scanned. Timeouts and warnings use server-observed contact and acknowledged schedule; source coverage requires per-source checkpoints, counts, failures and verified intervals. EPM owns real-world Tasks/deadlines and manual fallback.

For a qualified scheduled connection, a suggested warning baseline is no valid contact for twice the acknowledged interval, evaluated on app startup/resume. Before schedule acknowledgement, show **Not yet verified** against the requested interval. A fresh failed or partial poll clears a silence warning but retains its own source failure warning. Interactive connections show last activity and test status without missed-poll alarms. The app cannot raise a live warning while closed, and no contact threshold proves complete source coverage.

## Delivery and validation

Ship a versioned assistant-neutral contract pack and capability manifest, with transport-specific instructions. A connection is enabled for only the actions demonstrated in a synthetic round trip. UI-003 owns task-based setup, disclosure, test diagnostics, status, pause/revoke and recovery; it must not present source coverage before ASST-INTAKE-001 qualifies it. ASST-001 exposes typed operator APIs and internal adapter ports, not a public unauthenticated proposal route.

| Area | Cases |
| --- | --- |
| Happy paths | One bounded follow-up request → draft/error → operator review → durable result and receipt; later source proposal only after its separate qualification. |
| Invalid combinations | Wrong writer/connection, expired/paused grant, out-of-scope entity/data class, unregistered action, stale issue, oversized payload, forged identity or unsupported client. |
| Idempotency/retry | Exact request/result/submission replay, changed-key conflict, missed receipt, timeout/cancel race and cross-connection source duplicate. |
| Transaction rollback | No accepted result, proposal or official domain effect without its durable receipt and correlated audit. |
| Persistence/schema | Closed action, grant, result and receipt versions; retained identity and scope consistency; bounded history and audit validation. |
| Backup/restore | Retain history and pending status; invalidate usable grants/sessions; require fresh authorization and reconcile uncertain work. |
| Query budget | Bounded scoped reads, request lists, receipts and health without per-row source or evidence reads. |
