# Portfolio manual-status command readiness

Manual occupancy, correction, cancellation, replacement/rescheduling, availability,
and classification commands reuse the existing status revision and operation table.
Their success contract requires `operationId` and a positive `revision`. GET status
keeps its existing shape, including the optional nullable `operationId`.

Retained receipt reads:

- `GET /api/portfolio/status-operations/{operation_id}`
- `GET /api/spaces/{space_id}/status-operations/{idempotency_key}`

Both return `operationId`, `spaceId`, `idempotencyKey`, `revision`, `committedAt`, and
the original typed `result`. Lookup does not rebuild status or advance the revision.
Missing operations, another space's key, and lease-owned receipts return 404. The
key lookup supports reconciliation when a client never received the operation ID.

The fingerprint includes the normalized command, action/target, and expected
revision. Exact replay precedes revision and lifecycle checks and returns the
original result after subsequent commands or archival. Changing a payload, target,
or expected revision while reusing a key returns `portfolio_status_payload_conflict`.
A fresh key with an obsolete revision returns `portfolio_status_revision_conflict`.
Archived-space and source-owned-state conflicts return
`portfolio_status_lifecycle_conflict`. These 409 responses retain the full typed
current status, captured inside the command transaction. Combined classification
checks both axes before writing either one. Existing busy-writer handling retains
the generic `portfolio_conflict` code.

## Parent baseline integration

The sole DDL integration requirement is exported by
`app.modules.portfolio.infrastructure.receipt_triggers.STATUS_OPERATION_TRIGGERS`.
The parent has integrated it after the existing operation table/index creation:

```python
from app.modules.portfolio.infrastructure.receipt_triggers import STATUS_OPERATION_TRIGGERS

for sql in STATUS_OPERATION_TRIGGERS.values():
    op.execute(sql)
```

Drop each exported trigger before dropping the table in baseline `downgrade()`.
Names and semantics:

| Trigger | Required behavior |
| --- | --- |
| `space_status_operations_no_replace` | Reject insertion colliding with an existing ID, global key, or space/revision, including SQLite `INSERT OR REPLACE` without recursive triggers. |
| `space_status_operations_no_delete` | Reject every receipt deletion. |
| `space_status_operations_conditional_update` | Reject every update except one object-valued `consumerResult` attachment to an existing lease receipt without that field. Identity, fingerprint, revision, timestamp, and all original JSON facts must remain unchanged. |

The update exception compares JSON tree paths, types, and scalar values, so the
existing lease adapter may reserialize the original object. It rejects malformed
JSON, a null/array attachment, duplicate top-level `consumerResult` keys, changes
to original fields, and attachment replacement/removal after completion. The
existing lease command attaches its response in the same transaction as its source
timeline and audit writes. Its behavior and interfaces are unchanged; the trigger
does not introduce a separate pending-operation workflow.

Portfolio validation checks exact trigger bodies, global key uniqueness, contiguous
retained revisions, receipt identities/timestamps, the full typed manual snapshot,
and matching space references. It also verifies the existing append-only audit
trigger bodies. There are no new tables/columns, compatibility migrations, or
bootstrap/product-validator wiring requirements.

## Focused validation matrix

| Area | Real SQLite coverage |
| --- | --- |
| Happy paths | Typed manual responses; lookup by ID and key; real lease execute and response attachment. |
| Invalid combinations | Changed command/revision/key target; stale revision; archived space; source-owned availability during combined classification; invalid mutation response identity. |
| Idempotency/retry | Identical API original result replay after a later command and archival; no audit duplication; existing lease execution replay. |
| Transaction rollback | Failure on the second classification audit write rolls back status and the first audit event; receipt remains absent; retry succeeds. |
| Persistence/schema | Update/delete/replacement denial; one-time conditional attachment; missing/weakened triggers; offline snapshot corruption and missing retained revisions. |
| Backup/restore | Actual encrypted archive/restore preserves original manual receipt and exact replay after a later change. |
| Query budget | Operation-ID lookup performs one receipt SELECT without status hydration. Existing Portfolio bounded context/source-page tests remain in the focused suite. |

Run from `application/`: `.venv/bin/pytest apps/server/app/modules/portfolio/tests -q`.
Run `ruff check` and `ruff format --check` on changed Portfolio Python files using
`application/pyproject.toml`. Broader lease/inspection caller regression belongs to
the parent integration owner. No commits are part of this task.

Validation on 2026-10-08 against the parent-integrated baseline: **62 tests and 29
subtests passed**. `ruff check` and `ruff format --check` passed for all eight
changed Portfolio Python files. The scoped `git diff --check` passed. No test DDL
overlay or production-validation bypass remains.
