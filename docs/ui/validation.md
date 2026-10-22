# Browser validation and delivery evidence

## Evidence boundary

UI-001's delivery matrix records backend readiness through Slice 43 and browser delivery/acceptance through Slice 57 on October 12, 2026. This consolidation preserves that evidence; it does not rerun tests or close pending review findings. Later changes require focused regression validation and the repository quality gates.

TASK-001 completion on October 12, 2026 passed twelve focused Task browser cases in `work.spec.ts` and 120 backend tests. This includes combined priority/due filters and paging, compact recoverable quick add, confirmed row completion, and terminal outcome history. See the [completed acceptance record](../archive/designs/TASK-001_DESIGN_COMPLETED_2026-10-12.md) for the validation matrix and repository check limitations; current behavior is in the [Task module guide](../modules/tasks.md).

## Current Playwright coverage inventory

Inventory captured **October 22, 2026**, using test discovery for all four configurations below. Counts include parameterized cases, not just handwritten `test()` declarations. **Discovery is not execution:** these totals do not establish a current full-suite pass. The delivery evidence elsewhere on this page retains its original validation dates.

There is no configured Playwright line/branch or CSS coverage measurement, so no code-coverage percentage is available. Test counts also do not measure the percentage of backend API operations exercised.

### Configurations and boundaries

| Group | Tests | Spec files | Execution boundary |
| --- | ---: | ---: | --- |
| [Packaged application](../../application/playwright.config.ts) | 373 | 38 | Compiled wheel assets with real backend routes and disposable ready/unavailable workspaces; selected scenarios intercept responses to exercise faults or synthetic contracts. |
| [Shared components](../../application/playwright.components.config.ts) | 8 | 3 | Vite-backed component harness covering disclosures, async states, confirmation/focus, narrow layouts, reduced motion and Lease date presentation. Excludes the recovery spec. |
| [Recovery integration](../../application/playwright.recovery.config.ts) | 6 | 1 | Recovery harness through Vite with a real disposable backend; autosave, two-tab conflicts, interrupted/cancelled requests, original-key replay and source changes. |
| [Seeded demo](../../application/playwright.demo.config.ts) | 56 | 8 | Separately started synthetic demo server at port 8001; existing known records, read-only navigation/presentation by default. Not included in `test:web`. |
| **Total** | **443** | **50** | All configurations currently use Chromium. |

The component and recovery configurations select disjoint spec files; their totals do not double-count `recovery.spec.ts`. Some component cases execute controller/date logic rather than a complete browser workflow. The seeded-demo suites are documented separately in their [README](../../application/apps/web/tests-demo/README.md).

### Packaged application workflow coverage

The following groups partition the 373 discovered cases by spec file. A case can exercise several modules; these are navigation aids, not exhaustive feature-coverage percentages.

| Area | Cases | Specs and principal checks |
| --- | ---: | --- |
| Home | 46 | Nine `home*.spec.ts` files: local times, layout/disclosure, tabs, filters, live refresh, cancellation/stale responses, independent failure, bounded collections, source drill-down/return, exact totals and a local latency gate. |
| Property/Owner context and Portfolio status | 43 | `context-reads`, `portfolio-status`, `ownership-shares`: directories/overviews, ownership/contact selection, percentages, occupancy/leasing status, schedules/corrections, query bounds, viewport and current-source recovery. |
| Shared identity and Provider workflows | 23 | `workflows`: Party contacts/primary selection, Tenant preferences, Provider creation/designation, services/areas/references/reputation, categories, archived history and interrupted/stale command results. Also includes shared Property workflow cases. |
| Tenant directory and IDs | 5 | `tenant-directory`, `tenant-ids`: search/browse, bounded continuation, archived/error/empty states, masked identity details and recovery. |
| Provider categories and IDs | 5 | `provider-categories`, `provider-ids`: category administration/effective assignments, lost-response recovery and explicit reveal of optional full Provider ID numbers. |
| Leasing and Inspections | 30 | `leasing-inspections`: drafts, terms, participants, execution, renewal, end/termination/void, independent Lease/Space revisions, documents, checklists, evidence, acknowledgment/finalization and original-result recovery. |
| Money | 50 | `money`: reporting/scope/drill-down, expected and received rent, allocations/payment methods, expenses/categories/refunds, deposits/settlements, prepaid checks, owner reports, evidence and duplicate/stale/interrupted submissions. |
| Maintenance, Tasks and Communications | 61 | `work`, `schedule-pickers`: issue/reporter edits, appointments, editable zoned schedule/deadline pickers, optional appointment ends, daylight-saving conversion, quotes/assignments, journal corrections, cost/Expense boundaries, Tasks/reminders/waiting/follow-ups, manual communications, owner concerns, lifecycle recovery, bounds and unavailable evidence. |
| Intake | 8 | `intake`: admission/import, ordered attachment roles, saved-byte checks, correction/dismissal/reopening/supersession, fail-closed evidence disclosure, bounded lists and explicit communication links. |
| AI Governance | 4 | `ai-governance`: settings/capability gates, governed input/draft review, bounded status pages, cloud disclosure, write-only credentials and uncertain external effects. Synthetic scenarios do not qualify production inference. |
| Search and information review | 16 | `search-coverage`: bounded grouped metadata search, archived context, source-specific next steps, non-applicability/missing information, source revision conflicts, saved forms and review receipt recovery. |
| Cross-cutting delivery and interaction | 82 | `acceptance`, `delivery`, `detail-interactions`, `dynamic-filters`, `form-feedback`, `form-focus`, `navigation-coverage`, `page-tabs`, `parent-navigation`, `saved-results`, `shell`, `workspace-gate`, `recovery-page`, `restart-restore`: transport/readiness gates, packaged deep links, appearance/navigation, keyboard interaction, saved-result presentation, conflict handling and process restart/encrypted restore. |

### Seeded-demo coverage

These **56 additional cases** are separate from the 373 packaged-application tests. They inspect the demo portfolio without submitting normal business mutations; create-workflow tests primarily check entry/navigation, not a successful create lifecycle.

| Demo spec | Cases | Principal checks |
| --- | ---: | --- |
| `home.spec.ts` | 7 | Heading, work tabs, filters, collection links, inventory and money summaries. |
| `properties.spec.ts` | 8 | Listing/search, status filters, review attention, ownership/rental-unit disclosure, empty state and open/return/create entry. |
| `owners.spec.ts` | 6 | Names, related-property counts/previews, archive/relationship scope and return navigation. |
| `tenants.spec.ts` | 6 | Search, full-roster browse, empty state and open/return. |
| `leasing.spec.ts` | 7 | Lease list/status, terms/participants, commercial labels, Money navigation and draft entry. |
| `money.spec.ts` | 8 | Views/filters, expected/paid rent, scoped records, expenses, funded deposits and empty checks. |
| `maintenance.spec.ts` | 7 | Issue facts/filters, quotes/detail, owner-concern empty state and report entry. |
| `providers.spec.ts` | 7 | Name/category filters, service/area/preference facts, empty state, detail/return and catalog navigation. |

