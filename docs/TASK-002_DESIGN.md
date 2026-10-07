# TASK-002 — Waiting and Follow-up Design

## Status

All 13 recommendations were accepted on October 7, 2026. The resolved decisions below govern implementation. Backend implementation and focused acceptance coverage are recorded in [TASK-002_TEST_MATRIX.md](TASK-002_TEST_MATRIX.md); browser integration remains UI-001 work. The implementation-baseline observations below are historical, not the current capability state.

## Purpose

`TASK-002` adds explicit waiting context and a follow-up date to an existing TASK-001 task without changing the task's own due date, priority, lifecycle, or reminder history. It is the shared follow-up primitive for legal matters, HOA notices and shared repairs, owner concerns, and other source-owned work.

## Scope and boundaries

- A task remains the authoritative record for its status, deadline, priority, completion, and reminders.
- A follow-up describes when the operator should revisit work that is waiting on a person or event. It never rewrites a source record's deadline or resolves the source record.
- TASK-002 does not create external reminders, send communications, infer that a response is required, or alter source-domain urgency.
- The owning source remains responsible for any domain-specific waiting state. TASK-002 provides a typed, reusable linked task and presentation facts for DASH-001 and UI-001.

## Data contract

Extend `tasks` with these fields. All waiting/follow-up fields are nullable; `revision` is required:

| Field | Rule |
| --- | --- |
| `revision` | Positive integer, initially 1; advances once per actual task mutation. |
| `waiting_for_kind` | `person`, `organization`, `event`, or `other`; required when waiting context exists. |
| `waiting_for_label` | Required, trimmed 1–255 characters when waiting context exists; a durable human-readable description. |
| `follow_up_at_utc` | Optional aware instant, explicitly entered in the past, present, or future and normalized to UTC. It is independent of `due_at_utc`. |
| `follow_up_timezone` | Required with `follow_up_at_utc`; valid IANA zone used for presentation. |
| `waiting_set_at_utc` | Required when waiting context exists. |
| `waiting_cleared_at_utc` | Latest clear instant, whether operator-requested or recorded as a consequence of completion/cancellation; cleared when a new episode begins. |

An active task may be waiting with no scheduled follow-up. That is valid, but must render as **Follow-up not scheduled**. Completed and cancelled tasks cannot acquire or retain active waiting context; completion/cancellation clears it atomically through an audit-visible transition. Reopening preserves the cleared state; transitions between active statuses preserve waiting.

Use a database check for paired fields and a service-level invariant that `follow_up_at_utc` is not accepted without active waiting context. Add an index over active status and `follow_up_at_utc` for bounded resurfacing reads.

## Commands

`POST /api/tasks/{taskId}/waiting` accepts a strict request with `waitingForKind`, `waitingForLabel`, optional paired `followUpAt`/`followUpTimezone`. It replaces the complete waiting context; omitted date fields mean unscheduled. It requires an active task, updates the waiting fields atomically, and writes `task_waiting_set` to AUDIT-001.

`POST /api/tasks/{taskId}/waiting/clear` requires `confirmed: true`, clears active waiting/follow-up fields, and writes `task_waiting_cleared`. It does not complete the task or mutate any linked source record.

`POST /api/tasks/{taskId}/waiting/follow-up` updates only the paired follow-up date/time of an already waiting active task and writes `task_follow_up_rescheduled`; mutually exclusive `clearFollowUp: true` removes the date while retaining waiting and records a distinct removal reason. A new follow-up must be explicit; dismissing a TASK-001 reminder is never treated as rescheduling it.

The three waiting mutations require `expectedRevision` and a UUID idempotency key, use the workspace writer boundary and strict `extra="forbid"` requests, and return typed conflict/not-found responses. Task-owned operation results implement replay before revision checks; no existing Task idempotency capability is assumed.

## Read contract

Expose these additional facts in task detail, list items, and TASK-001 summary source records:

- `isWaiting`, `waitingFor`, `followUpAt`, `followUpTimezone`, `followUpState` (`scheduled`, `due`, `overdue`, `unscheduled`), `followUpDueToday`, `followUpActionable`, `taskDeadlineState`, and `revision`. Non-waiting/terminal records have null follow-up state and false actionable.
- A captured `asOf` instant determines all classifications. `followUpState` is never inferred from browser time.
- A task with an overdue Task due date remains overdue even if its follow-up is later. An urgent Task remains urgent while waiting. Authoritative source deadlines/urgency are composed separately through owning-source facts, not inferred by Tasks.

