# UI Interaction Test Plan — `http://127.0.0.1:8001`

## 1. Scope & Observed Baseline

Target URL: `http://127.0.0.1:8001` (redirects to `/home?horizonDays=7&fromOn=2026-11-01&throughOn=2026-11-30`).

| Area | Observed Live Baseline |
| --- | --- |
| Workspace mode | Local operator workspace (`Local workspace connected. · No successful backup yet`) |
| Top-level tabs (9) | `Home`, `Properties`, `Owners`, `Tenants`, `Leasing`, `Money`, `Maintenance`, `Providers`, `Settings` |
| Global utility routes | `Search (Ctrl/⌘ K)` (`/search`), `Unfinished forms` (`/settings/recovery`) |
| Existing data counts | 14 active properties (15 units), 10 active owners, 12 tenants, 9 signed leases, 18 rent expectations, 8 expense categories, 9 open maintenance issues, 0 owner concerns, 20 providers, 7 provider categories, 0 unfinished forms |
| Theme & preferences | `Light` theme, Home auto-refresh `Every 5 minutes (default)`, all 7 optional sidebar destinations visible in default order, AI destination `Off` |

## 2. Test Data Hygiene & Execution Rules

- **Naming convention**: Prefix every newly created test record with `[UI-TEST]` (e.g., `[UI-TEST] Cedar Duplex`, `[UI-TEST] Jordan Avery`, `[UI-TEST] Plumbing Check`) so synthetic records are unambiguous.
- **Cleanup**: Archive, void, or delete synthetic `[UI-TEST]` records created during the run and restore `Settings` (theme, nav order/visibility, refresh interval, AI destination) to baseline defaults at the end.
- **Observability gates (every section)**:
  - Zero uncaught browser console errors or unhandled promise rejections.
  - Zero unexpected HTTP `5xx` responses (expected `400`/`422`/`409` validation tests must render structured inline feedback without crashing or losing form input).
  - Keyboard focus, `← Back` / `Return to Home` links, and browser Back/Forward behave predictably.
- **Failure reporting requirement**:
  - For every failed, partial, or defective check, document explicit numbered **Steps to Reproduce**, **Expected Result**, and **Actual Result** (including exact URL, inputs, HTTP status/endpoint, and observed UI message).

---

## 3. Global Shell & Cross-Cutting Interactions

| ID | Area | Actions to Test | Expected Result |
| --- | --- | --- | --- |
| G-01 | Landing & Redirect | Open `http://127.0.0.1:8001/` | Redirects to `/home` with default `horizonDays`, `fromOn`, `throughOn` query params; sidebar shows all 9 tabs and local workspace/backup status. |
| G-02 | Keyboard Shortcut & Search | Press `Ctrl+K` / `⌘+K`, follow to `/search`; enter 1 char, then `>=2` chars (e.g., `Alder`), toggle `Include archived records`, open a result, click `← Back to Home` | Shortcut focuses `Search (Ctrl/⌘ K)`; `<2` chars prompts for 2+ chars; `>=2` chars returns matching records; clicking a result navigates cleanly. |
| G-03 | Unfinished Forms / Draft Recovery | Open a create form (e.g., `Create tenant`), type partial input, navigate away to `/settings/recovery`, verify draft appears under `Continue editing`, resume it, then discard/clear it | Draft persists with entered values, resumes into the form, and disappears from `/settings/recovery` once discarded or submitted. |
| G-04 | Theme Persistence | Switch `Light` → `Dark` in `/settings`, reload page, verify `data-theme="dark"` without flash; switch back to `Light` | Theme persists across reloads and updates all surfaces cleanly. |
| G-05 | Responsive Narrow Nav & Overflow | Resize viewport to mobile width (`<768px`), open/close `Navigation` `<details>` drawer, navigate via drawer; test desktop sidebar overflow `More` menu when hiding/reordering items | Narrow drawer opens, navigates, and auto-closes on route change; no horizontal overflow at 320–390px. |
| G-06 | Invalid Route Fallback | Navigate to `/nonexistent-route` and `/properties/not-a-uuid/overview` | Renders `Page unavailable` with working `Return Home` link (no crash). |