### Limits of the current evidence

- **Browser engines:** Chromium only; no configured Firefox/WebKit matrix or real-device proof. Narrow desktop viewports are not equivalent to real mobile-browser qualification.
- **Accessibility and layout:** 15 spec files invoke axe; 26 explicitly configure viewport sizes. These are selected checks, not complete WCAG or every-screen/device coverage.
- **Visual regression:** 17 spec files capture screenshots, but none uses `toHaveScreenshot` baseline comparisons. Screenshots support inspection; they do not automatically detect pixel regressions.
- **Failure/recovery:** substantial workflow coverage exists, but browser scenarios do not replace owning-domain transaction, schema, concurrency and backup tests. One restart/restore spec does not prove every module's portability.
- **External effects:** mocked/synthetic AI and injected failures verify UI contracts, not real provider transports, credentials, availability or model quality. The demo is not an external integration test.
- **Run freshness:** no full Playwright suite was executed for this inventory. Discovery found no `test.skip()`/`test.fixme()` calls in the inspected specs; this alone does not prove every execution path runs or passes.

### Discovery and focused execution

From `application/`, refresh counts without starting test servers or executing workflows:

```bash
npx playwright test --list
npx playwright test --config playwright.components.config.ts --list
npx playwright test --config playwright.recovery.config.ts --list
npx playwright test --config playwright.demo.config.ts --list
```

For actual runs, use the owning configuration and focused selection:

```bash
npm run test:web -- apps/web/tests/workflows.spec.ts --grep '<affected scenario>'
npm run test:components -- --grep '<affected component>'
npm run test:recovery -- --grep '<affected recovery scenario>'
npm run test:demo -- properties
```

Demo execution requires its already-running synthetic server; discovery does not. Packaged tests require a current build/wheel asset match. `test:web` without selection runs each ordinary spec with a fresh disposable server/workspace via its wrapper; invoking all specs directly through Playwright does not provide that per-suite isolation. Run focused tests by default, as required by repository guidance. Do not run mutating acceptance suites against the demo or an operator workspace.

When specs/configurations change, refresh this inventory's counts and date. Record executed test results separately with their command, date and scope; never promote discovered counts, screenshots or historical passes into a claim that the current full suite passed.

## Executable entry points

Create/edit completion (October 18, 2026): shared business-data confirmations replace record editors; embedded forms remain in their enclosing content. Lifecycle and credential actions are unchanged.

| Validation area | Focused proof |
| --- | --- |
| Happy paths / presentation | `saved-results.spec.ts`: Property create/edit; rent receipt, lease draft, Provider, maintenance issue, owner concern, standalone Task and Tenant creation; explicit item returns and embedded Task replacement. Tenant creation starts at the directory button and finishes at its saved record. Includes light/dark desktop/mobile and axe. |
| Parent navigation / browser history | `parent-navigation.spec.ts`: Money expectation/receipt, Provider, AI draft, Lease/Inspection and Owner workspace back-link labels, destinations and placement. `dynamic-filters.spec.ts`: Forward restores Provider, Property, Owner and Maintenance filters; directory changes replace history entries. |
| Disclosure / action rows | `detail-interactions.spec.ts`: issue, Task, Money and Lease disclosures support full-bar click, Enter/Space, independent rows and retained nested states. Primary-submit then unfinished-save ordering covers Money, work, Leasing, category and Intake forms. |
| Read failures / focus | `money.spec.ts`: a failed directory read cannot become empty or zero; explicit retry restores the actual records. `home-layout.spec.ts`: stale status retains the original capture. `form-focus.spec.ts`: Keep editing restores the navigation trigger; cancelling inline discard restores its button without losing the draft. Shared confirmation-dialog focus is also covered by `components.spec.ts`. |
| Invalid combinations / retry | Invalid/conflicting submissions do not show success. Interrupted Party edits remain unresolved until reconciliation; a failed immutable-detail read offers a read-only retry with one mutation. A later name change does not overwrite the original confirmation. |
| Privacy / bounds | Technical identifiers/revisions and raw JSON are omitted; Tenant/Provider ID regressions retain masked details and explicit Provider-number reveal. Receipt reads remain keyed and bounded; collections are capped in the confirmation. |
| Persistence / rollback / backup | No server, schema, transaction or archive changes. Existing source-owned receipts and recovery contracts remain authoritative; this slice does not claim new backend/backup proofs. |

October 21 contract follow-up: 31 focused packaged-application cases and one recovery integration case passed. The guard test exposed lost focus after **Keep editing**; the guard now focuses its choices when opened and returns focus to the initiating control when cancelled. The focused runs use disposable workspaces; no full-suite execution is claimed.

Focused validation: 21 workflow cases and 32 additional confirmation, recovery, navigation, identity, Money, Leasing/Inspection, Intake and AI cases passed (the corrected ownership-date case was rerun separately). Lint, formatting, type checking and the production build passed; the existing bundle-size warning remains informational. No full application suite was run.

Provider official IDs (October 18, 2026): profiles/quotes may remain incomplete; new Maintenance assignments require a recorded ID. Optional full numbers are supported for every Provider ID type and revealed explicitly, while Tenant IDs remain masked-only.

| Validation area | Focused proof |
| --- | --- |
| Happy paths and invalid combinations | `vendors/tests/test_official_ids.py`: all document types, optional bounded numbers/suffix agreement, malformed/duplicate/over-limit IDs and HTTP extra fields. `provider-ids.spec.ts`: add/edit/remove, explicit reveal/hide for license and passport, both themes/mobile and accessibility; `tenant-ids.spec.ts` guards masked-only Tenant behavior. |
| Idempotency and retries | Existing Provider revision/no-op/conflict/original-receipt contracts include IDs; original assignment replay succeeds after ID removal. |
| Transaction rollback | Profile audit failure rolls back IDs; missing-ID assignment and injected assignment audit failure leave the issue/assignment unchanged. Quotes without IDs remain valid. |
| Persistence/schema validation | Current baseline JSON shape/bounds and Provider command/audit reconstruction reject malformed or rewritten retained IDs. Full numbers are omitted from directory summaries and IDs are redacted from general activity. |
| Backup/restore | `vendors/tests/test_command_readiness.py::test_encrypted_restore_preserves_original_receipts_and_correlations` compares original receipts, full-ID profile detail and correlations after encrypted restore. |
| Query budget | Maintenance reuses the existing single Provider-context query on its writer connection, adding only a boolean ID fact; there is no nested session or per-ID query. Existing bounded Provider paging budgets remain covered. |

