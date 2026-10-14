# OWNER-004 — completed source acceptance, October 13, 2026

The concern source workflow is complete; current behavior is consolidated in the [Owner Management guide](../../modules/owner-management.md). The [original design](OWNER-004_DESIGN.md) retains rationale. The operator explicitly confirmed keeping Home owner-action presentation in [DASH-001](DASH-001_DESIGN_COMPLETED_2026-10-14.md); Home remains gated there. No source lifecycle, schema migration or money authority was added.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Browser create/edit, explicit resolution/dismissal, optional follow-up, retained/current context, vacancy snapshots and linked conversation drill-down; backend all lifecycle/reopen paths | Passed |
| Invalid combinations | Space/Lease/Tenant context rules, historical confirmation/reason, independent duplicate reason, same-source validation, malformed keys/revisions and unresolved Property archive guard | Passed |
| Historical context | Supported ownership ending and Party archival followed by explicitly confirmed backdated concern; no synthesized Local-operator Owner | Passed |
| Idempotency/retry | Lost follow-up response recovers one Task with one dispatch; original operations survive later Concern/Task state; same-key concurrency and changed-key rejection | Passed |
| Rollback | Existing source/audit/receipt/Task failure tests prove atomic rollback and stale-revision rejection | Passed |
| Persistence/privacy | Exact schema/operation/audit tampering rejection, append-only receipts, retained snapshots and redacted general activity | Passed |
| Correction/backup | Dismissed target corrected into one successor without erasing predecessor; expanded encrypted restore compares Concern/Task/Communication rows, links, lineage, operations and correlated audits, then replays original results | Passed |
| Query budgets | Existing one-read recovery, bounded/set-based concern/detail/attention tests and Work directory no-per-row HTTP proofs | Passed |
| Independent effects | Concern resolution leaves Task open; vacancy concern leaves Space status/revision unchanged; conversation creation retains concern revision | Passed |

## Results and limitations

- Focused Owner Management suites: **94 passed**.
- Work browser: **39 passed**, against packaged UI and real temporary workspaces.
- Shared components and recovery: **6 + 6 passed**.
- Python changed-file Ruff check/format, frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace checks passed.
- Repository-wide `npm run format:check` remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`. The bundle-size warning is informational.
- No full suite or independent manual usability review ran. Home/DASH presentation and unrelated review findings are not closed by this acceptance record.
