# VEND-CAT-001 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Provider guide](../../modules/providers.md#categories-and-selection); the [original design](VEND-CAT-001_DESIGN.md) retains rationale. This closes category catalog/assignment delivery, not legal engagements, spreadsheet import, AI recommendations or future SaaS export implementation.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Seven deterministic seeds; Settings catalog create/rename/describe/reorder/archive/restore; multi-category Provider creation, active category filtering and explicit Uncategorized | Passed |
| Invalid combinations | Normalized Unicode whitespace uniqueness, malformed UUID/unknown fields, missing/archived category membership and stale source/category revisions | Passed |
| Lifecycle/retry | Unchanged patches and identical archive reason are audit-free business no-ops; changed reason conflicts; concurrent edits/retries, original immutable results and interrupted category-create recovery | Passed |
| Rollback | Every category/assignment command fails closed on receipt/audit write; multi-category creation validates atomically | Passed |
| Persistence | Exact schema, stable seed IDs/idempotency identities and registered initial snapshot anchoring, canonical fingerprints and correlated audit/receipt tampering rejection | Passed |
| Backup/restore | Existing encrypted round trip compares category/assignment/command tables and Provider audits, then recovers original category and assignment responses | Passed |
| Query budgets | Existing bounded Provider pages, Unicode cursor ordering and one/100/200-row query-budget tests; bounded batch context and one-query category receipt recovery | Passed |
| Taxonomy separation | Services survive category rename/archive/restore unchanged; provider archival removes effective categories but retains history; no Maintenance/Finance/Legal side effect | Passed |

## Validation and limitations

- Provider focused backend suites: **111 passed**.
- Restricted static-delivery suite: **40 passed**, including direct Settings category navigation without opening a workspace.
- Browser proof: **2 new category cases + 7 existing Provider/category regressions passed**. `provider-categories.spec.ts` covers Settings, effective counts/filter reload, Services separation, archive/restore and original receipt recovery; `workflows.spec.ts` covers existing contextual commands. See [browser evidence](../../ui/validation.md).
- Frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace checks passed.
- Repository-wide formatting remains blocked by unchanged `application/demo/dataset.json` and `application/demo/README.md`; bundle-size warnings are informational.
- No full suite or independent manual usability review ran. No unrelated review findings or future import/engagement/AI workflows are closed by this acceptance.
