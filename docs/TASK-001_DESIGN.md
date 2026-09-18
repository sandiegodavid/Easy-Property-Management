# TASK-001 — Local Task Center

## Purpose

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
- A summary endpoint (`GET /api/tasks/summary`) returning counts and records for overdue, today, next seven days, and currently due reminders—this is the stable interface for `DASH-001`.

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

A task is **overdue** when its status is `open` or `in_progress` and its `due_at_utc` is in the past. A task without a due date is never overdue. This rule is applied in the summary endpoint and list queries.

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

`DELETE /api/tasks/{id}` is allowed **only** when the task has `status = 'open'` AND no reminders exist (or all reminders are `dismissed`). This prevents accidental deletion of tasks with history. The endpoint requires `StrictBool confirmed: true`. The deletion and its audit event occur in the same transaction.

### Add reminders

`POST /api/tasks/{id}/reminders` accepts one or more `{ remind_at_utc, remind_timezone? }` entries. The service converts each to UTC using the provided timezone (or the task's `due_timezone` as fallback) and creates `task_reminders` rows with `status = 'pending'`. Duplicate `remind_at_utc` for the same task are rejected.

### Acknowledge a reminder

`POST /api/tasks/{id}/reminders/{reminderId}/acknowledge` requires `StrictBool confirmed: true`. It sets `status = 'acknowledged'` and `acknowledged_at_utc = now()`. An acknowledged reminder no longer appears in “due reminders” lists.

### Dismiss a reminder

`POST /api/tasks/{id}/reminders/{reminderId}/dismiss` requires `StrictBool confirmed: true`. It sets `status = 'dismissed'` and `dismissed_at_utc = now()`. A dismissed reminder is hidden from pending lists but retained in history.

### Summary endpoint

`GET /api/tasks/summary` returns a single response with:

- `overdue`: tasks where `status IN ('open','in_progress') AND due_at_utc < now()` — ordered by `due_at_utc` asc.
- `today`: tasks where `status IN ('open','in_progress') AND due_at_utc` falls on the operator's current local date (in the stored `due_timezone` or fallback) — ordered by `due_at_utc` asc.
- `next7days`: tasks where `status IN ('open','in_progress') AND due_at_utc` is after today through 7 days — ordered by `due_at_utc` asc.
- `dueReminders`: `task_reminders` where `status = 'pending' AND remind_at_utc <= now()` — joined with task title, due date, and related label, ordered by `remind_at_utc` asc.

All times are evaluated using the application's injected clock boundary so tests do not depend on ambient server time. The summary is the contract for `DASH-001`.

### List and filter tasks

`GET /api/tasks` supports query parameters:

- `status`: comma-separated list (`open,in_progress,completed,cancelled`).
- `due`: `overdue`, `today`, `next7days`, `nodate`, or ISO date range `YYYY-MM-DD,YYYY-MM-DD`.
- `priority`: comma-separated list.
- `relatedEntityType`: filters by `related_entity_type`.
- `includeVoided`: `true` to include completed/cancelled (default false).
- Cursor pagination: default page size 100, max 500.
- Default ordering: `due_at_utc ASC NULLS LAST, created_at_utc DESC`.

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
| `GET` | `/api/tasks/summary` | Return overdue, today, next 7 days, and due reminders for dashboard. |
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
4. Implement overdue/today/next7days projections using the injected clock/time-zone boundary, then expose typed FastAPI routes with ready/writer-lock/error handling.
5. Register task audit policies (allowlist of auditable fields, no secret rejection needed) and add regression coverage for:
   - Status transitions and timestamp rules (completed_at_utc only on completed, etc.)
   - Due date timezone preservation and all-day rendering
   - Overdue/today/next7days classification across time zones
   - Reminder acknowledge/dismiss prevents repeat display
   - Generic related-record link portability (text identifiers only)
   - Delete only empty/draft tasks
   - Summary endpoint shape and ordering
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
8. Dashboard consumers can retrieve overdue and upcoming tasks via `GET /api/tasks/summary` without scanning unrelated tables.

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
- `DASH-001` (Dashboard) — consumes `/api/tasks/summary` for action cards.
- `RPT-004` (Scheduled reports) — creates report generation tasks.
- `APT-004` (Unit turnovers) — creates turnover workflow tasks.
- `BEGIN-003` (Beginner experience) — includes task onboarding.

None of these may reinterpret TASK-001 statuses or reminders beyond their defined semantics. TASK-001 remains the stable task foundation.