---

## 4. Tab-by-Tab Interaction Matrix

### Tab 1: Home (`/home`, `/home/collections/:collection`, `/home/inventory`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| H-01 | Filters & URL Sync | Open `Filters`, select a specific property, change `Upcoming horizon` (`7` → `30` → `90 days`), change `Money from` / `Money through`, click `Clear filters` | Query params update, scope banner reflects selected property, widgets refresh without errors, `Clear filters` restores defaults. |
| H-02 | Manual Refresh | Click `Refresh` | Button disables while loading, then re-enables with updated data. |
| H-03 | Work Queue Sub-tabs & Expandable Cards | Switch `Needs action` → `Waiting` → `Upcoming`; click `How to expand items`; expand/collapse an item card; click `Review issue`, `Record payment`, and `View` | Sub-tabs switch cleanly; cards expand/collapse with details; action links navigate to the exact target record with working `Return to Home`. |
| H-04 | Full Collection Drill-downs | Open `View all Needs action`, `View all Waiting`, `View all Upcoming`, `View all Calendar and appointments`, `View all Information review` | Each `/home/collections/*` view loads matching items, preserves filters, and navigates back cleanly. |
| H-05 | Recorded Money & Inventory Links | Click a `Recorded money` metric link (`Rent received`, `Expenses paid`, etc.) and `Vacant rental units` (`/home/inventory?occupancy=vacant`) | Opens `/money?tab=reporting&metric=...` with the date range prefilled, and `/home/inventory` filtered to vacant units. |

### Tab 2: Properties (`/properties`, `/properties/:id/*`, `/coverage/property/:id/:area`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P-01 | Portfolio Filters & Quick Links | Test search by name/address, `State` (`Active`/`Archived`/`All`), `Ownership context`, `Occupancy`, `Leasing status` + `About leasing status` info popover, `Needs attention`, quick status links (`Occupied`, `Vacant`, `Open for leasing now`, `Review status`), `Clear filters` | List count and cards update accurately for every filter combination; `Clear filters` resets to default 14 active properties. |
| P-02 | Create Property (Validation + Happy Path) | Click `Create property`; submit empty form to verify validation; then create `[UI-TEST] Cedar Duplex` (multi-unit or single-unit with address, ownership context, and owner share) | Inline validation blocks invalid submit; valid submit creates property and navigates to its workspace. |
| P-03 | Property Detail Sub-tabs (all 8) | On `[UI-TEST] Cedar Duplex` (and one existing property), visit all 8 tabs: `Overview`, `Units` (or layout-specific label), `Leases`, `Money`, `Maintenance`, `Conversations`, `Documents` (verify scheduled/unavailable placeholder), `Property setup`; test `View in Money` CTA | Every tab loads cleanly; `Documents` renders the expected availability notice without errors; `View in Money` opens `/money?propertyId=...`. |
| P-04 | Units / Spaces CRUD | On `Units` tab, add a unit (`[UI-TEST] Unit A`), edit its occupancy/leasing status or details, and archive/remove it | Unit lifecycle updates persist and reflect on property summary & portfolio counts. |
| P-05 | Property Setup Edit, Ownership & Archive/Restore | On `Property setup`, edit property fields (name/address/notes), test ownership share edit, archive `[UI-TEST] Cedar Duplex`, verify it appears under `State: Archived`, then restore or leave archived per cleanup | Changes persist across reload; archived property disappears from `Active` and appears in `Archived`. |
| P-06 | Information Review / Coverage Flow | From a property card or overview, open a coverage area (`/coverage/property/:id/:area`, e.g., `Occupancy` or `Maintenance`), inspect status, and test any review/acknowledge action | Coverage page loads area state and returns cleanly to the property. |

