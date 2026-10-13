# MAINT-002 — completed acceptance, October 13, 2026

The remaining quote/assignment browser gate is complete. Current behavior is consolidated in the [Maintenance guide](../../modules/maintenance.md#workflow-boundaries); the [original design](MAINT-002_DESIGN.md) retains rationale. No financial transaction, Provider ranking/contact, implicit issue/work completion or database migration was added. MAINT-003 retains its separate acceptance gate.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Exact quote comparison, paired quoted dates, explicit quote-backed/direct assignment, ending, withdrawal/replacement and atomic reassignment | Passed |
| Invalid combinations | Client paired-date/direct/reassignment checks; server issue/Provider/quote identity, expiry, lifecycle and one-current-assignment rules | Passed |
| Override/retry | Avoid status requires operator override; lost reassignment response makes one dispatch and recovers one replacement; backend original-response/stale/changed-key proofs | Passed |
| Rollback | Existing shared issue/child receipt, Task/Finance/audit transaction rollback tests | Passed |
| Persistence/schema | Immutable quote/assignment history, replacement single-use, audit snapshots and quoted-date pairing validation | Passed |
| Backup/restore | New encrypted round trip compares quote schedules/documents and assignment history; stable file IDs and original assignment receipt preserved | Passed |
| Query budgets | Existing bounded set-based comparison with document counts and Provider-state batches; browser comparison makes one source read, no per-quote Provider/file requests | Passed |
| Independent effects | Browser confirms issue remains open, no Expense or Task is created, and engagement ending is not work completion; documents remain Files-owned | Passed |

## Results and limitations

- Focused Maintenance model/workflow/command-readiness suites: **47 passed**.
- Work browser: **32 passed**, against the packaged UI and real temporary workspaces; includes expanded comparison/quote replacement and new avoided-Provider/reassignment recovery coverage.
- Shared components and recovery: **6 + 6 passed**.
- Changed Python Ruff check/format, frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace checks passed.
- Repository-wide `npm run format:check` remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`. The existing bundle-size warning is informational.
- Only focused suites ran; no independent manual usability review or unrelated review-queue closure is claimed.
