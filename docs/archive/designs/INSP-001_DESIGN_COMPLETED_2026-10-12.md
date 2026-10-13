# INSP-001 — completed acceptance, October 12, 2026

Current behavior is consolidated in the [Inspection module guide](../../modules/inspections.md). The [original design](INSP-001_DESIGN.md) preserves requirements and rationale. Existing UI-001 delivery provides report, checklist, acknowledgment, correction, comparison and evidence commands. This acceptance pass adds contextual metadata/history navigation and Space identity to reports and verifies the remaining owning requirements.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | Residential pre/post reports, office template snapshots, observations, active-participant acknowledgment, finalization, correction and explicit comparison | Passed |
| Invalid combinations | Backend strict contracts, current-report uniqueness, draft-only evidence creation; browser participant end boundaries, unavailable content and separate move-out/finalization | Passed |
| Idempotency/retries | Concurrent duplicate commands, immutable original responses after supersession, evidence byte reselection and lost-response reconciliation | Passed |
| Rollback | Attachment/audit failure and commit failure roll back metadata, command history and publication | Passed |
| Persistence/schema | Retained receipt/domain-audit tampering rejected; no schema changes in this pass | Passed |
| Backup/restore | Encrypted inspection round trip preserves templates, reports, observations, acknowledgments, comparisons, evidence and correlated audit history | Passed |
| Query budgets | Context-reader comparison/observation reads each execute one joined query; bounded command lookup remains covered | Passed |
| Finance integration | Finalized pre/post inspections remove missing-report warnings; explicit Finance commands select observation and comparison sources; comparison alone creates no deductions | Passed |
| Browser/accessibility | Draft evidence archival retains reason/history, unavailable evidence cannot open, report failure preserves Lease facts; office checklist/report review passes axe and 390px reflow in both themes | Passed |

Focused commands from `application/`:

- Inspection backend suite: **27 passed**.
- Finance `test_finance.py`: **43 passed**.
- Lease/Inspection browser cases: **24 passed**, comprising 23 passing cases in the suite and the corrected office-template case passing in a focused rerun.
- Frontend lint, complete type checking, changed-file formatting, configured Ruff checks and formatting: passed.
- Vite build and local wheel packaging: passed.

Root `npm run format:check` remains incomplete because existing `demo/dataset.json` and `demo/README.md` are unformatted. The full application suite and a live S3-provider acceptance run were not performed. Existing FILE-001 provider coverage remains the source of remote-storage proof; this change uses the same provider-neutral evidence API.

Maintenance continues to own repair records and Finance continues to own deductions and settlement approval. This acceptance does not close their backlog items or unrelated review findings.
