# VEND-002 — completed acceptance, October 12, 2026

Current behavior is consolidated in the [Provider guide](../../modules/providers.md). The [original design](VEND-002_DESIGN.md) preserves requirements and rationale. Existing commands provide manual reputation-link creation, editing, archive/restore and original-result recovery. This pass adds safe explicit external-review actions, verbatim URL/context display and bounded contextual history for each link.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | Browser Google, Yelp, Angi and named-other links, canonical URLs, notes/dates, edit/archive/restore and count-only summaries | Passed |
| Invalid combinations | Unsafe URLs, unnamed other sources, duplicate active source/URL, parent/child lifecycle, future dates and strict request shapes | Passed |
| Idempotency/retries | Original child receipts, no-op, changed reuse, concurrent writes and interrupted browser edit reconciled with one dispatch | Passed |
| Transaction rollback | Audit failure rolls back reputation mutation, Provider revision and operation receipt | Passed |
| Persistence/schema | Weakened reputation partial indexes and malformed retained metadata rejected | Passed |
| Backup/restore | Encrypted Provider round trip preserves reputation ID, canonical URL and correlated audit history | Passed |
| Query budgets | Bounded Provider hydration and indexed child receipt lookup; browser issues no per-link audit request before history is opened | Passed |
| Privacy/UI | General activity redacts URLs/notes; selected history shows original context; no automatic external requests; external links isolate opener/referrer; narrow Provider review passes axe in both themes | Passed |

Validation from `application/`: **60 backend tests** in `test_vendors.py` and `test_child_command_readiness.py`; **4 browser cases** selected by `reputation|Provider search` (two existing cases passed together, then both new cases passed after correcting their selectors); lint, complete type checking, changed-file formatting, Vite build, local wheel packaging and diff whitespace checks passed.

Root `npm run format:check` remains incomplete due to existing formatting in `demo/dataset.json` and `demo/README.md`. The full application suite and real review-site connectivity were not tested. VEND-002 stores operator-curated pointers; live review integrations and category acceptance retain their separate backlog status.
