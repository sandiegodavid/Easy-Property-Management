# COM-001 Communications command readiness

## Owning contract

Create draft or recorded, patch draft, record draft, and correct recorded history require a UUID `idempotencyKey` and an integer `expectedRevision`. Both are mandatory in HTTP inputs and application service calls. Create uses revision 0. Other commands use the revision returned by a fresh detail GET. Negative values, booleans, and non-integer revisions are invalid.

One communication revision covers payload, participants, links, recording, and correction. Creation starts at 1. Each accepted mutation increments it once, including a change affecting only participants or links. Correction increments the source revision and creates its replacement at revision 1; subsequent corrections retain the complete lineage. Empty and semantically unchanged draft patches produce an explicit `no_op` receipt, retaining revision and updated timestamp without change audits.

Inside the existing immediate transaction, commands look up their operation key first. Matching requests return the immutable original response before consulting current revision, lifecycle, party/link eligibility, or live task projections. Changed input or expected revision with a retained key raises typed `idempotency_conflict` (HTTP 409). A new key with a stale revision raises typed `stale_revision` (409) with required `currentRevision`. New-key lifecycle checks follow revision checks. Rejected commands leave no receipt.

## Immutable receipt and fresh detail

Command responses contain the original detail plus `operationId`, `revision`, and `outcome` (`applied` or `no_op`). The same response is stored canonically in the existing immutable `communication_operations` row. `GET /api/communications/operations/{operation_id}` returns that receipt under its stable operation UUID. Unknown operations return 404. Replay and receipt lookup each use one operation SELECT without rebuilding detail or issuing writes.

`GET /api/communications/{communication_id}` is separately fresh: it returns current communication revision, lifecycle, participants, links/context, and follow-up task projections. Receipts remain historical even after correction, task changes, tombstones, or changed link context. Callers should retain the receipt as proof of the command outcome and refresh detail before composing a new command; the receipt's revision is not a claim about current state. Lookup and commands use the existing workspace readiness/writer-lock dependency.

## Persistence and parent integration

COM tables are generated from the owning SQLAlchemy models in the baseline. Required non-null fields are:

| Table | Fields |
| --- | --- |
| `communications` | `revision` INTEGER, check `revision >= 1` |
| `communication_operations` | `expected_revision`, `result_revision` INTEGER; `outcome`, `request_json`, `response_json` strings |

Operation checks enforce nonnegative expected revision, positive result revision, `applied`/`no_op` outcomes, patch-only no-op outcomes, create expectation 0, and non-create expectations at least 1. Model lifecycle checks allow a replacement communication to be superseded again while retaining its original correction reason and backward link. No defaults or compatibility migration are added.

Install all entries in `communications.infrastructure.schema_validation.OPERATION_TRIGGERS` and drop all three on baseline downgrade. Preserve the existing update/delete guards and add the insert guard against SQLite `INSERT OR REPLACE` rewriting receipts when recursive triggers are disabled:

```sql
CREATE TRIGGER communication_operations_no_replace BEFORE INSERT ON communication_operations WHEN EXISTS (SELECT 1 FROM communication_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key) BEGIN SELECT RAISE(ABORT, 'communication operations are immutable'); END
CREATE TRIGGER communication_operations_no_update BEFORE UPDATE ON communication_operations BEGIN SELECT RAISE(ABORT, 'communication operations are immutable'); END
CREATE TRIGGER communication_operations_no_delete BEFORE DELETE ON communication_operations BEGIN SELECT RAISE(ABORT, 'communication operations are immutable'); END
```

Keep append-only audit history: `audit_events_no_update` and `audit_events_no_delete` raise `audit events are append-only`. COM uses existing audit policies, including sparse activity redaction, and adds revision to contextual lifecycle snapshots. No-op operations have no change-audit event. Receipt creation, payload/children, follow-up insertion, and all audits use the existing transaction and connection; failures roll back together. No new repositories or bootstrap dependencies are required.

The exact schema validator checks columns, types, constraints, indexes, foreign keys, and immutable receipt triggers. Retained validation checks canonical request JSON, reconstructed typed payload, SHA-256 request fingerprint, original response shape and identity, request/result agreement, result and source revision/audit correlation, historical child/task snapshots, no-op receipt agreement with prior history, contiguous revision history, and current state agreement with audit history. It does not rewrite receipts during validation or restore.

## External callers

Service signatures append required `expected_revision` to `create(command, key, expected_revision)`, `patch(id, command, key, expected_revision)`, `record(id, follow_up, key, expected_revision)`, and `correct(source_id, command, reason, key, expected_revision)`. HTTP clients must send `expectedRevision` in all four command bodies and consume typed receipts. Parent-owned frontend/generated-contract and external test updates are outside COM ownership.

`communications.application.service.command_fingerprint(action, target, command, expected_revision)` exposes the exact canonical request hash for recovery. Actions are `created`, `patched`, `recorded`, `corrected`; create target is `None`, other targets are communication IDs. Create/patch take their typed commands, record takes `FollowUpInput | None`, and correction takes `(CommunicationCommand, trimmed_reason)`. OPS create recovery passes revision 0 and must replace imports of the removed private `_fingerprint` helper.

`SQLiteCommunicationReceiptReader.receipt(connection, key)` preserves `id` (operation UUID), `result_communication_id`, and `request_fingerprint`, matching `bootstrap/operator_recovery.resolve_attempt`. It also returns `result_revision`, `outcome`, and `response_json`; it never resolves fresh detail. External COM callers include OPS context/recovery tests and Maintenance workflow tests. New task links must reject tombstones in parent-owned context validation; retained task links/FKs must remain valid, and fresh task projections must hide tombstones while historical receipts remain intact.

## Validation matrix

| Area | Focused proof |
| --- | --- |
| Happy paths | Draft and direct recorded creation, participant/link/payload edits, record, correction and correction chains |
| Invalid combinations | Required key/revision at application and HTTP boundaries; strict revision types; draft-only edits/recording; correction reason and lifecycle checks |
| Idempotency/retry | Every command's original receipt after later mutation; changed-key conflict before stale/lifecycle; stale response contains current revision; retry after failure |
| No-op | Empty and unchanged payload/participants/links persist a receipt with no revision, timestamp, or audit increment |
| Transaction rollback | Fail after follow-up insert for create/record/correct; communication/operation/task/audit counts remain unchanged; same key succeeds on retry |
| Persistence/schema | Canonical fingerprint and payload tampering; result/audit correlation; immutable update/delete triggers; historical revision continuity |
| API/OpenAPI | Stable receipt lookup, fresh detail distinction, missing metadata rejection, typed receipts and discriminated 409 conflicts |
| Backup/restore | Encrypted backup with direct creation and draft/patch/record/correction receipts; later mutations; receipt lookup and exact replay after restore; full restored-schema validation |
| Query budget | Replay and operation-ID lookup use one SELECT each, with no child/detail reads or writes |

Run focused tests with `application/.venv/bin/python -m pytest application/apps/server/app/modules/communications/tests/test_communications.py -q` from the repository root. Run Ruff check and format check on changed COM Python files using `application/pyproject.toml`. Shared baseline/bootstrap/product-schema integration must be complete for configured workspace and encrypted restore tests.

Validated on 2026-10-08 after parent integration: focused COM suite **30 passed, 18 subtests passed**; Ruff check and format check passed for all 21 COM Python files using `application/pyproject.toml`; owned-file diff whitespace check passed. Configured workspace/API and encrypted backup/restore tests ran against the real integrated baseline. No commits were created.