TASK-002 provides a bounded `GET /api/tasks/follow-ups` source read for DASH-001: active waiting tasks ordered by overdue, due, future today, unscheduled, then other future, with timestamp ascending where present and stable Task ID. It defaults to 50/max 100 rows and includes a complete filtered total, bound cursor, `asOf`, `evaluatedAt`, and Task identity. Follow-up actionability begins at its exact instant, not the start of its calendar day. It does not combine this result with unrelated task buckets.

## Operator behavior

UI-001 renders waiting context on the source task and in contextual record views. A waiting row identifies whom/what is awaited, the follow-up state, original deadline when present, and a clearly separate action to schedule or reschedule follow-up. It never presents a deferred reminder as resolved work.

DASH-001 may show the task in Waiting until the scheduled follow-up becomes due, then surface it in Needs action with the reason **Follow up with [label]**. Task urgency/overdue facts and separately available authoritative source urgency/deadlines govern placement and wording. A future follow-up today remains scheduled until its timestamp; undated waiting remains visible as Follow-up not scheduled.

## Resolved design decisions

### 1. Durable waiting-operation results

Introduce Task-owned immutable operation results for the three waiting commands. Require a UUID idempotency key; fingerprint action, task ID, normalized payload, and expected revision. In one immediate transaction, check replay before current-state/revision checks, then commit waiting change, task revision, audit, and receipt. Identical replay returns the original result; key/payload mismatch returns 409. Define receipt lookup/replay in OpenAPI. Retain results for at least 30 days and longer while an unresolved recovery attempt references them; after result expiry, retain a compact key/fingerprint tombstone and return an explicit expired-operation conflict rather than silently treating replay as a new write. Keep one correlation ID across required events. Source-owned coordinated task creation retains its existing source operation key; do not duplicate that authority.

### 2. Task revision and concurrent changes

Add an integer Task revision, initially 1, returned in all task projections and required as `expectedRevision` on new waiting commands. Every actual task mutation, including existing lifecycle transitions and automatic clearing, advances it once per operation. Validate under the writer transaction. Readiness and terminal-state checks apply to direct application calls as well as HTTP. Stale revision returns typed 409 with current revision. Update existing Task creation/mapping/transition adapters only as needed to preserve this invariant; existing commands' broader retry/confirmation gaps remain TASK-001 work.

### 3. Set, replace, reschedule, and clear semantics

Set creates/replaces the complete waiting context, including optional paired date/timezone; omitted date fields mean unscheduled. Reschedule accepts a required paired timestamp/timezone or an explicit `clearFollowUp: true`, mutually exclusive. Removing a date keeps waiting active and emits a distinct audit reason. Clear waiting requires strict `confirmed: true` and clears all active waiting/date fields. Reject unrecognized fields and ambiguous combinations. A semantically identical new command may return unchanged state without advancing revision or duplicating a change event, but still retain its operation result.

### 4. Explicit timed follow-ups

Accept explicitly entered past, present, or future aware instants, with the response showing immediately overdue work where applicable. Do not advance dates automatically. This supports recording an existing commitment and avoids clock-dependent rejection. Require an offset-bearing ISO instant and valid paired IANA presentation zone; normalize storage to UTC and use one injected clock. Reject naive timestamps and date-only input. The operator may choose a zone independently of the task due zone; source workflows can prefill the property's zone. All-day/date-only follow-ups remain outside this slice unless a separate calendar-date contract is designed.

### 5. Follow-up classification and ordering

For active waiting tasks, `followUpState` is `unscheduled` without a date, `scheduled` when timestamp is later than `asOf`, `due` at equality, and `overdue` when earlier. Add `followUpDueToday` in the stored follow-up zone and `followUpActionable = followUpAt <= asOf`; future today is still scheduled. Non-waiting/terminal records return null state and false actionable. Order the complete waiting collection by overdue, due, future today, unscheduled, then other future, with timestamp ascending where present and stable Task ID. Expose priority and task deadline independently so consumers can preserve urgency. DASH owns Home placement; the Tasks read does not hide an urgent/overdue task because it is awaiting someone.

### 6. Task deadline and source authority

Expose `taskDeadlineState` derived only from Task's stored due instant/all-day zone under TASK-001 rules, with `none`, `overdue`, `today`, `upcoming`, and `inactive` values. Preserve the original due fields and Task priority. Owning source projections supply authoritative source urgency/deadline facts separately through their own protocols; OPS/DASH composes them using the explicit relation. Do not add source-module dependencies to Tasks or label a task date as a verified source deadline. Where no source fact is available, show only the known Task deadline.

### 7. Waiting episodes and retained history

