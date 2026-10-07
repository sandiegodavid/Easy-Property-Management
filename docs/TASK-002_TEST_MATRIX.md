# TASK-002 backend validation

Implementation slices: contracts/ports, application/domain policy, current-baseline persistence, focused acceptance tests, and bootstrap/source integration. No React changes or compatibility migration.

| Area | Coverage |
| --- | --- |
| Happy paths | Set/replace, scheduled/unscheduled waiting, reschedule, remove date, explicit clear; deadline/priority/reminders remain independent |
| Invalid combinations | Direct command kind/label/zone/date/revision/key validation; strict HTTP fields, confirmations and mutually exclusive date removal |
| Idempotency/retry | Durable original-response replay, receipt lookup, changed payload and stale revision conflicts; concurrent same-key submissions commit once; semantic no-op retains receipt without task revision/audit change |
| Rollback/concurrency | Audit and receipt failures roll back task changes; counts/page share a snapshot across a committed writer; terminal clearing shares correlation with task/reminder changes |
| Lifecycle/time | Active transition preserves waiting; completion clears once; reopen does not resurrect waiting/reminders; exact follow-up instant, independently selected zone, local all-day task deadline |
| Persistence | Latest baseline, paired-field checks, positive revision, append-only operation triggers, canonical command fingerprints, historical response/audit validation; tampered waiting attribution rejected |
| Backup/restore | Encrypted archive preserves tasks, receipts, and prior audit rows; restored receipt returns the original response; full product validation exercised by backup/restore |
| Query/size budgets | Follow-up count/page/marker bounded to at most four SELECTs; one versus 100 rows has constant statement count; SQL LIMIT and populated index plan; parent previews capped with complete counts and no notes |
| Freshness/readiness | Cursor freezes `asOf`, binds filters/workspace/epoch/audit marker, expires after 15 minutes; stop and failed refresh deny direct calls before reads; successful restart resumes |
| Integration | Waiting remains in TASK-001 obligation/reminder buckets; communication, owner-concern and prepaid-check creation paths keep revision-1/empty-waiting defaults |

## Persistence and retention

`tasks` stores current waiting fields and revision; `task_waiting_operations` retains immutable UUID key, normalized command JSON/fingerprint, expected/resulting revisions, original result, correlation and UTC creation instant. Results are retained indefinitely in this release: no expiry deletes a receipt, so neither recovery references nor old retries can silently become new writes. Audit history remains the waiting episode history; no parallel waiting ledger exists.

`GET /api/tasks/waiting-operations/{key}` returns the original result. `/follow-ups` is registered before the task-ID route. Transaction-aware `TaskContextReader.previews_for_related_entities` accepts a captured instant, at most 100 parent IDs and a 1–50 per-parent cap, and returns typed facts/full counts with one windowed query.

Adjacent TASK-001 edit/delete/confirmation and reminder-status differences identified in the approved design are not part of the `3eb0f8` summary/waiting reconciliation and remain unchanged.

## Focused validation results

- Tasks: 34 passed, including 14 boundary subtests.
- Communication/owner-concern/prepaid-check integration selection: 11 passed (63 deselected).
- `ruff check`, `ruff format --check`, and `git diff --check`: passed for the implementation.
- Full suite and frontend checks were not run; no frontend code changed.

## Review finding 1 — receipt completeness (October 7, 2026)

Retained validation checks audit-to-receipt as well as receipt-to-audit relationships. Every recorded operation, including a semantic no-op, requires its retained receipt. Every explicit waiting mutation requires exactly one correlated change-producing receipt with matching task, action and revisions. Automatic terminal clearing instead requires the matching terminal lifecycle event and remains exempt from waiting-command receipts.

Regression coverage deletes mutation/no-op receipts while restoring the exact append-only trigger, and also removes both receipt and operation audit while retaining the explicit task mutation. Workspace open rejects these states. Authenticated encrypted archives with corrected inventories but missing receipts fail validation and restore without publishing a destination or changing the active workspace. Valid lifecycle clearing and ordinary backup/replay continue to pass.

## Review finding 2: database failure boundary

| Area | Focused coverage |
| --- | --- |
| Contention | Real `BEGIN IMMEDIATE` contention returns structured `503/task_waiting_busy`; exclusive-lock follow-up and receipt reads use the same contract |
| Database failures | Raw SQLite and SQLAlchemy-wrapped failures map BUSY/LOCKED, including extended codes, to 503; other failures return sanitized `500/task_waiting_storage_failure` without SQL, driver details, or paths |
| Rollback/retry | Receipt-write and commit failures leave task, audit, and receipt changes uncommitted; the same key can subsequently commit and replay once |
| Exception isolation | Domain conflicts and programming errors retain their original type; legacy TASK-001 writes remain unchanged |

## Review Finding 3: HTTP timestamp admission

| Area | Regression coverage |
| --- | --- |
| Invalid input | Set and reschedule reject numeric seconds/milliseconds, numeric strings, booleans, malformed strings, naive timestamps, and date-only values with structured 422 responses before mutation |
| Accepted input | Both routes accept explicit offsets and `Z`; the waiting command persists normalized UTC values |
| Optional dates | Set permits null follow-up fields; reschedule permits explicit date removal with `clearFollowUp=true` |

No persistence, backup, transaction, or query decomposition changes are required for this request-boundary fix.