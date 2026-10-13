# FIN-006 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Finance guide](../../modules/finance.md#rent-schedule-and-receipts); the [original design](FIN-006_DESIGN.md) preserves rationale. Existing immutable method snapshots and editable prior-receipt suggestions were delivered earlier. This pass closes explicit browser method review, Other-note disclosure, safe-reference draft validation and focused acceptance. No persistence/schema changes or payment-provider connection were added.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | All six actual methods, optional safe references, required Other explanation, editable latest-receipt suggestion and receipt detail | Passed |
| Invalid combinations | Missing/unsupported kinds, raw/unsafe references, Other-note pairing and lengths; incomplete recovery rejects raw references and trims safe masks | Passed |
| Idempotency/retries | Method-sensitive fingerprints, changed reuse, original responses after void/source changes and independent replacement snapshots | Passed |
| Rollback | Receipt/allocations/revisions/results/audit remain one atomic Finance command; shared recovery preserves unresolved requests | Passed |
| Persistence/schema | Exact current schema and safe method metadata checks reject corrupted reference values; contextual snapshots and global activity redaction | Passed |
| Backup/restore | Encrypted receipt method snapshot and original-result round trips retain safe fields and stable history | Passed |
| Query budgets | Suggestion uses at most four SELECTs including lease/location validation, with an ordered limited receipt lookup and no writes; method review adds no new lookup queries or tables | Passed |
| Browser/accessibility | Every method, editable prefills, raw-reference blocking, clearing stale method fields, correction history; shared narrow light/dark Money and component scenarios | Passed |

Focused validation from `application/`:

- `test_finance.py`, `test_commands.py`, `operator/tests/test_finance_command_forms.py`: **81 passed** together.
- `money.spec.ts`: **35 passed**, including seven new method-selection/suggestion cases.
- Shared component tests: **6 passed**; command-recovery tests: **6 passed**.
- Changed-Python Ruff checks/formatting, frontend lint, complete type checking, changed-file formatting, reproducible generated contracts, Vite build, local wheel packaging and diff whitespace: passed.

Root `npm run format:check` remains incomplete only because of existing `demo/dataset.json` and `demo/README.md` formatting. The informational bundle-size warning remains. The full application suite and a separate manual accessibility audit were not run. FIN-007 and other Finance features retain separate acceptance gates; no pending review finding is closed by this documentation consolidation.