Current Task fields describe only the active/latest episode. On first set or replacement, populate the episode's set instant and clear the current cleared instant; rescheduling retains that set instant. Clear removes the active kind/label/date/zone/set fields and records the latest clear instant. Keep every prior set/replacement/reschedule/date-removal/clear in append-only audit history, with old/new bounded values and explicit reason; receipt replays add no history. Provide a bounded filtered history path through existing Audit contracts rather than duplicating source communication history in a new waiting ledger.

### 8. Atomic lifecycle clearing

Completed/cancelled tasks have no active waiting fields. Clear any waiting episode atomically with terminal transition, preserving a cleared timestamp and audit reason `task_completed` or `task_cancelled`; all task, waiting, reminder, and operation events share correlation. Reopening never resurrects waiting or dismissed reminders. Active `open`/`in_progress` transitions preserve waiting. Make the schema and retained validators reflect these rules. Automatic clearing is an explicitly recorded consequence of the lifecycle command, not a separate operator click.

### 9. Waiting labels and independent reminders

V1 stores a required bounded label and kind only; no Party foreign key or guessed entity relationship. It supports an HOA/external party without making them a provider. Editing a source Party does not rewrite historical waiting labels. Follow-up dates are their own resurfacing facts and never create, reschedule, acknowledge, or dismiss TaskReminder rows. Waiting clear/date removal leaves reminders unchanged; terminal-task dismissal remains TASK-001 behavior. Dashboard may group explicitly linked duplicate presentations but preserves independent TaskReminder identities and deadlines.

### 10. Bounded follow-up paging and freshness

The new endpoint defaults to 50/max 100 rows, active waiting only, with validated state/actionable/priority and paired related-entity filters. Count, classification, sort, and slice are set-based under one deferred snapshot and captured UTC instant; no per-row source reads. Bind opaque cursors to endpoint/version, workspace ID/runtime epoch, normalized filters, read marker, captured instant, and last sort tuple/ID. Use a maximum 15-minute continuation lifetime consistent with OPS. Return 409 after source change/expiry; echo filters for restart. Freeze classification at cursor `asOf` across pages, return `evaluatedAt` separately for freshness, and require a fresh first page for live Home refresh. Exact totals and items share the same frozen classification. Endpoint budget: at most four SELECTs including the marker/count/page and any shared bounded metadata, independent of matching rows.

### 11. Typed projections and transaction-aware reads

Add consumer-neutral transaction-aware waiting/task fact reads accepting caller connection, captured instant, bounded parent IDs, and per-parent preview limit/counts. Source-owned Task adapters compute Task classifications; OPS uses them within its accepted one-snapshot contract. Add typed response models/stable operation IDs and waiting/revision fields to relevant projections; return `asOf` with derived states. Preserve TASK-001's four buckets/totals and its overdue/all-day rules rather than subtracting waiting tasks. Register literal `/follow-ups` before `/{task_id}`. Do not copy full task notes into search/overview previews. Use `platform/api_errors.py`: 413 content bounds, 422 malformed input, 404 missing task, 409 revision/lifecycle/key conflicts, 503 unavailable/busy, safe 500 integrity failure. Current router maps some Task validation to 400; new contracts must not assume it already supplies 422 globally.

### 12. Latest schema, retained integrity, and portability

Extend the latest baseline, ORM, Task value object, every factory/serializer/transition, unit-of-work and cross-module creation adapters, expected-table registry, exact schema checks, and retained-data/audit/receipt validation together. Enforce positive revision, paired kind/label/set fields, bounded trimmed label, paired date/zone, date requiring waiting, and no active waiting on terminal tasks. Validate canonical aware UTC timestamps and IANA zones on retained data as well as admission; a formerly future follow-up is not invalid on restore. Index actual status/waiting/time/relation filters and verify plans. Encrypted backup/export/restore includes waiting state, prior audit episodes, and receipts. Restore changes runtime epoch, not task dates or waiting state. No migration compatibility or legacy-format work.

### 13. Validation and delivery gates

Retain the existing summary implementation and run its focused boundary tests while extending waiting/revision facts. Complete the validation matrix below before marking the backend ready. TASK-001 summary documentation is reconciled with the inspected implementation; do not treat unrelated edit/delete or reminder-status gaps as silently solved by TASK-002. OPS/DASH consumers may use the new capability only once its typed ports and snapshot/freshness contracts exist. React remains UI-001 work.

## Required design validation matrix

