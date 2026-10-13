# COM-001 — completed acceptance, October 13, 2026

The remaining browser gate is complete. Current behavior is consolidated in the [Communications guide](../../modules/communications.md); the [original design](COM-001_DESIGN.md) retains rationale and the immutable command contract. This closes manual ledger delivery only, not mail ingestion, message delivery or automation. No backend persistence or API contract changed.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Browser draft/edit/record/correct, optional follow-up, active owner/contact selection, local occurrence and timeline filters; backend role-neutral recording | Passed |
| Invalid combinations | Backend participant/contact eligibility, required correction reason, typed metadata and context validation; recorded/superseded UI uses explicit lifecycle actions rather than edit | Passed |
| Idempotency/retry | Original receipts replay after later mutations; stale/changed keys and no-op receipts; lost browser recording response creates one communication and one Task | Passed |
| Rollback | Required Task/audit failures roll back commands and allow original-key retry | Passed |
| Persistence/schema | Exact schema, canonical receipt tampering, contiguous revision history, immutable operations and correlated follow-up audits | Passed |
| Backup/restore | Encrypted Communications dataset round trip preserves snapshots, correction lineage, operations, Tasks and exact replay results | Passed |
| Bounded reads | Existing cursor/filter scan budgets and one-SELECT receipt/replay tests; Work directory has no per-row HTTP reads; new participant search is capped at 25 and detail contact reads stay in command review | Passed |
| Privacy and shared UI | Backend global/contextual audit redaction; browser sensitive-context/no-delivery cues; shared components and recovery behavior | Passed |

## Validation commands and limitations

- `communications/tests/test_communications.py`: **30 passed**.
- `apps/web/tests/work.spec.ts`: **26 passed**, against the rebuilt packaged UI and real temporary workspaces; includes two new Communications cases and expanded draft/correction coverage.
- Shared component and recovery suites: **6 + 6 passed**.
- Frontend lint, complete typecheck, changed-file Prettier, contract reproducibility, package build and diff whitespace checks passed.
- Repository-wide `npm run format:check` remains blocked only by unchanged `application/demo/dataset.json` and `application/demo/README.md`. The existing bundle-size warning is informational. No Python files changed.
- Only focused suites ran; no separate manual usability acceptance or unrelated review-queue closure is claimed.
