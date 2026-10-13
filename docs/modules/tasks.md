# Tasks, reminders and waiting

## Responsibility

Tasks own an operator action's deadline, priority, lifecycle and reminders. Waiting adds whom or what the action awaits and an independent follow-up instant. A related-record identity provides context; completing a task does not complete its Maintenance, Lease, communication or owner-concern source.

## Record model and lifecycle

Active statuses are `open` and `in_progress`; completion and cancellation retain history. Deletion retains command evidence and a tombstone for recovery. Task reminders have their own identities and acknowledgment/dismissal state. Reopening a task does not resurrect cleared waiting or dismissed reminders.

A Task has one shared revision across edits, lifecycle, reminders and waiting. Creation uses revision zero; later commands use the displayed revision and a UUID key. Creation, mutation and waiting receipts have their owning lookup APIs. Identical keyed retries recover the original response; changed payloads or stale revisions conflict. The state, receipt and audit commit together.

## Deadlines and follow-up

Store aware instants in UTC with the presentation IANA zone; preserve the all-day deadline distinction. An all-day task becomes overdue after its local due day, rather than at its first instant. The summary retains overdue, today, next-seven-day and due-reminder buckets with complete totals.

Waiting requires a bounded kind and label. Its optional follow-up requires both an aware instant and a zone. An undated waiting task is valid and visibly unscheduled. Set replaces the complete waiting context; reschedule changes its date or explicitly removes the date; confirmed clear removes waiting. Date removal preserves the label. Terminal transitions clear waiting atomically and record the reason.

Follow-up is actionable at its exact instant. A future instant today is still scheduled. An overdue Task remains overdue while waiting; source urgency and deadlines remain separate facts supplied by source modules. Waiting never creates or dismisses a reminder.

## Read and integration contracts

`/api/tasks` supplies detail and bounded task pages; `/summary` supplies the existing task buckets; `/follow-ups` supplies active waiting tasks and full matching counts. Follow-ups order overdue, due, future today, unscheduled, then other future, with stable identity ties. Pages freeze classification at `asOf`; changed or expired continuations require a fresh first page.

Task source adapters accept the consumer's connection and captured instant, return capped previews and full counts, and avoid per-parent queries. Communications and other sources may create linked tasks inside a coordinated transaction. Their command remains the authority for that coordinated creation; it does not create an independent browser retry operation.

## Developer guardrails

Keep waiting, deadlines and reminder state independent. Preserve replay before current-state validation, task tombstones and original-result recovery. Return derived deadline/follow-up facts from the server; clients must not recalculate them from browser time.

## Browser workflow boundary

Live Task deadline/waiting directories use shared attention rows and recoverable source forms. Waiting retains independent deadline/urgency/reminder facts. Terminal/deleted Tasks retain command receipts for original-key reconciliation, including after live record removal. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

Active waiting Tasks expose Set waiting context again for complete replacement, alongside reschedule and confirmed clear. Replacement/reschedule forms prefill current waiting facts at the displayed Task revision. Date removal explicitly clears both date and zone with `clearFollowUp`, retains the label and displays Not scheduled. Expanded waiting rows show original deadline/zone and priority separately from server-derived follow-up state. Waiting changes do not alter pending reminders or deadlines; lost responses recover the original operation without another dispatch.

TASK-001 is complete. The Task directory combines status, priority, due period (overdue, today, next seven days, all dates or no date), and related-record filters; changing criteria resets the cursor. Priority also applies to waiting follow-ups. Deadline filtering applies to the ordinary Task directory, while waiting uses its separate follow-up state.

Inline quick add begins with the Task title and a due-date/no-date choice; choosing a date creates an all-day deadline in the displayed browser time zone. Optional details include exact deadline/time-zone fields and expand without losing input. The form uses the existing saved-form and original-result recovery contract. Completion checkboxes inside expanded deadline/directory rows open the confirmed completion form. Completed/cancelled rows and detail show the retained outcome note and timestamp together in a read-only history section. These presentations use existing page/summary fields without per-row detail requests.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/tasks/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/tasks/application).
- [HTTP contracts](../../application/apps/server/app/modules/tasks/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/tasks/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `tasks`, `task_reminders`, `task_waiting_operations`, `task_mutation_operations`, `task_creation_operations` | [sqlalchemy_models.py](../../application/apps/server/app/modules/tasks/infrastructure/sqlalchemy_models.py) |

## Validation

DASH-001's caller-transaction Task attention reader supplies SQL-filtered deadlines, waiting follow-ups and grouped reminder previews, including unlinked Tasks and retained archived context. Its source counts and SQL facts support the later Home composition; they do not replace the existing TASK-001 summary or enable Home on their own. See the [DASH delivery matrix](../active/DASH-001_CONTRACT_EXAMPLES.md#slice-3-task-reminder-and-waiting-facts) and [focused attention tests](../../application/apps/server/app/modules/tasks/tests/test_attention_reader.py).

Completion validation on October 12, 2026 passed the complete Task backend directory (120 tests) and twelve focused Task browser cases in [work.spec.ts](../../application/apps/web/tests/work.spec.ts). The [completed TASK-001 acceptance record](../archive/designs/TASK-001_DESIGN_COMPLETED_2026-10-12.md) records coverage and repository check limitations. The following executable specifications remain the starting point for focused regression validation.

- [test_creation.py](../../application/apps/server/app/modules/tasks/tests/test_creation.py).
- [test_tasks.py](../../application/apps/server/app/modules/tasks/tests/test_tasks.py).
- [test_waiting.py](../../application/apps/server/app/modules/tasks/tests/test_waiting.py).

TASK-002 acceptance completed October 13, 2026: **120 focused Task backend tests and 15 Task/waiting/reminder browser regressions passed**. The [completed acceptance matrix](../archive/designs/TASK-002_DESIGN_COMPLETED_2026-10-13.md) covers replacement/date removal, exact follow-up timing, independent reminders/deadlines, recovery, concurrent snapshots, four-SELECT bounds and encrypted history. Broader Home composition/performance acceptance remains DASH-001-owned.

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
