# OWNER-003 — completed acceptance, October 13, 2026

The remaining Owner-report browser gate is complete. Current behavior is consolidated in the [Owner accounting guide](../../modules/owner-accounting.md); the [original design](OWNER-003_DESIGN.md) retains rationale. Finance remains the only income authority. No Owner percentages, statements, disbursements, external reporting channel or schema migration was added.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Browser claim/edit/reject and adopt/create verification, exact cents/allocations, receipt drill-down, terminal replacement prefills | Passed |
| Historical context | Archived Party selected after supported ownership ending/Party archival; backdated payment uses retained Owner identity without restoring ownership or creating income | Passed |
| Invalid combinations | Strict request fields/dates, exclusive receipt mode, invalid allocation totals, missing evidence, Finance idempotency reuse, duplicate creation and last-available-evidence archival | Passed |
| Idempotency/retry | Duplicate receipt conflict requires explicit adoption; lost verification response recovers one operation/receipt with one dispatch; stale ledger preserves note for explicit review | Passed |
| Transaction rollback | Existing SQLite tests roll back Finance receipt/allocation writes when Owner operation fails, and reject stale Finance/report revisions | Passed |
| Persistence/privacy | Exact schema/tampered correlated-history rejection, creation/adoption provenance, nested evidence redaction and original-result validation | Passed |
| Replacement/backup | New exact report/receipt lineage test rejects adoption of the active predecessor, voids it through Finance, verifies its exact successor, and compares reports/operations/receipts/allocations/files/links after encrypted restore; existing restore test preserves original verification result and operations | Passed |
| Query budgets | One-versus-three report pages execute the same bounded SELECT count (at most six), including zero-evidence projection; browser filters execute bounded source reads | Passed |
| Independent effects | Pending/rejected/replacement claims remain non-income; only one active compatible Finance receipt counts; archival/replacement refresh preserves original committed response | Passed |

## Results and limitations

- Focused OWNER-003 backend suite: **23 passed**.
- Money browser: **40 passed**, against packaged UI and real temporary workspaces.
- Shared components and recovery: **6 + 6 passed**.
- Changed Python Ruff check/format, frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace checks passed.
- Repository-wide `npm run format:check` remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`. The existing bundle-size warning is informational.
- Only focused suites ran; no independent manual usability review or unrelated review-queue closure is claimed.
