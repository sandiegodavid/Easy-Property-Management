# VEND-001 — completed acceptance, October 12, 2026

Current behavior is consolidated in the [Provider guide](../../modules/providers.md). The [original design](VEND-001_DESIGN.md) retains requirements and rationale. Existing UI-001 delivery supplies identity/profile and child commands. This pass labels manual prior work, clarifies exact service/area filters and verifies the remaining acceptance gate through real temporary workspaces.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | Browser new Party/profile creation, existing identity designation, preferred/avoid profile, services/areas/manual prior work/references and archive/restore | Passed |
| Invalid combinations | Avoid without a reason, normalized duplicates, role/contact guards, child membership and strict HTTP/direct-call contracts | Passed |
| Idempotency/retries | Original lifecycle/child receipts, saved input, concurrent duplicates and lost committed service response without duplicate creation | Passed |
| Transaction rollback | Provider/Party/child mutations and correlated audit/receipt failures roll back atomically | Passed |
| Persistence/schema | Exact schema, portable descriptions/fingerprints, registered seed origins and correlated retained mutation histories | Passed |
| Backup/restore | Encrypted Provider history round trip retains stable identity, services, areas, references, manual prior work and audit history | Passed |
| Query budgets | Unicode cursor traversal and 1/100/200-row budgets; selection and LIMIT precede bounded hydration; indexed child receipt lookup | Passed |
| Owning-domain integration | Maintenance retains assignment choice/avoid override and issue-backed work-journal ownership; Provider archive preserves Party identity | Passed |
| Browser/accessibility | Combined filters, current/history views, narrow Provider review in both themes, keyboard shared-identity navigation and axe checks | Passed |

Commands run from `application/`:

- Provider and Party backend suites: **135 passed**.
- Maintenance assignment/avoid and journal-source cases: **2 passed**.
- Focused Provider/identity browser cases in `workflows.spec.ts`: **8 passed**, seven in the combined run and the corrected lifecycle-disclosure case in a focused rerun.
- Frontend lint, complete type checking and changed-file Prettier checks: passed.
- Vite build, local wheel packaging and `git diff --check`: passed.

Root `npm run format:check` remains incomplete because existing `demo/dataset.json` and `demo/README.md` are unformatted. The complete application suite was not run. Category/reputation tests in the focused backend suite provide regression coverage without closing VEND-CAT-001 or VEND-002 acceptance; discovery, assignment, costs and communications remain with their owning features.