### Tab 3: Owners (`/owners`, `/owners/:id/*`, `/coverage/owner/:id/:area`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| O-01 | Directory Filters & Links | Test `Search`, `State` (`Active`/`Archived`/`All`), `Show relationships` (`Current`/`Former`/`All`), `Property state`, `Clear filters`; click `Owner concerns` header link | Filtering updates matching owner cards; `Owner concerns` routes to `/maintenance?tab=concerns`. |
| O-02 | Owner Detail Sub-tabs (all 7) | Open an owner and visit all 7 tabs: `Overview`, `Properties`, `Leases`, `Money`, `Maintenance`, `Conversations`, `Details`; test `View in Money` CTA | All 7 tabs render owner-scoped data; `View in Money` opens `/money?ownerId=...`. |
| O-03 | Owner Edit & Contact/Identity Lifecycle | Create a new owner (if exposed via property ownership or party workflow) or edit `[UI-TEST]` contact note on a test owner, verify persistence, then revert/archive | Edits persist cleanly; original data restored if an existing owner is touched (prefer editing a newly created `[UI-TEST]` owner). |

### Tab 4: Tenants (`/tenants`, `/parties`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| T-01 | Search vs Browse Mode | On `/tenants`, verify initial prompt; type 1 char, then `>=2` chars; toggle `Include archived tenants`; click `Browse tenants` (`/tenants?browse=true`) | Live search filters results; Browse mode lists all 12 tenants. |
| T-02 | Create Tenant (Validation + Happy Path) | Click `Create tenant`; test missing required fields; create `[UI-TEST] Jordan Avery` with contact info/preferences | Validation catches missing fields; valid submit creates tenant and opens detail view. |
| T-03 | Edit Tenant, Contact Methods & Official ID | Edit `[UI-TEST] Jordan Avery` details, add/update a contact method or preference, test official ID add/view if available | Updates persist across page reload. |
| T-04 | Archive & Restore Tenant | Archive `[UI-TEST] Jordan Avery`, verify hidden by default and visible when `Include archived tenants` is checked, then restore (or keep archived during final cleanup) | Archive/restore transitions update status badge and directory visibility accurately. |

### Tab 5: Leasing (`/leasing`, `/leases/:id/*`, `/leasing?templates=true`, `/inspections/:id`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| L-01 | Lease List, Filter & Pagination | Filter by each `Lease status` (`All statuses`, `Draft`, `Signed`, `Ended`, `Terminated`, `Voided`); check pagination controls; open an existing signed lease (`/leases/:id/details`) | Filter updates list accurately; detail view renders lease terms, parties, dates, and linked sections. |
| L-02 | Create, Edit & Lifecycle Transitions on Lease Draft | Click `Create lease draft`; link `[UI-TEST]` property/unit and `[UI-TEST] Jordan Avery`; test validation (e.g., invalid date range); save draft; edit draft terms; test signing (or voiding) and verify status updates | Draft creation, editing, and status transition (`Draft` → `Signed` → `Ended`/`Terminated`/`Voided`, or `Draft` → `Voided`) succeed with confirmation dialogs where required. |
| L-03 | Lease Documents & Inspections | Inside a lease detail view, check document upload/linking and inspection creation (`/inspections/:id`) if available | Sub-flows open without errors; any created inspection can be edited/completed or archived. |
| L-04 | Inspection Templates | Click `Manage inspection templates` (`/leasing?templates=true`); create a `[UI-TEST]` inspection template, edit it, archive/delete it, and click `← Back to Leasing` | Template CRUD works end-to-end and returns to `/leasing`. |

