# ASST-INTAKE-001 — Qualified assistant source discovery

## Status and dependencies

Proposed feature design, October 20, 2026. [Agent triage research](../research/agent-triage-design.md#2-how-a-channel-message-reaches-the-record) defines the desired behavior. INGEST-001 retains original evidence; INGEST-002 owns the five operator decisions and atomic issue consequences; ASST-001 owns authenticated admission, grants, durable receipts and health. This feature qualifies discovery through **one** working transport, either MCP-001 or ASST-FILE-001. It does not require both and does not grant the assistant official issue-write or outbound-send authority.

## Channel discovery and evidence

The separately authorized assistant selects actual mailbox, label, SMS or transcript sources within its own account permissions. EPM holds no channel credentials or poller. Each enabled source reports the effective account/filter, acknowledged cadence, provider checkpoint range, last fully successful scan, scanned/submitted/excluded/retry counts, failed pages and unresolved intervals. Discovery paginates with overlap; every found message receives a disposition and the checkpoint does not advance past unresolved work. A sequence of submitted proposals alone cannot prove that no source message was missed.

For a candidate, submit the bounded original message or transcript, provider/account/message identity, occurrence time/zone, participants and relied-on attachments as source evidence **separate** from the typed proposal. Retain exact source revision, fingerprint and provenance before review. The assistant may suggest property/space/reporter/category/priority and an existing-issue candidate, but unresolved identity stays unresolved until the operator chooses. A source message can be dismissed, linked or used to create/update an issue only through INGEST-002; its five outcomes and one-live-proposal rule remain authoritative.

The closed submission envelope carries intent/action version, stable intent ID, connection-scoped idempotency key, verified transport-bound connection identity, source kind, provider/account/message identifiers, per-source proposal sequence, canonical payload fingerprint, evidence manifest, source revision/fingerprint and typed issue proposal with rationale, confidence and explicit unknowns. Its envelope display name is not authority. A Gmail ID, snippet or assistant summary is insufficient without the retained source content; absent relied-on attachments block a source-backed review. INGEST-002 and Maintenance determine final reporter, property/space, fixed issue category and priority policy. Provider categories and Finance categories are separate vocabularies.

ASST-001 returns an admission receipt first and a later operator/domain outcome receipt. Retry an unacknowledged submission with the same bytes, key, fingerprint and proposal sequence. Changed content under the same key conflicts. Cross-connection deduplication requires verified provider/account/message identity; uncertain duplicates remain hints. Source relabel/archive, if separately permitted, occurs only after the final outcome and never means EPM sent a message or completed a repair.

## Health, recovery and operator claim

Show contact, poll success, source coverage and pending review separately. A live heartbeat is not a successful source scan. A failed/partial source keeps a degraded state even when the connection is online. EPM can admit a written file promptly while open, but discovery depends on assistant schedule, device uptime, source access and provider retention. No email/SMS channel is an emergency-response guarantee. Urgent admitted suggestions may notify the operator; routine suggestions may digest. A quiet queue says nothing about unseen source gaps.

After sleep, outage or restore, the assistant resumes from a durable checkpoint with pagination and overlap; the app reconciles received submissions and receipts. A checkpoint exported through the file adapter is verified against provider and EPM history, never blindly trusted. Missing external assistant state, expired provider retention or failed pages produce visible unknown intervals. Manual intake and direct Maintenance entry remain available.

## Qualification and validation

Qualify each actual source/client/version/filter combination with a disposable account where practical. Verify scheduling rather than trusting requested cadence; prove folder or MCP identity and scope, complete evidence transfer, per-source catch-up, pause/revoke, and receipt recovery. Source coverage is not enabled merely because a synthetic proposal succeeded. UI-003 exposes connection setup and per-source health; UI-002 supplies the INGEST-002 review; DASH-003 may aggregate only qualified source attention.

| Area | Cases |
| --- | --- |
| Happy paths | Source page → exact evidence → proposal → operator create/link/update/dismiss/rework → final receipt, with manual fallback. |
| Invalid combinations | Wrong account/filter, missing attachment, ambiguous property/reporter, forged source identity, unregistered action, stale source, revoked grant or unsupported schedule. |
| Idempotency/retry | Exact/changed replay, same message across connections, missed admission/final receipt, failed page and overlap after outage. |
| Transaction rollback | Admission cannot leave a partial source/proposal/receipt; INGEST-002 terminal decision remains atomic with its owning domain. |
| Persistence/schema | Source identity, scan/disposition/checkpoint reports, proposal/evidence and audit remain consistent and bounded. |
| Backup/restore | EPM history survives, grants are invalidated, restored pending files are quarantined, external account/checkpoint gaps are disclosed. |
| Query budget | Review and health lists use bounded source-owned projections; no per-message evidence fetch in a collection read. |
