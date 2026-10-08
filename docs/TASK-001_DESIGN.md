# TASK-001 — Local Task Center

## Status

In progress — pending UI implementation. The backend summary returns bounded overdue,
today, next-seven-day and due-reminder collections with complete totals and one read
snapshot. Recoverable creation, editing, deletion, lifecycle and reminder commands
have source-owned revision/key/receipt contracts; deletion retains tombstones.
UI-001 and DASH-001 consume these server facts rather than reproducing policy in
the browser. New browser controls and OPS command forms remain independently gated.
[TASK-002](TASK-002_DESIGN.md#resolved-design-decisions) adds waiting/revision facts,
`asOf`, and transaction-aware bounded projections without replacing the four buckets.

## Purpose

### Recoverable creation contract

The consequential HTTP creation command requires `expectedRevision: 0` and a
UUID `idempotencyKey`. `TaskService.create_command` inserts the task, an immutable
`task_creation_operations` receipt and correlated Task/operation audits in one
immediate transaction. The receipt stores canonical request JSON and SHA-256,
the full original typed response (revision 1 and `operationId`), correlation ID
and captured UTC timestamp. Unique key and task constraints and append-only
triggers retain this history indefinitely; no legacy migration is supported.
Same-key/same-payload replay returns the stored response, including its original
`asOf`, regardless of later task changes; changed reuse is 409.
`GET /api/tasks/creation-operations/{key}` exposes the recorded result. A narrow
source-owned receipt reader enables OPS recovery on the caller's connection.
Creation has no pre-existing Task revision, so only exact integer zero is valid.
Internal `create`/`new_task` callers remain non-recoverable, and this contract does
not enable automatic retries for other task mutations.

### Recoverable lifecycle and reminder contract

Consequential HTTP start, complete, cancel, reopen, add-reminder, acknowledge and
dismiss commands require positive integer `expectedRevision` and UUID
`idempotencyKey`. `TaskMutationService` is the owning application boundary.
Reminders use the parent Task revision; each command advances it once, including
all terminal waiting/reminder effects. Outcome notes are bounded to 4,000
characters and reminder inputs must be aware timestamps normalized to UTC.

The current baseline includes append-only `task_mutation_operations`: UUID ID,
globally unique key within this command family, Task foreign key, action,
expected/resulting revisions, canonical request and SHA-256 fingerprint, complete
immutable result JSON, correlation ID and UTC commit instant. Task/revision is
unique for effective mutations, whose resulting revision is exactly expected
revision plus one; no-op edit receipts retain the expected revision. All changes
and audits commit atomically. Retained validation reconstructs the original
response from the correlated Task/reminder history and validates replay identity.

Same-key identical retry returns the original response before lifecycle checks;
changed payload or stale revision is 409, with current revision for stale requests.
The typed response contains `task`, nullable `reminder`, `revision`, and
`operationId`. `GET /api/tasks/mutation-operations/{key}` returns that response
without recalculating state. Missing targets or receipts are 404. Legacy internal
Task service helpers are not recoverable UI commands. New OPS form registration,
Task editing and deletion use the same command family as specified below.

### Recoverable editing and deletion contract

PATCH and DELETE require the parent Task's positive `expectedRevision` and UUID
`idempotencyKey`. Partial edits preserve omitted fields and distinguish explicit
nulls in the canonical request. Business fields are normalized before comparison.
An unchanged edit records an immutable receipt but changes neither revision nor
timestamp and emits no Task-change event. Effective edits advance revision once.
The effective-revision uniqueness index excludes no-op receipts; no-op results
retain the expected revision. All results replay their original full snapshot.

Deletion requires an open Task with no non-dismissed reminders and exact boolean
`confirmed: true`. It retains the Task as a tombstone with `deletedAtUtc`, advances
revision once, and clears waiting in the same transaction. Ordinary detail,
lists, summaries, search, and related previews exclude tombstones. Historical
references and immutable receipts retain their identities; original commands
still replay after deletion and encrypted restore. No physical deletion removes
operational audit or command history. New references cannot select deleted Tasks.
The mutation receipt's insertion guard also rejects SQLite `INSERT OR REPLACE`
collisions even when recursive triggers are disabled.

Complete, cancel, reopen, acknowledge, dismiss, and delete all require exact
boolean confirmation. Start, add-reminder, and edit do not accept a destructive
confirmation. The HTTP boundary declares typed results and stable operation IDs;
no new OPS recovery forms or consequential browser controls are enabled by this
backend implementation.

`TASK-001` provides a lightweight local “action center” that future modules can rely on for tracking work items with due dates, reminders, and generic record links—without becoming a calendar, communications system, or automation engine.

It is the foundational task layer for the local MVP. A standalone task can exist today; later modules (rent reminders, showings, repairs, owner concerns, prepaid checks, lease adjustments, recurring expenses) will link their domain work to tasks through the generic `entity_type` / `entity_id` / `label` relation. TASK-001 does not depend on those modules.

## Scope

TASK-001 provides:

- Task creation, editing, completion, reopening, cancellation, and deletion (only for empty/draft tasks).
- Status lifecycle: `open`, `in_progress`, `completed`, `cancelled`.
- Priority: `low`, `normal`, `high`, `urgent`.
- Due date/time with an optional all-day flag.
- Multiple reminders per task, each tracked as `pending`, `acknowledged`, `dismissed`, or `sent`.
- Completion/cancellation timestamp and optional outcome note.
- Generic related-record link captured at creation: `entity_type`, `entity_id`, and a readable `label`.
- Created/updated timestamps.
- A summary endpoint (`GET /api/tasks/summary`) returning total counts and bounded initial records for overdue, today, next seven days, and currently due reminders—this is the stable task-source interface for `DASH-001`.

TASK-001 does not provide:

- Email/SMS sending or delivery tracking: `COM-002`.
- Calendar synchronization: `COM-003`.
- Recurring task generation: `FIN-005`, `FIN-007`, `RPT-004`.
- Automatic creation from legal rent-adjustment rules: `ADJ-002`.
- Task assignments, multi-user permissions, or cloud sync: future SaaS.
- Complex workflow templates; later modules can create focused task templates.

## Core decisions

### Generic relation is intentional

TASK-001 comes before properties, leases, leads, maintenance, and payments. The generic `entity_type` / `entity_id` / `label` triple allows any future module to link its records without TASK-001 depending on them. The label is captured at creation so a task remains meaningful even if the linked record is later deleted or the module is not yet implemented.

### Reminders are local and in-app only

MVP reminders are not external notifications. The dashboard/task list shows overdue and due-soon work when the app runs. `task_reminders.status` tracks `pending`, `acknowledged`, `dismissed`, `sent` to prevent repeat display. No OS notifications, background scheduler, or delivery tracking is required.

### Overdue definition is explicit

A timed task is **overdue** when its status is `open` or `in_progress` and its `due_at_utc` is before the captured current instant. An all-day task is overdue only when its local due date in `due_timezone` is before the current date in that timezone; it remains due today throughout its due date. A task without a due date is never overdue. The `overdue`, `today`, and `next7days` classifications are mutually exclusive and use the same rules in the summary endpoint and list queries.

### Time is stored in UTC; display preserves the operator's timezone

`due_at_utc` is stored as timezone-aware UTC. The operator's entered IANA timezone is stored in `due_timezone` so the same local time renders correctly regardless of the machine running the app. `is_all_day` treats the date as a full calendar day in that timezone.

### No recurring tasks in TASK-001

Recurrence belongs in later modules where domain rules differ (rent expectations, prepaid checks, recurring expenses, scheduled reporting). TASK-001 tasks are one-off. A later module may create a task for each occurrence.

### Completed and cancelled tasks stay in history

They are not silently removed. The `completed_at_utc`, `cancelled_at_utc`, and `outcome_note` fields preserve the resolution. The History view shows them with their outcome.

### Audit from day one

Although the backlog lists only `LOCAL-001` as a hard dependency, this design uses the completed `AUDIT-001` capability. Task creation, edits, status transitions, reminder acknowledgement/dismissal, and deletion produce `AUDIT-001` events. Tasks drive rent, legal notice, lease, and owner workflows; their history is an operational record worth preserving.

## Data model

All IDs are UUIDs. Timestamps are timezone-aware UTC text (`YYYY-MM-DDTHH:MM:SSZ`). Dates are ISO local dates (`YYYY-MM-DD`). The schema is created by the workspace initialization and participates in exact schema validation, backup, export, and restore.

### `tasks`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `title` | Required, trimmed, 1–255 characters. |
| `notes` | Optional, trimmed, maximum 10,000 characters. |
| `status` | Required, one of `open`, `in_progress`, `completed`, `cancelled`. Default `open`. |
| `priority` | Required, one of `low`, `normal`, `high`, `urgent`. Default `normal`. |
| `due_at_utc` | Optional timezone-aware UTC timestamp. Null means no due time. |
| `due_timezone` | Optional IANA timezone name (e.g., `America/Los_Angeles`). Required when `due_at_utc` is not null. Null when no due date. |
| `is_all_day` | Required boolean. When true, `due_at_utc` represents midnight at start of the local date in `due_timezone`; the task is due on that calendar day. Default false. |
| `completed_at_utc` | Optional UTC timestamp. Required when status is `completed`. Null otherwise. |
| `cancelled_at_utc` | Optional UTC timestamp. Required when status is `cancelled`. Null otherwise. |
| `outcome_note` | Optional, trimmed, maximum 4,000 characters. Only meaningful when status is `completed` or `cancelled`. |
| `related_entity_type` | Optional string, e.g., `lease`, `property`, `tenant`, `maintenance`, `owner_concern`, `prepaid_check`, `rent_adjustment`, `expense`. Max 64 chars. Null means standalone task. |
| `related_entity_id` | Optional UUID string matching the related record's ID. Required when `related_entity_type` is set. Null otherwise. |
| `related_label` | Optional trimmed string, 1–255 characters. Human-readable label captured at creation (e.g., “Unit 3B lease”, “July rent reminder”). Null when no relation. |
| `created_at_utc` | Required UTC creation timestamp. |
| `updated_at_utc` | Required UTC timestamp updated on every write. |

**Constraints and indexes:**

- `CHECK (status IN ('open','in_progress','completed','cancelled'))`
- `CHECK (priority IN ('low','normal','high','urgent'))`
- `CHECK ((due_at_utc IS NULL AND due_timezone IS NULL AND is_all_day = false) OR (due_at_utc IS NOT NULL AND due_timezone IS NOT NULL))`
- `CHECK ((status = 'completed' AND completed_at_utc IS NOT NULL) OR (status != 'completed' AND completed_at_utc IS NULL))`
- `CHECK ((status = 'cancelled' AND cancelled_at_utc IS NOT NULL) OR (status != 'cancelled' AND cancelled_at_utc IS NULL))`
- `CHECK (related_entity_type IS NULL AND related_entity_id IS NULL AND related_label IS NULL OR related_entity_type IS NOT NULL AND related_entity_id IS NOT NULL)`
- `INDEX idx_tasks_status_due (status, due_at_utc)` — supports open/overdue/upcoming lists.
- `INDEX idx_tasks_related (related_entity_type, related_entity_id)` — supports future record drill-down.
- `INDEX idx_tasks_created (created_at_utc)` — supports History view ordering.

### `task_reminders`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `task_id` | Required foreign key to `tasks.id`. |
| `remind_at_utc` | Required timezone-aware UTC timestamp when the reminder should fire. |
| `status` | Required, one of `pending`, `acknowledged`, `dismissed`, `sent`. Default `pending`. |
| `acknowledged_at_utc` | Optional UTC timestamp. Required when status is `acknowledged`. Null otherwise. |
| `dismissed_at_utc` | Optional UTC timestamp. Required when status is `dismissed`. Null otherwise. |
| `created_at_utc` | Required UTC creation timestamp. |

**Constraints and indexes:**

- `CHECK (status IN ('pending','acknowledged','dismissed','sent'))`
- `CHECK ((status = 'acknowledged' AND acknowledged_at_utc IS NOT NULL) OR (status != 'acknowledged' AND acknowledged_at_utc IS NULL))`
- `CHECK ((status = 'dismissed' AND dismissed_at_utc IS NOT NULL) OR (status != 'dismissed' AND dismissed_at_utc IS NULL))`
- `INDEX idx_task_reminders_status_remind (status, remind_at_utc)` — supports due reminders query.
- `INDEX idx_task_reminders_task (task_id)` — supports task detail.

## Workflows and invariants

### Create a task

`POST /api/tasks` creates a task with title, optional notes, priority, due date/time/timezone/all-day, and optional related-record link. Reminders are created separately. The response includes the created task with its ID and timestamps.

### Edit a task

`PATCH /api/tasks/{id}` allows updating title, notes, priority, due date/time/timezone/all-day, and related-record link. Status, completion/cancellation timestamps, and outcome note are **not** editable through this endpoint—they change only through explicit lifecycle endpoints. Updated at timestamp is set automatically.

### Complete a task

`POST /api/tasks/{id}/complete` requires `StrictBool confirmed: true` and optional `outcomeNote` (trimmed, 1–4,000 chars). It sets `status = 'completed'`, `completed_at_utc = now()`, and `outcome_note`. A completed task cannot be edited; it can only be reopened.

### Reopen a task

`POST /api/tasks/{id}/reopen` requires `StrictBool confirmed: true`. It sets `status = 'open'`, clears `completed_at_utc` and `outcome_note`, and updates `updated_at_utc`. The task returns to the active list.

### Cancel a task

`POST /api/tasks/{id}/cancel` requires `StrictBool confirmed: true` and optional `outcomeNote` (trimmed, 1–4,000 chars). It sets `status = 'cancelled'`, `cancelled_at_utc = now()`, and `outcome_note`. A cancelled task cannot be edited; it can only be reopened (which clears the cancellation).

### Delete a task

`DELETE /api/tasks/{id}` is allowed **only** when the task has `status = 'open'` AND no reminders exist (or all reminders are `dismissed`). The endpoint requires `StrictBool confirmed: true`, the expected parent revision, and a UUID idempotency key. A retained deletion tombstone, waiting cleanup, audit event, and immutable receipt commit in the same transaction; normal reads no longer expose the Task.

### Add reminders

`POST /api/tasks/{id}/reminders` accepts one or more `{ remind_at_utc, remind_timezone? }` entries. The service converts each to UTC using the provided timezone (or the task's `due_timezone` as fallback) and creates `task_reminders` rows with `status = 'pending'`. Duplicate `remind_at_utc` for the same task are rejected.

### Acknowledge a reminder

`POST /api/tasks/{id}/reminders/{reminderId}/acknowledge` requires `StrictBool confirmed: true`. It sets `status = 'acknowledged'` and `acknowledged_at_utc = now()`. An acknowledged reminder no longer appears in “due reminders” lists.

### Dismiss a reminder

`POST /api/tasks/{id}/reminders/{reminderId}/dismiss` requires `StrictBool confirmed: true`. It sets `status = 'dismissed'` and `dismissed_at_utc = now()`. A dismissed reminder is hidden from pending lists but retained in history.

### Summary endpoint

`GET /api/tasks/summary?limitPerBucket=20` accepts `limitPerBucket` from 1 through 100 and returns one response with:

- `overdue` and `overdueTotal`: the first bounded tasks and complete count where `status IN ('open','in_progress')` and the explicit overdue rule above is true, ordered by `due_at_utc` ascending.
- `today` and `todayTotal`: the first bounded non-overdue tasks and complete count where `status IN ('open','in_progress')` and the due date in the stored `due_timezone` is today, ordered by `due_at_utc` ascending.
- `next7days` and `next7daysTotal`: the first bounded tasks and complete count where `status IN ('open','in_progress')` and the task's due date in its stored `due_timezone` is after today through seven days, ordered by `due_at_utc` ascending.
- `dueReminders` and `dueRemindersTotal`: the first bounded pending reminders and complete count where `remind_at_utc <= now()`, joined with task title, due date, and related label and ordered by `remind_at_utc` ascending.

All four collection keys and their four total keys are always present, including when arrays are empty or totals are zero. Totals describe the complete matching set, not just the returned slice. All times are evaluated from one instant captured through the application's injected clock boundary, so every bucket is internally consistent and tests do not depend on ambient server time. The repository computes each count and bounded slice with set-based queries; it does not call the paginated HTTP list endpoint or load an unbounded task history into application memory. The summary is the task-source contract consumed by `DASH-001`.

**Implementation baseline:** the bounded summary, four totals, typed response, mutually exclusive timezone/all-day classifications, and snapshot tests are implemented at `5ca7672`. Preserve these contracts when adding TASK-002 waiting/revision facts and `asOf`. Waiting does not subtract a task from obligation buckets or acknowledge its independent reminders. The generic filtered list still uses the documented bounded scan strategy; TASK-002's new exact-total follow-up endpoint uses a separate set-based read. Other differences between this design and implementation remain subject to TASK-001 verification rather than being implicitly resolved by summary completion.

### List and filter tasks

`GET /api/tasks` supports query parameters:

- `status`: comma-separated list (`open,in_progress,completed,cancelled`).
- `due`: `overdue`, `today`, `next7days`, `nodate`, or ISO date range `YYYY-MM-DD,YYYY-MM-DD`.
- `priority`: comma-separated list.
- `relatedEntityType` and `relatedEntityId`: supplied together to filter the generic related-record link. This supports a bounded complete follow-up history for a record such as `owner_concern` without loading unrelated tasks.
- `includeVoided`: `true` to include completed/cancelled (default false).
- Cursor pagination: default page size 100, max 500.
- Default ordering: `due_at_utc ASC NULLS LAST, created_at_utc DESC`.

The persistence query applies status, priority, and related-record predicates before
pagination. Due filters use each task's stored due timezone, so they are applied by
the application after reading ordered bounded chunks. A request examines at most
1,000 candidate rows, in at most ten persistence queries. When more than
`pageSize` matches are found, `nextCursor` identifies the final returned item, so
matches already scanned but not yet returned remain available on the next page. When
the 1,000-candidate scan budget is exhausted before filling a page,
`nextCursor` instead identifies the final scanned candidate. Consequently a
selective due filter may return fewer than `pageSize` items, including an empty
`items` array, with a non-null `nextCursor`. Clients must continue requesting pages
whenever `nextCursor` is present; only a null cursor denotes exhaustion. This
explicitly trades a small number of sparse pages for a fixed read/query budget and
avoids an unbounded scan of the task history.

### Get task detail

`GET /api/tasks/{id}` returns the task with its reminders (including status and timestamps) and the computed `isOverdue` flag.

## Operator workflow delivered by UI-001

UI-001 adds a **Tasks** workflow with plain-language, task-first presentation:

- **My tasks** (default view): shows overdue, today, and next 7 days in three sections. Each task row shows title, due date/time (or “No due date”), priority badge, status badge, and a clear completion checkbox. Clicking the checkbox calls `POST /complete` with confirmation.
- **Quick add**: a compact inline form asking only for task name and due date (with a “No due date” option). Details (notes, priority, reminders, related record) are optional and expandable.
- **Filters**: status, priority, due period (overdue/today/next 7/all/no date), linked record type.
- **History view**: shows completed and cancelled tasks with outcome note and completion/cancellation timestamp. Read-only.
- **Task detail**: shows full notes, all reminders with acknowledge/dismiss actions, related record link (label only; future modules may make it a drill-down), and audit history via `AUDIT-001`.
- **Future modules**: show linked tasks in a small “Next actions” section on their record detail screens.

## API contract

All routes require a ready workspace. Mutations require the writer lock. Request models use `extra="forbid"`, `StrictBool` confirmations, and typed ISO dates/timestamps. All responses use explicit Pydantic models.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/tasks` | Create a task. |
| `GET` | `/api/tasks` | List tasks with filters and pagination. |
| `GET` | `/api/tasks/summary` | Return totals and bounded `overdue`, `today`, `next7days`, and `dueReminders` collections; `limitPerBucket` defaults to 20 and is capped at 100. |
| `GET` | `/api/tasks/{id}` | Return one task with its reminders. |
| `PATCH` | `/api/tasks/{id}` | Edit task fields (not status/lifecycle). |
| `POST` | `/api/tasks/{id}/complete` | Complete a task with optional outcome note. |
| `POST` | `/api/tasks/{id}/reopen` | Reopen a completed or cancelled task. |
| `POST` | `/api/tasks/{id}/cancel` | Cancel a task with optional outcome note. |
| `DELETE` | `/api/tasks/{id}` | Delete only an empty/draft task. |
| `POST` | `/api/tasks/{id}/reminders` | Add one or more reminders. |
| `POST` | `/api/tasks/{id}/reminders/{reminderId}/acknowledge` | Acknowledge a reminder. |
| `POST` | `/api/tasks/{id}/reminders/{reminderId}/dismiss` | Dismiss a reminder. |

**Request/response shapes (key fields):**

- Create task: `{ title, notes?, priority?, due_at_utc?, due_timezone?, is_all_day?, related_entity_type?, related_entity_id?, related_label? }`
- Edit task: same fields, all optional.
- Complete: `{ confirmed: true, outcome_note? }`
- Reopen: `{ confirmed: true }`
- Cancel: `{ confirmed: true, outcome_note? }`
- Delete: `{ confirmed: true }`
- Add reminders: `{ reminders: [{ remind_at_utc, remind_timezone? }] }`
- Acknowledge/dismiss: `{ confirmed: true }`

**Error codes:**

- `413`: Oversized request content (payload too large).

- `400`: Invalid business data (e.g., due_at_utc without due_timezone, invalid status transition).
- `404`: Task or reminder not found.
- `409`: Invalid lifecycle transition (e.g., complete an already completed task, delete a task with history, duplicate reminder time).
- `422`: Malformed request data (validation error).

## Audit, privacy, and portability

Each write persists its rows and `AUDIT-001` changes in one immediate transaction and one correlation ID.

**Entity types:** `task`, `task_reminder`.

**Actions and snapshots:**

- Task creation: `created` action with `after_snapshot` containing all fields.
- Task edit: `updated` action with `before_snapshot` / `after_snapshot` and `changed_fields`.
- Complete: `status_changed` action with `before_snapshot` (status open/in_progress) and `after_snapshot` (status completed, completed_at_utc, outcome_note).
- Reopen: `status_changed` action with before/after showing status back to open and cleared timestamps.
- Cancel: `status_changed` action with before/after showing status cancelled, cancelled_at_utc, outcome_note.
- Delete: `deleted` action with `before_snapshot` (full task) — only allowed for empty/draft tasks.
- Reminder creation: `created` action on `task_reminder` entity.
- Reminder acknowledge: `status_changed` on `task_reminder` with before/after showing `pending` → `acknowledged` and `acknowledged_at_utc`.
- Reminder dismiss: `status_changed` on `task_reminder` with before/after showing `pending` → `dismissed` and `dismissed_at_utc`.

**Redaction policy:**

- Task `outcome_note` is not redacted for the local operator.
- Task `notes` is not redacted.
- Related record `label` is not redacted.
- Summary and list endpoints return full data; the operator owns all local records.

TASK-001 data and audit history are retained in the encrypted workspace backup/export/restore package (`LOCAL-002`). No secrets or external credentials are stored.

## Implementation outline

1. Add TASK-001 SQLAlchemy models, constraints, indexes, module-owned exact schema validation, and baseline/product/archive validation updates for the greenfield current schema.
2. Define immutable domain values and validated commands for task lifecycle, reminders, and summary queries; reject floats, invalid status transitions, missing timezone with due date, and unchecked direct construction.
3. Define task unit-of-work and transaction protocols. Compose concrete adapters in bootstrap; keep task application code independent of Portfolio, Leases, Finance, and other domain SQLAlchemy infrastructure.
4. Reconcile the summary and due-filter implementation with the mutually exclusive timed/all-day rules above. Add `today`, `next7days`, complete totals, and bounded set-based repository queries using one injected clock instant. Add an explicit response model with all required collection and total keys; do not assemble the summary through repeated HTTP calls, unbounded in-memory scans, or browser-side classification.
5. Register task audit policies (allowlist of auditable fields, no secret rejection needed) and add regression coverage for:
   - Status transitions and timestamp rules (completed_at_utc only on completed, etc.)
   - Due date timezone preservation and all-day rendering
   - Overdue/today/next7days classification across time zones
   - Reminder acknowledge/dismiss prevents repeat display
   - Generic related-record link portability (text identifiers only)
   - Delete only empty/draft tasks
   - Summary endpoint shape, required empty/zero keys, per-bucket limits, complete totals, ordering, query bounds, and agreement with corresponding list-filter classifications
   - Concurrency (writer lock)
   - Schema rejection and exact validation
   - Encrypted backup/export/restore preservation

## Acceptance criteria

TASK-001 is complete when:

1. A local workspace initialization creates `tasks` and `task_reminders` tables with all constraints, indexes, and triggers safely.
2. A user can create and complete a standalone task (no related record).
3. Due and overdue states calculate correctly across time zones, including all-day tasks.
4. Reminder acknowledgement and dismissal prevent repeat display as pending.
5. Related-record links remain portable text identifiers and do not require unavailable modules.
6. Task activity (creation, edits, status transitions, reminder actions, deletion) is audit-recorded via `AUDIT-001` with correct before/after snapshots.
7. Backup/restore preserves tasks, reminders, and their audit history.
8. Dashboard consumers can retrieve complete totals and bounded `overdue`, `today`, `next7days`, and `dueReminders` collections through one typed `GET /api/tasks/summary` response without unbounded reads, scanning unrelated tables, issuing compensating list requests, or reimplementing time-zone rules.

## Dependencies and follow-on work

TASK-001 requires completed `LOCAL-001` and `AUDIT-001`. It has no direct dependency on Portfolio, Leases, Finance, or other domain modules.

**Follow-on work that depends on TASK-001:**

- `FIN-007` (Prepaid checks) — creates deposit reminder tasks.
- `COM-001` (Communications) — creates follow-up tasks from communication entries.
- `MAINT-001` (Repairs) — creates repair appointment and follow-up tasks.
- `OWNER-004` (Owner management) — creates owner concern tasks.
- `LEAD-001` / `LEAD-002` (Leads) — creates lead follow-up and showing tasks.
- `ADJ-001` / `ADJ-002` (Rent strategy) — creates rent review and notice deadline tasks.
- `FIN-005` (Recurring expenses) — creates payable reminder tasks.
- `DASH-001` (Dashboard) — consumes the reconciled four-collection `/api/tasks/summary` contract for Home composition; it must not treat the current partial response as complete.
- `RPT-004` (Scheduled reports) — creates report generation tasks.
- `APT-004` (Unit turnovers) — creates turnover workflow tasks.
- `BEGIN-003` (Beginner experience) — includes task onboarding.

None of these may reinterpret TASK-001 statuses or reminders beyond their defined semantics. TASK-001 remains the stable task foundation.

For OWNER-004 specifically, `related_entity_type = 'owner_concern'` links a task to the stable concern ID. Task completion or cancellation never resolves or dismisses the concern, and concern resolution, dismissal, or reopening never mutates the task. OWNER-004 may coordinate task creation in its caller-owned transaction, but TASK-001 remains authoritative for validation and lifecycle.
