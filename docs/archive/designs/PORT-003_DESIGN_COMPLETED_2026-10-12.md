# PORT-003 — completed acceptance, October 12, 2026

PORT-003 is complete. Current behavior is consolidated in the [Portfolio module guide](../../modules/portfolio.md). The [original design](PORT-003_DESIGN.md) preserves the original requirements and rationale. UI-001 Slices 48–53 delivered the source forms and contextual reads; Slice 57 recorded shared integration acceptance. This record closes the remaining PORT-003 display and validation gaps with focused tests.

## Delivered scope

- Portfolio and Property detail show source-owned occupancy/availability counts. Portfolio counts link to matching property filters and disclose their scope and captured instant; property summaries link to source Spaces.
- Bounded property cards use plain-language occupancy/availability labels and offer status review when classification is needed. Combined ownership, occupancy, availability and attention filters retain source-owned totals and cursors.
- Space detail distinguishes recorded intention from effective availability, displays dates, source ownership, attention and scheduled history, and links Lease-owned occupancy to Leasing. Archived Spaces retain history without manual correction actions.
- Existing classification, occupancy, availability, correction, scheduled replacement/cancellation/rescheduling, revision and original-result recovery commands remain the authorities. Invalid available-later input receives a typed validation error during OPS attempt preparation and remains editable.
- The portfolio summary now executes one SQL aggregate under the owning read transaction instead of hydrating every Property, ownership, Space and status history. Each property's local date comes from the same captured UTC instant.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | `portfolio-status.spec.ts`: unknown review/classification, independent availability, portfolio/property summaries, scheduling, correction, rescheduling/cancellation and source drill-down | Passed |
| Invalid combinations | Missing available-later date rejected without writes; owning suites cover timeline collisions, source ownership, archived lifecycle and stale revisions | Passed |
| Idempotency and retries | Stale form keeps input; explicit revision review; interrupted availability response reconciles one write; existing saved correction and original-receipt tests | Passed |
| Transaction rollback | Portfolio command-readiness tests cover audit-failure rollback; rejected OPS attempt leaves source state unchanged | Passed |
| Persistence/schema | Complete Portfolio suite covers current schema, retained histories and immutable receipts | Passed; no schema changes |
| Backup/restore | Portfolio command-readiness encrypted restore preserves original manual receipt and exact replay; UI-001 Slice 57 shared browser restore evidence retained | Backend passed; shared browser restore not rerun |
| Query budgets | Empty, one-Property and eleven-Property summaries each execute one aggregate without hydration; property-local date boundary and archived inventory exclusion; directory bounds/totals/continuations | Passed |
| UI integration/accessibility | New status review keyboard path and axe WCAG checks in both themes at 390px; existing property/ownership and contextual-directory regressions | Passed |

Commands run from `application/`:

- `node scripts/python.mjs -m pytest apps/server/app/modules/portfolio/tests apps/server/app/modules/operator/tests/test_directories.py -q`: **109 passed**.
- `node scripts/python.mjs -m pytest apps/server/app/modules/operator/tests/test_recovery_composition.py -q -k 'portfolio or occupancy'`: **9 passed**.
- `npm run test:web -- apps/web/tests/portfolio-status.spec.ts`: **5 passed**.
- `npm run test:web -- apps/web/tests/workflows.spec.ts --grep 'property|occupancy|ownership'`: **4 passed**.
- `npm run test:web -- apps/web/tests/context-reads.spec.ts`: **4 passed**.
- Configured Ruff lint/format checks for all seven changed Python files, root frontend lint/type checking, changed-file Prettier checks and `git diff --check`: passed.
- Current web workspace build and wheel packaging: passed; browser tests ran against those assets.

Adjacent repository checks remain incomplete: root `npm run format:check` reports existing `demo/dataset.json` and `demo/README.md` formatting, and `npm run contracts:check` reports the generated OpenAPI snapshot stale after Home API changes. The web workspace build and direct packaging were used for focused acceptance; no public API schema changed here. These unrelated artifacts and configured quality rules were not changed.

The [completed UI-001 matrix](../implementation-plans/UI-001_IMPLEMENTATION_MATRIX_COMPLETED_2026-10-12.md) and [earlier PORT-003 command-readiness record](../implementation-plans/PORT-003_COMMAND_READINESS.md) preserve earlier delivery evidence.
