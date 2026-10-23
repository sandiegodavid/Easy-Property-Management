# ASST-FILE-001 — Managed local file adapter trial

## Status and delivery boundary

Proposed technical design, October 23, 2026. The [agent triage design](agent-triage-design.md) supplies the accepted direction: one managed exchange inside the workspace, operator review, one encrypted backup, and automatic exchange only after isolation and identity qualification. The recommendations under **Contradictions and missing decisions** remain proposed. This document does not claim a working Muse integration or change application code.

ASST-FILE-001 owns the file transport, its qualification and operator workflow, and its workspace/archive extensions. [ASST-001](ASST-001_DESIGN.md) owns connections, grants, requests, authenticated admission, immutable receipts and policy. AI Governance owns the draft and review. Files never authorize official writes, approvals, sending, or external account access. MCP is an alternative transport, not a dependency.

| Dependency | Required contribution |
| --- | --- |
| ASST-001 | Shared principal, grant/pause policy, bounded request/projection/admission ports, durable receipts, recovery and Settings shell. Its proposed policy decisions must be settled before implementation. |
| LOCAL-002 | Existing encrypted archive, validation, restore and workspace operation coordination. This feature extends those mechanisms; it does not reopen the completed backlog or create a separate backup product. |
| AI-DRAFT-001 | Registered follow-up action, bounded Maintenance context, shared draft editor and advisory approval for the first real connected trial. Non-production fixtures can test transport mechanics beforehand. |
| AUDIT-001, OPS-001, UI-001 | Existing audit, original-command recovery and browser foundations, reused through owning ports. |
| ASST-INTAKE-001 / INGEST-002 | Later source discovery, evidence attachments, checkpoints and issue review. Not prerequisites for the first request/result trial. |

Completion requires one qualified real assistant/client on a declared host configuration, an operator-started follow-up and receipt round trip, manual-only operation, and backup/restore acceptance. Muse remains the first candidate per accepted direction; its reported file capabilities are hypotheses to verify. If it fails confinement or attribution, record the trial result and leave the production capability disabled. A synthetic adapter or manual import does not count as qualified automatic exchange.

## Current implementation and required extensions

These are design-time observations of the current checkout, not test results.