### Tab 6: Money (`/money` — all 8 sub-tabs)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| M-01 | `Rent` (`/money?tab=rent`) | Test `Settlement`, `Timeliness`, `Due from`/`Due to`, `Include voided history` filters; open a `Rent due` card (`/money?record=expectation&id=...`); test recording a payment (on `[UI-TEST]` lease expectation if created, or inspect detail drawer actions) | Filters narrow expectations accurately; detail view shows balance, due date, and payment actions. |
| M-02 | `Received rent` (`/money?tab=receipts`) | Test date/party/replacement/voided filters; open a `Rent received` card; on a `[UI-TEST]` receipt, test edit/replace/void lifecycle | Voided receipt hides when `Include voided history` is unchecked and appears when checked. |
| M-03 | `Expenses` (`/money?tab=expenses`) | Test filters (`Space ID`, `Category`, `Provider`, `Payer`, `Paid by`, date range, `Evidence`, `Include voided history`); click `Record paid expense`, create `[UI-TEST]` expense (test validation first), open detail view, test refund/evidence/void | Expense is created, appears in filtered list, and voids cleanly during cleanup. |
| M-04 | `Deposits` (`/money?tab=deposits`) | Test filters (`Settlement state`, `Recorded deadline state`, `Unresolved deposit balance`); click `Create deposit account`, create `[UI-TEST]` deposit account, open detail view, test record transaction / settlement draft / void if supported | Deposit account creation and balance calculations render accurately. |
| M-05 | `Scheduled checks` (`/money?tab=checks`) | Test `Check lifecycle`, `Deposit eligibility`, `Space ID`, `Payer`, `Expectation ID` filters; if check creation is accessible from rent/lease context, test creating and voiding a `[UI-TEST]` scheduled check | Filters work cleanly on empty and populated states. |
| M-06 | `Owner reports` (`/money?tab=reports`) | Click `Record owner rent report`, test validation, create a `[UI-TEST]` owner report, filter by `Report status` (`pending`/`verified`/`rejected`), test status transition (verify/reject) | Report appears in list and transitions status cleanly. |
| M-07 | `Expense categories` (`/money?tab=categories`) | Click `Create expense category`, create `[UI-TEST] Testing Fees`, edit its name/description, archive it (and verify history/restore if present) | Category CRUD persists and respects active/archived visibility. |
| M-08 | `Reporting` (`/money?tab=reporting`) | Verify initial explicit date-range prompt; enter `2026-11-01` through `2026-11-30`, switch `Reporting property state` (`All retained properties`/`Active`/`Archived`), verify totals match `Home → Recorded money` | Reporting loads totals/breakdowns matching Home metrics; invalid range (from > through) shows clear error. |

### Tab 7: Maintenance (`/maintenance`, `/maintenance?tab=concerns`, `/tasks`, `/conversations`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| MT-01 | `Issues` Filters & `More filters` | Test `Status`, `Property`, `Issue category`, `Issue priority`, expand `More filters` (`Reporter role/subject`, `Evidence`, `Linked paid Expense`, `Active follow-up Task`, date range), `Clear filters` | All filters narrow the 9 open issues accurately; `Clear filters` restores full list. |
| MT-02 | Report Issue & Detail Lifecycle | Click `Report maintenance issue`; test validation; create `[UI-TEST] Leaky Faucet` on `[UI-TEST]` property; open detail view (`/maintenance?record=issue&id=...`); update status (`Open` → `In progress` → `Resolved`/`Cancelled`) | Issue persists across reload and status transitions record cleanly. |
| MT-03 | Issue Sub-workflows (Quotes, Appointments, Tasks, Evidence, Linked Expenses) | Inside `[UI-TEST] Leaky Faucet`, add a quote, schedule an appointment, create/complete a follow-up task (`/tasks`), log a conversation (`/conversations`), and verify cross-links back to Home (`Upcoming` / `Calendar and appointments`) | Each sub-workflow saves, updates the issue journal, and reflects on Home when scheduled. |
| MT-04 | `Owner concerns` (`/maintenance?tab=concerns`) | Switch to `Owner concerns`, click `Record concern`, create `[UI-TEST]` concern, test all concern filters (`Owner`, `Property`, `Concern type`, `Tenant`, `Status`, `Priority`, date range), transition status (`Open` → `Dismissed`/`Resolved`) | Concern creates, filters accurately, and transitions cleanly. |

