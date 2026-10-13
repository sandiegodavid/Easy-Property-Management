# OPS-001 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Operator guide](../../modules/operator.md). The [original design](OPS-001_DESIGN.md) preserves the 13 accepted decisions. This closes Operator bootstrap, preferences, directories/overviews, metadata search, coverage and recoverable forms, not Home/DASH aggregation or later optional source registrations.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Ready/unavailable bootstrap, preferences, property/owner contexts, metadata search, area coverage and registered source-command recovery | Passed |
| Invalid combinations | Capability/membership failures, unknown contracts/extra fields, bounded input/capacity, expired or mismatched cursors and stale source reviews | Passed |
| Snapshot/bounds | One read transaction/instant, filters before count/limit, complete matching totals, bounded child previews, independent section/group failures and fixed query budgets | Passed |
| Retry/rollback | Immutable original results, identical-key replay, changed reuse/stale conflict, dirty-form preservation, receipt/audit rollback and explicit unknown-effect reconciliation | Passed |
| Coverage/privacy | Required gaps cannot be acknowledged away; source revisions invalidate reviews; allowed non-applicability/provenance, metadata-only search and secret-free recovery summaries | Passed |
| Persistence/backup | Append-only reviews/operations and tampering rejection; encrypted preference/recovery/coverage/search portability, original receipt preservation and old-runtime cursor invalidation | Passed |
| Browser integration | Typed targets, archived opt-in and hidden destinations, independent continuations, fresh stale-group restart, explicit Property money periods, themes/keyboard and original-result recovery | Passed |

## Validation boundary

Focused Operator backend validation excludes `test_home_api.py`, `test_home_composition.py`, `test_home_contracts.py`, `test_home_money.py` and `test_coverage_attention.py`, which are DASH-specific. Browser validation covers `context-reads.spec.ts`, `search-coverage.spec.ts`, `recovery-page.spec.ts` and `shell.spec.ts`. Dated counts are recorded in [browser evidence](../../ui/validation.md).

Operator backend result: **519 passed**, including source-owned recovery integrations, consistent/bounded compositions, retained-data rejection and encrypted restore.

Packaged browser acceptance: **20 passed**. Shared recovery and component regressions: **6 + 6 passed**. Real temporary workspaces prove commits and contextual/archive navigation; controlled unavailable/stale responses complement the backend rollback and cursor tests.

Frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace pass. Repository-wide formatting remains blocked by unchanged `application/demo/dataset.json` and `application/demo/README.md`; bundle-size warnings are informational. No full application suite or independent manual usability review ran. No unrelated pending review findings or domain consequences are closed by this acceptance.
