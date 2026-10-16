# Browser validation and delivery evidence

## Evidence boundary

UI-001's delivery matrix records backend readiness through Slice 43 and browser delivery/acceptance through Slice 57 on October 12, 2026. This consolidation preserves that evidence; it does not rerun tests or close pending review findings. Later changes require focused regression validation and the repository quality gates.

TASK-001 completion on October 12, 2026 passed twelve focused Task browser cases in `work.spec.ts` and 120 backend tests. This includes combined priority/due filters and paging, compact recoverable quick add, confirmed row completion, and terminal outcome history. See the [completed acceptance record](../archive/designs/TASK-001_DESIGN_COMPLETED_2026-10-12.md) for the validation matrix and repository check limitations; current behavior is in the [Task module guide](../modules/tasks.md).

## Executable entry points

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
| Transition / visible minute | Passed: live attention refetches at its returned `nextTransitionAt`; a response with no transition receives the 60-second visible check. Browser code does not classify the due work itself. |
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
