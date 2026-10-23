# ASST-FILE-001 — Managed local file adapter trial

## Status and boundary

Proposed optional adapter design, October 20, 2026. The [agent triage design](agent-triage-design.md#3-the-proposed-local-file-adapter) and [Muse research](../research/META_MUSE_RESEARCH.md#proposed-file-exchange-adapter) motivate a file-capable assistant trial. This backlog owns only the transport and its workspace/backup lifecycle; [ASST-001](ASST-001_DESIGN.md) owns grants, requests, admission, results, receipts and audit. It is independent of the MCP protocol. Muse capabilities are unverified until an end-to-end qualification; no file-capable product is assumed to have a trustworthy schedule or writer identity.

## Managed exchange and access

EPM creates `integrations/assistant-exchange/<connection-id>/` inside the chosen workspace and binds it to one connection. The operator uses one EPM workspace and one EPM backup flow. The assistant may access **only** its connection subfolder, not the workspace root, sibling exchanges, SQLite, evidence files, backup archives or app-owned settings. No credential or bearer secret is put in exported JSON. A subfolder is not by itself a security boundary: verify the product's actual read/write confinement and writer attribution, including same-OS-user behavior, before automatic exchange can be enabled. If these properties cannot be demonstrated, use explicit manual handoff, not a supposedly connected file adapter.

Versioned scoped exports (`config/`, `context/`), EPM request projections (`requests/`), assistant completed submissions (`inbox/`), EPM receipt projections (`receipts/`), poll health (`health/`), and bounded processed/error/quarantine areas have distinct ownership. Optional `state/` contains only completed portable assistant checkpoints and pending-submission metadata that the product can actually export. EPM's database, not the folder, is authoritative for grants, accepted submissions, requests, outcomes and audit.

The assistant writes a temporary file and atomically renames it on the same filesystem, or uses another completion protocol proven to reject partial input. EPM accepts only bounded regular files with allowed names, no symlink/traversal escape, closed schemas and verified writer/grant. An OS watcher prompts scans; startup, resume and periodic reconciliation recover missed events. After a durable ASST-001 result commits, EPM moves or quarantines the submission and publishes a versioned receipt. A crash between commit and file projection repairs from the durable result without reapplying the action. A filename, mtime or claimed assistant name never authenticates a submission or fresh source coverage.

### Shared-contract handoff

Shared service/UI acceptance in ASST-001 uses non-production fixtures and does not require this adapter. This item's real connected follow-up qualification additionally requires AI-DRAFT-001. Verify interactive versus unattended processing and expose any required assistant-side action; file access alone proves neither scheduling nor trustworthy identity.

The adapter publishes only committed ASST-001 projections. Receipt repair must recheck current disclosure authorization; knowing an old key does not authorize a revoked writer to read historical context. Repeated publication preserves request identity/version, and file deletion is not cancellation. Preserve the distinction between immutable admission receipts and later decision receipts. A received advisory draft is not a sent message or official issue update.

The [ASST-001 proposed decisions](ASST-001_DESIGN.md#contradictions-and-missing-decisions) define the recommended deadline, pause/restart and grant-revision semantics; settle them before implementing this adapter. Its workspace archive extension preserves historical grant facts while excluding usable device/session authorization. This item still owns filesystem confinement, writer attribution, safe capture and quarantine; the shared boundary does not establish those properties on its behalf.

## One backup and careful restore

Extend LOCAL-002's encrypted, consistent archive to include completed unadmitted inbox files and validated portable `state/` snapshots for this managed exchange. Ignore temporary files and regenerate cached exports, receipt projections and heartbeats from durable EPM state. Capture only complete regular files within the assigned folder; verify size/digest and reject symlink escapes. A racing or inconsistent capture fails the backup without publishing it as complete. There is no separate operator backup for the bridge. External mailboxes, account credentials, cloud memory and checkpoints an assistant does not export remain outside EPM's archive.

Restore invalidates grants, quarantines pending unadmitted files and never admits them under a new grant automatically. After operator reauthorization, reconcile restored pending files and any portable checkpoint against EPM receipts and the source provider; regenerate exports/receipts. Mark intervals outside verified provider catch-up as unknown. A successful workspace restore does not promise exact continuation of the external assistant.

## Qualification and test matrix

Qualify a direct EPM-initiated work request first; scheduled source scanning is separate ASST-INTAKE-001 work. The setup test must distinguish app preflight, assistant permission, writer/isolation, request/submission and receipt stages. A synthetic round trip creates no official issue or Communication. Pack version and adapter capability mismatches disable only affected actions. Neither a test file nor a heartbeat proves subfolder confinement or full source coverage.

| Area | Cases |
| --- | --- |
| Happy paths | Scoped exchange setup, synthetic request/result/receipt, optional later source submission, one EPM backup and reviewed restore. |
| Invalid combinations | Broad workspace access, unverified same-user writer, symlink/traversal, partial/oversized/malformed file, paused or wrong grant, unsupported pack. |
| Idempotency/retry | Same-key/same-content receipt replay; changed-content conflict; watcher miss, failed move/receipt write and restart reconciliation. |
| Transaction rollback | No authoritative effect before durable ASST-001 commit; file cleanup never substitutes for database commit. |
| Persistence/schema | Closed manifests, bounded files and exact archived contents validated against connection identity. |
| Backup/restore | Concurrent file write, changed digest, pending-file quarantine, revoked grants, portable/hidden checkpoint differences, source catch-up gaps. |
| Query budget | Folder scan and receipt projection use bounded pages/counts; no per-file unbounded source hydration. |

## Included operator interface delivery

This UI is part of this functional backlog and its completion criteria. Reuse the delivered UI-001 shell, generated contracts, source-owned commands, Light/Dark themes, keyboard/focus behavior and recovery patterns. Validate real temporary-workspace reads/writes, stale revisions, lost responses, restart/restore and bounded queries; backend-only delivery is incomplete.

Deliver managed exchange-folder permission handoff, writer/isolation qualification, version checks, synthetic file/result/receipt diagnostics and Retry test within ASST-001 Settings. Explain missing folder access or failed isolation and provide the manual alternative. Restore shows Setup required and quarantined pending exchange state; a heartbeat is not proof of filesystem isolation.
