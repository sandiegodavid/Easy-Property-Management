# AI-DRAFT-001 — Draft a maintenance follow-up

## Status and boundary

Design decisions accepted October 22, 2026; implementation remains pending. The [agent triage design](agent-triage-design.md#5-assistance-on-existing-issues) motivates a useful first AI action that needs no connected assistant or mailbox permission. AI-GOV-001 provides generation, limits, disclosure, pause, provenance, review and original-result mechanics; Maintenance supplies issue facts; Communications records interactions but does not send. This item registers one production action and its operator workflow. It does not implement ASST-001, MCP, file exchange, intake review, or outbound delivery.

## Operator outcome

On an existing issue, **Draft follow-up** previews the bounded facts to be supplied and the configured on-device or hosted model destination. The operator starts a request, receives a draft or typed error, edits it in issue context, and sends it through their own channel. Recording a sent interaction is a separate COM-001 action. Generating or accepting a draft never changes the issue, sends a message, creates a Task, or establishes that a tenant or Provider replied.

The first implementation includes qualification of one hosted model; a local model is optional and needs its own runtime qualification. Neither an unavailable model nor a failed local call silently falls back to a cloud model. If no model/action is qualified, show the ordinary manual drafting path with a truthful unavailable state.

## Contract and lifecycle

- Register a closed `maintenance.follow_up_draft` action with a versioned bounded input and output schema. Inputs identify the issue and captured issue revision, intended recipient role and purpose, selected relevant issue/journal/appointment/Task/Communication facts, and any operator-supplied instruction. The owning sources provide these facts; no raw database or unscoped history is exposed. Exclude credentials, unrelated tenants, and full file bytes unless a later action explicitly permits them.
- Keep governed input, model output, operator edits and any later recorded communication distinct. Record actual provider/model/runtime provenance, disclosure decision, correlation ID, source revisions, limits and audit. Draft text is advisory; uncertain timing or missing facts become visible placeholders or a typed error, never invented commitments.
- An operator request has a stable key and captured revision. Exact retries return its original result or current request state; changed reuse conflicts. An issue changed while the request was running requires a visible refresh before the draft is used as current advice. Cancellation and timeout stop accepting a late result for that request version; they do not claim to cancel a remote computation already started. New attempts use new IDs.
- The UI owns review ergonomics and manual send. COM-001 owns the separately recorded interaction, MAINT-001 owns any issue update, and TASK-002 owns a follow-up commitment. No draft approval is an implicit command to any of them.

## Delivery and validation

1. Register the action, source-owned context projection, disclosure profile, provider capability check, limits and typed draft/error result with AI Governance.
2. Add issue-context start, pending, error, timeout, edit and copy/use states. Preserve operator edits through a stale-context warning; record a sent interaction only through COM-001's command.
3. Qualify one real model/runtime and verify supported input/output bounds and privacy destination before offering the action. Synthetic registry tests alone do not establish production availability.

| Area | Cases |
| --- | --- |
| Happy paths | Bounded issue context → qualified model → editable draft → optional separately recorded interaction; manual path works without AI. |
| Invalid combinations | No model, unsupported action, paused assistance, denied hosted disclosure, missing/stale issue, forbidden data class, malformed response or invalid source references; factuality qualification cases and operator review for unsupported claims. |
| Idempotency/retry | Lost response, exact-key replay, changed-key payload, cancellation/timeout race and late result. |
| Transaction rollback | No partial official issue/Task/Communication effect when generation or draft persistence fails. |
| Persistence/schema | Closed action versions, governed input/output/edit lineage, provenance and audit survive restart and retained validation. |
| Backup/restore | Draft/review history survives; model credentials and running requests do not become usable after restore. |
| Query budget | One bounded source-owned issue/context read without per-journal-entry or per-Communication queries. |

## Implementation assessment — October 22, 2026

The implementation assessment below records the baseline reviewed on October 22, 2026. All twelve recommendations are accepted; the resolved decisions govern the implementation contract. Provider/model selection remains a qualification task before adapter implementation, not an unresolved product-scope decision.

- `application/apps/server/app/modules/ai_governance/application/registry.py` currently constructs empty action, redaction-profile and adapter registries. This feature must register and qualify real definitions; the existing Settings/review screens do not establish generation availability.
- `application/apps/server/app/modules/ai_governance/application/service.py` already reserves durable generation runs, fingerprints governed requests, calls the provider outside the write transaction and admits results through a separate write. Reuse those boundaries. Its `provider.generate()` call is synchronous: asynchronous HTTP admission, durable run lookup and cancellation cannot be assumed from it.
- `application/apps/server/app/modules/ai_governance/api/router.py` exposes Settings, connections, limits, draft editing/approval/dismissal and command recovery. It does not expose this Maintenance context-preview/start/status/cancel workflow. Add typed feature contracts rather than exposing arbitrary candidate JSON as a public generation API.
- Maintenance supplies issue, journal and appointment facts through its application boundary. Communications supplies only explicitly linked, operator-selected interactions. A generic history query or matching property address is not authorization to disclose a conversation.
- Existing browser AI review provides a reusable draft detail and decision surface. AI-DRAFT-001 still owns the contextual trigger, preview, asynchronous request tracking and edited draft handoff. UI-002 and UI-003 are not prerequisites.

## Technical design

### Ownership and bounded context

Maintenance owns a follow-up application service and context reader. AI Governance owns execution, policy, provider configuration, run/draft persistence and review. Composition injects source-owned read ports; neither the browser nor an adapter reads another module's tables directly.

Preview identifies the issue, its current lifecycle, intended recipient role, purpose, optional operator instruction and explicit selected source IDs. Return a snapshot identifier, source revision/fingerprint manifest, governed preview, disclosure destination and expiry. The server resolves and validates IDs, verifies relationships and creates the canonical candidate. The browser cannot supply authoritative facts, provider identities or redaction results.

Accepted initial limits: one issue, one recipient role, up to ten selected contextual records in total, 2,000 characters of instruction, 32 KiB governed input and 8 KiB structured output. Reject excess content with 413; do not silently truncate selected evidence. Model token ceilings may be tighter and must be checked before dispatch. Preview expiry is 15 minutes. Use one consistent bounded read transaction; allow at most twelve SELECTs for preview with no query per selected record. Measure this budget in integration tests before registration.

Default context contains issue summary/status and the operator's purpose. Journal entries, appointments, Tasks and Communications require visible selection. File bytes, raw Intake evidence, unrelated occupants and payment instructions are excluded. Source text is untrusted material, never executable instructions. Display missing facts and omitted optional context explicitly.

Output is a closed versioned object containing `body`, optional `subject`, source-reference IDs and bounded warnings/placeholders. Returned source IDs must be a subset of the captured manifest. Schema validity cannot prove factual correctness: the operator must review commitments, dates, names and amounts against displayed evidence. No confidence score establishes safety or permission to send.

### Request and persistence contract

Maintenance endpoints cover context preview, start, request detail, request-by-original-key and cancel, all issue-bound. Final paths and generated contracts are assigned in the API slice. Preview is read-only. Start takes the preview identity/fingerprint and a UUID operation key, rechecks source/disclosure/configuration readiness, persists admission and returns 202 with a stable run reference. Exact replay returns the original admitted request without another model call; changed reuse returns 409. Missing records return 404, malformed combinations 422 and oversized payloads 413 through the common API error mapper.

Use AI Governance's run as the authoritative execution record, extending its supported lifecycle where necessary rather than creating an independent Maintenance job ledger. Record the exact source manifest, action/profile versions, governed context, actual model/runtime, correlation ID and output lineage. Keep provider credentials outside portable state. Draft edits use existing revision-aware commands and preserve original output separately.

A bounded in-process executor performs the provider call outside the canonical writer transaction. Admission reserves capacity before returning success. Result admission rechecks pause, configuration, cancellation, deadline and request state in one short write. Poll only while the view is active, with backoff; navigating away does not cancel an admitted request. The rest of the application remains usable.

The default deadline is 60 seconds, bounded by the qualified adapter. Cancellation is a durable state transition, not a claim that the remote provider stopped. A cancel/result race has one committed winner. After restart, abandoned running requests become interrupted and are never silently resubmitted; a new attempt requires operator action and a new key. A lost HTTP response is reconciled with the original key before retry. Restore retains history but prevents restored running work from dispatching automatically.

### Review and manual communication

Keep generation state separate from review state. A completed run can yield an unreviewed, edited, approved or dismissed draft; approval records acceptance of advisory text only. Recheck the complete selected-source manifest when presenting a draft as current and when accepting it. Changes to a Communication, appointment or Task can invalidate context even if the issue revision is unchanged. Preserve edited text during refresh; regeneration creates a linked replacement rather than overwriting it.

Show Draft follow-up inside the expanded issue detail. Preview shows recipient role, purpose, selected facts and destination. Pending, canceled, interrupted, timed-out, unavailable and failed states each have an appropriate recovery action. Copying text does not record a send. A separate Record interaction action opens COM-001 with editable content and context, and requires its normal confirmation; approval alone does not create a Communication. Tasks and issue updates remain separately confirmed commands.

## Resolved design decisions

Accepted October 22, 2026. The numbered decisions retain the original review numbering for traceability.

1. **Production provider is unspecified.** Empty production registries mean this is more than an action/UI slice. Decision: include one real hosted adapter qualification in AI-DRAFT-001; select its vendor/model before implementation. Do not infer API access from an assistant subscription. A local runtime stays optional.
2. **Asynchronous lifecycle is not supplied by the existing generation API.** Decision: extend AI Governance with durable run admission/status/cancellation and bounded execution as described above, within this feature's scope. Do not hold a writer transaction across inference or treat browser abort as cancellation.
3. **Issue revision alone misses changed selected evidence.** Decision: capture and revalidate a manifest for every selected source, including deletions/archive state; require fresh review after a mismatch.
4. **“Accept/use draft” is ambiguous.** Decision: advisory approval records reviewed text only; copy and manual send remain separate. Do not reuse an approval handler that creates an official issue or communication.
5. **Recipient and channel scope is unspecified.** Decision: start with tenant, owner or assigned-provider follow-ups on an existing open issue; one recipient role per draft, no automatic address lookup, bulk audience or send capability. Closed/archived issues retain historical drafts but cannot start this action.
6. **The original context list implies additional dependencies.** Decision: issue-only drafting must work with MAINT-001, AI-GOV-001 and COM-001. Journal, appointment and Task selections are optional registered source capabilities; do not make MAINT-003 or TASK-002 mandatory merely for enrichment.
7. **Disclosure preview and execution could diverge.** Decision: bind admission to the governed snapshot, destination/configuration revision and disclosure authorization; refresh the preview after any change. Never silently switch model or destination.
8. **Limits, timeout and cost policy were unspecified.** Decision: apply the accepted bounds and 60-second deadline, apply existing per-action daily/token caps, and show unknown cost honestly. Reject oversized context rather than silently excluding selected evidence.
9. **Restart and uncertain provider completion need an explicit rule.** Decision: interrupted requests require a new operator-triggered attempt; explain that the prior provider call may have incurred cost. Local idempotency prevents repeat dispatch of the same admitted request, not a guarantee of exactly-once external billing.
10. **First-version UI ownership is implicit.** Decision: AI-DRAFT-001 includes its Maintenance UI and generated contracts using delivered UI-001 patterns. UI-003 adds the connected-agent execution path later; ASST-001, INGEST-002 and mailbox access are not blockers.
11. **“Malformed or invented response” cannot be mechanically guaranteed.** Decision: reject malformed schemas and invalid source references, use qualification examples to assess factuality, and retain mandatory operator review. Do not claim hallucination-free output.
12. **Portable retention and edit recovery are underspecified.** Decision: retain governed input, output, edits and decision lineage with existing AI Governance history and encrypted backup policy; keep canceled/failed metadata without raw provider diagnostics. Validate action schemas during restore and use existing OPS recovery only for unfinished operator edits, never as an execution queue.

## Ordered implementation slices

1. Select the hosted provider/model against the accepted scope, privacy destination, structured-output support, timeout/token controls, cost and factuality fixtures; record the choice and qualification criteria before adapter implementation. Define action schemas and enforce the accepted source scope and budgets. Selection does not authorize disclosure of real customer data or claim production readiness.
2. Build Maintenance-owned bounded context preview and complete revision manifest using source ports; validate privacy and query budget.
3. Register the action/redaction profile and one qualified adapter, including credentials, disclosure, token limits and availability checks.
4. Extend the shared governed run lifecycle with admission, lookup, cancellation, deadline and restart handling; implement idempotent API contracts and retained-schema validation.
5. Deliver contextual preview, pending/recovery, review/edit/copy and separate COM-001 handoff; regenerate API clients and register only qualified capabilities.
6. Verify the end-to-end real-provider path with synthetic property data, cancellation races, changed evidence, lost responses, rollback, restart and encrypted restore. Keep production availability disabled until this gate passes.

The validation matrix above remains mandatory. Add explicit tests for preview/destination drift, changed child-source revisions, concurrent starts at capacity, cancel-versus-success ordering, duplicate request lookup after restart, no automatic restore dispatch, keyboard/focus recovery and the twelve-SELECT preview ceiling. Quality fixtures should include hostile instructions in correspondence, missing appointment confirmation and uncertain responsibility; evaluate factuality and useful drafting without allowing any domain write or outbound send.