Tenant official IDs (October 18, 2026): masked metadata is optional during profile/draft creation and required for every participant at lease execution. No full document numbers or scans are retained.

| Validation area | Focused proof |
| --- | --- |
| Happy paths and invalid combinations | `tenants/tests/test_official_ids.py`: masked type/country/region/last-four/date validation, duplicate and ten-entry bounds, HTTP extra-field/number rejection; `tenant-ids.spec.ts`: add, edit, remove, empty-profile guidance, both themes/mobile and accessibility. |
| Idempotency and retries | Tenant original receipts, no-op revisions, changed-key/stale conflicts; execution replays its original result even after ID removal. |
| Transaction rollback | Audit failure rolls back ID changes; missing primary/co-tenant IDs prevent lease execution and leave the draft unchanged. |
| Persistence/schema validation | Current-baseline JSON shape constraints and full command/audit reconstruction reject malformed or unaudited retained ID state. |
| Backup/restore | `test_command_readiness.py::test_encrypted_restore_preserves_receipts_and_revisions` compares masked records and original command rows after encrypted restore. |
| Query budget | All participant IDs are checked by one set-based Tenant query on the Lease writer connection; profile hydration uses the existing row without per-ID queries. |

Ownership portions (October 18, 2026): optional per-property percentages use exact basis points, with no inferred shares or changes to Finance calculations. The current baseline changes; demo workspaces must be rebuilt.

| Validation area | Focused proof |
| --- | --- |
| Happy paths and invalid combinations | `test_ownership_shares.py`: exact totals/rounding, optional unknowns, typed percentages, malformed/range/type and aggregate rejection; browser forms and Property/Owner Relationships. |
| Idempotency and retries | Share-only changes advance the Property revision once; identical sets remain no-ops, original receipts replay, changed key reuse and stale revisions conflict. |
| Transaction rollback | Injected failure after an ownership insert leaves no new property, Party, share or receipt. |
| Persistence/schema | Current integer/null/range checks plus timeline aggregate and audit/receipt validation; tampered shares fail workspace validation. |
| Backup/restore | Encrypted round trip compares stable ownership rows, exact shares and original receipt result, then validates the restored schema/history. |
| Bounded reads | Existing Portfolio/Operator directory and overview query-budget tests cover the same set-based reads with added share projections; no per-owner share lookups. |

Parent navigation (October 18, 2026): `parent-navigation.spec.ts` checks top-level exclusions, one top parent link on representative detail/form/secondary pages, direct-URL fallbacks, filtered list and click-time scroll restoration across detail/form returns, tab/reload preservation, and unsafe or stale return state. Focused Home, lease/inspection, tenant, provider and maintenance regressions retain recovery and unsaved-form behavior. Return context is bounded router state, not new persistence; commands, schema and backup contracts are unchanged.

Lease-filtered Money context (October 18, 2026): focused browser checks cover the named property/address and overview link without money rows, persistence across Money tabs, clearing the lease filter, and retry after context lookup failure. The existing bounded money-context endpoint is reused; no backend, mutation, schema or backup contract changed.

Tenant detail actions (October 18, 2026): focused browser checks cover inline contact/preference buttons, removal of unrelated role actions on `/tenants`, low-emphasis tenant archival below preferences, explicit restoration, contact editing and independent Party/Tenant revisions. Light/dark desktop/mobile layout and accessibility checks cover the heading/action rows. Preferences retain their existing fields and notes; no schema, mutation or backup contract changed.

Maintenance issue detail cleanup (October 18, 2026): focused browser cases cover named property context, compact description/status/reporter facts, primary and secondary actions, collapsed empty sections, quote comparison, appointment completion/rescheduling/cancellation and reporter correction. Light/dark desktop/mobile screenshots check layout and horizontal overflow. Issue mutations, schema, rollback and backup contracts are unchanged; this does not re-prove those backend guarantees.

Lease detail cleanup (October 18, 2026): focused browser cases cover named property/participants, distinct date and rent panels, last-covered-day presentation, state-appropriate actions, documents and original-result recovery, plus independent property/name/inspection failures. Desktop/mobile light/dark screenshots and accessibility checks cover the layout. Names are fetched in batches of at most 100; the Party endpoint's focused tests cover UUID/size validation, name-only output and a one-query upper bound. Lease mutation, persistence/schema and backup contracts are unchanged.

Shared page tabs (October 18, 2026): `page-tabs.spec.ts` compares Property/Owner detail, Money, Work and retained-source navigation in both appearances at desktop/mobile widths; it checks active styling, focus, navigation and horizontal overflow without page widening. Home checks retain arrow/Home/End key selection and tabpanel semantics, with automated accessibility checks; `home-cards.spec.ts` preserves existing panel/disclosure behavior. Property status filters remain visually separate. This presentation-only change does not alter commands, persistence or backup contracts.

Tenant browsing (October 18, 2026): the explicit **Browse tenants** action lists names alphabetically in pages of 20, without loading contact details per row. Focused backend/browser cases cover Unicode ordering, no-gap/no-duplicate continuation, archived opt-in with cursor reset, switching to search, filtered return navigation, and failure/retry without a false empty state. Backend checks enforce request/cursor limits and a fixed query upper bound. The read-only endpoint changes no mutation, transaction rollback, persistence/schema or backup contracts.

Providers directory cleanup (October 18, 2026): nine focused browser checks cover automatic search and combined filters, cursor reset and browser Back, clear/reset, error/retry versus empty results, provider creation/designation and category navigation/history. Desktop/mobile light/dark screenshots and accessibility checks cover the new cards. Directory requests remain bounded to 50 providers with no per-card detail or category-history reads. Provider mutations, persistence/schema and backup contracts are unchanged, not newly re-proven.

Maintenance directory cleanup (October 18, 2026): focused browser coverage checks named property selection, automatic status/category/priority and secondary filters, clearing filters, empty/error/retry states, issue navigation and existing report/reporter/follow-up workflows. Light/dark desktop/mobile screenshots and accessibility checks cover the directory. Lists remain bounded to 25 issues and property searches to ten matches, with no per-card detail requests. This is read/presentation work; revision/idempotency, transactional rollback, schema and backup contracts are unchanged, not newly re-proven.

Leasing directory cleanup (October 18, 2026): cards show batched property/rental names, human-readable statuses and inclusive contract dates without UUIDs. Focused browser coverage checks status filtering, empty results, bounded continuation/restart, draft creation and narrow light/dark accessibility; screenshots cover desktop/mobile. Forty Lease command-readiness tests pass, including a fixed four-query upper bound for page selection and name hydration. No mutation, persistence-schema or backup contracts changed. The older lease-end browser case still expects a Leases section on Property Overview; that unrelated expectation was not changed here.