### Tab 8: Providers (`/providers`, `/providers/:id/*`, `/settings/provider-categories`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| PR-01 | Filters, `More filters` & Pagination | Test `Search providers`, `Preference`, `Category`, expand `More filters` (`Show providers`, `Category assignment`, `Service`, `Service area`, `Has references`), `Clear filters`, and `Provider pages` pagination | Filters and pagination update the 20-provider list cleanly. |
| PR-02 | Create, Edit, Preferences, References & Archive Provider | Click `Create provider`; test validation; create `[UI-TEST] Acme Plumbing`; open detail view (`/providers/:id/details`); edit preference (`Preferred`/`Avoid`), assign category, add a reference, archive and restore/archive for cleanup | All edits persist across reload; archived provider only shows when `Show providers` includes archived. |
| PR-03 | Provider Categories Link & CRUD | Click `Manage provider categories` (`/settings/provider-categories`); click `Add category` to create `[UI-TEST] Calibration`, click `Edit category`, view `History`, click `Archive category` | Category CRUD and history view work without errors; active count returns to 7 after archiving. |

### Tab 9: Settings (`/settings`, `/settings/provider-categories`, `/settings/ai`, `/settings/recovery`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| S-01 | Appearance & Home Refresh | Toggle `Light`/`Dark`, change `Automatic refresh` interval, click `Save preferences`, reload page, then restore defaults | Preferences persist across reload and restore cleanly. |
| S-02 | Navigation Order & Visibility | Uncheck a destination (e.g., `Providers`), move a destination `Up`/`Down`, click `Save preferences`, verify sidebar reflects order and moves hidden item into `More`; click `Restore defaults` and save | Sidebar immediately reflects order/visibility and restores to default 9-tab layout. |
| S-03 | AI Assistance (`/settings/ai`) | Inspect `Destination` (`Off`/`On this device`/`Cloud service`), toggle `Pause all AI assistance`, click `Save destination`, inspect `Model connections`, `Supported tasks and safeguards`, `Redaction profiles`, and `Drafts for review` status filter; restore `Off` & unpaused | Settings save cleanly without errors; draft filter switches through all 6 statuses. |

---

## 5. Recommended Execution Order

1. **Global Shell & Settings** (`G-01`..`G-06`, `S-01`..`S-03`) — verify shell, search, theme, nav customization, and restore defaults.
2. **Core Directory Setup** (`PR-01`..`PR-03`, `T-01`..`T-04`, `P-01`..`P-06`, `O-01`..`O-03`) — create `[UI-TEST]` provider, category, tenant, property, and unit so downstream tabs have isolated test entities.
3. **Leasing & Inspections** (`L-01`..`L-04`) — create `[UI-TEST]` lease draft & inspection template using the `[UI-TEST]` property/unit/tenant.
4. **Money** (`M-01`..`M-08`) — exercise all 8 Money tabs (including `[UI-TEST]` expense, deposit, owner report, expense category, and reporting parity with Home).
5. **Maintenance & Home** (`MT-01`..`MT-04`, `H-01`..`H-05`) — exercise issues, sub-workflows (quote/appointment/task/conversation), owner concerns, and verify Home work queue / calendar / filters reflect live updates.
6. **Cleanup & Verification** — void/archive all `[UI-TEST]` records, verify `Unfinished forms` is `0`, verify baseline counts & default settings are restored, and report all Pass/Fail/Defect findings with screenshots and exact reproduction steps.


---

## 6. Phase 2: Deep `manual/` Workflow Coverage

The checks below cover documented live operator workflows from [manual/operation-index.md](../../manual/operation-index.md) and the `manual/` chapters that were outside the initial Phase 1 smoke/CRUD pass. Prefix all synthetic Phase 2 records with `[UI-TEST-P2]` and follow the same failure-reproduction rule (numbered Steps to Reproduce, Expected Result, Actual Result).

