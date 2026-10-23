> Archived completed UI-001 record, October 12, 2026. Current behavior is consolidated in [UI guides](../../ui/operator-experience.md) and [module guides](../../README.md#current-modules). Historical planning language and dated evidence below are retained for traceability.

# UI-001 implementation slices

Status: backend readiness Slices 41–43 and frontend Slices 44–57 delivered — October 12, 2026. UI-001's implementation and acceptance gates are complete. Home aggregation remains DASH-001; issue-proposal review and connected assistants remain UI-002.

Scope alignment — October 9, 2026: INGEST-002 issue-proposal review and its
feature-specific AI approval modes, Intake attention consequences, coordinated
Maintenance writes and OPS recovery registration belong to UI-002. The former
planned Slice 40 is tracked in [UI-002's preliminary design](../../active/DATA-002_DESIGN.md#ingest-002--issue-review-readiness-and-recovery-former-slice-40).
None of that work gates UI-001. Delivered generic AI-governance and local-operator
Intake contracts remain in this matrix; their delivery does not enable INGEST-002.
The recorded backend readiness gate and React scaffold are complete; browser workflow delivery follows the ordered UI slices below.

## Subsequent UI slices — ordered implementation plan

Updated October 12, 2026. Backend Slices 41–43 and browser Slices 44–57 are delivered, including manual Intake, cross-workflow acceptance and encrypted restart/restore proofs. The following ordered slices record that delivery. Slice numbers continue after the backend sequence; Slice 40 stays assigned to UI-002.
The [UI-001 design](../../archive/designs/UI-001_DESIGN_COMPLETED_2026-10-12.md#technical-implementation-design) owns the
interaction and technical requirements.

Each slice includes its focused component/HTTP/browser tests as it is implemented;
do not defer basic correctness or accessibility to the final slice. Before completing
frontend changes, run `npm run lint`, `npm run format:check` and `npm run typecheck`
from `application/`, and verify generated-contract reproducibility when contracts
change. Use real temporary workspaces for critical integration paths. Fixtures
support visual development but do not establish backend or workflow readiness.

**Frontend validation matrix instructions (Slices 44–57)**

Use the shared coverage areas below to select focused frontend tests. In each
slice's existing entry, record only the scenarios specific to that slice, their
test file or named test, the observed result and any remaining gap. Use a compact
`Scenario | Evidence | Result / gap` table for multiple independent workflows or
failure paths; a short validation paragraph is sufficient for a small slice.
Do not create a second delivery section or appendix, repeat the shared matrix,
or use an aggregate passing test count as the sole evidence of workflow coverage.

| Coverage area | Required checks when applicable |
| --- | --- |
| Reads and availability | Happy path, loading, empty, error and partial failure; unavailable data must not appear empty; bounded paging preserves filters, totals and continuation without per-row request fan-out |
| Forms and accessibility | Required/invalid combinations, actionable field errors, explicit confirmations, keyboard operation, labels, focus and status announcements; invalid input preserves edits and prevents dispatch |
| Concurrency and submission | Displayed source identity/revision, stale-source conflict with edits retained, explicit current-source review, and protection against duplicate dispatch |
| Interrupted writes and recovery | Lost response, original-key reconciliation/replay, saved-form reload/resume and child context; unresolved outcomes cannot silently create a new attempt |
| Navigation and context | Direct links, back/forward navigation, unsaved-edit handling, correct owning record and child membership, workspace changes and lifecycle/capability guards |
| Presentation | Supported narrow layouts and themes, readable errors and exact domain formatting; history and unavailable content remain distinguishable from current actionable data |

Mark evidence as **passed**, **failed**, **not run**, or **not applicable**. Give
a reason for exclusions and identify any deferred acceptance proof by its owning
slice. Mark a slice delivered only after its applicable implementation checks
pass; explicitly scheduled final cross-workflow acceptance may remain in Slice 57.
Reuse named shared-component tests when behavior is unchanged, but verify newly
enabled critical read/write paths against a real temporary workspace. Mocks may
exercise failures that are difficult to reproduce; they do not prove persistence
or receipt integration. Reference existing backend schema, rollback and
backup/restore proofs unless the frontend change alters that boundary. Run the
quality checks above and report blockers without marking unrun checks passed.

1. **Slice 44: React/Vite scaffold, generated contracts and packaged smoke test (delivered).**
   Extend the existing Node workspace with `apps/web`, `packages/contracts` and
   `packages/ui`, one lockfile and reproducible pinned OpenAPI generation. Establish
   relative `/api` transport, the development proxy and an actual production build.
   Verify discovery/generation without opening a workspace. Exercise Slice 43 with
   real compiled assets: direct/deep-link loads, reserved API paths, missing assets,
   security headers and startup with an unavailable workspace. Completion requires
   actual-source frontend quality checks and a temporary-workspace browser smoke
   test; fixture-only static tests do not complete packaged-browser validation.

2. **Slice 45: Bootstrap and workspace gate (delivered).**
   Consume the typed OPS bootstrap before domain reads. Implement ready, missing,
   busy, invalid and migration-required states, separate network failure, nullable
   preferences and truthful write capability. Show only supported retry, locate
   and restore actions or explicit setup guidance. Reset workspace-bound caches
   and continuations on identity/runtime changes. Verify that unavailable data
   never appears as an empty portfolio and that gated states cannot submit writes.

3. **Slice 46: Application shell, routes, appearance and navigation settings (delivered).**
   Deliver configurable Home/Properties/Owners/Leasing/Money/Maintenance/Providers
   destinations, contextual navigation, typed deep links and Light/Dark Settings.
   Persist preferences through their revision-safe OPS contract. Hidden destinations
   must remain reachable from supported contextual links; hiding a destination
   must not hide obligations. Verify restore/reload, stale preference conflicts,
   both themes, keyboard use and supported narrow layouts. Unsupported UI-002
   routes/actions remain gated with an accurate explanation.

4. **Slice 47: Shared presentation, disclosure and async components (delivered).**
   Build domain-neutral components, tables/directories, section availability,
   loading/empty/stale/error states, confirmations and accessible form primitives.
   Implement D35: clicking or keyboard-activating the entire non-editable summary
   bar toggles details beneath it; expanded inputs/actions do not toggle the bar.
   Include the operator guidance, focus restoration, status announcements and
   reduced-motion support. Verify unavailable versus empty sections, partial
   failures, keyboard/focus behavior and both themes.

5. **Slice 48: Mutation transport, autosave and incomplete-form recovery (delivered).**
   Connect Query/Form state ownership, error normalization, source revision checks,
   canonical request identity and registered OPS form save/prepare/reconcile APIs.
   Do not automatically retry mutations. Preserve edits on conflicts and reconcile
   unknown outcomes using the original key before any new attempt. Serialize
   autosave, distinguish dirty/saving/saved/failed/conflicted states and guard
   navigation. Secrets and file bytes remain outside persisted recovery. Verify
   lost responses, same-key replay, changed-payload conflict, two-tab stale edits,
   cancellation, restart/restore and file-reselection guidance on real commands.

6. **Slice 49: Property/owner directories and contextual read workspaces (delivered).**
   Consume OPS bounded directories and overviews with recognition, filters, exact
   totals, independent continuations, `asOf`, partial availability and source
   drill-down. Implement current/former owner relationships and explicit-period
   whole-property money without implying owner entitlement. Verify multiple
   properties/owners, cursor expiry, sparse pages, date boundaries and section
   failures. Use composed backend contracts; no browser joins or authoritative
   aggregation. Later domain slices enable their corresponding write actions.

7. **Slice 50: Portfolio, Party/Tenant and Provider workflows (delivered).**
   Delivered browser forms for Property/Space creation, editing, lifecycle, ownership and manual
   occupancy/availability actions; shared identity/contact and Tenant lifecycle;
   Provider profiles, categories, assignments, service areas, history, references
   and reputation. Reuses previously delivered backend receipts and OPS contracts,
   including Slice 41 inventory recovery; the only Python addition is the `/parties`
   packaged route and its test. New frontend work includes generated typed command
   dispatch, progressive setup, contextual history, saved-form resumption and
   explicit stale-source review/original-result reconciliation.
   Validation: 21 packaged browser tests, 6 shared recovery tests and 104 focused
   Python tests passed, covering child membership, lifecycle guards, inline
   identity handling and interrupted writes. Lint, format, type, contract and
   packaging checks passed. Legal engagements remain UI-002.

8. **Slice 51: Leasing and inspection workflows (delivered).**
   Added bounded Lease directory paging and contextual Lease/Inspection workspaces;
   registered forms cover drafts, participants, terms, execution, renewal,
   termination negotiation/completion, move-out, templates, checklists,
   acknowledgments, finalization, correction, comparison and evidence attachment/archive.
   Lease and Space revisions remain independent. Saved forms retain child identity;
   recovery displays original owning-domain receipts rather than current records.
   Evidence saves metadata/hash only and requires matching byte reselection.
   Inspection failures do not hide an already committed Lease. Rent setup and
   settlement links remain separate steps; Money controls belong to Slice 52.

   Evidence below is in `apps/web/tests/leasing-inspections.spec.ts` unless noted.

   | Scenario | Evidence | Result / gap |
   | --- | --- | --- |
   | Draft create/edit, participants, terms and renewal | Complete draft creation; saved edit resumption; child add/update/remove; distinct renewal edit/decision requests; `removed participants resume original-result recovery without another removal` | Passed against real workspaces; prepared removal resumes its original receipt after the child disappears; fresh missing-child mutations still fail closed |
   | Execution, move-out and termination | Independent Lease/Space checks; stale Space preserves edits; end/terminate/void; termination request/proposal/accept/complete | Passed; isolated smoke-server clock advances lifecycle fixtures without changing production policy |
   | Inspection lifecycle and comparison | Template create/edit; draft/checklist setup; acknowledgments/finalization; correction remains a draft; explicit post-move-out comparison; `acknowledgments require only walkthrough-active participants at exclusive boundaries` | Passed; acknowledgment controls require exactly the active set, with participation dates shown; Inspection actions do not change the committed Lease lifecycle |
   | Evidence and interrupted writes | Matching-file reselection after restart; changed bytes rejected; lost-response original-key reconciliation; draft archival/history; unavailable download disabled | Passed; bytes never enter persisted OPS recovery; unavailable-state presentation uses a targeted read mock |
   | Partial failure and bounded reads | Inspection section failure leaves Lease visible; Lease directory no-gap paging, scoped-cursor/date-edit/runtime/expiry rejection and fixed three-query budget in `leases/tests/test_command_readiness.py`; `changed Lease directory continuation restarts with its filters retained`; observation ownership read in `inspections/tests/test_command_readiness.py` | Passed; marker validation, count and page share one snapshot; stale continuations return typed 409 and restart without dropping filters; no directory detail hydration or per-row browser reads |
   | Shared transport and final acceptance | Existing `workflows.spec.ts` and shared recovery tests; reproducible contracts and wheel packaging | Passed; full cross-workflow/theme/narrow-layout and encrypted restart/restore acceptance remains Slice 57 |

   Initial delivery validation: 28 packaged browser tests (16 Slice 51 and 12 shared workflow
   regressions), 6 shared recovery tests and 71 focused backend Lease, Inspection
   and File readiness/workflow tests passed.
   Review fixes (October 11, 2026): 19 Slice 51 browser tests and 56 focused Lease/Inspection
   readiness tests passed. Frontend lint, formatting, type checking, contract reproducibility,
   wheel packaging and changed-file Python checks passed using the current configuration
   from `application/`. No lint rules were changed. Schema, mutation rollback and encrypted
   backup/restore behavior are unchanged by these read/form fixes; final browser restore
   acceptance remains Slice 57.

9. **Slice 52: Money workflows and reporting drill-down (delivered).**
   Added Rent, Received rent, Expenses, Deposits, Scheduled checks, Owner reports,
   Expense categories and explicit-period Reporting views. All 41 approved
   Finance/Owner forms from Slices 31A–31E use generated request contracts and
   shared OPS preparation, source review and original-result recovery. Rent-ledger,
   Expense, Deposit-account, category and report revisions retain their owning
   scopes; Owner verification reviews both report and ledger revisions and requires
   an explicit receipt-adoption or receipt-creation choice. Supporting uploads are
   separate recoverable commands with byte reselection; an attachment failure does
   not undo or duplicate recorded money.

   Reporting consumes FIN-003 totals and bounded source/property continuations,
   preserves period/scope on changed-view restart and formats USD cents with integer
   arithmetic. Scheduled checks and pending claims remain separate from income.
   Unsupported Lease/Property combinations do not silently become portfolio reads;
   Owner reporting requires an explicit related Property and does not imply amounts
   due to an owner. A typed account-detail GET exposes the existing Deposit read
   projection; Expense detail uses retained link history while list projections keep
   active links, and its typed evidence response includes storage availability and
   verification time. Owner PATCH converts payment-method enums to application strings.
   Persistence, financial policy, schema and transaction ownership are unchanged.

   Evidence is in `apps/web/tests/money.spec.ts` unless noted.

   | Scenario | Evidence | Result / gap |
   | --- | --- | --- |
   | Rent setup, partial allocations and corrections | `rent synchronization and a partial receipt keep allocations and remaining balance visible`; `rent receipt correction voids the predecessor and preserves one current received payment` | Passed against real workspaces; explicit anchor, remaining balance, void/replacement lineage and original receipts |
   | Revision conflicts and retry | `stale rent-ledger input is retained for explicit current-source review`; `owner verification refreshes both revisions after a stale ledger without losing the review note`; `lost expense response reconciles once and evidence failure leaves spending committed` | Passed; edits survive, reviewed revisions are applied explicitly and lost responses recover the original operation without another write |
   | Expense/category lifecycle | `expense no-op, refunds and explicit void/replacement retain original history`; `Expense category create, edit, archive and restore use the catalog receipts` | Passed; no-op preserves timestamp/revision, actual refunds and category receipts remain independent |
   | Scheduled checks | Scheduling/deposit/return and replacement/void tests | Passed; scheduling creates no rent income; explicit deposit creates one receipt, return voids it, and replacement follows a returned/voided predecessor |
   | Deposit settlement | Zero-dollar approval/completion and `settlement evidence, child deletion recovery and partial refunds preserve held-money arithmetic` | Passed; evidence-backed deductions, draft credit editing/deletion, recovery after deletion, approved arithmetic, partial refunds and completion |
   | Owner reports | Creation/patch/rejection and separate existing/create verification tests | Passed; claims are not receipts, both verification modes retain one Finance receipt, and API enum translation is covered |
   | Evidence history and reselection | `supporting evidence can be reselected after restart and metadata retains verified history`; independent upload-failure test | Passed; metadata includes verification/history, archived associations stay in contextual history, bytes stay outside saved OPS payloads, and payment recording remains committed after upload failure |
   | Reporting and bounded reads | Explicit-period totals/source-drill-down test; reporting changed-view restart test; `finance/tests/test_money_summary.py` | Passed; one composed page request, no per-row detail requests, backend totals, source identity and explicit unavailable states |
   | Persistence, rollback and portability | Focused Finance consumer commands, Owner reports and OPS financial-batch/Finance-form suites | Passed; source-owned rollback/schema/encrypted backup and original-receipt proofs reused; account GET has typed identity/revision and missing-record coverage |
   | Shared UI acceptance | `leasing-inspections.spec.ts` and `workflows.spec.ts` | Passed; 31 shared browser regressions. Full cross-workflow theme/narrow-layout, accessibility and encrypted browser restore acceptance remains Slice 57 |

   Validation: 17 Money browser tests, 31 shared browser regressions and 137 focused
   backend tests passed. Frontend lint, formatting, type checking, reproducible
   contracts, wheel packaging, changed-file Python checks and diff whitespace
   validation passed. The existing Vite chunk-size warning remains non-fatal.
   Owner statements, disbursements and fees remain outside this slice.

10. **Slice 53: Maintenance, communications, Tasks and owner concerns (delivered).**
    Bounded work directories and source records now connect the registered issue,
    appointment, cost, quote, assignment, expense-association, journal, follow-up,
    conversation, Task/reminder and Owner-concern commands to the shared editor.
    Current records, reporter attribution, contextual history and related records
    remain distinct from immutable original receipts. Completed Tasks and cancelled
    appointments do not resolve issues; provider-reported partial work is not
    operator verification. Waiting preserves the original deadline and urgency.
    Evidence attachments remain separate recoverable FILE-001 commands, with
    metadata review and unavailable-content guards. No ingestion approval, sending,
    legal or HOA controls are enabled.

    Integration fixes include source-owned Task/issue creation fingerprints and
    accurate OPS descriptors, correction preparation matching COM's recorded
    command, a typed bounded reminder read, Maintenance's existing storage-state
    evidence fields, and packaged `/conversations` routing. No persistence format
    or domain lifecycle policy changes. Choice lists and reminder reads explicitly
    disclose their 100-record bound rather than claiming complete history.

    | Scenario | Evidence | Result / gap |
    | --- | --- | --- |
    | Issue/reporting and attribution | `work.spec.ts`: issue creation; related Property and reporter projection | Passed; real SQLite command and original receipt |
    | Appointment and physical-work separation | Appointment completion/cancellation; provider-reported partial completion and verification flags | Passed; reason required on cancellation, neither appointment nor journal entry resolves its issue |
    | Provider and financial context | Quote, assignment and ending; separate evidence attachment | Passed; source-owned guards and receipts; quoted/assigned work does not create paid expenses |
    | Manual conversations | Draft creation, optional follow-up, recording and correction | Passed; one follow-up remains independent, predecessor and corrected records retain linked context; nothing sent |
    | Task lifecycle and waiting | Creation/reload, edit/stale review, start/cancel/reopen/delete, reminder acknowledgement, completion and waiting clear | Passed; original deadline/priority preserved, reminders and waiting do not complete Tasks |
    | Owner concerns | Create/edit, independent follow-up, resolution and Owner/Property context | Passed; effective relationship checked by owning service, follow-up remains open after concern resolution |
    | Interrupted writes and source loss | Lost issue resolution and lost Task deletion followed by reload/reconciliation | Passed; original-key lookup, one mutation, durable result readable without a live deleted source |
    | Invalid combinations and membership | Missing cancellation reason; foreign-issue child; stale Task input | Passed; input retained and unauthorized/invalid mutation prevented |
    | Read failures, bounds and evidence | Independent directory failure, no per-row HTTP detail reads, 26-Task cursor traversal, available/unavailable metadata | Passed; failure not presented as empty, no gaps/duplicates; unavailable-content presentation includes a simulated provider state |
    | Accessibility and shared editor | Narrow-layout keyboard action; `money.spec.ts` and `workflows.spec.ts` | Passed; 21 slice-specific browser tests and 29 shared regressions. Broad cross-workflow/theme/accessibility acceptance remains Slice 57 |
    | Persistence, rollback and portability | Focused Tasks, Maintenance, Communications, Owner-concern and OPS suites | Passed; 281 backend tests include source rollback/schema and encrypted Task/maintenance history proofs. Browser restore acceptance remains Slice 57; no new schema |

    Frontend lint, formatting, complete type checking, reproducible contracts,
    wheel packaging, changed-file Python checks and diff whitespace validation
    passed. A further 143-test OPS endpoint/recovery contract run passed after
    aligning the source-owned fingerprint descriptors. The existing Vite
    chunk-size warning remains non-fatal.

11. **Slice 54: Search, coverage and review prompts across workspaces (delivered).**
    Global metadata search uses the registered OPS groups, ten-result slices,
    matching totals, archived markers and independent URL continuations. Typed
    targets open their owning records; hidden destinations remain reachable.
    Search typing is debounced and obsolete reads are cancelled. Existing contextual
    directory searches and section continuations remain the workspace search paths.

    Coverage links connect Property/Owner overview facts, inventory spaces, Lease
    records and Maintenance context to area-specific source reads. Explanations,
    applicability, causes, relevant-change prompts and last-review/local-date
    metadata come from OPS. Reviews submit the displayed evidence revision;
    acknowledging a review never fills a required gap. Editable reasons and dates
    survive refreshed or unavailable source facts. A changed revision requires an
    explicit operator review before reuse.

    `coverage.review` is now an allowlisted OPS form with a source-derived
    fingerprint and original review receipt. It reuses Slice 48's autosave,
    navigation guards, immutable attempts and reconciliation rather than introducing
    another store. Interrupted attempts can resume after reload and reconcile the
    original result. Rejected prepared attempts retain their edits and remain locked
    under the shared OPS outcome-resolution rules. Existing Task waiting workflows
    remain the follow-up mechanism. No schema or coverage-policy changes.

    | Scenario | Evidence | Result / gap |
    | --- | --- | --- |
    | Bounded search and typed navigation | `search-coverage.spec.ts`: eleven Task hits, separate continuation, detail/back navigation and hidden Property destination | Passed; ten plus one without gaps/duplicates, two search requests, URL retains the selected group page |
    | Independent failures and cursor restart | Search-source failure/retry and expired group continuation; `context-reads.spec.ts` | Passed; retry targets one group, filters survive restart, unavailable results do not appear empty |
    | Review states and required gaps | Real Maintenance acknowledgment; unknown occupancy and non-applicable lease | Passed; original receipt recorded, gaps retained and non-applicability offered only when source rules permit it |
    | Changed facts, conflicts and outages | Explicit revision review, stale admission race, missing/unsupported subject and unavailable coverage with open edits | Passed; text retained, stale submission rejected, no review written and duplicate/new dispatch guarded |
    | Recovery and original results | Saved-review resume; committed response loss, reload and original-key reconciliation | Passed; uses the existing OPS controller and source receipt, with no list-row recovery fan-out |
    | Persistence, retry and portability | `test_coverage_recovery.py`, `test_coverage.py`, `test_operator.py`, `test_search.py`, `test_web_delivery.py` | Passed; 130 focused tests cover replay, audit rollback, retained tampering, encrypted recovery/receipt round trip and existing query bounds |
    | Accessibility and context | Labeled forms/buttons, narrow unavailable-state layout; contextual directory/source browser regressions | Passed; nine slice-specific and four contextual browser tests. Full theme/keyboard/restore browser acceptance remains Slice 57 |

    Frontend lint, formatting, complete type checking, reproducible contracts,
    changed-file Python checks, wheel packaging and diff whitespace validation
    passed. The existing Vite chunk-size warning remains non-fatal.

12. **Slice 55: Built-in AI configuration, governance and supported draft review (delivered).**
    The Settings route now provides Off/On this device/Cloud service controls,
    registry-derived adapter/model/action capabilities, explicit cloud data-class
    disclosure, write-only credential entry, synthetic connection tests,
    per-action limits, redaction-profile summaries and the global pause. Mutations
    persist allowlisted intents and original attempt keys through OPS before
    dispatch, restore unresolved attempts after navigation/reload, and use
    source-owned revision/idempotency contracts. Credential effects are never
    automatically retried: uncertain results require lookup by the original key
    and explicit acknowledgment. Draft review shows frozen provenance, governed
    input, source comparison, edits and history. Approval is offered only when a
    registered owning-domain handler exists and the source is current and
    available and the displayed JSON matches the acknowledged saved payload.
    Editing clears review confirmation; approval requires review of the saved
    version. Action readiness checks the selected qualified model allowlist and
    enabled connection, as well as the revision-specific synthetic probe.
    Otherwise the UI explains the unavailable or stale state. The API
    response now exposes required data classes and approval availability as typed
    fields. No models are downloaded and no transport fallback is implied.

    | Scenario | Evidence | Result / gap |
    | --- | --- | --- |
    | Settings, pause and no registered capabilities | `ai-governance.spec.ts`: real Settings API pause/clear plus no-adapter/no-action state | Passed; state persists and absence is explicit |
    | Registered cloud connection and disclosure | `ai-governance.spec.ts`: registered adapter/model fixture, connection creation and explicit data-class consent | Passed; choices are registry-bound and disclosure is connection-scoped |
    | Durable command recovery and external uncertainty | `ai-governance.spec.ts`: aborted connection-create, draft-edit and credential responses followed by reload; OPS preparation before dispatch, original-key lookup and acknowledgment | Passed; attempts survive reload, fresh dispatch stays locked, secret excluded from OPS, one request per action |
    | Saved payload approval and action readiness | `ai-governance.spec.ts`: unsaved/invalid JSON, edit reconciliation, renewed version confirmation, successful probe followed by model disallow and connection disable | Passed; approval uses acknowledged edits; availability explains policy failures |
    | Stale or unsupported draft approval | `ai-governance.spec.ts`: changed source and unavailable handler | Passed; governed input and provenance remain visible; approval is not offered |
    | API contracts and focused persistence behavior | `test_governance.py -k run_retains_only_redacted_input_and_replays_same_request`; OpenAPI generation/check | Passed; typed `requiredDataClasses` and `approvalAvailable`, redaction/replay regression retained |
    | Accessibility, shell navigation and quality gates | AI governance and shell Playwright specs; lint, format, typecheck, contracts, Ruff, packaging | Passed; packaged-serving warning about the existing large Vite chunk is non-fatal |

    This delivers the configurable workflow surface, not production model
    availability: the current installation registers no production adapters,
    actions, or owning-domain approval handlers, so generation and approval remain
    explicitly unavailable until those source-owned registrations are composed.
    Model-runtime installation/selection beyond registered options, INGEST-002
    modes, and connected assistants remain outside UI-001; connected assistants
    remain UI-002. Slice 57 still owns broad integration/accessibility acceptance.

13. **Slice 56: Home shell and shared attention/calendar primitives (delivered).**
    Home explains that the combined work queue/calendar is unavailable and links
    to delivered Task deadlines and Waiting follow-ups. Shared typed components
    render Needs action, Waiting, Upcoming, information review and calendar items
    through D35 disclosures. Source adapters supply classifications, totals,
    timestamps and actions; calendar display preserves all-day dates and explicit
    timed zones. Live Task deadline and follow-up directories reuse these rows and
    open the existing recoverable Task workflows. No new aggregate endpoint or
    browser-derived Home queue is introduced. DASH-001 retains Home composition
    and its aggregate acceptance criteria.

    | Scenario | Evidence | Result / gap |
    | --- | --- | --- |
    | Attention, calendar and information-review presentation | `component-tests/attention.spec.ts`: typed fixtures for all four queues and all-day/timed appointments | Passed; source totals and temporal facts are displayed without classification or date conversion |
    | D35, narrow layout and themes | Same component test: full-bar pointer, Enter/Space, retained input, local collapse/focus, unique panel IDs, theme switch and 390px viewport | Passed; controls stay outside the summary bar and edits survive collapse |
    | Home availability and live source actions | `tests/home.spec.ts`: real overdue Task, Home navigation, disclosure, committed Start command and Waiting directory | Passed; source status remains authoritative and an unscheduled follow-up preserves the overdue deadline |
    | Shell and frontend checks | `tests/shell.spec.ts`; lint, format, typecheck, contracts and packaging | Passed; existing bundle-size warning is non-fatal |
    | Persistence, retries and restore | Existing Task/OPS receipts are consumed without backend or schema changes | No new persistence; broader interrupted-command and encrypted-restore browser acceptance remains Slice 57 |

14. **Slice 57: UI-001 integration, accessibility and production hardening (delivered).**
    The acceptance runner gives each workflow suite a fresh temporary workspace,
    preserving state within each suite for original-key recovery. Packaged wheel
    assets serve the delivered routes; browser multipart submissions from an
    unrelated origin fail before request admission. Source actions pass keyboard,
    focus, reduced-motion, 200% text-reflow and WCAG automated checks in Light and
    Dark at 390px, 900px and 1440px. Narrow-window heading and control sizing was
    corrected after the reflow test exposed overflow.

    The restart/restore acceptance case interrupts a committed Task response,
    resumes its saved original attempt after a real process restart, and checks
    that there was one dispatch. Production encrypted backup/restore preserves
    workspace identity, the original command receipt, Task state, saved form,
    appearance preference, immutable evidence metadata, archived association
    history, Intake provenance/correction/supersession history and exact content
    bytes. Each new runtime has a different epoch;
    sensitive form and record text stays out of browser storage. Backup secrets
    are supplied only to the local test coordinator and are never browser inputs.

    Manual Intake is available under Conversations → Retained source evidence.
    Its six registered commands use generated contracts and the shared OPS form,
    revision-review and original-receipt controls. The directory filters and
    continuation remain server-owned and bounded; full evidence opens through
    Intake's fail-closed audited read. Imports retain ordered roles/digests while
    bytes require reselection after recovery. Failed or superseded sources retain
    contextual history and do not offer new operator changes.

    | Scenario | Evidence | Result / gap |
    | --- | --- | --- |
    | Keyboard, focus, supported widths and themes | `tests/acceptance.spec.ts`: six real Task edit paths, reduced motion, 200% text reflow and axe WCAG checks; shared component disclosure/dialog tests | Passed; automated checks supplement keyboard/focus validation |
    | Production assets and browser transport | `tests/delivery.spec.ts` and unrelated-origin multipart case in `tests/acceptance.spec.ts` | Passed; actual wheel assets, deep links, CSP/nosniff/cache headers, reserved routes and rejected foreign commands |
    | Lost response, restart and encrypted restore | `tests/restart-restore.spec.ts`; `scripts/web_acceptance_restore.py` invokes production BackupService while the fixture runtime is stopped | Passed; original receipt and stable IDs/history/content survive, epochs change and dispatch count remains one |
    | Domain policy and consequential workflow boundaries | `leasing-inspections.spec.ts`, `money.spec.ts`, `work.spec.ts`, `workflows.spec.ts` | Passed; real source commits, revision conflicts, evidence partial success, receipt adoption, settlement steps, archive history and original-result recovery |
    | Partial sections, paging, navigation and capability gates | `context-reads.spec.ts`, `search-coverage.spec.ts`, `shell.spec.ts`, `workspace-gate.spec.ts`, `ai-governance.spec.ts`, `home.spec.ts` | Passed; independent failures and unavailable integrations remain explicit; source rules and authoritative totals come from the server |
    | Reproducibility and quality | Contracts check, packaged build, frontend lint/format/typecheck; changed Python lint/format | Passed; existing large-bundle warning remains informational |
    | Manual Intake browser workstream | `tests/intake.spec.ts`: real admission/import/correction/supersession/dismissal/reopening, saved input, changed-byte rejection, stale-source review, failed sensitive-read admission and two-page/no-fan-out checks | Passed; original admission dispatch occurs once, raw-source roles and hashes remain ordered, corrections retain reasons, 30 records traverse two bounded pages without gaps |
    | Serialized recovery and conflicting windows | `component-tests/recovery.spec.ts` plus real source conflicts in domain browser suites | Passed; acknowledged autosave, explicit discard, retained competing edits, original-key reconciliation/replay and rejected secret/file recovery |

    Validation: 119 browser cases across isolated workflow suites, six shared
    component cases and six recovery cases passed. Frontend lint, formatting,
    typecheck, reproducible contracts, packaging, changed Python lint/format and
    diff whitespace checks passed. No persistence format changed in this slice.

## Command-safety readiness inventory

The approved backend contracts, OPS registrations and browser acceptance are delivered. This inventory
records their source-owned boundaries and browser handoffs in UI Slices 44–57.
A delivered receipt does not enable a browser control or authorize automatic retries.

| Workflow | Delivered backend boundary | UI handoff or scope boundary |
| --- | --- | --- |
| OPS preferences/recovery | Revision check, immutable operation receipt, same-key replay, payload conflict | Consume through UI Slices 45–48 |
| Communication create/patch/record/correct | Required revision/key, immutable typed original receipt and detailed conflict; explicit OPS form/receipt composition | Backend Slices 10 and 19 and browser Slices 48 and 53 delivered |
| Maintenance issue and child commands | Shared issue revision, required key, atomic effects and immutable typed receipts; explicit OPS issue/child forms | Backend Slices 11 and 19 and browser Slices 48 and 53 delivered |
| Task creation | Required revision zero and UUID key; immutable creation receipt, replay, payload conflict and OPS reconciliation | Backend Slice 7 and browser Slices 48 and 53 delivered; OPS derives the source fingerprint and retains the original attempt key |
| Task waiting/follow-up | TASK-002 expected revision, idempotency and operation lookup; explicit OPS forms | Backend Slice 19 and browser Slices 48 and 53 delivered |
| Task start/complete/cancel/reopen and reminder add/acknowledge/dismiss | Required parent revision and UUID key; atomic immutable receipt, typed response and lookup, same-key replay; explicit OPS forms | Backend Slices 8 and 19 and browser Slices 48 and 53 delivered |
| Task editing/deletion | Required shared revision/key, immutable edit/no-op/delete receipts and retained tombstones; explicit OPS forms | Backend Slices 9 and 19 and browser Slices 48 and 53 delivered; lost deletion reconciles without a live source |
| Portfolio manual status | Required revision/key, complete typed snapshots/conflicts and immutable operation/key lookup; explicit OPS forms | Slices 12 and 19 delivered; browser client/workflow acceptance delivered in UI Slices 48–53 |
| Lease draft/child and timeline actions | Required shared Lease revision/key, immutable original receipts and public read-only ID/key lookup; timeline actions also require the independent Space revision | Slice 13 source contracts and Slice 30 OPS recovery registration delivered; browser integration delivered in UI Slices 48 and 51 |
| Property/Space lifecycle and ownership changes | Required shared Property revision/key, atomic immutable original receipts, typed conflicts and read-only ID/global/scoped key lookup | Slice 14 source contracts and Slice 41's nine inventory OPS forms delivered; browser acceptance delivered in Slices 50–57 |
| Rent and prepaid-check commands | Shared ledger revision/key, immutable original receipts, atomic check/receipt/reminder effects and read-only key recovery; Owner receipt creation uses the same ledger contract | Slice 15 source contracts and all approved Finance OPS batches in Slices 31A–31E delivered; browser client integration delivered in UI Slices 48–53 |
| Expense, Deposit and Owner-report commands | Required aggregate revision/key, original-result recovery, atomic child effects; Owner verification checks both report and ledger revisions | Slice 15 source contracts, Slice 28 category contracts and Slices 31C–31E OPS registration delivered; browser workflow acceptance delivered in UI Slices 48–53 |
| Intake commands | Required source/evidence revisions, immutable original operator results and indexed recovery; consumer attention remains transaction-aware | Slice 16 source contract, Slice 32's six local-operator OPS forms and Slice 57 browser acceptance delivered; system integrity remains source-owned, INGEST-002 consumer consequences belong to UI-002 |
| Files upload / link archival | Required UUID key; immutable original result and bounded recovery; archival requires association revision and returns a current-link conflict snapshot | Slice 17 source contract and Slice 33's two OPS forms delivered; internal reuse and system storage verification are not standalone OPS forms; browser acceptance delivered in Slices 50–57 |
| Owning attachments / inspection lifecycle | Intake and Inspection own immutable receipts and Files batches; Inspection uses a lease-scoped revision and separate template revisions | Intake source contract and import OPS recovery delivered in Slices 16 and 32; Inspection source contract and ten OPS forms delivered in Slices 18 and 34; internal attachment consequences remain owning-workflow operations, not extra Files forms; browser acceptance delivered in Slices 50–57 |
| Party identity | Required Party revision/UUID key, immutable identity receipts, detailed stale conflicts and indexed ID/global-key recovery | Slice 21 source contracts and Slice 35 OPS registration delivered; browser integration delivered in UI Slices 48 and 50 |
| Party contact methods | Required shared Party revision/UUID key, immutable contact results, atomic owning-reference coordination and shared indexed recovery; Tenant resolutions additionally require their current Tenant revision | Slice 22 source contracts and Slice 35 OPS registration delivered; internal role-reference resolution remains an atomic owning consequence; browser integration delivered in UI Slices 48 and 50 |
| Tenant creation/designation, profile/preferences, archive/restore | Required Tenant revision/UUID key, immutable original Tenant results, detailed stale conflicts and indexed ID/global-key recovery; Party identity/contact effects and preference-resolution receipts commit atomically | Slice 23 source contracts and Slice 35 OPS registration delivered; browser integration delivered in UI Slices 48 and 50 |
| Provider creation/designation, profile, archive/restore | Required Provider revision/UUID key, immutable identity/profile results, current-profile stale conflicts and indexed ID/global-key recovery; initial Party/contact/child/category effects and audits commit atomically | Slice 24 source contracts and Slice 36 OPS registration delivered; browser integration delivered in UI Slices 48 and 50 |
| Provider services, areas, work history, references and reputation | Required shared Provider revision/UUID key, immutable original child results, atomic child/profile/audit effects and indexed ID/global-key recovery | Slice 25 source contracts and Slice 36 OPS registration delivered; browser integration delivered in UI Slices 48 and 50 |
| Provider categories and assignments | Required category revision/key or shared Provider revision/key; assign/restore also checks category revision; immutable typed original results and indexed recovery | Slice 26 source contracts and Slice 36 OPS registration delivered; browser integration delivered in UI Slices 48 and 50 |
| Owner concerns and follow-ups | Required shared concern revision/UUID key; immutable original concern and Task results, atomic correlated effects, detailed stale conflicts and indexed recovery; links use COM-owned receipts | Backend Slices 27 and 37 and browser Slices 48 and 53 delivered |
| Expense categories / Maintenance taxonomy | Required category revision/UUID key, immutable original results and indexed recovery; Maintenance has a fixed vocabulary and issue-owned category-edit receipts | Slice 28 source contracts and Slice 31C Expense-category OPS forms delivered; Maintenance category editing uses the existing issue-owned form; editable Maintenance category administration is outside scope; browser acceptance delivered in Slices 50–57 |
| AI configuration and draft review | Required configuration revision or draft version and UUID key; immutable original results, detailed stale conflicts, indexed ID/key recovery; approval receipt and official effects commit in the owning transaction | Slice 29 source contracts and Slice 38 OPS registration delivered for currently registered commands; INGEST-002 approval/dismissal extensions move to UI-002; browser integration delivered in UI Slice 55 |
| AI credentials and connection probes | Required connection revision/key; durable sanitized intent/result, explicit uncertainty acknowledgement, original ID/key/OPS recovery; no automatic external retries | Slice 39 delivered under its approved non-atomic recovery contract; device-local readiness and browser workflow acceptance belong to UI Slice 55 |

The registry now contains 192 explicit command-form keys, including all 41
Slice 31A–31E forms, six Slice 32 forms, two Slice 33 forms, ten Slice 34 forms,
thirteen Slice 35 forms, 32 Slice 36 forms, seven Slice 37 forms, eight Slice 38 forms
and three Slice 39 forms and nine Slice 41 forms,
plus the three existing task-create, maintenance-issue-create and communication-record
schemas (195 total). Only these registered schemas can
begin recoverable attempts. An idempotency field alone does not prove readiness.
Other source-owned APIs remain available but are not thereby registered for
OPS recovery. This inventory does not authorize generic UI retries.

## Backend readiness status and UI handoff

Updated October 9, 2026. **No numbered UI-001 backend readiness slice remains
planned in this inventory.** The approved source/OPS contracts and server
foundation are recorded as delivered. UI-001 remains incomplete until the
[ordered UI slices 44–57](#subsequent-ui-slices--ordered-implementation-plan)
meet their workflow and packaged-browser acceptance gates.

### Delivered backend scope

| Slice group | Delivered boundary |
| --- | --- |
| 1–30 | Selected typed projections, bounded compositions, source-owned revision/idempotency/receipt contracts and initial OPS recovery registrations. Detailed scope and proofs remain in each slice above. |
| 31A–31E | All 41 approved Finance and Owner-report recovery forms. |
| 32–34 | Six local-operator Intake forms, two Files forms and ten Inspection forms. |
| 35–37 | Thirteen Party/Tenant forms, 32 Provider/category forms and seven Owner-concern forms. |
| 38–39 | Eight AI configuration/review forms and three secret-free external-effect forms; credential/probe recovery retains its explicit uncertainty contract. |
| 41 | Nine Property/Space inventory and ownership forms, completing the approved Portfolio recovery batch. |
| 42 | Server-side local browser Host/Origin and cross-origin request protection. |
| 43 | Restricted static/SPA serving, package-data isolation and fixture-wheel delivery proofs. |

The command-safety inventory above identifies each workflow's source authority and
browser integration gate. Preserve its 195 registered OPS schemas and reuse the
existing owning commands, revisions, canonical fingerprints and immutable original
results. Backend delivery does not authorize automatic mutation retries or establish
that a browser control is ready.

### Browser acceptance delivery

- **Slice 44 delivered:** actual generated client contracts, React/Vite assets,
  wheel asset inventory and temporary-workspace browser delivery now pass their
  focused gate. This read-only scaffold does not establish domain workflow readiness.
- **Slice 45 delivered:** bootstrap gates domain children, distinguishes safe
  workspace reasons from connection failure, and isolates workspace query scopes.
- **Slice 46 delivered:** shared navigation registry, explicit nested property/owner
  sections, responsive navigation and revision-safe appearance/navigation Settings.
  Domain routes explain pending UI delivery without claiming empty results.
- **Slice 47 delivered:** reusable D35 disclosures, async availability states,
  directories/tables, form and confirmation primitives with focused browser proofs.
- **Slice 48 delivered:** mutation error normalization, serialized autosave,
  durable OPS attempts, receipt reconciliation, RHF form ownership and guarded
  navigation; real Task commands exercise the shared recovery contracts.
- **Slice 49 delivered:** bounded property/owner directories, contextual read
  workspaces, independent section continuations, explicit-period whole-property
  money and on-demand source detail.
- **Slice 50 delivered:** registered Portfolio inventory/manual-status, shared
  Party/contact, Tenant and Provider/category/child forms, contextual history,
  source review, recovery and original-receipt reconciliation.
- **Slice 51 delivered:** Lease/Inspection forms, independent timeline revisions,
  original receipts, byte-reselection recovery and bounded contextual reads.
- **Slice 52 delivered:** Money records and Finance/Owner forms, original receipts,
  explicit-period reporting, backend totals and bounded source drill-down.
- **Slice 53 delivered:** Maintenance/child, manual conversation, Task/reminder,
  waiting and Owner-concern workflows, bounded reads, source guards and original
  receipts, including lost-response recovery after Task deletion.
- **Slice 54 delivered:** grouped metadata search, typed contextual links,
  source-backed coverage prompts and review decisions, with OPS form recovery,
  immutable original receipts and retained-data/restore validation.
- **Slices 55–56 delivered:** source-owned AI configuration/review controls,
  truthful registration gates and shared Home attention/calendar primitives.
- **Slice 57 delivered:** manual Intake workflows, packaged browser acceptance,
  unrelated-origin multipart security, accessibility/reflow, shared recovery and
  encrypted restart/restore proofs complete UI-001's acceptance gate.

### Scope boundaries

Slice 40 remains assigned to
[UI-002 issue-review readiness](../../active/DATA-002_DESIGN.md#ingest-002--issue-review-readiness-and-recovery-former-slice-40);
do not reuse its number. INGEST-002 approval modes, consumer-owned dismissal,
Intake/Maintenance consequences and issue-review OPS forms do not gate UI-001.
Generic AI review and local-operator Intake registrations remain available in
UI-001. DASH-001 owns real Home aggregation; UI-001 supplies its shell and primitives.

Internal file reuse, storage verification and system Intake transitions retain
their source/consumer ownership and are intentionally not standalone OPS forms.
New operator workflows require a separately defined scope and registration batch.
Optional production model/action availability remains capability-gated and does
not block manual workflows.

### Validation policy for future backend extensions

If an approved UI workflow reveals a new backend requirement, record its owning
contract, exact scope, receipt/recovery authority and focused test locations before
adding a slice. Reuse existing source contracts and transactions; do not introduce
another mutation ledger or rebuild original outcomes from current state. Document
the delivered evidence in the owning slice and command-safety inventory.

The following matrix applies to command/persistence extensions. Pure transport
or static-serving work documents no-effects and zero-database-query proofs,
with schema/backup areas explicitly unchanged where applicable.

| Area | Focused proof |
| --- | --- |
| Happy paths | Real persistence-backed commands, lifecycle changes and no-ops; effective changes advance the owning revision according to its contract; original typed results are recorded before commit |
| Invalid combinations | Required revision/key validation from HTTP and direct callers; lifecycle, ownership and field-combination guards; typed stale conflicts include the current owning state |
| Idempotency/retry | Same-key replay returns the original result after later changes; changed payload reuse conflicts; concurrent duplicate submissions and competing revisions behave correctly; read-only ID/key recovery uses retained receipts |
| Rollback | Domain effects, revisions, receipts and correlated audits commit or roll back together; cross-module writes and attachment publication/cleanup participate where applicable |
| Persistence/schema | Exact current schema, constraints, indexes and immutable receipt triggers; canonical requests/fingerprints/results, legal revision history and correlated audit evidence; retained-data tampering is rejected |
| Backup/restore | Encrypted LOCAL-002 round trip preserves stable IDs, original results, revisions, lineage and correlated audit history |
| Query budget | Bounded projections and indexed recovery; no per-record recovery reads, N+1 queries or post-commit reconstruction of original mutation results |

The backend delivery record and detailed validation evidence follow. Their delivered
status does not replace the route/workflow acceptance required by these UI slices.

## Delivery history and source contracts

Backend Slices 1–43 and the detailed original delivery record are preserved in the [historical matrix](../../archive/implementation-plans/UI-001_IMPLEMENTATION_MATRIX.md). Current backend contracts are documented in [module guides](../../README.md#current-modules). This active matrix owns ordered browser delivery and remaining acceptance.

## Explicit manual Intake acceptance (delivered)

Slice 57 delivers the manual Intake browser workstream and records its focused evidence in the validation table above. Issue-proposal approval and assistant setup remain UI-002.