Tenant directory cleanup (October 18, 2026): focused browser checks cover dynamic bounded name search, archived results, error/retry and empty states, filtered return navigation, and tenant creation entry. Existing tenant contact/preferences, restoration and stable-shell navigation regressions also pass. Light/dark desktop/mobile layouts and accessibility are checked. Reads remain bounded to 20 results without per-card requests; mutation, persistence and backup contracts are unchanged.

Tenant routing (October 18, 2026): six focused browser checks cover `/tenants` navigation and direct delivery, tenant preferences and restoration, property-to-tenant links, and shared-person links. All 51 static-delivery tests passed, including the new route without workspace access. Frontend checks/build and changed-file Python lint/format checks passed.

Automatic filters (October 17, 2026): 24 focused browser cases passed across directories, Home, work lists and Money. `dynamic-filters.spec.ts` covers debounced typing without losing focus, cursor reset, immediate choices preserving pending text, Back restoring controls, invalid date ranges, cancellation on leaving a page, and complete Intake timestamps. Existing workflow cases verify combined filters, bounded continuations, property-content scroll and independent Home reads. Build/contracts, lint, formatting and full frontend type checking passed. Filters remain read operations; no mutation, schema or backup contracts changed.

October 17, 2026 property/owner form refinement: ten focused packaged cases passed in `portfolio-status.spec.ts`, `workflows.spec.ts` and `shell.spec.ts`. Light/Dark desktop and mobile screenshots were inspected. Build/contracts, lint, formatting and full frontend type checking passed.

| Validation area | Focused proof |
| --- | --- |
| Happy paths | Shared owner picker for create/change ownership; existing and inline owners, contacts, office suites and Tenants navigation. |
| Invalid/unfinished input | Owner composition disables both saves until Add or Cancel; Enter in search cannot submit the property; dirty navigation remains guarded. |
| Retry/recovery | Saved US property draft retains State and inline owners; resumption creates exactly one property. Technical recovery disclosure is omitted, not its safety mechanisms. |
| Persistence/atomicity | Real workspace reads confirm US, owners, contacts and preserved ownership history. No backend/schema changes; existing transactional rollback and backup/restore contracts are unchanged, not newly re-proven here. |
| Bounded reads | Live search debounces typing, ignores stale matches and resets paging; explicit browse stays at ten per page with stable viewport. |
| Presentation | No Search/Hide results buttons or country input on create; State label, responsive owner composer and both appearances. |

Property-create follow-up: `portfolio-status.spec.ts` checks that delayed autosave does not move or blur inputs, saved drafts remain resumable, and interrupted creation reconciles without a second create. `saved-results.spec.ts` checks the confirmed data and explicit **Back to property** action. Autosave remains active without transient saving/saved text above the fields. No persistence or backup behavior changes.

Property-edit follow-up: the focused property-edit browser test checks the same US address labels as creation (State, no Country code), grouped save actions, a single named top return link, and preservation of country, ownership and rental status after saving. It exercises light/dark and desktop/mobile layouts. A confirmed edit opens the property's Setup tab; the interrupted-edit test verifies that navigation waits for reconciliation and does not repeat the write. The Units and Setup tabs display the address consistently with other detail tabs, with desktop/mobile regression coverage. No persistence contract changes.

Shared form actions (October 17, 2026): 26 focused packaged browser cases passed across Property/rental, Party/Tenant, Task, Maintenance, Conversations, Intake, Money, Leasing/Inspection, Provider/category and AI draft editors. Coverage includes contextual save labels, saved-input recovery, stale-source review, interrupted-save reconciliation, and keyboard/contrast/200% reflow in both themes at 390/900/1440px. Workflow forms share the bottom primary/unfinished-save row; AI review uses its existing edit/dismiss actions with the same styling. Build/contracts, lint, formatting and full frontend type checking passed. No backend, schema or backup changes.

Create-action follow-up: 22 focused packaged browser cases passed for the shared create actions, including Task and Property creation, contacts, Provider/category setup, Leasing/Inspection, Intake import, financial records, Maintenance, and AI connection setup. Coverage includes unfinished-form recovery, interrupted responses, validation and disabled actions; the Task test asserts “Create task” followed by “Save unfinished form”. Build/contracts, lint, formatting and type checking passed. These presentation changes do not alter persistence or backup contracts.

October 15, 2026 visual refresh: **20 focused packaged browser cases and six shared component cases passed** across `shell.spec.ts`, `acceptance.spec.ts`, `home-layout.spec.ts` and the component suite. The SPA adopts the operator-experience reference's styling while retaining existing content, menus, preferences and workflows. Proof covers Light/Dark at 390/900/1440px, automated contrast, keyboard focus and 200% reflow, hidden/reordered destinations, saved/conflicted preferences, source-form commits and Home loading/refresh/disclosure behavior. Desktop Light/Dark and mobile screenshots were inspected. Build/contracts, lint, full type checking and changed-file formatting passed; the global format check still reports only the unchanged demo files.

INSP-001 completion on October 12, 2026 verified 27 Inspection backend tests, 43 Finance regressions and 24 Lease/Inspection browser cases (23 passing in the suite followed by the corrected office case passing independently). Office template snapshots and narrow report review pass accessibility checks in both themes; selected evidence metadata retains archive reasons. The [completed acceptance record](../archive/designs/INSP-001_DESIGN_COMPLETED_2026-10-12.md) records the full validation matrix and check limitations.

Paths below are relative to `application/apps/web/`. Packaged browser cases use real temporary workspaces for persistence/recovery. Mocked unavailable/partial states complement these cases; they do not prove commits. Shared component fixtures test disclosure, forms and recovery without claiming a live Home aggregate.

