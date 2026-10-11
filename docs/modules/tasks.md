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

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_creation.py](../../application/apps/server/app/modules/tasks/tests/test_creation.py).
- [test_tasks.py](../../application/apps/server/app/modules/tasks/tests/test_tasks.py).
- [test_waiting.py](../../application/apps/server/app/modules/tasks/tests/test_waiting.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Browser acceptance is tracked separately in [active UI delivery](../active/UI-001_IMPLEMENTATION_MATRIX.md).