### 6.1 Office Multi-Suite Properties & Scheduled Occupancy (`manual/portfolio-and-people.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-OF-01 | Create Office Property & Multi-Suite CRUD | Create an `Office` property (`[UI-TEST-P2] Harbor Plaza`, multi-suite layout); on the `Suites` tab, run `Add suite` (`[UI-TEST-P2] Suite 200` and `Suite 201`), `Edit suite`, `Classify suite`, `Archive suite` (`Suite 201`), and `Restore suite` | Tab label renders `Suites`; suite lifecycle changes persist and reflect in property summary and Owner concerns `Suite` filter. |
| P2-OF-02 | Scheduled Occupancy Lifecycle | On `[UI-TEST-P2] Suite 200`, schedule a future occupancy change (`Change occupancy` with future effective date); verify `Scheduled occupancy` section appears; test `Reschedule occupancy`, `Replace scheduled occupancy`, and `Cancel scheduled occupancy` | Each scheduled-occupancy transition updates history and removes the section once cancelled. |

### 6.2 Ownership Shares, Contact Management & Shared `/parties` Roles (`manual/portfolio-and-people.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-OW-01 | `Change ownership` & Share Validation | On `[UI-TEST-P2] Harbor Plaza` → `Overview` → `Change ownership`, use `Create a new owner` inline (`[UI-TEST-P2] Summit Holdings`) alongside `You`; test invalid total share (e.g., `60%` + `60%`), then valid `50%` + `50%` (and partial known + `Not recorded`), save, and verify shares appear on Properties list, Property `Owners`, and Owner `Relationships` | Invalid >100% / non-100% all-known totals are blocked with clear validation; valid shares persist and prior shares stay in history. |
| P2-OW-02 | Primary Contact Switching & Removal | Via `Manage contact details` (from `Change ownership` or `/parties`), add two emails to `[UI-TEST-P2] Summit Holdings`; attempt to remove the `Primary` email while a secondary exists; use `Make primary` on the second email, then remove/archive the first and restore it | Removing primary with alternatives requires switching primary first; `Make primary`, archive (`Remove`), and restore persist cleanly. |
| P2-OW-03 | Shared Identity Multi-Role Reuse (`/parties`) | Open `[UI-TEST-P2] Summit Holdings` under `/parties`; test `Use identity as tenant` and `More actions → Add provider role`; verify the same person/org appears across Owners, Tenants, and Providers with shared contacts | Shared identity links cleanly across roles without duplicating contact records. |

### 6.3 Provider Rich Profile & Official ID Gate (`manual/portfolio-and-people.md`, `manual/maintenance.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-PR-01 | Provider Sub-records Lifecycle | On a `[UI-TEST-P2]` provider, run `Add`/`Edit`/`Archive`/`Restore` for `Services`, `Service areas`, `Work history`, `Reputation links`, and `Category assignment` | Each sub-record persists, toggles archived visibility cleanly, and restores without errors. |
| P2-PR-02 | Provider Full Official ID Reveal & Assignment Gate | Create a `[UI-TEST-P2]` provider with **no** Official ID and attempt `Assign provider` on a maintenance issue; then open `Manage official IDs`, save an ID with an optional **full ID number**, verify it is hidden by default, test `Show ID number` / `Hide ID number`, and verify `Assign provider` now succeeds | Assignment is blocked until an Official ID is recorded; full number stays masked by default and toggles cleanly via Show/Hide. |