| Boundary | Test entry points / recorded proof |
| --- | --- |
| Packaged transport | `tests/delivery.spec.ts`, `tests/acceptance.spec.ts`: compiled wheel assets, deep links, reserved paths/security headers and rejection of unrelated-origin multipart commands |
| Bootstrap/navigation | `tests/workspace-gate.spec.ts`, `tests/shell.spec.ts`, `tests/context-reads.spec.ts`: readiness, scope/runtime, themes, partial sections and bounded contextual reads |
| OPS-001 | October 13 acceptance: 519 focused backend tests, 20 packaged search/information review/context/preferences/recovery-page cases and six shared recovery/component cases each passed. Stale search restart fetches a fresh first page; real archived search opens retained context. [Completed acceptance](../archive/designs/OPS-001_DESIGN_COMPLETED_2026-10-13.md) records scope, query/portability proofs and check limitations; Home remains DASH-001-owned |
| Portfolio/identity/providers | `tests/workflows.spec.ts`: current source context, lifecycle/child guards, saved forms and interrupted-command recovery; see the completed record for slice-specific cases |
| Provider categories | `tests/provider-categories.spec.ts`: Settings and direct-load catalog access, active/archive separation, multi-category creation, rename/description/order, effective counts, active category filter/reload, Uncategorized and lost-response recovery. [October 13 acceptance](../archive/designs/VEND-CAT-001_DESIGN_COMPLETED_2026-10-13.md): two new browser cases plus seven existing Provider/category regressions, 111 Provider backend and 40 static-delivery tests |
| Portfolio status | `tests/portfolio-status.spec.ts`: source summaries and drill-down, unknown classification, recorded/effective availability, invalid date correction, scheduled reschedule/cancel/correction, combined filters, stale/lost-response recovery, keyboard access and both themes at 390px; [PORT-003 completion](../archive/designs/PORT-003_DESIGN_COMPLETED_2026-10-12.md) records five new cases plus eight shared browser regressions |
| Lease/Inspection | `tests/leasing-inspections.spec.ts`: residential/commercial contracts, independent Lease/Space revisions, termination/renewal/move-out, participant-date acknowledgment, draft correction, original child-removal results, document reselection/lost-response recovery, termination proposal context, unavailable evidence, bounded metadata reads and directory cursor guards; [LEASE-001 completion](../archive/designs/LEASE-001_DESIGN_COMPLETED_2026-10-12.md) records 23 focused browser cases and narrow keyboard/accessibility checks in both themes |
| Money | `tests/money.spec.ts`: partial rent/corrections, dual-revision report verification, checks/deposits/settlement/refunds, evidence partial success, original receipts and exact period source pages |
| FIN-003 Reporting | `tests/money.spec.ts --grep reporting`: explicit period, exact backend totals/source counts, no detail fan-out, same-period Property drill-down, fresh metric/account cursors and unavailable/stale restart preserving filters. [October 13 acceptance](../archive/designs/FIN-003_DESIGN_COMPLETED_2026-10-13.md): 21 backend and three reporting browser tests |
| Maintenance/communications/Tasks/concerns | `tests/work.spec.ts`: independent lifecycles, waiting/reminders, quotes/journal/expense links, child identity and deleted-Task result recovery |
| TASK-002 waiting | `tests/work.spec.ts --grep 'Task\|Waiting\|Reminder'`: replacement, timed reschedule/date removal, unscheduled deadline/priority display, reminder independence and lost-response recovery. [October 13 acceptance](../archive/designs/TASK-002_DESIGN_COMPLETED_2026-10-13.md): 120 Task backend tests and 15 browser regressions |
| Search and Information review | `tests/search-coverage.spec.ts`: grouped paging/retry, typed navigation, required gaps, source review conflicts and original information-review receipt recovery |
| AI governance | `tests/ai-governance.spec.ts`: real empty-registry Settings/pause; synthetic cloud disclosure/probes/limits, saved-payload/current-source approval gates, qualified provenance/confidence, predecessor/result history, terminal immutability, bounded status paging, secret-free original-key recovery and explicit external-effect uncertainty. [October 13 foundation acceptance](../archive/designs/AI-GOV-001_DESIGN_COMPLETED_2026-10-13.md): 82 backend and four browser tests; INGEST-002 terminal-mode extensions remain gated |
| Home foundation and transport | `tests/home-transport.spec.ts`, `tests/home.spec.ts`, `tests/workspace-gate.spec.ts`: independent full/live reads, server-selected calendar month, normalized scope, cancelled/late reads, readiness and existing Task navigation/actions. [Slice 12 evidence](#dash-001-slice-12-transport). Source-supplied disclosure/calendar fixtures remain `component-tests/attention.spec.ts` |
| Manual Intake | `tests/intake.spec.ts`: admission/import/correction/supersession/dismissal/reopening, ordered roles/digests, stale-source review, audited current/exact historical evidence and withheld-read failure, byte reselection, independent Communications links and bounded 30-record/two-page traversal. [October 13 acceptance](../archive/designs/INGEST-001_DESIGN_COMPLETED_2026-10-13.md): 72 focused backend and seven browser tests |
| Accessibility/recovery | `tests/acceptance.spec.ts`, `component-tests/recovery.spec.ts`: keyboard/focus, reduced motion, 200% text reflow, Light/Dark WCAG automated checks at 390/900/1440px, serialized autosave/conflicting windows |
| Restart/encrypted restore | `tests/restart-restore.spec.ts`, `application/scripts/web_acceptance_restore.py`: committed lost Task response, one dispatch across restart, original receipt/saved form, stable workspace/evidence/Intake histories and changed runtime epoch |

Backend focused suites continue to prove owning schema, rollback, exact receipts and portable validation; links live in module guides. New boundary changes must extend the appropriate proof rather than assume old test counts apply.

## DASH-001 Slice 12 transport

October 14, 2026: 16 focused cases passed across `home-transport.spec.ts`, `home.spec.ts` and `workspace-gate.spec.ts`, using the final packaged application and disposable real workspaces. The five new transport cases combine real HTTP reads with explicitly delayed, capability-disabled and mismatched-runtime responses. This accepts the transport boundary; Home section layout, delayed/timeout presentation, detailed actions and browser performance remain Slices 13–18.

| Validation area | Proof / result |
| --- | --- |
| Happy path | Passed: full Home/live attention start independently; real responses retain separate capture times; visible leap-year month defaults use injected bootstrap UTC, not ambient browser date. |
| Invalid combinations | Passed: invalid/reversed date and horizon/UUID URL inputs normalize; mismatched response runtime is withheld; absent Home capability shows unavailable and sends no Home requests. |
| Retry/deduplication | Passed: initial URL normalization causes one request per key; money/horizon changes make one new full request while retaining the independent live capture. Workspace network/recovery retries retain existing behavior. |
| Cancellation/navigation | Passed: changing property cancels the old read; its delayed fulfillment finishes without replacing current content. Navigation to Tasks remains usable while full Home is pending and live attention has completed. |
| Read-only/persistence | Backend injected-clock test leaves audit counts unchanged. No new persisted frontend or canonical state; existing Task action and workspace disposal/re-admission regressions pass. Backup/restore source behavior remains backend-owned. |
| Quality checks | Generated contracts/reproducibility, packaged build, lint, complete type checking, changed-file Prettier, Python Ruff check/format and diff checks passed. Global `npm run format:check` is blocked by existing `demo/dataset.json` and `demo/README.md` formatting. |

## DASH-001 Slice 13 layout and latency

October 14, 2026: 12 distinct focused browser cases passed across `home-layout.spec.ts`, `home-transport.spec.ts` and `home.spec.ts` (11 in the combined run, then the corrected real-appointment fixture passed independently). The six layout cases use the packaged application, real disposable Task/Property/Issue/appointment records and explicit mocked failure/latency responses. Source commands remain in their owning workflows. Collection pages, expanded actions, automatic refresh/editor reconciliation and integrated performance remain Slices 14–18.

| Validation area | Proof / result |
| --- | --- |
| Happy path / navigation | Passed: all seven regions render, source exact totals and money strings remain intact, whole-row Task disclosure opens its source link, and a real appointment preserves its zone and opens its owning issue. |
| Invalid/unavailable | Passed: independent money/live failures expose unavailable state without fake counts or zero-action assurance; Inventory/Waiting remain usable. Existing wrong-runtime and missing-readiness regressions pass. |
| Delayed/timeout/retry | Passed: seven bounded skeletons show no counts; two-second elapsed feedback preserves typing; ten-second client timeout enables explicit independent retry without duplicate requests. |
| Refresh / state | Passed: refresh retains original captures and filter input; failed reads keep visible stale content and suppress all-clear. Newly qualifying work keeps its latest exact total in a persistent announcement until Show updated list. |
| Accessibility / layout | Passed: Enter/Space, expansion state and focus retention; no horizontal overflow at 390px; axe reports no Home violations in Light/Dark. Source dates remain supplied by the backend. |
| Persistence / query bounds | No Home mutation or new persisted/cache state. Focused backend source/composition/API tests retain rollback, encrypted restore and query-budget proofs; appointment context is added to the existing bounded SQL projection. |
| Quality checks | Packaged build/contracts, lint, complete type checking, changed-file formatting, changed-Python Ruff checks and diff validation passed. Global format check still flags existing `demo/dataset.json` and `demo/README.md`. |

## DASH-001 Slice 14 collections and return navigation

October 14, 2026: 17 distinct focused browser cases passed: five cases in `home-collections.spec.ts` plus the existing twelve Home layout/transport/source-action regressions. The collection suite uses real temporary Property/Task/Issue records and the source collection API. The combined run passed fifteen cases, its unfinished-request test fixture was corrected, and all five collection cases passed against the final package. No generic command or source classification is added to Home.

| Validation area | Proof / result |
| --- | --- |
| Preview/page parity | Passed: View all keeps the exact preview capture and 55-item total; default first page has 50 rows, next page has five, with no overlap. Page size 100 returns the bounded complete set. |
| Continuation/filter changes | Passed: one-row traversal has no gaps/duplicates; changing horizon and property discards the old token and starts a fresh scoped page. Pages are replaced, never appended to a refreshed list. |
| Conflict/recovery | Passed: a real Task completion invalidates the preview token; 409 withholds further continuation and Restart retains filters with a fresh count. A separately changed runtime token is rejected. |
| Navigation/context | Passed: source detail retains collection URL, explicit money period and Home horizon in return context; source return restores nonzero scroll. Hidden Maintenance remains reachable from its collection row. |
| Readiness/deep links | Passed: all five collection routes load directly; missing `operator.home` dispatches no collection query and reports unavailable. Registered-path and unknown-path behavior has focused backend coverage. |
| Quality/portability | Generated contracts, packaged build, lint, full type checking, changed-file formatting and Python Ruff checks passed. Backend restore/query-budget/read-only proofs pass; no new persisted Home state. Global format check still flags existing `demo/dataset.json` and `demo/README.md`. |

## DASH-001 Slice 15 source workflows and recovery

October 14, 2026: **25 focused packaged browser cases passed**, including eight new `home-workflows.spec.ts` cases and the Home collection/layout/transport regressions. **82 focused backend Home contract/API tests passed.** The appointment regression now verifies the exact owning-issue/appointment fragment. No new Home command, database schema or aggregate query is introduced.

| Validation area | Proof / result |
| --- | --- |
| Source adapters / happy paths | All eight initial source/action pairs reach existing owning workflows. Real commits cover rent payment, grouped issue follow-ups/reminder acknowledgement, appointment attendance, Owner concern follow-up, report rejection, Task completion, lease renewal option and information review. |
| Group bounds / disclosure | Three nested Task/reminder previews remain metadata-only; expansion performs no sensitive issue-detail read. All 26 explicit issue follow-ups are reachable across 25+1 source-directory pages without gaps. Owning Task pages retain their explicit bounded reminder-history notice. No per-row Home fetches. |
| Current-state validation / failures | A concurrent Task start causes a conflict without losing the outcome note; explicit source review admits a new attempt. Unavailable current issue detail withholds lifecycle controls while preserving Home return navigation. |
| Idempotency / retry | Interrupted Task completion and payment responses reconcile original immutable receipts with exactly one dispatch and one resulting mutation/receipt. Existing source forms own attempt keys, confirmation and recovery. |
| Partial success / independent lifecycles | Reminder acknowledgement and appointment attendance leave the issue open and physical completion unrecorded. Concern follow-up leaves the concern open; rejected Owner reports create no Finance receipt; an open renewal option does not imply executed continuation. |
| Navigation / accessibility | Home context survives detail → command → current record and child-directory paging. Collection/filter/scroll, hidden-destination access, keyboard disclosure, narrow Light/Dark accessibility and transport cancellation regressions pass. Information review areas and captured revisions are explicit. |
| Persistence / rollback / portability | This slice changes navigation/presentation only. Commands use existing source transactions, audit/evidence policies and immutable receipts; no new transaction, rollback path, schema or backup format is added. Existing source portability proofs remain authoritative; no new encrypted archive round trip was run. |
| Quality checks | Packaged build, reproducible contracts, lint, full frontend type checking, changed-file formatting and diff checks passed. Global `npm run format:check` still flags the pre-existing `demo/dataset.json` and `demo/README.md` formatting issues; they were not changed. |

## DASH-001 Slice 16 money, inventory and review drill-downs

October 14, 2026: **31 distinct focused Home browser cases passed** across drill-down, workflow, collection, layout and transport suites; all six new `home-drilldowns.spec.ts` cases passed in the final focused run. The backend inventory/Finance/portability matrix is [recorded with the contracts](../archive/validation/DASH-001_CONTRACT_EXAMPLES_COMPLETED_2026-10-14.md#slice-16-money-inventory-and-review-drill-downs).

| Validation area | Proof / result |
| --- | --- |
| Money/source parity | All five metric links open Finance contributions with matching exact totals, explicit inclusive dates, property ID, captured revision and all-retained archive scope. Real archived paid Expense/refund history contributes; an empty contribution view remains a successful zero. Labels disclaim profit, bank balance and Owner entitlement. |
| Inventory/count parity | Actual vacant classification and unknown occupancy open separate active-Space lists. One-row continuation has no duplicates, excludes vacant Spaces from unknown results and preserves current Property/Space source return. No property count substitutes for the Space count. |
| Conflict / retry / unavailable | Real source mutations reject stale money/inventory captures; Restart retains the relevant filters. An unavailable inventory source shows no zero/count inference; a subsequent successful empty read displays zero explicitly. |
| Information review/source resolution | Missing occupancy opens the actual owning Property/Space status page using current Space context. A committed acknowledgment leaves required occupancy/availability gaps unresolved; source changes remain separate commands. |
| Agenda/time/context | Los Angeles and Tokyo appointments display their own local times, IANA zones and exact original instants. Source actions retain their owning issue context; the browser formats time without classifying eligibility. |
| Safety / integration | Existing keyboard, narrow Light/Dark, hidden-destination, input preservation, one-dispatch recovery, cancellation and identity-binding regressions pass. No new mutation, schema or persisted Home cache; existing source transactions/receipts remain authoritative. |
| Quality checks | Packaged build, reproducible generated contracts, lint, complete type checking and changed-file formatting pass. Global formatting still flags existing `demo/dataset.json` and `demo/README.md`; these files remain unchanged. |

## DASH-001 Slice 17 live refresh and protected interaction state

October 14, 2026: **8 focused packaged Home browser cases passed** in `home-layout.spec.ts`. The two new cases freeze browser time and prove the server-declared transition and visible-minute refresh paths without claiming a scheduler or backend snapshot. The backend source-read and command-recovery matrices remain authoritative.

| Validation area | Proof / result |
| --- | --- |
| Transition / visible interval | Home refreshes its cards at the saved browser interval (default 5 minutes); live attention also refetches at its returned `nextTransitionAt` when sooner. Browser code does not classify the due work itself. |
| Focus / coalescing | Passed: several focus events while one live request is in flight leave one request for the same workspace/runtime/scope query key. Existing late-scope cancellation prevents old responses applying. |
| Protected interaction | Passed: an expanded attention disclosure stays open through the staged transition refresh. Newly qualifying work remains announced with its exact latest total until the operator chooses **Show updated list**. |
| Assurance / failure | Passed: in-flight, stale, timed-out and failed live checks do not state an all-clear; prior refresh failure retains its original capture and input. Existing source-command invalidation uses the shared workspace query client. |
| Scope / persistence / quality | No new endpoint, command, cache, canonical row or backup state. Packaged build, generated-contract reproducibility, lint, complete type checking and changed-file Prettier passed. Global formatting still flags only unchanged `demo/dataset.json` and `demo/README.md`. |

## DASH-001 Slice 18 integrated experience and latency gate

October 14, 2026: **35 focused packaged browser cases passed** across Home collections, drill-downs, layout, live transport/refresh, all eight source workflows, source return/recovery and encrypted restart/restore. The dedicated ten-sample supported-local measurement passed with **881 ms initial Home p95**, **341 ms collection p95**, **334 ms live-refresh p95** and **98 ms in-app shell-navigation feedback p95**. The focused backend 1/10/50-property Home-performance suite also passed three cases, retaining its worker-wait/read-duration/query-budget proof.

| Validation area | Proof / result |
| --- | --- |
| Initial sources / source workflow | Passed: Task, rent, issue/follow-up/reminder, appointment, Owner report, Owner concern, Lease review and information-review flows retain their source-owned action/recovery contracts. Money, inventory and information-review resolution drill-downs retain exact source context. |
| Interaction / accessibility | Passed: narrow Light/Dark keyboard disclosure, current source return/scroll, retained Home filter input, expanded-row staging and no fabricated zero/unavailable state. Home does not own consequential commands. |
| Slow / cancellation / refresh | Passed: deliberate slow and timeout responses retain navigation/input; cancellation and late scope responses are withheld; focus/transition/minute refresh checks coalesce and preserve all-clear safety. |
| Restart / portability | Passed: encrypted restart/restore preserves the committed source receipt and saved form while the changed runtime rejects prior Home response/cursor identity. No Dashboard cache enters the archive. |
| Latency / snapshot decision | Passed: p95 measurements meet the one-second read and 100-ms shell-feedback targets with existing bounded live reads. Slice 11 still supplies the representative 1/10/50-property backend read/worker/query evidence. Conditional snapshot Slices 19–20 are skipped; independent cron remains post-MVP. |
| Quality checks | Packaged build/contracts, lint, complete type checking, changed-file Prettier and diff validation passed. Global formatting still flags only unchanged `demo/dataset.json` and `demo/README.md`. |

## DASH-001 Slice 21 acceptance handoff

October 14, 2026: **115 focused backend tests passed in 69.96 seconds** across `test_home_contracts.py`, `test_home_api.py`, `test_home_composition.py`, `test_home_inventory.py`, `test_home_money.py` and `test_home_performance.py`. This handoff changes documentation only. Slice 18's **35 packaged browser cases** and recorded local timings are prior evidence; they were not rerun during documentation consolidation.

| Acceptance area | Evidence / outcome |
| --- | --- |
| Sources, happy paths and invalid combinations | Eight registered initial source/action pairs, independent unavailable sections, typed request/cursor bounds, active inventory and exact Finance contributions; backend regressions passed, source browser paths passed in Slice 18. |
| Retry and interaction | Read-only requests leave the ledger unchanged; original source-command recovery, input retention, focus, scope/runtime cancellation and stale assurance suppression use Slices 15–18 browser evidence. |
| Transactions and persistence | Composition concurrent-write/rollback cases, current-baseline contract checks, no Home canonical tables and bounded source reads passed. |
| Backup and restore | Backend encrypted Home reconstruction and runtime/cursor invalidation passed; Slice 18 separately records the browser saved-form/original-result encrypted round trip. |
| Query and latency | Current 1/10/50-property performance regressions passed. Slice 18's browser measurements cover its actual disposable-workspace dataset; they are separate from the larger backend datasets and do not measure machine cold boot or sustained contention. The accepted local gate skipped snapshot Slices 19–20. |
| Scope and documentation | Current guides and backlog updated; fulfilled design and contract evidence archived with links repaired. No DASH-001 comments exist in the pending queue; separate FILE-001 findings remain open. UI-002, showing/assistant/value extensions and optional post-MVP cron retain their own gates. |

The [completed acceptance design](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md) preserves decisions; the [contract matrices](../archive/validation/DASH-001_CONTRACT_EXAMPLES_COMPLETED_2026-10-14.md) preserve backend evidence. Documentation-link and whitespace checks complete the handoff; implementation lint results remain the dated Slice 18 evidence.

## Maintenance validation

VEND-001 completion on October 12, 2026 verified 135 Provider/Party backend tests, two Maintenance integration cases and eight focused Provider/identity browser cases (seven passing together and the corrected lifecycle-disclosure case passing independently). New browser proof covers new/shared identity, avoid reasons, combined filters, retained lifecycle state and narrow keyboard/axe review in both themes. See the [completed acceptance record](../archive/designs/VEND-001_DESIGN_COMPLETED_2026-10-12.md).

Select cases for happy paths; invalid combinations and source/child membership; revision conflicts and same-key original-result recovery; transaction rollback; retained-schema validation; backup/restore; bounded paging/query budgets; navigation, unavailable/stale states and accessibility. Mark actual results passed/failed/not run/not applicable with reasons. Run root frontend lint, formatting and complete type checking for frontend changes; run configured Ruff checks for changed Python. Do not relax rules to pass validation.

## Historical records

FIN-006 completion on October 13, 2026 passed 81 focused Finance/OPS backend tests and 35 Money browser cases, including all six actual methods, safe-reference/Other-note validation, editable prior-method suggestions and independent replacement snapshots. Shared component and recovery suites passed six cases each. See the [completed acceptance record](../archive/designs/FIN-006_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

FIN-007 completion on October 13, 2026 passed 96 focused Finance/OPS backend tests, 37 Money browser cases and six shared component/recovery cases each. New proof covers property-midnight read-only eligibility, future-check queue filters, replacement prefills and lost deposit-response recovery with one receipt/allocation and no second dispatch. See the [completed acceptance record](../archive/designs/FIN-007_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

COM-001 completion on October 13, 2026 passed 30 Communications backend tests, 26 Work browser cases and six shared component/recovery cases each. Proof covers draft edit/record/correction, active participant/contact selection, local-date filters and lost recording-response recovery without duplicating its Task. See the [completed acceptance record](../archive/designs/COM-001_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

MAINT-001 completion on October 13, 2026 passed 46 Maintenance backend tests, 28 Work browser cases and six shared component/recovery cases each. Proof covers matching-Space creation, operational cost replacement, unchanged paid spending after association archival, appointment rescheduling, independent Task filters and retained evidence archival. See the [completed acceptance record](../archive/designs/MAINT-001_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

MAINT-004 completion on October 13, 2026 passed 76 Maintenance/Communications backend tests, 31 Work browser cases and six shared component/recovery cases each. New proof covers owner correction without rewriting a communication, draft/executed tenant eligibility, archived-owner correction through supported lifecycle commands, and reporter filters/snapshots. See the [completed acceptance record](../archive/designs/MAINT-004_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

MAINT-002 completion on October 13, 2026 passed 47 Maintenance backend tests, 32 Work browser cases and six shared component/recovery cases each. Proof covers quote comparison/paired dates, withdrawal/replacement, avoided-Provider direct selection, atomic reassignment recovery and encrypted schedule/document/history preservation. See the [completed acceptance record](../archive/designs/MAINT-002_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

MAINT-003 completion on October 13, 2026 passed 49 Maintenance backend tests, 34 Work browser cases and six shared component/recovery cases each. Proof covers bounded journal/Provider history, terminal-history confirmation, reported versus verified partial outcomes, correction replay, independent evidence archival and encrypted original/correction/audit/file preservation. See the [completed acceptance record](../archive/designs/MAINT-003_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

OWNER-003 completion on October 13, 2026 passed 23 Owner-report backend tests, 40 Money browser cases and six shared component/recovery cases each. Proof covers historical archived Owner context, claim/edit/reject/replacement, explicit receipt adoption/creation, duplicate refusal/recovery, evidence archival/filters and encrypted exact report/receipt lineage. See the [completed acceptance record](../archive/designs/OWNER-003_DESIGN_COMPLETED_2026-10-13.md) for the matrix and check limitations.

OWNER-004 source completion on October 13, 2026 passed 94 Owner Management backend tests, 39 Work browser cases and six shared component/recovery cases each. Proof covers historical confirmation, typed vacancy context, duplicate review, dismissed correction, independent follow-up/conversations and encrypted lineage/history restoration. Home owner-action presentation subsequently passed DASH-001 acceptance on October 14, 2026. See the [completed acceptance record](../archive/designs/OWNER-004_DESIGN_COMPLETED_2026-10-13.md).

FIN-008 completion on October 13, 2026 passed 84 focused Finance/Party backend tests and 28 Money browser cases. New proof covers exact interest/override review and confirmation invalidation, bounded Party selection, duplicate receipt/refund review, void/replacement lineage, reviewed deduction sources and draft evidence archival/history. Settlement detail passes narrow light/dark axe checks. See the [completed acceptance matrix](../archive/designs/FIN-008_DESIGN_COMPLETED_2026-10-13.md) for scope and check limitations.

FIN-002 completion on October 13, 2026 passed 52 focused backend tests and 24 Money browser cases. New proof covers bounded duplicate review before writes, Property/Space/time-zone and Provider/Party-payer context, combined filters, archived-category confirmation, category correction, evidence archival and refund replacement. Lost-response recovery and upload failure preserve committed spending. See the [completed acceptance matrix](../archive/designs/FIN-002_DESIGN_COMPLETED_2026-10-13.md) for results and check limitations.

FIN-001 completion on October 12, 2026 passed 71 focused Finance backend tests and 20 Money browser cases. New proof covers server-calculated schedule preview, separately confirmed responsibility proration, approval invalidation, exact allocation balance, multi-period payment, filters/drill-down and missed/clear history. Narrow receipt review passes axe in both themes. See the [completed acceptance record](../archive/designs/FIN-001_DESIGN_COMPLETED_2026-10-12.md) for the matrix and check limitations.

VEND-002 completion on October 12, 2026 passed 60 focused backend tests and four Provider/reputation browser cases. Proof includes all manual source types, verbatim URLs, lifecycle history, safe external-link attributes, no automatic external requests, count-only summaries and one-dispatch lost-response recovery. See the [completed acceptance record](../archive/designs/VEND-002_DESIGN_COMPLETED_2026-10-12.md) for the validation matrix and check limitations.

- [Completed design](../archive/designs/UI-001_DESIGN_COMPLETED_2026-10-12.md): preserved interaction decision IDs and technical rationale.
- [Completed browser matrix](../archive/implementation-plans/UI-001_IMPLEMENTATION_MATRIX_COMPLETED_2026-10-12.md): full slice-specific scenarios, dated results and command-safety inventory. Final acceptance recorded 119 browser cases, six shared component cases and six recovery cases; this is historical evidence.
- [Earlier backend matrix](../archive/implementation-plans/UI-001_IMPLEMENTATION_MATRIX.md): detailed source readiness sequence through the backend handoff.

The existing bundle-size warning was recorded as informational. No test execution or production model qualification occurred during documentation consolidation. [DASH-001](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md) and [UI-002](../active/UI-002_DESIGN_preliminary.md) have separate acceptance records; DASH-001 completed October 14, 2026 and UI-002 remains active.
