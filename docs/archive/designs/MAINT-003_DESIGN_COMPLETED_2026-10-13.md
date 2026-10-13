# MAINT-003 — completed acceptance, October 13, 2026

The remaining journal browser gate is complete. Current behavior is consolidated in the [Maintenance guide](../../modules/maintenance.md#work-evidence-and-completion); the [original design](MAINT-003_DESIGN.md) retains rationale. Existing backend contracts/schema are preserved. No implicit issue, assignment, appointment, Task, Finance or manual Provider-history mutation was added.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Append start/progress/blocked/note/completion; report versus operator verification; optional assignment; quoted/actual timing and separate Provider history | Passed |
| Invalid combinations | Completion outcome requirements, Provider-report assignment requirement, same-issue membership, correction single-use and terminal historical confirmation | Passed |
| Idempotency/retry | Browser loses committed correction response, reconciles original receipt with one dispatch and two retained entries; existing source revision/retry proofs | Passed |
| Rollback | Existing Maintenance shared issue/child/audit fail-closed transaction tests | Passed |
| Persistence/schema/privacy | Immutable/nonbranching journal tests, malformed/missing/orphan audit and future-occurrence workspace rejection; contextual correction/outcome retained and redacted from general activity | Passed |
| Backup/restore | Encrypted round trip compares original/correction journal page, original receipt, journal audit events, stable file/link IDs, archived reason, verified timestamp and exact bytes | Passed |
| Query budgets | One-versus-20 journal rows use the same bounded SELECT count (at most six); browser pages 20 + 1 rows with reset; no per-row Provider reads | Passed |
| Independent effects | Partial verified correction removes the completed-work summary but leaves issue open; terminal note does not reopen; assignments remain current and manual Provider history stays empty | Passed |

## Results and limitations

- Focused Maintenance model/workflow/command-readiness suites: **49 passed**.
- Work browser: **34 passed**, against packaged UI and real temporary workspaces.
- Shared components and recovery: **6 + 6 passed**.
- Changed Python Ruff check/format, frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace checks passed.
- Repository-wide `npm run format:check` remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`. The existing bundle-size warning is informational.
- Only focused suites ran; no independent manual usability review or unrelated review-queue closure is claimed.