### 6.4 Leasing & Inspections Depth (`manual/leases-and-inspections.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-LS-01 | Draft Rent Terms, Participants & Official ID Gate | Create a `[UI-TEST-P2]` lease draft; run `Change rent terms`, `Add lease participant`, `Edit lease participant`, and `Remove lease participant`; attempt `Record signed lease` with a participant who has **no** Official ID, then add an Official ID and execute | Draft edits persist; execution is blocked until every participant has at least one Official ID, then succeeds. |
| P2-LS-02 | Renewal Options | On a `[UI-TEST-P2]` signed lease, run `Add renewal option`, `Edit renewal option`, and `Decide renewal option` | Renewal option lifecycle records the reviewed decision in history without silently creating a successor lease. |
| P2-LS-03 | Inspection Checklist, Correction & Condition Comparison | Create a move-in inspection draft, run `Edit inspection checklist`, attach evidence, finalize; run `Correct finalized inspection` and finalize the correction (confirm original is retained); create a move-out inspection and run `Review condition comparison` | Checklist edits, correction lineage, and condition comparison decision save cleanly without auto-creating deductions. |
| P2-LS-04 | `Void lease` Discovery & Execution | Verify where `Void lease` is exposed (signed vs draft lease) and execute `Void lease` on a `[UI-TEST-P2]` lease with required reason/confirmation | Lease transitions to `Voided`, appears under `/leasing` `Voided` filter, and retains history. |

### 6.5 Money Depth (`manual/money.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-MN-01 | Partial / Multi-Period Rent Allocation, Timeliness & Void Expectation | On `[UI-TEST-P2]` rent expectations, record a partial payment (verify unallocated-total validation blocks mismatched submit), then record a multi-period payment using `Allocate remaining…`; test `Review rent timeliness` (mark missed / clear missed) and `Void rent expectation` | Allocations split accurately across periods; timeliness decisions and voided expectations update balances and history. |
| P2-MN-02 | Prepaid Check Deposit, Return & Replace | Schedule a `[UI-TEST-P2]` prepaid check; test `Replace prepaid check` (verify predecessor lineage); on an eligible check, run `Deposit prepaid check` (creating/adopting receipt) and `Return prepaid check` | Deposit creates/links receipt; Return reverses receipt and reopens the expectation balance cleanly. |
| P2-MN-03 | Expense Context Edit & Expense Refunds | Record a `[UI-TEST-P2]` paid expense; run `Edit expense context`, `Record expense refund`, verify `Net recorded expenses` decreases in Reporting, then `Void expense refund` | Context edits, refund creation, reporting math, and refund voiding all match `manual/money.md`. |
| P2-MN-04 | Full Deposit Settlement Lifecycle | On a `[UI-TEST-P2]` deposit account with a held receipt, run `Prepare deposit settlement` → `Add`/`Edit`/`Delete` settlement deduction, credit, and deduction source (file/inspection/expense/expectation) → `Approve deposit settlement` → `Record deposit refund` (partial, then remainder) → `Complete deposit settlement`; also test `Void deposit receipt` / `Void deposit settlement` on a second test deposit | Frozen approval, partial vs full refund tracking, zero-balance completion guard, and void lineage work without errors. |
| P2-MN-05 | Owner Rent Report Full Lifecycle | On an owner-managed property (`[UI-TEST-P2] Harbor Plaza`), run `Record owner rent report` → `Edit owner rent report` → `Verify owner rent report` (test adopting existing receipt vs creating receipt); create a second report and `Reject owner rent report` with explanation | Pending reports do not inflate received income; verified report counts the Finance receipt exactly once; rejected report retains explanation. |

### 6.6 Maintenance Depth (`manual/maintenance.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-MT-01 | Edit Issue & Correct Reporter | On a `[UI-TEST-P2]` issue, run `Edit issue` and change reporter attribution (test missing correction reason validation, then valid reason) | Both detail and reporter updates save atomically; report time, property, and status remain unchanged. |
| P2-MT-02 | Quotes, Provider Assignment & Avoided Override | Record two quotes, `Withdraw quote` on one; `Assign provider` from the other quote; test `End provider assignment`, direct assignment (with required reason), and assigning an `Avoid`-preference provider (verifying explicit override/reason prompt) | Quote/assignment lifecycle and avoided-provider override work cleanly and retain history. |
| P2-MT-03 | Appointments, Cost Context, Linked Expense & Work Journal | Run `Reschedule appointment`, `Record cost context` / `Void cost context`, `Link paid expense` / `Archive expense association` (confirming underlying Finance expense stays active), `Record work journal entry`, and `Return issue to open` | All issue sub-records persist and follow non-duplication rules (quotes/costs/expenses stay distinct). |

