# UI-001 implementation slices

Status: backend readiness Slices 41–43 and frontend Slices 44–51 delivered — October 11, 2026. Browser workflows in Slices 52–57 remain open; UI-001 is not complete.

Scope alignment — October 9, 2026: INGEST-002 issue-proposal review and its
feature-specific AI approval modes, Intake attention consequences, coordinated
Maintenance writes and OPS recovery registration belong to UI-002. The former
planned Slice 40 is tracked in [UI-002's preliminary design](UI-002_DESIGN_preliminary.md#ingest-002--issue-review-readiness-and-recovery-former-slice-40).
None of that work gates UI-001. Delivered generic AI-governance and local-operator
Intake contracts remain in this matrix; their delivery does not enable INGEST-002.
The recorded backend readiness gate and React scaffold are complete; browser workflow delivery follows the ordered UI slices below.

## Subsequent UI slices — ordered implementation plan

Updated October 11, 2026. Backend Slices 41–43 are recorded as delivered;
Slices 44–51's React build, workspace gate, navigation, shared components, recovery transport, contextual reads and Portfolio/identity/Provider/Lease/Inspection workflows are delivered. Implement the
following slices sequentially. Slice numbers continue after the backend sequence;
Slice 40 stays assigned to UI-002. Slices 44–51 are delivered; Slices 52–57 remain planned.
The [UI-001 design](UI-001_DESIGN.md#technical-implementation-design) owns the
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

9. **Slice 52: Money workflows and reporting drill-down.**
   Deliver Rent, Expenses, Deposits, Scheduled checks and Owner reports using the
   approved Finance/Owner forms in Slices 31A–31E. Include rent setup/synchronization,
   allocations/corrections, prepaid-check handling, Expense categories, settlement
   and owner-report verification. Format money exactly and use backend totals;
   scheduled checks and pending reports are never received income. Verify partial
   payments, stale ledger/aggregate conflicts, no-op replay, corrections/history,
   explicit-period FIN-003 reporting and source-record drill-down. Later owner
   statements/disbursements/fees remain outside this slice.

10. **Slice 53: Maintenance, communications, Tasks and owner concerns.**
    Connect issue/reporting and child workflows, assignment/appointments/work
    journals, completion review, manual conversations and optional follow-up,
    Task/reminder lifecycle and owner concerns. Keep issue resolution, physical
    verification, appointment completion and Task/reminder completion distinct.
    Preserve waiting context, due follow-up and original deadlines/urgency.
    Verify source-owned guards, related-record links, partial outcomes and original
    receipt recovery. No ingestion approval, sending, legal or HOA controls are added.

11. **Slice 54: Search, coverage and review prompts across workspaces.**
    Add bounded contextual/global search, grouped results, typed targets, archived
    markers and continuations. Present source-backed coverage states, explanations,
    non-applicability and review decisions with the displayed area evidence revision.
    Preserve required gaps and dirty forms when sources change. Verify membership
    failures, stale review conflicts, relevant-change prompts, hidden-destination
    links and absent/unavailable coverage. Reuse recovery from Slice 48 and waiting
    workflows from Slice 53; do not create duplicate state stores or policies.

12. **Slice 55: Built-in AI configuration, governance and supported draft review.**
    Deliver Off/On this device/Cloud service controls, registered capabilities,
    write-only credentials, explicit destination disclosure, synthetic tests,
    per-action limits and global pause. Use Slice 39's external-effect uncertainty
    and acknowledgement contract; no automatic credential/probe retries. Show
    frozen provenance, governed input, edits and source-checked review only for
    registered owning handlers. Verify unavailable runtime, missing credentials,
    unsupported modality, pause, restore and stale-source failures. Optional model
    availability must not block manual work. INGEST-002 modes and connected
    assistants remain UI-002.

13. **Slice 56: Home shell and shared attention/calendar primitives.**
    Connect the Home route, reusable Needs action/Waiting/Upcoming/calendar and
    information-review components, D35 disclosure and ready source-action adapters.
    Test rendering and interaction using typed fixtures plus real domain actions.
    Show an explicit limited/unavailable state until the DASH-001 composition is
    delivered; do not simulate completed Home with browser-derived aggregates.
    DASH-001 retains real Home aggregation and its aggregate acceptance criteria.

14. **Slice 57: UI-001 integration, accessibility and production hardening.**
    Run the design's validation scenarios across real temporary workspaces,
    complete risk-based browser tests and verify keyboard/focus, both themes,
    narrow layouts, mixed-section failures and context-preserving navigation.
    Exercise source conflicts, interrupted commands, restart and encrypted restore,
    credential isolation and no duplicate effects. Finish actual packaged-serving
    and unrelated-origin/multipart security proofs from Slices 42–44. Verify every
    visible control has a delivered capability, generated contracts are reproducible
    and all frontend quality checks pass. Record remaining unavailable optional
    features truthfully; mark UI-001 complete only when its definition of done passes.

## Command-safety readiness inventory

The approved backend contracts and OPS registrations are delivered. This inventory
separates that delivery from pending browser workflow acceptance in UI Slices 52–57.
A delivered receipt does not enable a browser control or authorize automatic retries.

| Workflow | Delivered backend boundary | UI handoff or scope boundary |
| --- | --- | --- |
| OPS preferences/recovery | Revision check, immutable operation receipt, same-key replay, payload conflict | Consume through UI Slices 45–48 |
| Communication create/patch/record/correct | Required revision/key, immutable typed original receipt and detailed conflict; explicit OPS form/receipt composition | Slices 10 and 19 backend contracts delivered; browser client integration follows UI Slices 48–53 |
| Maintenance issue and child commands | Shared issue revision, required key, atomic effects and immutable typed receipts; explicit OPS issue/child forms | Slices 11 and 19 backend contracts delivered; browser client integration follows UI Slices 48–53 |
| Task creation | Required revision zero and UUID key; immutable creation receipt, replay, payload conflict and OPS reconciliation | Backend contract delivered in slice 7; UI Slices 48 and 53 must retain the exact command fingerprint and attempt key |
| Task waiting/follow-up | TASK-002 expected revision, idempotency and operation lookup; explicit OPS forms | Slice 19 registration delivered; browser attempt integration follows UI Slices 48 and 53 |
| Task start/complete/cancel/reopen and reminder add/acknowledge/dismiss | Required parent revision and UUID key; atomic immutable receipt, typed response and lookup, same-key replay; explicit OPS forms | Slices 8 and 19 delivered; browser client/workflow acceptance remains in UI Slices 48–53 |
| Task editing/deletion | Required shared revision/key, immutable edit/no-op/delete receipts and retained tombstones; explicit OPS forms | Slices 9 and 19 delivered; browser client integration follows UI Slices 48–53 |
| Portfolio manual status | Required revision/key, complete typed snapshots/conflicts and immutable operation/key lookup; explicit OPS forms | Slices 12 and 19 delivered; browser client/workflow acceptance remains in UI Slices 48–53 |
| Lease draft/child and timeline actions | Required shared Lease revision/key, immutable original receipts and public read-only ID/key lookup; timeline actions also require the independent Space revision | Slice 13 source contracts and Slice 30 OPS recovery registration delivered; browser integration follows UI Slices 48 and 51 |
| Property/Space lifecycle and ownership changes | Required shared Property revision/key, atomic immutable original receipts, typed conflicts and read-only ID/global/scoped key lookup | Slice 14 source contracts and Slice 41's nine inventory OPS forms delivered; browser transport follows |
| Rent and prepaid-check commands | Shared ledger revision/key, immutable original receipts, atomic check/receipt/reminder effects and read-only key recovery; Owner receipt creation uses the same ledger contract | Slice 15 source contracts and all approved Finance OPS batches in Slices 31A–31E delivered; browser client integration follows UI Slices 48–53 |
| Expense, Deposit and Owner-report commands | Required aggregate revision/key, original-result recovery, atomic child effects; Owner verification checks both report and ledger revisions | Slice 15 source contracts, Slice 28 category contracts and Slices 31C–31E OPS registration delivered; browser workflow acceptance remains in UI Slices 48–53 |
| Intake commands | Required source/evidence revisions, immutable original operator results and indexed recovery; consumer attention remains transaction-aware | Slice 16 source contract and Slice 32's six local-operator OPS forms delivered; system integrity remains source-owned, INGEST-002 consumer consequences belong to UI-002; browser transport follows |
| Files upload / link archival | Required UUID key; immutable original result and bounded recovery; archival requires association revision and returns a current-link conflict snapshot | Slice 17 source contract and Slice 33's two OPS forms delivered; internal reuse and system storage verification are not standalone OPS forms; browser transport follows |
| Owning attachments / inspection lifecycle | Intake and Inspection own immutable receipts and Files batches; Inspection uses a lease-scoped revision and separate template revisions | Intake source contract and import OPS recovery delivered in Slices 16 and 32; Inspection source contract and ten OPS forms delivered in Slices 18 and 34; internal attachment consequences remain owning-workflow operations, not extra Files forms; browser transport follows |
| Party identity | Required Party revision/UUID key, immutable identity receipts, detailed stale conflicts and indexed ID/global-key recovery | Slice 21 source contracts and Slice 35 OPS registration delivered; browser integration follows UI Slices 48 and 50 |
| Party contact methods | Required shared Party revision/UUID key, immutable contact results, atomic owning-reference coordination and shared indexed recovery; Tenant resolutions additionally require their current Tenant revision | Slice 22 source contracts and Slice 35 OPS registration delivered; internal role-reference resolution remains an atomic owning consequence; browser integration follows UI Slices 48 and 50 |
| Tenant creation/designation, profile/preferences, archive/restore | Required Tenant revision/UUID key, immutable original Tenant results, detailed stale conflicts and indexed ID/global-key recovery; Party identity/contact effects and preference-resolution receipts commit atomically | Slice 23 source contracts and Slice 35 OPS registration delivered; browser integration follows UI Slices 48 and 50 |
| Provider creation/designation, profile, archive/restore | Required Provider revision/UUID key, immutable identity/profile results, current-profile stale conflicts and indexed ID/global-key recovery; initial Party/contact/child/category effects and audits commit atomically | Slice 24 source contracts and Slice 36 OPS registration delivered; browser integration follows UI Slices 48 and 50 |
| Provider services, areas, work history, references and reputation | Required shared Provider revision/UUID key, immutable original child results, atomic child/profile/audit effects and indexed ID/global-key recovery | Slice 25 source contracts and Slice 36 OPS registration delivered; browser integration follows UI Slices 48 and 50 |
| Provider categories and assignments | Required category revision/key or shared Provider revision/key; assign/restore also checks category revision; immutable typed original results and indexed recovery | Slice 26 source contracts and Slice 36 OPS registration delivered; browser integration follows UI Slices 48 and 50 |
| Owner concerns and follow-ups | Required shared concern revision/UUID key; immutable original concern and Task results, atomic correlated effects, detailed stale conflicts and indexed recovery; links use COM-owned receipts | Slice 27 source contracts and Slice 37 OPS registration delivered; browser integration follows UI Slices 48 and 53 |
| Expense categories / Maintenance taxonomy | Required category revision/UUID key, immutable original results and indexed recovery; Maintenance has a fixed vocabulary and issue-owned category-edit receipts | Slice 28 source contracts and Slice 31C Expense-category OPS forms delivered; Maintenance category editing uses the existing issue-owned form; editable Maintenance category administration is outside scope; browser transport follows |
| AI configuration and draft review | Required configuration revision or draft version and UUID key; immutable original results, detailed stale conflicts, indexed ID/key recovery; approval receipt and official effects commit in the owning transaction | Slice 29 source contracts and Slice 38 OPS registration delivered for currently registered commands; INGEST-002 approval/dismissal extensions move to UI-002; browser integration follows UI Slice 55 |
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

### Remaining acceptance belongs to UI delivery

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
- **Slices 52–56:** consume the delivered bootstrap, source and OPS contracts;
  implement route states, contextual workflows, recovery and accessibility. Each
  enabled workflow needs a real critical read/write integration path and truthful
  capability registration. Do not reconstruct domain rules or receipts in the browser.
- **Slice 57:** finish cross-workflow verification, unrelated-origin/multipart
  browser security, actual packaged serving, restart/restore and the UI-001
  definition of done. Keep these final acceptance proofs distinct from the
  delivered server-only evidence in Slices 42–43.

### Scope boundaries

Slice 40 remains assigned to
[UI-002 issue-review readiness](UI-002_DESIGN_preliminary.md#ingest-002--issue-review-readiness-and-recovery-former-slice-40);
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

Backend Slices 1–43 and the detailed original delivery record are preserved in the [historical matrix](../archive/implementation-plans/UI-001_IMPLEMENTATION_MATRIX.md). Current backend contracts are documented in [module guides](../README.md#current-modules). This active matrix owns ordered browser delivery and remaining acceptance.

## Explicit manual Intake acceptance

UI-001 retains manual source admission/import, bounded source/detail presentation, correction/supersession, dismissal/reopening, sensitive-read failure handling, attachments and original-operation recovery. Track these as a named workstream within the remaining UI delivery before Slice 57 completion. The existing numbered Slice 55 focuses AI controls; that focus must not drop manual Intake obligations. Issue-proposal approval and assistant setup stay in UI-002.
