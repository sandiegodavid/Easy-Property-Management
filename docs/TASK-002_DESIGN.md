# TASK-002 — Waiting and Follow-up Design

## Purpose

`TASK-002` adds explicit waiting context and a follow-up date to an existing TASK-001 task without changing the task's own due date, priority, lifecycle, or reminder history. It is the shared follow-up primitive for legal matters, HOA notices and shared repairs, owner concerns, and other source-owned work.

## Scope and boundaries

- A task remains the authoritative record for its status, deadline, priority, completion, and reminders.
- A follow-up describes when the operator should revisit work that is waiting on a person or event. It never rewrites a source record's deadline or resolves the source record.
- TASK-002 does not create external reminders, send communications, infer that a response is required, or alter source-domain urgency.
- The owning source remains responsible for any domain-specific waiting state. TASK-002 provides a typed, reusable linked task and presentation facts for DASH-001 and UI-001.

## Data contract

Extend `tasks` with nullable fields:

| Field | Rule |
| --- | --- |
| `waiting_for_kind` | `person`, `organization`, `event`, or `other`; required when waiting context exists. |
| `waiting_for_label` | Required, trimmed 1–255 characters when waiting context exists; a durable human-readable description. |
| `follow_up_at_utc` | Optional future-or-present instant. It is independent of `due_at_utc`. |
| `follow_up_timezone` | Required with `follow_up_at_utc`; valid IANA zone used for presentation. |
| `waiting_set_at_utc` | Required when waiting context exists. |
| `waiting_cleared_at_utc` | Set only when waiting context is explicitly cleared. |

An active task may be waiting with no scheduled follow-up. That is valid, but must render as **Follow-up not scheduled**. Completed and cancelled tasks cannot acquire or retain active waiting context; completing, cancelling, or reopening clears it through an explicit audit-visible transition.

Use a database check for paired fields and a service-level invariant that `follow_up_at_utc` is not accepted without active waiting context. Add an index over active status and `follow_up_at_utc` for bounded resurfacing reads.

## Commands

`POST /api/tasks/{taskId}/waiting` accepts a strict request with `waitingForKind`, `waitingForLabel`, optional `followUpAt`, and `followUpTimezone`. It requires an active task, updates the waiting fields atomically, and writes `task_waiting_set` to AUDIT-001.

`POST /api/tasks/{taskId}/waiting/clear` requires `confirmed: true`, clears active waiting/follow-up fields, and writes `task_waiting_cleared`. It does not complete the task or mutate any linked source record.

`POST /api/tasks/{taskId}/waiting/follow-up` updates only the follow-up date/time of an already waiting active task and writes `task_follow_up_rescheduled`. A new follow-up must be explicit; dismissing a TASK-001 reminder is never treated as rescheduling it.

All mutations use the workspace writer boundary, request `extra="forbid"`, typed conflict/not-found responses, and the existing operation-key/idempotency policy.

## Read contract

Expose these additional facts in task detail, list items, and TASK-001 summary source records:

- `isWaiting`, `waitingFor`, `followUpAt`, `followUpTimezone`, `followUpState` (`scheduled`, `due`, `overdue`, `unscheduled`), and `sourceDeadlineState`.
- A captured `asOf` instant determines all classifications. `followUpState` is never inferred from browser time.
- A task with an overdue source due date remains overdue even if its follow-up is later. An urgent task remains urgent while waiting.

TASK-002 provides a bounded `GET /api/tasks/follow-ups` source read for DASH-001: active waiting tasks ordered by overdue follow-up, due-today follow-up, unscheduled follow-up, then stable ID. It includes a complete filtered total, cursor, `asOf`, and source task identity. It does not combine this result with unrelated task buckets.

## Operator behavior

UI-001 renders waiting context on the source task and in contextual record views. A waiting row identifies whom/what is awaited, the follow-up state, original deadline when present, and a clearly separate action to schedule or reschedule follow-up. It never presents a deferred reminder as resolved work.

DASH-001 may show the task in Waiting until the scheduled follow-up becomes due, then surface it in Needs action with the reason **Follow up with [label]**. If its source deadline is overdue or priority urgent, the source urgency governs its placement and wording.

## Verification

1. Set waiting context on a task with a deadline; verify the deadline and priority do not change.
2. Reschedule and dismiss a reminder independently; neither operation performs the other.
3. Surface an overdue urgent task with a future follow-up; it remains urgent/overdue.
4. Surface a waiting task without a date as unscheduled rather than silently omitting it.
5. Complete, reopen, and cancel tasks; verify waiting transitions are explicit, auditable, and no inactive task is active-waiting.
6. Verify captured-clock timezone boundaries, cursor totals, and no browser-side date classification.

## Definition of done

TASK-002 is complete when the typed persistence, audit, command, bounded read, and regression contracts above exist; all existing TASK-001 semantics remain intact; and UI/DASH consumers can distinguish waiting, due follow-up, unscheduled follow-up, and source urgency without client-side derivation.