| Evidence | Implication |
| --- | --- |
| [Workspace archive staging](../../application/apps/server/app/modules/workspace/application/archive_service.py) stages the manifest, consistent SQLite snapshot and managed files; `_create_runtime_directories` creates database/files/exports/backups. | Merely placing an exchange in the workspace does not include it in backup. Add an explicit managed-exchange inventory and restore validation. Never recursively copy arbitrary workspace directories. |
| [Archive validation](../../application/apps/server/app/modules/workspace/infrastructure/encrypted_archive.py) checks exact manifest inventory, hashes and current format/schema. | Extend the current greenfield package and retained validators together. No legacy migration/compatibility scope. |
| [Backup policy](../../application/apps/server/app/modules/workspace/application/backup_policy.py) uses workspace operation locks and private POSIX modes. | These protect EPM operations; they do not stop an external same-user process writing files or prove connection identity. |
| [Workspace runtime](../../application/apps/server/app/modules/workspace/application/runtime.py) holds one server writer lock and rotates a read epoch. | Run admission through the active server. A watcher/helper must not become a second SQLite writer. Fence queued work on workspace/runtime changes. |
| [AI registries](../../application/apps/server/app/modules/ai_governance/application/registry.py) and [ASST-001 implementation assessment](ASST-001_DESIGN.md#current-implementation-assessment) show the missing production action and assistant boundary. | Do not reuse model credential/probe operations for file submissions. Shared admission and the real action must exist before enabling the adapter. |
| [AI Settings](../../application/apps/web/src/workflows/ai-governance.tsx) implements the current model workflow. | Add file-specific setup/diagnostics inside ASST-001's Connected assistants UI; do not imply that a model connection grants filesystem access. |

Follow [Architecture](../ARCHITECTURE.md), [workspace ownership](../modules/workspace.md), [API contracts](../platform/api-contracts.md) and [frontend architecture](../ui/frontend-architecture.md). Current module guides describe shipped behavior; this active document owns the proposed extensions.

## Ownership, identity and permissions

Implement the adapter beneath the proposed `assistants` infrastructure, composed by bootstrap. Its worker performs bounded file I/O outside database transactions, then calls the shared application port. Workspace owns archive publication and restore; a narrow exchange snapshot/validation port supplies capture facts. No cross-module ORM access or separate daemon writing canonical data.

A connection's identity must come from a qualified sandbox/OS execution boundary, not JSON, a path, mtime, file owner alone, or a secret exported in the folder. Setup must prove both: the assistant cannot escape its assigned folder, and an unrelated process/connection cannot submit as that assistant. Ordinary same-OS-user directory permissions do not establish either property. Prefer a product-enforced sandbox or dedicated restricted identity with verified read/write capabilities; evaluate the actual mechanism before choosing platform APIs. A dedicated identity also needs narrow traversal/access configuration without exposing the workspace root or weakening the existing private workspace policy. If the product cannot provide this, stop automatic qualification. Do not build an OS sandbox product as an implicit expansion of this trial.

EPM remains the sole writer of request/configuration/receipt projections. The assistant can read those and write only designated inbox/health/state completion areas. EPM-private staging, archived pending content and quarantine are not assistant-readable. All paths derive from application-generated connection/generation IDs. Never accept operator-supplied arbitrary exchange paths or source paths in a submission.

Live exchange requires a qualified local filesystem; cloud-synchronized folders, network shares and remote object stores are unsupported. Qualify atomic rename, permission behavior, safe descriptor-relative access and power-loss behavior on the actual host. File-access support alone proves neither unattended execution nor reliable scheduling.

## Folder and contract pack

The logical layout is `integrations/assistant-exchange/<connection-id>/`. One operator workspace remains the unit of setup and backup. Actual access controls must enforce the following ownership; naming alone does not.

| Area | Owner and purpose |
| --- | --- |
| `config/` | EPM-written non-secret contract/capability and exact permitted export manifests. Never a copy of app settings. |
| `context/` | EPM-written task-specific governed context, request-bound source revisions and expiry. No standing full portfolio export for the first trial. |
| `requests/` | EPM-written immutable request versions and cancellation/expiry tombstones. |
| `inbox/` | Assistant publishes completed result envelopes; temporary files are ignored. No receipt files here. |
| `receipts/` | EPM-written immutable admission and subsequent decision receipt versions, independently identifiable. |
| `health/` | Completed bounded reports, treated as claims until validated through the qualified identity boundary. Contact is not source coverage. |
| `state/` | Optional validated portable checkpoints only when a later source adapter defines their schema. Disabled in the initial follow-up trial. |
| EPM-private capture/quarantine | Immutable captured submissions and safe diagnostic metadata, outside assistant access. Not a new official evidence store. |

`receipts/` is the proposed current name replacing the illustrative `acks/` in triage; do not implement both formats. IDs use a restricted application-generated alphabet; never use raw idempotency keys as filenames. Each complete document names a closed contract version, workspace/connection, authorization generation, document kind/ID/version and relevant request ID/version. A result also carries the shared idempotency key, action/version and typed output or failure. Authorize envelope identity against the transport principal, never from the envelope itself. Reject duplicate JSON keys, unsupported fields/versions, invalid encoding and excessive nesting before application admission. Fingerprints use ASST-001 canonicalization; retain a separate byte digest for capture integrity.

Ship the versioned contract pack in the release package: exact closed schemas, bounded publication/read rules, receipt and retry semantics, action runbook, cancellation instructions and synthetic conformance fixtures. Package digests establish integrity, not assistant identity. EPM checks the actual client/adapter/pack combination and host permissions; unsupported changes require retest. Instructions carried in source content never alter grants or pack policy.

## Publication, capture and admission

1. **Create and disclose.** ASST-001 validates the operator preview and commits the request. Before publication, recheck current authorization, source manifest and runtime. Commit a fail-closed disclosure audit and projection intent before bytes become assistant-readable. Record available/published separately from assistant acknowledgment; file appearance does not prove consumption.
2. **Publish safely.** Write a complete private temporary projection, flush as required by the qualified filesystem, then publish its immutable generation/version atomically. Serialize publication with pause/revoke and workspace lifecycle operations through a bounded per-connection fence. Do no filesystem I/O inside the database writer transaction. Recheck the fence immediately before publishing; if invalid, do not publish. Crash recovery treats an uncertain publication as possible disclosure, not as never exported.
3. **Complete a result.** The assistant writes temporary bytes, closes them and renames on the same filesystem into the completed namespace. Its pack requires completed files to be immutable until EPM acknowledges. This protocol still requires defensive capture; two equal size/mtime readings are not proof of completion.
4. **Capture once.** The worker uses pinned directory/file handles with no-follow checks, rejects symlinks, hard links, devices/FIFOs and traversal, enforces size before reading, and copies exact bytes into EPM-private immutable staging. Check descriptor identity and metadata before/after, plus digest; reject a changing input. Admission uses this captured copy, never reopens the attacker-controlled pathname. If the host cannot implement the required checks, qualification fails.
5. **Admit atomically.** Authenticate the captured submission's qualified writer/generation and call ASST-001. Revalidate current grant, pause, request deadline/version, action and source manifest. Request transition, governed external run/draft, immutable admission receipt and audit commit together. No file move or receipt write substitutes for this transaction.
6. **Project and clean up.** Publish the authorized committed receipt after commit, then remove the acknowledged exchange input safely by captured identity. A failed cleanup/projection is retried from the database result. Never overwrite a changed file at the same name. The shared decision port later creates the separate final receipt; advisory approval means “Draft accepted,” not sent or officially recorded as a Communication.

Same-key/same-content replay returns the authorized existing receipt; changed content conflicts, and a new key cannot create a second terminal result for one request. Authenticate before replay. Unexpected DB/audit failure leaves no accepted receipt and retains captured input for retry. Deterministic invalid input yields safe diagnostic metadata; do not echo sensitive payloads or reveal another connection's record existence. Transport receipts use stable problem codes and retryability; operator HTTP endpoints use shared 413/422/409/503 mappings as appropriate. Files themselves have no HTTP status.

Use an OS watcher only as a wake-up hint. A server-owned bounded reconciliation worker also runs at startup, resume and every 30 seconds while enabled. Process at most 50 entries or two seconds per batch, round-robin across connections, with a resumable bounded directory traversal so early invalid names cannot starve later files. Scan after an overflow event; do not enqueue one unbounded job per watcher notification. Stop promptly on runtime fencing. When EPM is closed/asleep, files may wait but are not admitted; show this limitation.

Proposed initial budgets: shared 64 KiB envelope ceiling, AI-DRAFT's stricter 8 KiB output/32 KiB context bounds, 100 completed pending inputs and 16 MiB exchange data per connection, and 128 MiB workspace exchange ceiling. Reserve headroom for receipts/control tombstones. Enforce an actual sandbox storage quota if supported; scanner limits alone cannot stop an external writer filling the disk. At exhaustion, disable new exports/admission, preserve authoritative history and valid pending material, and show repair guidance. Never silently delete unadmitted valid input. Reject malformed raw content without keeping its bytes indefinitely; keep sanitized diagnostics under ASST-001's proposed 30-day policy. Cleanup of accepted projections must retain durable replay facts and respect current receipt access.

## Pause, restart and restore

Pause/revoke/grant replacement blocks new disclosure/admission immediately and invalidates outstanding work according to ASST-001. Revoke transport permissions where supported, remove readable context/request projections, and publish only authorized non-sensitive terminal state. Removal failure marks cleanup incomplete and requires repair. Files already read/copied cannot be retracted, and EPM cannot stop independently authorized external activity. Unlike live reads, authorization cannot be checked again whenever an assistant opens already-published bytes; this exposure is a qualification/disclosure consideration.

Ordinary restart establishes a fresh authenticated transport session, fences old work and marks unresolved requests interrupted under the proposed ASST-001 policy. Reconciliation may repair authorized receipts for committed outcomes; it never republishes an interrupted request as new work. Old-generation pending results remain inspectable by the operator but cannot become a new draft by resuming the connection.

Restore preserves historical grants/receipts, but no usable session, sandbox authorization or credential. Restore into the existing new/empty destination workflow with connection Setup required, captured pending files quarantined and all publication disabled. Reauthorization creates a fresh generation; old requests are not reactivated. An operator may inspect recovered material, then start a new scoped request or use existing manual entry with its own review. Do not add a “trust and admit quarantine” button. Later source recovery must reconcile provider checkpoints and EPM receipts under ASST-INTAKE-001; unknown intervals stay unknown.

## One consistent encrypted backup

Extend LOCAL-002's current manifest and validators with an explicit exchange capture inventory: connection, original generation, document kind, capture ID, byte count/digest and whether the matching submission was admitted in the database snapshot. Capture only complete bounded pending inputs and explicitly validated portable state. Exclude temporary/partial files, malformed raw payloads, live permissions/secrets, cached config/context/requests/receipts, and heartbeat projections. Business receipts and admitted drafts already reside in SQLite. A sanitized diagnostic history can remain in its owning records.

A filesystem walk plus SQLite backup is not an atomic cross-resource snapshot. Use a coordinated capture barrier:

1. Pause EPM exchange admission/cleanup/publication through the existing workspace-operation lifecycle; drain in-flight admission. Do not claim the EPM lock pauses the assistant.
2. Establish a bounded input cutoff inventory and capture immutable eligible files privately using the safe-read rules. Preserve the inventory until archive completion. Newly completed files after the cutoff belong to the next backup; report the cutoff, not “all files at archive completion.” A disappearing/changing selected file fails this attempt.
3. Freeze validated capture metadata and take the consistent SQLite snapshot while EPM admission remains fenced. Reconcile captures against that snapshot's durable receipts, so an accepted record is not mistaken for unadmitted work. Include the frozen portable checkpoint, if enabled, only with its exact referenced captured/committed submission identities.
4. Release the short capture barrier after immutable staging and database snapshot are complete. Encryption and final validation/publication use only staged content. Verify exact inventory and hashes; on inconsistency or missing selected content, fail the backup without publishing a complete archive. Preserve the previous good backup and show the specific failure.

No external quiescence promise is needed for files arriving after the cutoff; immutable completed-file behavior and safe capture remain qualification requirements. Apply a bounded capture deadline (proposed 30 seconds); retry is explicit/bounded, never an endless backup stall. CLI/manual and scheduled backups must use the same capture coordination, including when the server is not running. Restore validates all references and bytes before accepting the package and puts unadmitted captures into EPM-private quarantine. The user configures one EPM backup, not a second bridge job. External mailboxes, cloud memory, hidden checkpoints and account permissions remain outside that backup.

## Operator workflow and API integration

Include this UI in ASST-FILE-001; reuse ASST-001 Settings and generated contracts, existing summary-bar expand/collapse, Light/Dark themes and keyboard/focus behavior. No new permanent destination or second review queue.

Setup follows **Choose assistant/job → EPM preflight → exact folder permission step → isolation/identity qualification → synthetic round trip → enable qualified capability**. Show only the managed connection folder for permission handoff, never suggest granting the workspace root. A browser cannot change native assistant permissions; provide verified product instructions. No raw JSON editing is required. Advanced diagnostics may expose safe paths/versions, not context or secrets.

Add typed adapter detail/preflight/start-test/cancel-test/test-status and quarantine-summary reads beneath ASST-001's connection API. Tests are asynchronous durable operations with original-key lookup, bounded deadlines and cancel/retry behavior. A synthetic round trip produces no business draft or official record; real qualification uses the actual AI-DRAFT action and disposable data. Separate identity/confinement proof from round-trip proof. Invalid grants, unsupported host/client and unknown test outcomes cannot be bypassed by Enable.

Detail shows verified client/pack/mode, access status, last authenticated contact, pending count, oldest receipt delay, last reconciliation, capacity and backup capture status. It distinguishes offline/asleep, failed isolation, malformed input, unsupported version, storage full, paused/expired, cleanup incomplete and restored Setup required. Zero pending is not “source fully checked.” Poll only visible active tests using the shared backoff/runtime-fencing pattern. Query failure retains a stale/unavailable state, not a successful empty view.

Offer specific Retry test, Review permission instructions, Retry receipt repair and existing manual-work routes. Receipt repair reauthorizes but does not redispatch. Quarantine shows sanitized reason/time/ID and a safe inspect/rework route; untrusted content is never rendered as HTML or promoted by one click. Uncertain operator-command outcomes reconcile by original key and preserve selections/edits. Restore guidance explains which pending work was recovered and why it needs a new request or later source reconciliation. Avoid implying that one EPM setup can waive a third-party product's own permission dialog.

## Contradictions and missing decisions

These recommendations are reflected above but require confirmation before implementation. Shared ASST-001 recommendations remain separately proposed.

1. **Identity and confinement mechanism is unverified.** Ordinary same-user files cannot prove the claimed writer or limit root access. Recommend a time-boxed Muse qualification spike against an actual sandbox/identity boundary before building the automatic adapter. Fail closed to existing manual handoff; no fabricated connected identity.
2. **Supported host configuration is unspecified.** Recommend one qualified macOS/local-filesystem configuration for the initial Muse trial; keep contracts neutral but do not promise Windows/Linux, cloud folders or arbitrary assistants. Record the exact tested client/OS versions.
3. **First capability versus source discovery is ambiguous.** Recommend bounded EPM-initiated follow-up first, with AI-DRAFT-001 required for real acceptance. Defer source attachments/checkpoints and scanning to ASST-INTAKE-001; reserve their contract kinds without enabling them.
4. **`acks/` versus `receipts/`, and “optional later” requests conflict across documents.** Recommend the single current `receipts/` format and first-class requests for this trial; triage filenames are illustrative until this decision is accepted. No dual-format compatibility.
5. **Publication cannot retract disclosure.** Recommend audit-before-publication, serialized publication/revocation, minimized request-specific exports, cleanup diagnostics and explicit “already disclosed data cannot be recalled.” Do not claim live authorization on every file read.
6. **Watcher completion and immutable input need a concrete guarantee.** Recommend temp-close-rename plus safe descriptor capture and completed-file immutability. No mtime-based completion or generic path-read fallback. Reject unsupported filesystem semantics.
7. **Backup locks do not freeze external writers.** Recommend the cutoff/capture barrier above, exact hash inventory and fail-on-selected-file-race. Include later arrivals next time; retain one EPM backup flow without promising an impossible simultaneous snapshot of an uncontrolled external process.
8. **Restored pending work could regain authority.** Recommend private quarantine, fresh generation and explicit new request/manual review; no automatic replay under a replacement grant. Preserve historical authorization facts, not usable access.
9. **Limits and disk-pressure behavior are missing.** Recommend the stated envelope/count/byte/batch limits, 30-second reconciliation/capture bounds and actual quota qualification. Pending valid data is not silently discarded. Shared lifetime limits and diagnostic retention follow ASST-001 once accepted.
10. **Attachment transport and portable state lack schemas.** Recommend no attachment-bearing source envelope or opaque checkpoint blob in this trial. ASST-INTAKE-001 must define bounded manifest/blob transfer and validated state with FILE/Intake policy before enabling those kinds; never stuff evidence into the 64 KiB control envelope or accept arbitrary source paths.
11. **Manual fallback is not specified as a trusted import.** Recommend existing operator entry and explicitly reviewed copy/paste only. Do not add a general JSON importer, authenticate it as Muse, or broaden DATA backlog scope. A future richer manual import needs its own contract.
12. **What counts as completion needs a failure outcome.** Recommend separately recording technical conformance, real assistant qualification and operator acceptance. If the candidate fails identity/isolation, document the blocked production capability and trial findings; do not mark automatic delivery complete because synthetic tests pass. Shared/other transport work can proceed independently.

## Ordered implementation slices

Resolve the decisions above first. Each slice includes its required UI and focused validation; no application code is supplied by this document.

1. **Qualify feasibility.** Test the actual candidate's confined read/write boundary, writer attribution, atomic completion and interactive mode on disposable data; document exact product permission steps and go/no-go evidence. Unattended scheduling is a separate claim.
2. **Define the current contract pack.** Closed document schemas, path/ownership rules, identity binding, limits, immutable versions and fixtures; agree ASST-001 ports and Workspace capture/restore integration. No synthetic production option.
3. **Provision and manage setup.** Safe managed path lifecycle, host preflight, generation/permissions, Settings handoff, asynchronous tests and original-result recovery. Verify failed isolation cannot enable automatic mode.
4. **Publish and capture.** Request-specific disclosure, fenced publication, safe input capture, bounded watcher/reconciliation and storage-pressure UI. Verify pause/restart/cancel races and responsiveness.
5. **Admit and repair.** Shared atomic result admission, immutable admission/decision receipts, cleanup/replay, quarantine diagnostics and AI-DRAFT editor handoff. Exercise crashes at every commit/projection boundary.
6. **Package and recover workspace.** Current archive inventory/retained validators, cutoff capture, portable quarantine and Setup required restore; test manual/CLI/scheduled backup paths and server-off capture. Add user guidance within existing Data & Backup.
7. **Real-client acceptance and documentation.** Packaged installation and synthetic workspace trial with actual follow-up, manual-only fallback, changed version/permission retest, UI and query budgets. Record limitations; update current module/manual guides only for delivered behavior.

## Validation matrix

| Area | Required cases |
| --- | --- |
| Happy paths | Setup and isolated round trip, real follow-up → advisory draft → operator decision → receipt, usable manual alternative, one encrypted backup and restore. |
| Invalid combinations | Forged/wrong-generation identity, broad/root or sibling access, modified EPM projections, unsupported client/schema, malformed/deep/duplicate-key JSON, oversized input, nonregular/hard-linked/symlinked files and path replacement races. |
| Idempotency/retry | Identical/changed key, another key for terminal request, missed watcher event, receipt loss, commit-before-crash, cleanup failure and duplicate events; assert one authoritative result and no repeat quota charge. |
| Transaction rollback | Fail audit, draft or receipt commit; no partial admission. Fail publication after disclosure audit; retain honest possible-disclosure state. Cancel/pause/source edit competing with result or export. |
| Persistence/schema | Validate current archive and relational linkage, generation/request/receipt versions, captured digest/size and quarantine identity. No bearer secrets or raw payloads in logs/recovery. |
| Backup/restore | Input changes/disappears at cutoff, new arrival after cutoff, snapshot/capture mismatch, orphan checkpoint, interrupted encryption, restored old-generation files, no server running, concurrent scheduled/manual backup. Previous valid archive remains usable. |
| Budget and reliability | Fifty-entry/two-second batches, fairness under malformed-file flood, quota/disk exhaustion and bounded diagnostic throttling. Target at most eight SELECTs per diagnostics page (25 default/100 max) and one batched receipt lookup per scan batch; no per-file source hydration. Publication rechecks must remain authoritative. |
| UI | Keyboard/narrow layout/themes, exact permission instructions, setup cancel/retry/lost response, capacity/cleanup failure, restore quarantine, stale health, manual-only and dirty-editor preservation. Tests against temporary-workspace persistence. |
| Qualification | Independently prove confinement, attribution, request/result/receipt behavior and any unattended claim. A test file or heartbeat proves neither isolation nor full source coverage. |

No implementation tests were run for this documentation-only design.
