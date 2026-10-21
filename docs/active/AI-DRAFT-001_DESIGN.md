# AI-DRAFT-001 — Draft a maintenance follow-up

## Status and boundary

Proposed feature design, October 20, 2026. [Agent triage research](../research/agent-triage-design.md#5-assistance-on-existing-issues) motivates a useful first AI action that needs no connected assistant or mailbox permission. AI-GOV-001 provides generation, limits, disclosure, pause, provenance, review and original-result mechanics; Maintenance supplies issue facts; Communications records interactions but does not send. This item registers one production action and its operator workflow. It does not implement ASST-001, MCP, file exchange, intake review, or outbound delivery.

## Operator outcome

On an existing issue, **Draft follow-up** previews the bounded facts to be supplied and the configured on-device or hosted model destination. The operator starts a request, receives a draft or typed error, edits it in issue context, and sends it through their own channel. Recording a sent interaction is a separate COM-001 action. Generating or accepting a draft never changes the issue, sends a message, creates a Task, or establishes that a tenant or Provider replied.

The first implementation may qualify a hosted model; a local model is optional and needs its own runtime qualification. Neither an unavailable model nor a failed local call silently falls back to a cloud model. If no model/action is qualified, show the ordinary manual drafting path with a truthful unavailable state.

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
| Invalid combinations | No model, unsupported action, paused assistance, denied hosted disclosure, missing/stale issue, forbidden data class, malformed or invented response. |
| Idempotency/retry | Lost response, exact-key replay, changed-key payload, cancellation/timeout race and late result. |
| Transaction rollback | No partial official issue/Task/Communication effect when generation or draft persistence fails. |
| Persistence/schema | Closed action versions, governed input/output/edit lineage, provenance and audit survive restart and retained validation. |
| Backup/restore | Draft/review history survives; model credentials and running requests do not become usable after restore. |
| Query budget | One bounded source-owned issue/context read without per-journal-entry or per-Communication queries. |