| Area | Required scenarios and outcomes |
| --- | --- |
| Happy paths | Set/replace waiting, scheduled/unscheduled states, reschedule, remove only date, clear, source-linked and standalone tasks; preserve task due date/priority and independent reminders |
| Invalid combinations | Unknown kind, blank/oversized label, naive/date-only timestamps, invalid zone, unmatched date/zone, unknown fields, reschedule without waiting, terminal waiting, conflicting clear/date fields; typed 413/422/404/409 |
| Idempotency/retry | Lost-response replay returns original result/audit once; changed key payload 409; past date stays valid on replay; receipt retention never permits a silent duplicate |
| Concurrency/rollback | Two screens share revision: second fails; complete versus reschedule race remains consistent; failed audit/receipt rolls back every field/revision/reminder consequence |
| Lifecycle/history | Repeated episodes/reschedules remain visible; start preserves waiting; complete/cancel clears atomically; reopen restores neither waiting nor dismissed reminders |
| Time boundaries | Exact instant, earlier/future today, local midnight, DST offsets, independently selected zones, all-day Task deadline versus timed follow-up, retained past date |
| Persistence/schema | Latest baseline and every cross-domain Task factory produce valid revisions/empty waiting state; malformed retained waiting pairs/status/timestamps/receipts fail validation |
| Backup/restore | Waiting history/receipts survive encrypted archive; runtime epoch invalidates cursors; overdue follow-ups remain overdue without silent rescheduling |
| Query budgets | Complete filtered totals and bounded page under four SELECTs; parent previews cap children with full counts; no candidate scanning for exact-total endpoint or per-row reads |
| Composition/regression | One caller-owned snapshot/instant across OPS sources; waiting tasks remain in TASK-001 obligation buckets; source urgency is not inferred from Task priority; reminders and waiting resurface independently |

## Baseline review validation

Focused existing summary tests: `pytest apps/server/app/modules/tasks/tests/test_tasks.py -q -k summary` — 3 passed, 12 deselected. This confirms the current summary baseline only; no TASK-002 implementation tests exist yet. No full suite or application code changes were performed.

## Implementation baseline and dependencies

Inspected October 7, 2026 at `5ca7672`. These are implementation observations, not completed TASK-002 capabilities.

- Waiting/follow-up fields do not exist in `application/apps/server/app/modules/tasks/domain/models.py:11`, the Task API response at `api/router.py:138`, or the current Task schema. TASK-002 is not implemented.
- The existing Task service has no task revision, operation-key parameter, or durable task-operation receipt (`application/apps/server/app/modules/tasks/application/service.py:102–295`). Its unit of work already supplies an immediate write transaction (`infrastructure/unit_of_work.py:32`) and fail-closed auditing, which TASK-002 should reuse.
- TASK-001 summary reconciliation is already present: `service.py:295`, typed `api/router.py:172`, and `infrastructure/unit_of_work.py:99` return bounded overdue/today/next-seven-day/reminder slices and complete totals under one snapshot. The stale summary warnings in TASK-001 and the backlog have been corrected. This does not prove every TASK-001 design requirement is implemented.
- Current task paging supports status/priority/relation filters but evaluates due filters by bounded candidate scanning (`service.py:144`). It returns no complete matching total. That is a documented TASK-001 tradeoff, not the complete-count contract required for the new follow-up endpoint.
- Current `TaskContextReader` supports a caller-owned connection but supplies no captured instant or waiting facts; its related-entity batch can return every linked task (`infrastructure/context_reader.py:22`). OPS cannot use that unbounded history as an overview slice.
- Direct dependencies remain AUDIT-001 and TASK-001; LOCAL-001/002 are transitive durability foundations. Keep TASK-002 independent of OPS-001, UI-001, DASH-001, LEGAL-001, HOA-001, and source-domain modules. Those consumers depend on Tasks, not the reverse. AUDIT-001 may supply a consumer-neutral read marker without a new dependency.
- Adjacent TASK-001 differences include documented edit/delete/confirmation contracts that are absent from the present router, title bounds of 255 in the design versus 240 in code, and documented reminder status `sent` versus the retained schema's three local statuses. Resolve these under TASK-001; do not silently expand TASK-002 into a general Task rewrite.

Baseline implementation references are relative to `application/apps/server/app/modules/tasks/` unless stated otherwise.

## Verification

1. Set waiting context on a task with a deadline; verify the deadline and priority do not change.
2. Reschedule and dismiss a reminder independently; neither operation performs the other.
3. Surface an overdue urgent task with a future follow-up; it remains urgent/overdue.
4. Surface a waiting task without a date as unscheduled rather than silently omitting it.
5. Complete, reopen, and cancel tasks; verify waiting transitions are explicit, auditable, and no inactive task is active-waiting.
6. Verify captured-clock timezone boundaries, cursor totals, and no browser-side date classification.

## Definition of done

TASK-002 is complete when the typed persistence, audit, command, bounded read, and regression contracts above exist; all existing TASK-001 semantics remain intact; and UI/DASH consumers can distinguish waiting, due follow-up, unscheduled follow-up, and source urgency without client-side derivation.