### 6.7 Tasks, Waiting, Reminders, Conversations & Retained Sources (`manual/tasks-and-evidence.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-TK-01 | Tasks Quick Add, Timed Deadlines, Time Zones & DST | On `/tasks`, test Quick add (all-day) and `Optional Task details` (`Due at` timed + `Due time zone`, plus a DST-skipped local time like `2026-03-08 02:30 America/Los_Angeles`); test status/priority/due-window filters, `Start`, `Edit`, `Cancel`, `Reopen`, and `Delete task` | DST-skipped time is rejected without losing form input; all task lifecycle states and filters work cleanly. |
| P2-TK-02 | Waiting Context & Home `Waiting` Tab | On an open `[UI-TEST-P2]` task, run `Set waiting context` (person/event + follow-up time/zone), verify it appears under Home **Waiting** tab; run `Reschedule follow-up` and remove follow-up date (verify `Not scheduled` label); run `Clear waiting context` | Home `Waiting` tab reflects live waiting state and clears when waiting is removed or task is completed. |
| P2-TK-03 | Task Reminders | On a `[UI-TEST-P2]` task, run `Add task reminder`, then test `Acknowledge reminder` and `Dismiss reminder` | Reminder displays in related property's time zone (or browser zone if unlinked) and transitions cleanly. |
| P2-TK-04 | Conversations Draft → Record → Correct | On `/conversations`, run `Create conversation` (save as draft if supported) → `Edit conversation draft` → `Record conversation` → `Correct recorded conversation` (with reason) | Original recorded time is preserved on correction; history retains revision. |
| P2-TK-05 | Retained Sources (`/conversations?intake=true`) | Open `/conversations?intake=true`; test `Retain source`, `Import source evidence`, `Correct source`, `Supersede source`, `Dismiss source`, `Reopen source`, plus filters and pagination | Full retained-source lifecycle persists with provenance, duplicate checks, and revision history. |

### 6.8 Supporting File Attachments & Revision Conflicts (`manual/tasks-and-evidence.md`, `manual/troubleshooting.md`)

| ID | Interaction | Steps | Expected Result |
| --- | --- | --- | --- |
| P2-FL-01 | Attach, Download & Archive Evidence | Upload a small test file (`Attach supporting evidence`) on a `[UI-TEST-P2]` lease, expense, or maintenance issue; verify metadata/download works; run `Archive evidence link` with required reason | File uploads cleanly, downloads intact, and archives the association while preserving history. |
| P2-CF-01 | Two-Tab Stale Revision Conflict | Open the same `[UI-TEST-P2]` record (and `/settings`) in two browser tabs; save a change in Tab 1, then submit a stale edit in Tab 2 | Tab 2 surfaces a clear revision conflict (`Load current preferences` in Settings, or latest-source review on records) without silently overwriting Tab 1's save or discarding Tab 2's edits. |

### 6.9 Phase 2 Execution Order & Cleanup

1. **Office, Ownership & Shared Identities** (`P2-OF-01`..`P2-OW-03`)
2. **Provider Depth & Official ID Gate** (`P2-PR-01`..`P2-PR-02`)
3. **Leasing & Inspections Depth** (`P2-LS-01`..`P2-LS-04`)
4. **Money Depth** (`P2-MN-01`..`P2-MN-05`)
5. **Maintenance Depth** (`P2-MT-01`..`P2-MT-03`)
6. **Tasks, Waiting, Reminders, Conversations & Retained Sources** (`P2-TK-01`..`P2-TK-05`)
7. **File Evidence & Two-Tab Revision Conflicts** (`P2-FL-01`, `P2-CF-01`)
8. **Phase 2 Cleanup**: Void/archive/dismiss all `[UI-TEST-P2]` records, verify `/settings/recovery` has `0 forms`, and verify zero unexpected `5xx` or console errors.
