# UI-003 — Connected-assistant operator experience

## Status and allocation

Preliminary design, October 20, 2026. UI-003 extends the delivered UI-001 shell for the [shared assistant boundary](ASST-001_DESIGN.md) and the [agent triage design](agent-triage-design.md#1-what-the-operator-configures-and-sees). UI-002 continues to own INGEST-002 issue-review pages and spreadsheet intake; post-MVP legal/HOA workflows belong to UI-004. AI-DRAFT-001 can put an EPM-invoked **Draft follow-up** on an issue before UI-003 or any assistant connection exists. UI-003 adds the connected alternative without creating another daily work surface or approval path.

This carries UI-002's earlier D46 decision: Connected assistants appear beside, and remain independent of, Built-in AI in Settings. Choosing a model never grants assistant access; changing an assistant never changes the selected model or its disclosure destination.

## Operator flow

The entry question is **What would you like help with?** Offer bounded jobs such as drafting on an existing issue or watching a selected source. Show only the technical prerequisites of the chosen job: drafting does not request mailbox access; source watching does. Operators can use manual EPM workflows or choose any qualified capability without first enabling an unrelated tier. No channel access is default-on. An unqualified product/client/capability is unavailable with a reason and manual alternative, not silently substituted.

Setup stays in Settings → AI assistance → Connected assistants, beside the independent Built-in AI card. It is task-specific:

1. Choose actual assistant/client, transport and job; preview exact property/unit, data-class, source-account and action scope, disclosure and expiry.
2. Preflight EPM's workspace, managed exchange when relevant, contract/action version, and proposed grant before switching apps. Show the single concrete assistant-side folder/account permission step, then return to EPM.
3. Run a synthetic request/proposal and receipt round trip with no official business record. Show which stage failed—assistant unavailable, permission/isolation, grant, version, submission or receipt—and a specific **Retry test** action. A heartbeat or test file does not prove source scanning or filesystem isolation.
4. Enable only the demonstrated capability. Source discovery separately verifies account/filter, schedule, catch-up and per-source reports under ASST-INTAKE-001. A draft test cannot label a mailbox “watched.”

The normal issue page hosts connected draft requests, pending/error/timeout states and review. INGEST-002's normal queue hosts source-backed suggestions; there is no second agent approval queue. Paused/revoked connections leave already admitted drafts visible with provenance and current-source warnings. A model-generated draft labels its verified model/runtime and device/cloud destination; an assistant-proposed draft labels verified connection/transport separately from assistant-claimed model details. The operator sends externally and records any Communication separately.

## Health and recovery

Settings shows a plain-language **What this assistant can see now** receipt: granted entities, sources, roles, data classes, expiry, recent EPM-mediated exports/submissions/decisions, and pause/revoke. This does not claim to list everything the assistant can see through its independent channel accounts. Connection detail separates last authenticated contact, pack compatibility, pending submissions, oldest unacknowledged item and admission-receipt delay. Scheduled source detail additionally separates last fully successful scan, partial/failed polls, requested versus acknowledged cadence, unknown intervals and provider-retention catch-up limits. Interactive clients have no fabricated missed-poll alarm.

A degraded/offline banner names the affected capability, last verified scan, and manual or reconnect path without promising unseen messages will later be found. **Reconnect source** opens product-specific permission guidance; **Update adapter** identifies the required version; **Retry test** checks the repair. EPM may republish a missing receipt or refresh a bounded export from durable state. It does not widen scope, repeat uncertain outbound work, or treat a fresh heartbeat as a completed scan. Restore marks connections Setup required; pending files cannot be admitted under a new grant automatically.

Invitations to add assistance appear at moments of relevant work, can be dismissed with **Don't suggest this again** for that invitation type, and never block manual tasks. Early suggestions may need corrections; any accuracy/time-saved report card uses measured observations and never promises automatic learning. Technical JSON/path details belong only in advanced setup or diagnostics. Mobile review, keyboard/focus behavior, light/dark themes and UI-001's full-summary-bar disclosure remain intact.

## Delivery gate and validation

UI-003 requires ASST-001 and at least one qualified transport before claiming a working connected assistant. MCP-001 and ASST-FILE-001 are alternatives. ASST-INTAKE-001 is required only for source-watching UI and health claims, while INGEST-002/UI-002 are required for official issue-proposal decisions. Capabilities and routes remain hidden or explicitly unavailable until their owning backend and UI registrations both pass. A synthetic setup screen is not production proof.

| Area | Cases |
| --- | --- |
| Happy paths | Contextual task choice → scoped setup → synthetic round trip → connected issue draft; separately qualified source proposal → UI-002 review. |
| Invalid combinations | Missing assistant, unqualified transport, unsupported action/modality, denied disclosure, broad folder access, wrong scope, paused/revoked grant, unavailable source. |
| Idempotency/retry | Lost test receipt, duplicate result, canceled request, retry after repair, overlapping source connections. |
| Transaction rollback | UI never presents an official outcome until its owner returns a committed result; setup failure does not leave an enabled grant. |
| Persistence/schema | Exact capability, grant, request, result and health versions match generated API contracts and survive restart. |
| Backup/restore | History stays visible, authorization becomes Setup required, source catch-up remains qualified and pending submissions remain quarantined. |
| Query budget | Bounded connection/health/activity pages and contextual draft summaries; no per-row evidence load. |
| UI regression | Existing UI-001 and UI-002 navigation, manual paths, source review, keyboard operation and both themes still work. |

## Accepted AI-DRAFT-001 handoff

[AI-DRAFT-001](AI-DRAFT-001_DESIGN.md#resolved-design-decisions) owns the first Maintenance draft workflow, including context preview, pending/status/cancel recovery, editing, advisory approval, copy and separate COM-001 recording. UI-003 reuses that issue surface for a qualified connected-agent execution path. It adds explicit connection/grant and destination disclosure without silently switching from a model to an assistant. Preserve the complete source manifest and stale-context review, original-result recovery, operator edits and no-send semantics. Qualifying this action requires AI-DRAFT-001; generic assistant setup remains independently deliverable. Model execution deadlines do not establish a connected assistant scheduling guarantee; ASST-001 must expose its actual request expiry.
