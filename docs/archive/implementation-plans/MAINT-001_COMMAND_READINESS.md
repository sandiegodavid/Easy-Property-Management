# MAINT-001 command readiness amendment

Approved scope: shared issue aggregate revision and immutable command receipts for
all source-owned issue and child mutation APIs. Greenfield current schema only.

## Parent integration (schema shape settled)

In `database/sqlite-migrations/versions/0001_initial_schema.py`, import
`MaintenanceCommandReceiptModel` from
`app.modules.maintenance.infrastructure.sqlalchemy_models` and create its table
after `MaintenanceIssueModel.__table__` (and before source data can be written).
Existing creation of `MaintenanceIssueModel.__table__` automatically includes the
new `revision INTEGER NOT NULL DEFAULT 1` column and the check
`typeof(revision)='integer' AND revision >= 1`.

New table: `maintenance_command_receipts`, source model
`MaintenanceCommandReceiptModel`:

| Column | Type / constraint |
| --- | --- |
| id | String, primary key, operation UUID |
| idempotency_key | String, required, unique UUID |
| issue_id | String, required FK maintenance_issues.id |
| action | String, required |
| target_kind | String, required |
| target_id | String, nullable (only create_issue) |
| expected_revision | Integer, required |
| revision | Integer, required |
| effective | Integer, required, 0 or 1 |
| request_payload | String, required canonical JSON object |
| request_fingerprint | String, required SHA-256 |
| response_payload | String, required full original JSON response |
| response_fingerprint | String, required SHA-256 |
| created_at | String, required UTC instant |

The receipt table has **14 columns**.

Model-owned checks: nonnegative integer expected revision; positive integer
result revision; integer boolean effective; revision = expected_revision +
effective; target kind in issue/appointment/cost_context/expense_link/quote/
assignment; create_issue has null target, zero expected revision and effective=1;
all other commands require nonnull target and positive expected revision; both
payloads are valid JSON objects; both fingerprints have length 64.

Model-owned indexes: `maintenance_receipts_issue_revision` (issue_id, revision);
`maintenance_receipts_effective_revision` unique (issue_id, revision) WHERE
effective=1. The idempotency key also has a unique constraint.

