# TASK-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Tasks, reminders and waiting](../modules/tasks.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 53, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Task create/edit/delete and start/complete/cancel/reopen; reminder add/acknowledge/dismiss; source links, confirmations and original-outcome recovery.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Retained operator requirements

UI-001 adds a **Tasks** workflow with plain-language, task-first presentation:

- **My tasks** (default view): shows overdue, today, and next 7 days in three sections. Each task row shows title, due date/time (or “No due date”), priority badge, status badge, and a clear completion checkbox. Clicking the checkbox calls `POST /complete` with confirmation.
- **Quick add**: a compact inline form asking only for task name and due date (with a “No due date” option). Details (notes, priority, reminders, related record) are optional and expandable.
- **Filters**: status, priority, due period (overdue/today/next 7/all/no date), linked record type.
- **History view**: shows completed and cancelled tasks with outcome note and completion/cancellation timestamp. Read-only.
- **Task detail**: shows full notes, all reminders with acknowledge/dismiss actions, related record link (label only; future modules may make it a drill-down), and audit history via `AUDIT-001`.
- **Future modules**: show linked tasks in a small “Next actions” section on their record detail screens.

## Acceptance constraints to verify

TASK-001 is complete when:

1. A local workspace initialization creates `tasks` and `task_reminders` tables with all constraints, indexes, and triggers safely.
2. A user can create and complete a standalone task (no related record).
3. Due and overdue states calculate correctly across time zones, including all-day tasks.
4. Reminder acknowledgement and dismissal prevent repeat display as pending.
5. Related-record links remain portable text identifiers and do not require unavailable modules.
6. Task activity (creation, edits, status transitions, reminder actions, deletion) is audit-recorded via `AUDIT-001` with correct before/after snapshots.
7. Backup/restore preserves tasks, reminders, and their audit history.
8. Dashboard consumers can retrieve complete totals and bounded `overdue`, `today`, `next7days`, and `dueReminders` collections through one typed `GET /api/tasks/summary` response without unbounded reads, scanning unrelated tables, issuing compensating list requests, or reimplementing time-zone rules.

## Validation and delivery references

- [Current module and focused tests](../modules/tasks.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/TASK-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
