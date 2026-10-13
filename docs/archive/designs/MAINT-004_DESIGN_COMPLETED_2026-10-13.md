# MAINT-004 — completed acceptance, October 13, 2026

The remaining reporter-attribution browser gate is complete. Current behavior is consolidated in the [Maintenance guide](../../modules/maintenance.md); the [original design](MAINT-004_DESIGN.md) retains rationale. No workforce/authentication model, fake Party, implicit reporter inference or persistence migration was added. Relationship rejection preserves the existing typed `409 reporter_relationship` contract; it was not changed to the original plan's generic business-validation `400`.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Owner Party creation/correction, manager/staff Local operator, tenant after explicit lease execution; Party-reporter communication prefill and stored list/detail snapshots | Passed |
| Invalid combinations | Typed role/subject rules and client guard; draft tenant rejection without an issue; backend occupancy/participant/date boundaries and missing attribution rules | Passed |
| Historical selection | Active-only search default, archived toggle, required confirmation/reason and correction at original report date; browser ownership ended through Portfolio then Party archived through supported API | Passed |
| Idempotency/retry | Reporter-sensitive fingerprints, stale/changed-key conflicts and immutable issue/child receipts in backend command tests; shared dirty-input/recovery tests | Passed |
| Rollback | Required issue/child/audit effects remain atomic under command-receipt tests | Passed |
| Persistence/privacy | Reporter correction-chain tampering rejected; raw historical/correction context retained while general activity redacts identity/narrative; communication participants unchanged after issue correction | Passed |
| Backup/restore | Encrypted stable attribution plus linked Communications; original receipt/source-reader preservation | Passed |
| Query budgets | Existing stored-reporter list isolation and bounded communication summaries; browser list remains row-lookup-free; identity search capped at 25 | Passed |

## Results and limitations

- Focused Maintenance model/workflow/command-readiness and Communications suites: **76 passed**.
- Work browser suite: **31 passed**, against the packaged UI and real temporary workspaces, including three new reporter-specific cases.
- Shared components and recovery: **6 + 6 passed**.
- Changed Python Ruff check/format, frontend lint/typecheck, changed-file Prettier, contract reproducibility, package build and diff whitespace checks passed.
- The historical-owner test fixture injects a past Property clock through the real Portfolio application service. Ownership ending and Party archival use supported HTTP commands; no raw-table edits, extra tables or production test endpoints are introduced.
- Repository-wide formatting remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`. The existing bundle-size warning is informational.
- Only focused suites ran; no independent manual usability review or broader review-queue closure is claimed.