Install these exact triggers (also exported as `COMMAND_RECEIPT_TRIGGERS` by
Maintenance's schema validator):

```sql
CREATE TRIGGER maintenance_command_receipts_no_update BEFORE UPDATE ON maintenance_command_receipts BEGIN SELECT RAISE(ABORT, 'maintenance command receipts are immutable'); END
CREATE TRIGGER maintenance_command_receipts_no_delete BEFORE DELETE ON maintenance_command_receipts BEGIN SELECT RAISE(ABORT, 'maintenance command receipts are immutable'); END
CREATE TRIGGER maintenance_command_receipts_no_replace BEFORE INSERT ON maintenance_command_receipts WHEN EXISTS (SELECT 1 FROM maintenance_command_receipts WHERE id=NEW.id OR idempotency_key=NEW.idempotency_key OR (effective=1 AND NEW.effective=1 AND issue_id=NEW.issue_id AND revision=NEW.revision)) BEGIN SELECT RAISE(ABORT, 'maintenance command receipts are immutable'); END
```

For downgrade, drop all three receipt triggers and the receipt table before dropping
maintenance_issues. Keep existing follow-up and work-journal triggers.

Register the receipt model/table in any explicit current-schema table inventory
in `product_migrations`; continue calling `validate_maintenance_schema` during
startup and encrypted restore. The validator will require the new table,
revision column, indexes, checks, triggers, receipt chains and correlated audits.
Do not add a transitional migration or old-format compatibility.

## Bootstrap and callers

MaintenanceService and WorkJournalService reuse their existing Maintenance UoW;
**no new constructor dependency or bootstrap injection is needed**. Their mutation
methods require keyword-only `expected_revision`; previously keyless methods
also require keyword-only `idempotency_key`. Creation requires revision zero.
Callers performing a larger atomic operation can pass `transaction=` using an
existing MaintenanceTransaction. No nested transaction is opened.

External callers of `create_issue` must supply `expected_revision=0`. Keep
`SQLiteIssueCommandReceiptReader` injected into Operator recovery. Its typed
projection reads the immutable creation receipt: `id` is the operation UUID,
`result_issue_id` is the issue UUID, and `request_fingerprint` is the full command
envelope digest. Parent bootstrap now uses `result_issue_id` as the source target.
The reader also exposes the original `request_payload`, `response_payload` and
result `revision`; it does not consult the current issue representation.

Callers can use `command_fingerprint` from
`maintenance.application.commands` without duplicating the canonical schema:

```python
digest = command_fingerprint(
    action="create_issue",
    target_kind="issue",
    target_id=None,
    payload={"command": normalized_issue_create},
    expected_revision=0,
)
```

Both the helper and executor use the source-owned `command_request` envelope.
The issue row's retained creation fingerprint is the older domain evidence digest;
it is not the immutable command fingerprint used by recovery.
Normal Task GET may hide tombstones; historic task context facts must retain
tombstones. Follow-up replay reads the saved Maintenance response independently
of the current Task representation.

## Command and API contract

All mutations require `expectedRevision` (strict integer >= 0) and UUID
`idempotencyKey`. A successful command response preserves its resource fields
and adds required `revision` and `operationId`. Issue reads expose revision.
Receipt GET: `/api/maintenance-command-receipts/{operation_id}`.
Its response uses the same typed resource contracts as mutations, including
datetime serialization and default fields. All included mutation endpoints
document the typed HTTP 409 conflict envelope in OpenAPI.
Every included command route and receipt GET has an explicit stable camelCase
OpenAPI operation ID. Focused assertions pin the exact endpoint-to-ID mapping,
uniqueness and explicit route registration; handler renames cannot change the
generated-client contract.

Full canonical semantic payload includes action, target, revision, every input
including confirmation/reasons and patch field presence. Receipts are consulted
before current target, revision, lifecycle and external-context validation.
An identical retry returns the original response without another audit or write.
Changed payload with the same key returns idempotency_conflict; stale revision
returns stale_revision. Typed conflict metadata includes currentRevision.
An effective action increments the issue once, including replacements affecting
several child rows. No-op edits persist a receipt at the existing revision.
Every command audit binds both the request and response fingerprints to the
operation UUID. Retained validation requires contiguous effective revision chains,
canonical payloads, valid identities/ownership, matching command audit markers,
effective mutation evidence and no orphan source mutation audits. Existing
reporter, quote, assignment and work-journal historical policy validators remain
in force during workspace open and restore.

This is backend command readiness only. It does not enable consequential browser
controls or close command gates owned by other modules.

## Verification matrix

Validated October 8, 2026 in the shared worktree, with parent-owned schema and
bootstrap integration in place. Focused Maintenance suite: **46 passed**.

| Area | Proof / result |
| --- | --- |
| Happy paths | Issue create/edit/reporter/lifecycle; appointment create/edit/finish; costs create/void/replace; expense link/archive; quote create/withdraw/replace; assignment create/replace/end; follow-up and journal/correction workflows pass. |
| Invalid combinations | Existing domain policy tests plus required UUID keys and strict revisions, missing metadata, stale issue revisions and changed-key payload conflicts pass. OpenAPI checks cover every included mutation. |
| Idempotency/retry | Original creation and lifecycle replay after later writes; replay of all child workflows after terminal changes; immutable no-op receipts; follow-up replay after Task deletion pass. |
| Transaction rollback | Real SQLite caller transaction changes Finance expense data, links an expense, creates a Task, then fails: Finance/Task/Maintenance rows, revisions, receipts and audits roll back. Injected receipt persistence failure also rolls back Task/revision. Caller executes one UoW write. |
| Persistence/schema | UPDATE/DELETE triggers reject changes. With recursive triggers off, INSERT OR REPLACE collisions on operation ID, idempotency key and effective issue/revision are independently rejected and the original row survives. Missing trigger, altered current revision, missing command audit, and forged request/response with recomputed row hashes are rejected. Existing retained reporter/journal/assignment tampering tests pass. |
| Backup/restore | Actual encrypted archive restore retains original immutable response despite later writes, keyed source receipt identity/digest and current issue revision. Existing reporter/work-journal portability proof also passes. |
| Source recovery | Actual issue creation with public canonical digest reconciles through parent-composed Operator references; receipt operation UUID differs from issue UUID and resolves to the correct issue. |
| Query budget | Existing bounded list/detail and quote-comparison projection tests pass. Receipt reads use PK/unique-key lookup; no separate measured mutation-query ceiling is asserted. |

Commands run from `application/`:

```text
.venv/bin/pytest apps/server/app/modules/maintenance/tests -q --tb=short --maxfail=4
.venv/bin/ruff check apps/server/app/modules/maintenance
.venv/bin/ruff format --check apps/server/app/modules/maintenance
```

No full suite requested or run. No commits created. No baseline, bootstrap,
product inventory or root implementation-matrix files edited by Maintenance.
