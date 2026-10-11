# Slice 15 — Financial command readiness

Updated October 8, 2026. **Source-owned backend contracts complete.** New OPS
recovery forms and consequential browser controls are not enabled.

## Approved revision scopes

| Aggregate | Shared revision covers | Response field |
| --- | --- | --- |
| Lease rent ledger | Expectations, receipts/allocations and prepaid checks | `rentLedgerRevision` |
| Expense | Expense and refund changes/voiding | `expenseRevision` |
| Deposit account | Account, receipts, settlements, deductions, credits, sources and refunds | `depositAccountRevision` |
| Owner report | Create, patch, verify and reject | `reportRevision` |

These revisions are independent of Lease lifecycle and Space status revisions.
Owner verification also checks the rent-ledger revision. Creation advances both
scopes atomically; adoption checks but does not change the ledger. Existing Owner
and prepaid operation authorities are retained. Immutable original replay
supersedes earlier current-representation retry wording for selected commands.

## Contracts/ports

- Exact non-negative integer revisions (not booleans) and canonical UUID keys are
  required in HTTP and direct application calls.
- A Finance-owned canonical identity includes scope, action, target, expected
  revision and complete semantic payload. Allocation order is not semantic.
  Changed key reuse is a typed conflict; stale conflicts include current revision.
- Caller-transaction command operations never open another connection or unit of
  work. The neutral receipt handoff uses the caller's ledger revision/correlation.
- Exact replay precedes lifecycle and eligibility checks and returns only the
  stored original response. Responses require an operation ID and resulting
  aggregate revision. No-op patches/synchronization retain timestamps/revisions
  and still record an immutable result.
- One instant supplies command timestamps and derived result state. Monetary
  policy, duplicate checks, explicit adoption/creation and correction lineage
  remain owned by their existing workflows.

## Implementation inventory

| Workflow | Selected commands | Atomic effects |
| --- | --- | --- |
| Rent | Synchronize expectations, record/void receipt, void expectation, review timeliness | Expectations/reviews/receipt allocations, ledger and receipt/audits |
| Prepaid | Create, deposit, return, void, replace | Check, nested receipt/void, Task/reminders and both operation histories; one ledger increment per action |
| Expense | Record, patch, void; record/void refund | Expense/refund, shared revision and receipt/audits |
| Deposit | Create account; record/void receipt; create/patch/approve/complete/void settlement; add/update/delete deduction or credit; add/delete source; record/void refund | Account children, approval snapshots, shared revision and retained original results including deleted children |
| Owner | Create, patch, verify, reject | Report revision and existing operation receipt; verification-created Finance receipt/allocations and ledger receipt under the same transaction/correlation |

No new accounting or payment-execution workflow is introduced. Category
administration, new OPS recovery registrations and browser transport remain
outside this delivery and gated.

## Persistence

- Latest greenfield baseline adds `finance_command_revisions` and
  `finance_command_operations`; no compatibility migration.
- Checked scope references identify a Lease, Expense or Deposit account.
  Immutable receipts retain canonical request/result JSON and hashes, ordered
  sequence identity, globally unique Finance keys and scoped effective revisions.
- Prepaid operations share ID/key/correlation/time with their Finance receipt.
  Owner operations extend their existing table with expected/result revisions,
  effect flag and canonical request/original-result fields; reports store revision.
- Triggers reject receipt update, deletion and replacement. Current-schema and
  retained-data validation reconstruct revision chains, require aggregate roots,
  validate typed results and correlated business/operation/scope audits, and bind
  Owner/prepaid histories to their monetary effects.
- General activity excludes request/result payloads, keys, hashes and sensitive
  target IDs. Contextual recovery returns the original result.
- Existing current-schema validation is reused by workspace open, archive and
  restore; encrypted round trips preserve IDs, histories, correlations and results.

## Integration and recovery

- Required typed mutation contracts and stable OpenAPI operation IDs cover the
  selected commands. Deposit deletions require command metadata in their body.
- `GET /api/leases/{lease_id}/rent-ledger` reads the current ledger revision.
  Expense/Deposit/Owner current representations include their aggregate revision.
- `GET /api/finance/command-operations/{idempotency_key}` recovers typed original
  rent, prepaid, Expense or Deposit results through one indexed read-only lookup.
- `GET /api/owner-rent-report-operations/{idempotency_key}` recovers the existing
  Owner operation's typed immutable result with one indexed read-only lookup.
- Expense list revision hydration is bounded/set-based; Deposit account revisions
  are projected in bounded batches. Empty revision inputs issue no query.
- Business fixtures use explicitly named command helpers. Service methods are not
  replaced with wrappers that silently supply required arguments.

## Focused validation matrix

| Area | Proof |
| --- | --- |
| Happy paths | Rent commands, Expense/refunds, Deposit lifecycle/children, prepaid lifecycle and Owner adoption/creation |
| Invalid combinations | Strict signatures/revisions/keys, stale scope/ledger checks, changed reuse and existing monetary/adoption/lineage policy |
| Idempotency/retry | Original responses after later changes, voids, review or deletion; no-op results; concurrent rent same-key submission |
| Rollback | Receipt/allocations/audits; Expense refund and Deposit child; prepaid check/Task/reminder; Owner verification plus Finance ledger/receipt |
| Persistence/schema | Append-only guards, canonical request/result history, contiguous revisions, rewritten result and missing correlated business audit rejection |
| Backup/restore | Encrypted preservation of all Finance scopes and Owner receipts; prepaid replacement/check/Task/reminder histories and exact replay results |
| Query budgets | One-SELECT command recovery; one bounded revision query for up to 500 scopes and zero for empty; constant Expense-page projection cost |

Validation: **246 focused tests and 90 subtests passed** across Finance,
Owner-report, changed Maintenance/OPS coverage boundaries, Audit and workspace
baseline/open/encrypted backup tests. Ruff check and format-check passed on all
44 changed Python files; `git diff --check` passed. No full application suite or
frontend validation is claimed for this backend slice.
