# MCP-001 — Local MCP transport for connected assistants

## Status and purpose

Proposed transport design, revised October 20, 2026. The stable backlog ID now owns **one qualified local MCP adapter**, not the whole assistant integration. [ASST-001](ASST-001_DESIGN.md) owns assistant-neutral connections, grants, bounded work requests, proposal admission, receipts, pause/revoke, audit and recovery. [AI-DRAFT-001](AI-DRAFT-001_DESIGN.md) owns the first task action. [ASST-INTAKE-001](ASST-INTAKE-001_DESIGN.md) later qualifies scheduled source discovery and retained-evidence issue proposals. A model API is not an MCP client, and a ChatGPT product connection is not an OpenAI model API key. No named client is assumed compatible without a real test.

MCP is one protocol choice. The [managed file adapter](ASST-FILE-001_DESIGN.md) is independent and must call the same ASST-001 application boundary; it does not become an MCP tool or require this backlog. Neither transport is a direct domain-write path. Manual EPM use and EPM-invoked model drafting work without MCP.

## First client and process boundary

Qualify local STDIO with one actual desktop MCP client, recording exact client/adapter version and demonstrated tools. A trusted launcher binds the process/session to a preapproved workspace, connection and grant without command-line plaintext secrets or an unauthenticated launch. It connects to the running EPM application boundary; it never becomes a second SQLite writer. Client labels or tool-call arguments cannot select another connection. Local streamable HTTP is a separate adapter qualification with loopback binding, request authentication, host/origin and protocol/session checks. Localhost is not authentication. A public endpoint, tunnel or hosted MCP deployment is outside this item.

The first end-to-end capability is a bounded EPM-initiated `maintenance.follow_up_draft` request and its draft/error result. The MCP adapter exposes only registered request, response, receipt and authorized scoped-read tools needed for that action. It must not advertise mailbox scanning, maintenance issue submission, calendar access or outbound sending merely because the client supports MCP. Later ASST-INTAKE-001 registration may expose source evidence and proposal submission through ASST-001 when INGEST-002 review is ready.

## Tool and authorization contract

Every tool call resolves the bound principal, active grant, workspace, action and data-class/entity scope through ASST-001. Recheck pause, expiry, revocation, disclosure, bounds and source revisions before reads or result admission. Source-owned projections return bounded pages and opaque revisions; no SQL, arbitrary filesystem path, raw attachment tree or workspace archive tool exists. A request/result/proposal tool can alter the review queue, so it must not be described as read-only. Tool annotations inform the client; EPM authorization is server-enforced.

Register tools only as their source contracts become available. The first client needs connection/configuration, bounded issue context, assigned work requests, draft/error submission and receipt reads. Later permitted reads may include Properties, issues, Providers, Tasks, lease/rent facts or Communication excerpts through source-owned projections with explicit purpose and field scope. `sources.submit` and `proposals.submit` are absent until ASST-INTAKE-001 and INGEST-002 qualify them. A change cursor is metadata-only and returns an explicit resync requirement when expired, not an empty successful page. No tool exposes an approval or an unrestricted provider-run endpoint.

The first result is idempotent by connection/request/version and canonical fingerprint. Same key/content yields the durable ASST-001 receipt; changed reuse conflicts. A missed response is recovered from the original request/receipt, not by rerunning an official command. Cancellation and timeout are state versions that reject late results. Later source submissions additionally use connection-scoped idempotency and verified provider/account/message deduplication through ASST-INTAKE-001. MCP never approves an AI draft, creates an issue, assigns a Provider, sends a message or records spending.

Connection health reports authenticated client activity and test status. Scheduled poll and source-coverage fields are available only for an actual qualified ASST-INTAKE-001 client; a tool call or heartbeat alone does not prove a mailbox scan. Global/per-connection pause and revocation take effect on the next check but cannot retract data already disclosed or stop a separate client-side schedule. Restore invalidates live launch/session authorization and requires a fresh test.

## Delivery and validation

Ship transport-specific instructions in the versioned assistant contract pack. MCP-001, within ASST-001 Settings, guides client choice, grant, setup preflight, client-side permission, synthetic request/result/receipt round trip, and failure recovery. Qualify the selected client in a disposable workspace with synthetic data. Unsupported clients remain unavailable with a reason; do not claim universal MCP compatibility or a five-minute setup guarantee.

| Area | Cases |
| --- | --- |
| Happy paths | One real local client: scoped context → EPM request → draft/error → durable receipt → operator review; later source path only after separate qualification. |
| Invalid combinations | Unbound launch, wrong workspace/grant, forged client label, overbroad read, expired/paused grant, unsupported tool, malformed/oversized result, stale issue. |
| Idempotency/retry | Exact/changed result replay, missed receipt, disconnect after commit, cancel/timeout race and client restart. |
| Transaction rollback | No accepted result without ASST-001 receipt/audit; no tool commits an owning domain effect. |
| Persistence/schema | Closed tool/action versions and original receipts survive restart and retained validation. |
| Backup/restore | Preserve historical requests/results; exclude usable sessions and secrets; retest after reauthorization. |
| Query budget | Bounded scoped reads, cursor/continuation behavior and no per-row domain hydration. |

## Included operator interface delivery

This UI is part of this functional backlog and its completion criteria. Reuse the delivered UI-001 shell, generated contracts, source-owned commands, Light/Dark themes, keyboard/focus behavior and recovery patterns. Validate real temporary-workspace reads/writes, stale revisions, lost responses, restart/restore and bounded queries; backend-only delivery is incomplete.

Deliver client-specific MCP setup/permission instructions, version/compatibility preflight, synthetic request/result/receipt diagnostics and Retry test within ASST-001 Settings. Report stage-specific failures and enable only qualified capabilities. Reuse the shared grants, activity, pause/revoke and recovery UI; no separate destination.
