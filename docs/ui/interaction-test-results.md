# UI Interaction Test Results — `http://127.0.0.1:8001`

- **Plan**: [interaction-test-plan.md](interaction-test-plan.md)
- **Date**: 2026-11-24
- **Target**: `http://127.0.0.1:8001` (Local operator workspace)
- **Status**: Completed

## Summary

| Step | Scope | Status | Pass | Fail / Defect | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Global Shell & Settings (`G-01`..`G-06`, `S-01`..`S-03`) | Done | 7 Pass | 1 Fail, 1 Partial | `G-06` raw JSON 404; `S-03` AI destination silently reverts to Off; `G-03` minor back-link label |
| 2 | Providers, Tenants, Properties, Owners (`PR`, `T`, `P`, `O`) | Done | 14 Pass | 1 Partial, 3 Minor | Background `PUT /api/operator/recovery/...` 422 on autosave; pluralization (`1 matching properties`/`owners`); single-unit-only Create property |
| 3 | Leasing & Inspections (`L-01`..`L-04`) | Done | 2 Pass | 2 Partial | No Draft Void UI; no Inspection Template archive/delete UI; inspection acknowledgment stuck on `Loading participant name…`; opaque 422 message on invalid dates |
| 4 | Money (`M-01`..`M-08`) | Done | 8 Pass | 0 Fail, 1 Minor | All 8 Money sub-tabs passed; minor UX leak: switching from `checks` to `reports` carries `&status=voided` |
| 5 | Maintenance & Home (`MT-01`..`MT-04`, `H-01`..`H-05`) | Done | 7 Pass | 1 Partial (HTTP 500), 2 Minor | **High**: `HTTP 500` on `Report maintenance issue` when `Category detail` is filled (+ `Discard…` 500); **Medium**: voided prepaid check still appears in Home `Upcoming`; **Low**: Home Property `<select>` missing accessible label |
| 6 | Cleanup & Baseline Verification | Done | Partial cleanup | Same-day lease end constraint | Provider archived, settings/recovery restored, baseline money/maintenance/provider/owner counts restored; same-day lease termination blocked (`actual_move_out > occupancy_start` & `<= today`), keeping `[UI-TEST]` lease/property/tenant active until tomorrow |

---

## Detailed Step Logs

### Step 1: Global Shell & Settings (`G-01`..`G-06`, `S-01`..`S-03`)

- **Console errors**: `0`
- **Unexpected HTTP errors**: `GET /nonexistent-route` and `GET /properties/not-a-uuid/overview` returned raw JSON `404 {"detail":"Not Found"}` (`G-06`).

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `G-01` | PASS | `/` redirected cleanly to `/home?horizonDays=7&fromOn=2026-11-01&throughOn=2026-11-30`; all 9 sidebar tabs and `Local workspace connected. · No successful backup yet` rendered. |
| `G-02` | PASS | `Ctrl+K` and `⌘+K` focused `#search-entry`; 1-char input prompted `>=2` chars; `"Alder"` returned matches; `Include archived records` toggled URL param; result link navigated to `/properties/.../overview`; `← Back to Home` worked. |
| `G-03` | PASS *(minor)* | Leave-guard banner (`Save and leave` / `Discard and leave` / `Keep editing`) saved `Create tenant · [UI-TEST] Draft Person` to `/settings/recovery`; resume restored input; `Discard…` returned recovery count to `0`. **Minor defect**: resumed tenant form displayed `← Back to Properties` instead of `← Back to Tenants`. |
| `G-04` / `S-01` | PASS | `Dark` theme (`data-theme="dark"`) and `Every 10 minutes` refresh persisted across reload; restored to `Light` and `Every 5 minutes (default)`. |
| `S-02` | PASS | Unchecking `Providers` and moving `Owners` up reordered sidebar and placed `Providers` under `More`; `Restore defaults` restored 9-tab layout. |
| `G-05` | PASS *(minor)* | At `375x812`, narrow `Navigation` `<details>` drawer opened, navigated to `/properties`, and auto-closed with zero page-level horizontal overflow. *(Minor visual note: internal `Property status filters` strip clips/scrolls inside its own box at 375px.)* |
| `S-03` | PARTIAL | `Pause all AI assistance` persisted across reload and all 6 `Draft status` filters worked. **Defect (Medium)**: selecting `On this device` and clicking `Save destination` displayed `"AI destination settings saved."` with no warning/error, yet `Current state` stayed `Off` and reverted on reload. Restored to `Off` & unpaused. |
| `G-06` | FAIL | **Defect (High)**: Direct navigation to `/nonexistent-route` and `/properties/not-a-uuid/overview` returned raw FastAPI JSON `404 {"detail":"Not Found"}` instead of the SPA `"Page unavailable"` page with `"Return Home"`. |


### Step 2: Providers, Tenants, Properties, Owners (`PR-01`..`PR-03`, `T-01`..`T-04`, `P-01`..`P-06`, `O-01`..`O-03`)

- **Console errors**: `0`
- **Unexpected HTTP errors**:
  - `PUT /api/operator/recovery/...` returned `422` in the background during draft autosave while editing provider/tenant forms.
  - `PUT /api/spaces/54515873-569f-46b3-bcdd-9ec21984ab94/occupancy` returned `400 Bad Request` (`"A transition already exists for this effective date."`) when using `Change occupancy` on the property creation date (`2026-11-24`); `Correct an error` succeeded.
- **Active `[UI-TEST]` entities retained for Steps 3–5**:
  - Provider: `[UI-TEST] Acme Plumbing` (`a60105d6-e7fc-4d01-b4ca-f294b4ded3e0`)
  - Tenant: `[UI-TEST] Jordan Avery` (`60ecd4c0-4680-47f2-923d-66ad3b2d1f2b`)
  - Property: `[UI-TEST] Cedar Duplex` (`4a353014-57c8-4b9c-ae6e-27d21b2f0e26`)
  - Unit/Home: `[UI-TEST] Unit A` (`54515873-569f-46b3-bcdd-9ec21984ab94`)

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `PR-01` | PASS | Search (`"Acme"` -> 1), `Preference=Preferred` (5), `Category=Plumbing` (1), `More filters` (`Show providers`, `Category assignment`, `Service`, `Service area`, `Has references`), and `Clear filters` (20) all worked. Pagination did not render at <=20 items. |
| `PR-02` | PASS | Empty submit validated via `"Please review your form"`. Created `[UI-TEST] Acme Plumbing`, set `Preferred`, added Official ID (`License`, `US/OR`, `9102`), assigned `Plumbing`, added reference `Pat Miller`, archived (visible in Archived), and restored to Active. |
| `PR-03` | PASS | On `/settings/provider-categories`, created `[UI-TEST] Calibration` (7 -> 8), edited to `[UI-TEST] Calibration Updated`, viewed `History`, and archived with reason (returned to 7 active, 1 archived). |
| `T-01` | PASS | Initial prompt shown; 1-char prompted `>=2` chars; `"Ma"` matched `Maya Chen (Demo)`; `Include archived tenants` toggled; `Browse tenants` listed 12 baseline tenants. |
| `T-02`..`T-04` | PASS | Empty submit validated. Created `[UI-TEST] Jordan Avery` with email & Driver's license ID, added phone `503-555-0142`, updated notes/preferred contact, archived (verified hidden/shown with toggle), and restored to Active. |
| `P-01` | PASS *(minor)* | Search, `State`, `Ownership context`, `Occupancy`, `Leasing status` + `"About leasing status"` info, `Needs attention`, quick status links, and `Clear filters` all worked. **Minor defect**: displays `"1 matching properties"` when count is 1. |
| `P-02`..`P-06` | PARTIAL | Created `[UI-TEST] Cedar Duplex` (`Single-family home`), visited all 8 sub-tabs (`Overview`, `Home`, `Leases`, `Money`, `Maintenance`, `Conversations`, `Documents` placeholder, `Property setup`) + `View in Money`, renamed unit to `[UI-TEST] Unit A` & set `Vacant` / `Open for leasing now`, edited notes, archived & restored, and opened Maintenance coverage (`/coverage/property/.../maintenance`). **Notes**: `Create property` uses browser HTML5 `required` tooltip instead of `"Please review your form"` banner and only exposes single-unit property types (`Single-family home`, `Condo`, `Townhome`, `Office`), so multi-unit "Add unit" is unavailable. |
| `O-01`..`O-03` | PASS *(minor)* | Directory filters, `Owner concerns` link, all 7 sub-tabs on `Morgan Chen (Demo)`, and `View in Money` worked. `Details` tab is read-only (shows Relationships; no inline edit controls). **Minor defect**: displays `"1 matching owners"` when count is 1. |


### Step 3: Leasing & Inspections (`L-01`..`L-04`)

- **Console errors**: `0`
- **Unexpected HTTP errors**:
  - Background `PUT /api/operator/recovery/...` returned `422` during form draft autosave on `Create inspection draft`.
- **Created `[UI-TEST]` records**:
  - Active Signed Lease: `024a6974-5e55-4148-b739-02f079ac18e9` (`/leases/024a6974-5e55-4148-b739-02f079ac18e9/details`)
  - Finalized Move-In Inspection: `cbd6aff6-e787-4608-bdd1-cd9c23fc1ccc` (`/inspections/cbd6aff6-e787-4608-bdd1-cd9c23fc1ccc`)
  - Extra Draft Lease (no Void UI available): `7e8657b7-54e3-447b-b1af-5cd007c6059d`
  - Inspection Template (no Archive/Delete UI available): `[UI-TEST] Standard Move-In` (`117b7bde-3e26-40ef-91c9-f1ae111633df`)

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `L-01` | PASS | Filtered all 6 `Lease status` values (`All`, `Draft`, `Signed`, `Ended`, `Terminated`, `Voided`); pagination nav present (hidden while `<=11` items); opened `Spruce House` lease and verified all 11 detail sections. |
| `L-02` | PARTIAL | Empty submit showed `"Please review your form"` with 6 required fields. Created draft `024a6974-...`, edited notes, and signed (`Executed on 2026-11-24`), transitioning to `Signed` with `Move-in inspection: Due` and signed actions. **Defects**: (1) Invalid date range (`end < start`) returned `422` with opaque technical message `"Complete a valid owning command before starting an attempt."`; (2) Draft leases expose **no Void action** in `Lease actions` or `Edit lease`, leaving `Voided` unreachable from the UI. |
| `L-03` | PASS *(minor)* | Verified lease documents link (`file.upload`), condition comparison review, created Move-in inspection `cbd6aff6-...`, edited draft, recorded acknowledgment, and finalized (`Move-in inspection: Complete`). **Minor defect**: `Acknowledgments` section displayed `"Loading participant name…"` instead of resolving `[UI-TEST] Jordan Avery`. |
| `L-04` | PARTIAL | Created `[UI-TEST] Standard Move-In` template, edited notes, and returned via `← Back to Leasing`. **Defect**: Neither the template card nor `Edit inspection template` exposes an Archive or Delete control. |


### Step 4: Money (`M-01`..`M-08`)

- **Console errors**: `0`
- **Unexpected HTTP errors**: `0` (only expected `400` before setting initial rent schedule recurrence anchor, handled with `Use suggested anchor`).
- **Created / modified `[UI-TEST]` records**:
  - Rent expectations: `34b5ad6f-a36e-4607-8568-e06b7f697bd4` (Nov 2026), `831f60ef-cf28-4396-afac-e5d39e5c4123` (Dec 2026)
  - Rent receipt: `d7bd2d58-32ff-4812-9650-f7a2121dce64` (**Voided**)
  - Paid expense: `4db31c76-27a7-422e-bf29-62d73f424ca0` (**Voided**)
  - Deposit account: `298dc357-6b30-4b50-9ba1-c3e76dfe865b` (Agreed USD 1,800.00; Receipt USD 1,800.00; Variance USD 0.00)
  - Scheduled check: `1a698188-f917-4212-b894-b4df260d4f4e` (**Voided**)
  - Expense category: `479a2d4e-d19e-4734-95d0-c6bd7de56057` (`[UI-TEST] Pest Control Updated`, **Archived**)

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `M-01` | PASS | Synchronized Nov & Dec 2026 rent expectations via `Review and create rent schedule` + `Use suggested anchor`; tested `Settlement`, `Timeliness`, `Due from`/`Due to`, and `Include voided history`; recorded USD 1,800.00 Bank transfer payment on Nov expectation (`Paid`). |
| `M-02` | PASS | Voided `[UI-TEST]` rent receipt with reason; verified hidden when `Include voided history` unchecked (`9`) and visible when checked (`10`); tested date/party/replaces filters. |
| `M-03` | PASS | Verified pagination (25 -> 15) and all expense filters; validated empty submit (`Please review your form`, 5 fields); created USD 125.00 expense on `[UI-TEST] Unit A` / `[UI-TEST] Acme Plumbing`, inspected detail actions (`Edit notes`, `Void`, `Record refund`, `Evidence`), and voided cleanly. |
| `M-04` | PASS | Tested all 4 deposit filters; validated empty submit; created deposit account `298dc357-...`, recorded USD 1,800.00 receipt from `[UI-TEST] Jordan Avery` (variance `USD 0.00`), verified `Prepare deposit settlement` form and discarded cleanly. |
| `M-05` | PASS | Tested all 5 scheduled check filters; created prepaid check `1a698188-...` from Dec expectation; verified `scheduled` & `not_yet_eligible` filters; voided cleanly (`Reminder status: dismissed`). |
| `M-06` | PASS *(minor)* | Tested owner reports filters and `Record owner rent report` validation. **Minor UX defect**: switching from `/money?tab=checks&status=voided` to `Owner reports` tab carried `&status=voided` into `/money?tab=reports&status=voided` even though `voided` is not a valid report status. |
| `M-07` | PASS | Validated empty submit; created `[UI-TEST] Pest Control`, edited to `[UI-TEST] Pest Control Updated`, verified `History`, and archived (8 Active + 1 Archived). |
| `M-08` | PASS | Verified initial date-range prompt; invalid range (`2026-12-01`..`2026-11-01`) showed inline error `"The start date must be on or before the end date."`; `2026-11-01`..`2026-11-30` matched Home totals (`Rent received USD 21,000.00`, `Expenses paid USD 13,908.00`, `Rent less net expenses USD 7,092.00`, `Deposit receipts USD 22,400.00`) and `Archived` showed 0 properties. |


### Step 5: Maintenance & Home (`MT-01`..`MT-04`, `H-01`..`H-05`)

- **Console errors**: `0` on final Home check (`net::ERR_ABORTED` appeared intermittently when navigating mid-fetch).
- **Unexpected HTTP errors**:
  - **Defect (High)**: `POST /api/operator/recovery/:id/attempt` returned **HTTP 500 Internal Server Error** twice when submitting `Report maintenance issue` with `Category detail` populated; afterward `Retry same submission` returned `"Reconcile preparation first."` and `Discard…` also returned **HTTP 500** until `Fix and continue` unlocked it. Leaving `Category detail` blank succeeded (`HTTP 201`).
- **Created / modified `[UI-TEST]` records**:
  - Maintenance issue: `[UI-TEST] Leaky Faucet` (`a02627e9-4705-409d-9102-a8be5e931f6f`, **Resolved**), with Quote (`[UI-TEST] Acme Plumbing`, USD 175.00), Appointment (`eab6983a-...`, **Completed**), Task (`ad775000-...`, **Completed**), Conversation (`3f1a0e5c-...`)
  - Duplicate issue: `70291ce5-b656-4d73-9062-6a680b46592b` (**Cancelled**)
  - Owner concern: `[UI-TEST] Seasonal gutter review` (`a2962f3c-938e-4ce6-8d60-c4047d20bb14`, **Resolved**)

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `MT-01` | PASS | Tested `Status`, `Property`, `Issue category`, `Issue priority`, `More filters` (`Reporter role/subject`, `Evidence`, `Linked paid Expense`, `Active follow-up Task`, date ranges), and `Clear filters` (9 open issues restored). |
| `MT-02` / `MT-03` | PARTIAL | Empty validation worked. **Defect (High)**: populating `Category detail` caused `HTTP 500` on `/api/operator/recovery/:id/attempt` and blocked `Discard…` with `500`. Leaving `Category detail` blank created the issue; quote, appointment (reflected live on Home `Calendar and appointments` 3 -> 4 and `Upcoming` 13 -> 14), follow-up task (`/tasks`), conversation (`/conversations`), `Open -> In progress`, `409` guard blocking resolve while appointment is scheduled, appointment completion, `Resolve`, `Reopen`, and re-`Resolve` all worked cleanly. |
| `MT-04` | PASS | Tested all Owner concern filters, `Record concern` validation (5 required fields), created `[UI-TEST] Seasonal gutter review` on `Alder House — Co-owned` / `Morgan Chen (Demo)`, and resolved it (`Status: Resolved`). |
| `H-01`..`H-05` | PASS *(2 minor/med)* | Switched `Needs action` / `Waiting` / `Upcoming`, tested `"How to expand items"`, Home `Filters` (`Property`, `Upcoming horizon`, `Money from`/`through`, `Clear filters`), `Refresh`, `/home/collections/appointments`, `/home/collections/information_review`, `Recorded money` -> `/money?tab=reporting&metric=...`, and `Vacant rental units` -> `/home/inventory?occupancy=vacant`. **Defect (Medium)**: `Upcoming` still lists `Deposit prepaid check` for `[UI-TEST] Cedar Duplex / [UI-TEST] Unit A` (`Dec 1, 2026`) even though that check was voided (`Reminder status: dismissed`) in Step 4. **Minor a11y defect**: Home `Property` filter `<select>` lacks an accessible `<label>` / `aria-label`. |


### Step 6: Cleanup & Baseline Verification

- **Console errors**: `0`
- **Settings & Recovery**:
  - `/settings/recovery`: `0 forms`
  - `/settings`: `Light` theme, `Every 5 minutes (default)`, default 9-tab navigation
  - `/settings/ai`: `Off`, `Pause all AI assistance` unchecked
- **Cleanup actions**:
  - **Completed**: Archived `[UI-TEST] Acme Plumbing` provider (`a60105d6-e7fc-4d01-b4ca-f294b4ded3e0`). All Step 4 `[UI-TEST]` rent receipt, paid expense, scheduled check, and expense category were already voided/archived; all Step 5 `[UI-TEST]` issues, appointment, task, and owner concern were already resolved/completed/cancelled.
  - **Blocked by same-day lease business rule**: Early termination for `[UI-TEST]` signed lease `024a6974-5e55-4148-b739-02f079ac18e9` progressed through `Request termination` -> `Review` -> `Add proposal` -> `Accept proposal`, but `Complete termination` / `Terminate lease` rejected both `2026-11-24` (`"Actual move-out must follow occupancy start"`) and `2026-11-25` (future move-out disallowed). Because the lease remained `Signed`, archiving `[UI-TEST] Cedar Duplex` (`400: "An occupied space cannot be archived."`) and `[UI-TEST] Jordan Avery` (`409: "A tenant with current or scheduled lease participation cannot be archived."`) were also blocked until at least `2026-11-25`.
- **Final Active Counts vs. Baseline**:
  - `Properties`: `15` (baseline `14` + `[UI-TEST] Cedar Duplex`)
  - `Owners`: `10` (matches baseline `10`)
  - `Tenants`: `13` (baseline `12` + `[UI-TEST] Jordan Avery`)
  - `Leasing`: `10 signed`, `1 draft` (baseline `9 signed` + `[UI-TEST]` signed lease + `[UI-TEST]` draft lease without Void UI)
  - `Maintenance`: `9 open` issues, `0 open` owner concerns (matches baseline)
  - `Providers`: `20 active`, `7 active` provider categories (matches baseline)
  - `Home`: `Recorded money` (Nov 1–30: `USD 21,000.00` rent, `USD 13,908.00` expenses, `USD 7,092.00` net), `Calendar and appointments` (`3`), `Inventory` (`6` vacant, `0` unknown) all match baseline; `Needs action` is `12` (+1 overdue `[UI-TEST]` Nov rent expectation) and `Information review` is `16` (+1 `[UI-TEST] Cedar Duplex`).

---

## Consolidated Defects & Gaps Found

| Priority | Test ID | Area | Finding |
| --- | --- | --- | --- |
| **High** | `MT-02` | Maintenance (`maintenance.issue.create`) | Submitting `Report maintenance issue` with `Category detail` populated triggers **HTTP 500** on `POST /api/operator/recovery/:id/attempt`; afterward `Retry same submission` fails with `"Reconcile preparation first."` and `Discard…` also returns **HTTP 500** until `Fix and continue` unlocks it. |
| **High** | `G-06` | Routing / SPA Fallback | Direct navigation to `/nonexistent-route` or `/properties/not-a-uuid/overview` returns raw FastAPI JSON `404 {"detail":"Not Found"}` instead of the SPA `"Page unavailable"` view with `"Return Home"`. |
| **Medium** | `S-03` | Settings → AI (`/settings/ai`) | Selecting `On this device` and clicking `Save destination` reports `"AI destination settings saved."` with no error/warning, yet `Current state` stays `Off` and reverts on reload (no disabled state or validation message when no adapters are registered). |
| **Medium** | `H-03` / `M-05` | Home `Upcoming` / Prepaid Checks | Home `Upcoming` continues to show `Deposit prepaid check` for `[UI-TEST] Cedar Duplex / [UI-TEST] Unit A` (`Dec 1, 2026`) even after that check was voided (`Reminder status: dismissed`). |
| **Medium** | `L-02` | Leasing (Draft Leases) | Draft leases expose **no Void action** in `Lease actions` or `Edit lease`, leaving the `Voided` status filter unreachable from the UI. Also, submitting `end < start` on `lease.create` surfaces the internal message `"Complete a valid owning command before starting an attempt."` instead of a field-level date error. |
| **Medium** | `L-04` | Leasing (Inspection Templates) | `/leasing?templates=true` and `Edit inspection template` expose **no Archive or Delete** action for inspection templates. |
| **Medium** | `PR-02`, `T-02`, `L-03`, `MT-02` | Draft Autosave Recovery | Background `PUT /api/operator/recovery/...` repeatedly returns **HTTP 422** during form autosave while fields are partially filled. |
| **Low** | `G-03` | Recovery Resume | Resuming a `Create tenant` draft from `/settings/recovery` renders the top back link as `← Back to Properties` instead of `← Back to Tenants`. |
| **Low** | `L-03` | Inspections Detail | On a finalized inspection (`/inspections/:id`), the `Acknowledgments` section remained stuck on `"Loading participant name…"` instead of resolving the tenant name. |
| **Low** | `M-06` | Money Tab Navigation | Switching from `/money?tab=checks&status=voided` to the `Owner reports` tab carried `&status=voided` into `/money?tab=reports&status=voided`, which is not a valid `Report status`. |
| **Low** | `P-01`, `O-01` | Pluralization | Directory counts display `"1 matching properties"` and `"1 matching owners"` when count is `1`. |
| **Low** | `P-02` | Properties Create | `Create property` uses browser HTML5 `required` tooltips instead of the in-page `"Please review your form"` banner used by other create workflows, and only offers single-unit types (`Single-family home`, `Condo`, `Townhome`, `Office`). |
| **Low** | `H-01` | Home Accessibility | Home `Property` filter `<select>` lacks an accessible `<label>` / `aria-label`. |
| **Low** | `G-05` | Mobile Layout (`375px`) | On `/properties` at `375px`, the internal `Property status filters` strip clips/scrolls inside its own box (`Needs occu...`). |


---

## Detailed Reproduction Steps for Failures & Defects

### 1. [High] `MT-02` — HTTP 500 when submitting `Report maintenance issue` with `Category detail` populated

- **Steps to Reproduce**:
  1. Open `http://127.0.0.1:8001/maintenance` and click **Report maintenance issue** (`/maintenance?workflow=maintenance.issue.create`).
  2. Fill in the required fields (e.g., Property/Unit `[UI-TEST] Cedar Duplex` / `[UI-TEST] Unit A`, Title `[UI-TEST] Leaky Faucet`, Category `Plumbing`, Priority `Normal`, Reporter role/details).
  3. Enter any non-empty text in **Category detail** (e.g., `Kitchen sink`).
  4. Click submit.
  5. After the failure banner appears, click **Retry same submission**, then click **Discard…** and confirm.
- **Expected Result**:
  - Submitting a valid issue with `Category detail` creates the issue (`HTTP 201`) and navigates to its detail page.
  - If a submission fails, **Retry same submission** and **Discard…** operate cleanly without server errors.
- **Actual Result**:
  - `POST /api/operator/recovery/:id/attempt` returns **HTTP 500 Internal Server Error**.
  - Clicking **Retry same submission** fails with `"Reconcile preparation first."`.
  - Clicking **Discard…** also returns **HTTP 500** until **Fix and continue** is clicked first.
  - Leaving **Category detail** blank succeeds (`HTTP 201` on `POST /api/maintenance-issues`).

### 2. [High] `G-06` — Direct navigation to invalid routes returns raw JSON `404` instead of SPA `"Page unavailable"`

- **Steps to Reproduce**:
  1. In the browser address bar, navigate directly to `http://127.0.0.1:8001/nonexistent-route`.
  2. Next, navigate directly to `http://127.0.0.1:8001/properties/not-a-uuid/overview`.
- **Expected Result**:
  - The server serves the SPA shell and React Router renders the `"Page unavailable"` view with a working **Return Home** link.
- **Actual Result**:
  - Both URLs return raw FastAPI/Uvicorn JSON `HTTP 404 Not Found`: `{"detail":"Not Found"}` with no navigation or recovery UI.

### 3. [Medium] `S-03` — Saving AI Destination `On this device` reports success but silently reverts to `Off`

- **Steps to Reproduce**:
  1. Open `http://127.0.0.1:8001/settings/ai` (on an installation with `"No AI adapters are registered in this installation"`).
  2. Under **Destination**, select **On this device**.
  3. Click **Save destination**.
  4. Observe `Current state` and reload the page (`Cmd+R` / `F5`).
- **Expected Result**:
  - Either `On this device` persists when saved, or the radio/save action is disabled or returns a clear validation message explaining that an AI adapter must be registered first.
- **Actual Result**:
  - The UI displays `"AI destination settings saved."` with no warning or error, yet `Current state` remains `"Off. Not currently verified."` and the radio reverts to **Off** on reload.

### 4. [Medium] `H-03` / `M-05` — Voided prepaid check still appears in Home `Upcoming`

- **Steps to Reproduce**:
  1. Open an unpaid rent expectation (e.g., Dec 2026 expectation on `/money?tab=rent`) and click **Record prepaid check** to schedule a check (e.g., dated `2026-12-01`).
  2. Open `/money?tab=checks`, open the scheduled check detail view, and click **Void prepaid check** (confirming `Reminder status: dismissed`).
  3. Navigate to `http://127.0.0.1:8001/home` and select the **Upcoming** tab under **Work queue**.
- **Expected Result**:
  - The voided prepaid check (whose reminder is `dismissed`) does not appear in Home **Upcoming**.
- **Actual Result**:
  - Home **Upcoming** still lists `Deposit prepaid check` for `[UI-TEST] Cedar Duplex / [UI-TEST] Unit A` (`Dec 1, 2026`).

### 5. [Medium] `L-02` — Draft leases have no `Void` UI action, and invalid dates show an internal error

- **Steps to Reproduce (Part A — Missing Draft Void)**:
  1. Open `http://127.0.0.1:8001/leasing` and click **Create lease draft**.
  2. Create a valid draft lease and open its detail page (`/leases/:id/details`).
  3. Inspect **Lease actions** and **Edit lease**.
- **Expected Result (Part A)**:
  - A **Void lease** action is available for draft leases so operators can transition `Draft -> Voided` (matching the `Voided` filter on `/leasing`).
- **Actual Result (Part A)**:
  - Only `Edit lease`, `Change rent terms`, `Add participant`, and `Record signed lease` are shown; no Void action exists in the UI.
- **Steps to Reproduce (Part B — Opaque Invalid Date Error)**:
  1. Open `/leasing?workflow=lease.create`.
  2. Fill all required fields, setting **Contract start** to `2026-11-01` and **Contract end boundary (exclusive)** to `2026-10-01` (earlier than start).
  3. Click submit.
- **Expected Result (Part B)**:
  - A clear field-level validation message stating that the end date must be after the start date.
- **Actual Result (Part B)**:
  - `POST /api/operator/recovery/:id/attempt` returns `HTTP 422` and displays the internal message: `"Complete a valid owning command before starting an attempt."`.

### 6. [Medium] `L-04` — Inspection templates have no Archive or Delete UI

- **Steps to Reproduce**:
  1. Open `http://127.0.0.1:8001/leasing` and click **Manage inspection templates** (`/leasing?templates=true`).
  2. Expand **Template actions** and create a template (e.g., `[UI-TEST] Standard Move-In`).
  3. Inspect the created template card and open **Edit inspection template**.
- **Expected Result**:
  - An Archive or Delete action is available to retire obsolete or mistaken inspection templates.
- **Actual Result**:
  - Neither the template card nor **Edit inspection template** exposes any Archive or Delete control.

### 7. [Medium] `PR-02` / `T-02` / `L-03` / `MT-02` — Background draft autosave sends `PUT /api/operator/recovery/...` and receives `HTTP 422`

- **Steps to Reproduce**:
  1. Open DevTools Network tab.
  2. Navigate to any create/edit workflow form (e.g., `/providers?workflow=provider.create`, `/tenants?workflow=tenant.create`, or `Create inspection draft`).
  3. Type into a single field while other required fields are still blank and wait for autosave to fire.
- **Expected Result**:
  - Draft autosave persists partial/incomplete input cleanly (`HTTP 200`/`204`) without triggering validation errors.
- **Actual Result**:
  - Background `PUT /api/operator/recovery/:id` requests return `HTTP 422 Unprocessable Entity` while fields are partially filled.

### 8. [Medium / Business Rule] Step 6 — Same-day executed lease cannot be terminated on its execution date

- **Steps to Reproduce**:
  1. Create and sign a lease today (`2026-11-24`) whose `Occupancy starts` becomes `2026-11-24`.
  2. Progress early termination through **Request termination** -> **Review** -> **Add termination proposal** (`2026-11-24`) -> **Accept termination proposal**.
  3. Attempt **Complete termination** or **Terminate lease** with `Actual move out on = 2026-11-24`, then try `2026-11-25`.
- **Expected Result**:
  - An operator who signs a lease in error or cancels move-in on the same day has a supported way to end/void/terminate the lease on the same day.
- **Actual Result**:
  - `2026-11-24` is rejected (`HTTP 409`: `"Actual move-out must follow occupancy start"`) and `2026-11-25` is rejected because future move-out dates are disallowed, leaving the lease active (and blocking archival of its property and tenant) until the next calendar day.

### 9. [Low] `G-03` — Resumed `Create tenant` draft shows wrong back-link label

- **Steps to Reproduce**:
  1. Open `/tenants`, click **Create tenant**, type `"Draft Person"`, click **Unfinished forms**, and choose **Save and leave**.
  2. On `/settings/recovery`, click **Continue editing: Create tenant**.
- **Expected Result**: Top back link reads `← Back to Tenants`.
- **Actual Result**: Top back link reads `← Back to Properties`.

### 10. [Low] `L-03` — Finalized inspection `Acknowledgments` stuck on `"Loading participant name…"`

- **Steps to Reproduce**:
  1. Create a move-in inspection on a signed lease, record tenant acknowledgment (`Acknowledged`), and click **Finalize inspection**.
  2. Inspect the **Acknowledgments** section on `/inspections/:id`.
- **Expected Result**: Displays the acknowledging tenant's name (e.g., `[UI-TEST] Jordan Avery`).
- **Actual Result**: Displays `"Loading participant name…"` next to `Status: Acknowledged`.

### 11. [Low] `M-06` — Switching Money sub-tabs carries incompatible `status` query parameter

- **Steps to Reproduce**:
  1. Open `/money?tab=checks` and set **Check lifecycle** to `Voided` (URL becomes `/money?tab=checks&status=voided`).
  2. Click the **Owner reports** sub-tab.
- **Expected Result**: Navigating to **Owner reports** clears check-specific filter params (URL `/money?tab=reports`).
- **Actual Result**: URL carries `&status=voided` into `/money?tab=reports&status=voided`, even though `voided` is not a valid `Report status`.

### 12. [Low] `P-01` / `O-01` — Singular count pluralization

- **Steps to Reproduce**:
  1. On `/properties`, search `"Alder"` (1 result).
  2. On `/owners`, search `"Elena"` (1 result).
- **Expected Result**: `"1 matching property"` and `"1 matching owner"`.
- **Actual Result**: `"1 matching properties"` and `"1 matching owners"`.

### 13. [Low] `P-02` — `Create property` validation style inconsistency & single-unit-only types

- **Steps to Reproduce**:
  1. Open `/properties` and click **Create property**.
  2. Click submit with empty fields, and inspect the **Property type** dropdown.
- **Expected Result**: Consistent `"Please review your form"` inline validation summary; option to create a multi-unit property if supported by the portfolio model.
- **Actual Result**: Uses browser-native HTML5 `required` tooltip focus instead of the in-page banner, and only lists `Single-family home`, `Condo`, `Townhome`, and `Office`.

### 14. [Low] `H-01` — Home `Property` filter `<select>` missing accessible label

- **Steps to Reproduce**:
  1. Open `/home` and click **Filters**.
  2. Inspect the Property `<select>` element in the accessibility tree (or query `getByRole('combobox', { name: 'Property' })`).
- **Expected Result**: The `<select>` has an associated `<label>` or `aria-label="Property"`.
- **Actual Result**: The `<select>` has no accessible name, failing role+name lookup and screen-reader labeling.

### 15. [Low] `G-05` — Internal filter strip clipping on `/properties` at `375px` width

- **Steps to Reproduce**:
  1. Resize the viewport to `375x812` and navigate to `/properties`.
  2. Inspect the `Property status filters` strip above the filter form.
- **Expected Result**: Filter chips wrap or display a clean scroll affordance without clipped mid-word text.
- **Actual Result**: The internal strip clips mid-word (`Needs occu...`) inside its container (page-level horizontal overflow remains `0`).


---

## Cross-Check Against `manual/`

Cross-checked [interaction-test-plan.md](interaction-test-plan.md) and these Phase 1 results against all chapters in [manual/](../../manual/README.md) (especially [manual/operation-index.md](../../manual/operation-index.md)).

### 1. Reclassified Findings vs. Confirmed Regressions

- **Intentional design per `manual/` (not regressions)**:
  - **Single-unit residential properties (`P-02`)**: [manual/portfolio-and-people.md](../../manual/portfolio-and-people.md#L14) confirms residential homes/condos/townhomes have one rentable home per property; multi-unit support is scoped to **Office → Suites** only.
  - **No inspection template Archive/Delete (`L-04`)**: [manual/operation-index.md](../../manual/operation-index.md#L138-L139) only registers `Create inspection template` and `Edit inspection template` (still a usability gap when retiring mistaken templates).
  - **Read-only Owner `Details` tab (`O-03`)**: [manual/portfolio-and-people.md](../../manual/portfolio-and-people.md#L38-L48) routes owner contact editing through **Property → Overview → Owners → Change ownership → Manage contact details** or `/parties`.
- **Confirmed regressions against `manual/` promises**:
  - **Draft autosave `422` & broken `Discard…` `500` (`MT-02`, `PR-02`, `T-02`)** contradict [manual/daily-operation.md](../../manual/daily-operation.md#L66-L72).
  - **Missing `Void lease` on draft leases (`L-02`)** contradicts [manual/operation-index.md](../../manual/operation-index.md#L116) and [manual/leases-and-inspections.md](../../manual/leases-and-inspections.md#L27).
  - **Resumed tenant draft showing `← Back to Properties` (`G-03`)** contradicts [manual/daily-operation.md](../../manual/daily-operation.md#L18).
  - **Voided prepaid check lingering in Home `Upcoming` (`H-03` / `M-05`)** contradicts [manual/money.md](../../manual/money.md#L39) and [manual/daily-operation.md](../../manual/daily-operation.md#L36).

### 2. Coverage Gaps Added to Phase 2

All 9 untested workflow areas identified in `manual/` have been added to [interaction-test-plan.md](interaction-test-plan.md#L118-L212) as Phase 2 (`P2-OF-01`..`P2-CF-01`):

1. Office multi-suite properties (`Suites` CRUD) & scheduled occupancy (`P2-OF-01`..`P2-OF-02`)
2. Ownership shares (`100%` validation), primary contact switching & shared `/parties` multi-role reuse (`P2-OW-01`..`P2-OW-03`)
3. Provider sub-records (`Services`, `Service areas`, `Work history`, `Reputation links`, category assignment archive/restore), full Official ID reveal, and assignment ID gate (`P2-PR-01`..`P2-PR-02`)
4. Leasing & inspections depth: draft rent terms, participants & Official ID gate, renewal options, checklist edits, finalized inspection corrections, condition comparison, and `Void lease` (`P2-LS-01`..`P2-LS-04`)
5. Money depth: partial/multi-period rent allocation, timeliness, prepaid check deposit/return/replace, expense refunds, full deposit settlement lifecycle, and owner rent report verification/rejection (`P2-MN-01`..`P2-MN-05`)
6. Maintenance depth: reporter correction, provider assignment & avoided-provider override, quote withdrawal, cost context, linked expenses, and work journal (`P2-MT-01`..`P2-MT-03`)
7. Tasks (timed deadlines, time zones, DST-skipped rejection, waiting context + Home `Waiting` tab, reminders), conversations draft->record->correct, and retained sources (`/conversations?intake=true`) (`P2-TK-01`..`P2-TK-05`)
8. Supporting file upload, download, and `Archive evidence link` (`P2-FL-01`)
9. Two-tab stale revision conflict handling (`P2-CF-01`)

### 3. Usability Improvements & `manual/` Documentation Drift

- **Usability improvements**:
  1. Add escape hatches for mistaken records: `Void lease` on draft leases (`L-02`), `Archive` on inspection templates (`L-04`), and a same-day cancellation/void path for a lease accidentally signed on the current day (Step 6).
  2. Add a direct **Manage contact details** link on `/owners/:id/details` so operators don't have to detour through a Property's `Change ownership` flow (`O-03`).
  3. Disable unavailable AI destination radios on `/settings/ai` (or surface an explicit warning instead of `"AI destination settings saved."` when no adapters are registered, `S-03`).
  4. Replace `"Complete a valid owning command before starting an attempt."` (`L-02`) with a clear field-level date validation error, fix the `Category detail` HTTP 500 + `Discard…` HTTP 500 trap (`MT-02`), serve the SPA `"Page unavailable"` fallback on invalid routes (`G-06`), clear tab-specific query params on Money tab switch (`M-06`), fix resumed tenant draft back-link (`G-03`), resolve participant names in finalized inspection `Acknowledgments` (`L-03`), and add an accessible label to the Home `Property` filter `<select>` (`H-01`).
- **`manual/` documentation drift**:
  - [manual/daily-operation.md](../../manual/daily-operation.md#L42) states *"Current Home has a **Property ID** field rather than a name picker"*, whereas the live Home filter now provides a Property name dropdown (`All properties` + active property names).


---

# Phase 2 Test Results — Deep `manual/` Workflow Coverage

- **Plan**: [interaction-test-plan.md](interaction-test-plan.md#L118-L212)
- **Date**: 2026-11-24
- **Target**: `http://127.0.0.1:8001` (Local operator workspace)
- **Status**: Completed

## Phase 2 Summary

| Step | Scope | Status | Pass | Fail / Defect | Notes |
| --- | --- | --- | --- | --- | --- |
| P2-1 | Office, Ownership & Shared Identities (`P2-OF-01`..`P2-OW-03`) | Done | 4 Pass | 1 Partial, 3 Defects | `Classify suite` doesn't pre-fill today's date; `/owners/:id/details` omits contacts & `/parties` link; `/parties?identity=:id` fires `404` on `/api/tenants/:id` & shows `← Back to Tenants` for owner-only party |
| P2-2 | Provider Depth & Official ID Gate (`P2-PR-01`..`P2-PR-02`) | Done | 2 Pass | 0 Fail, 2 Minor UX | All 5 sub-record lifecycles + Official ID `409` gate passed; minor: no `Restore` button on archived category assignment (must re-assign), `Source name` not hidden/disabled for known reputation sources |
| P2-3 | Leasing & Inspections Depth (`P2-LS-01`..`P2-LS-04`) | Done | 4 Pass | 0 Fail | All guards (`409` Official ID, `400` business signatory, `409` condition comparison & post-move-out), renewals, checklist edit, inspection correction (`Superseded` lineage) passed; confirmed `Void lease` is on Signed leases (not Drafts) |
| P2-4 | Money Depth (`P2-MN-01`..`P2-MN-05`) | Done | 4 Pass | 1 Partial/Fail (Blocker) | `P2-MN-01`..`04` passed; **High/Blocker**: `Save verify owner rent report` stays permanently `disabled` in both Create & Adopt modes; `maskedReference` silently dropped on owner rent report |
| P2-5 | Maintenance Depth (`P2-MT-01`..`P2-MT-03`) | Done | 3 Pass | 0 Fail, 1 Minor | All reporter correction, quote withdrawal, avoided-provider override, reschedule, cost context, linked expense, work journal, and return-to-open workflows passed |
| P2-6 | Tasks, Waiting, Reminders, Conversations & Retained Sources (`P2-TK-01`..`P2-TK-05`) | Done | 4 Pass | 1 Partial, 3 Defects | DST validation, Waiting/Home sync, Conversations & Retained Sources passed; **Defects**: `Clear follow up` fails `422` unless omit checkboxes are checked; repeated workflow hits `409 -> 404` recovery error; `Delete task` fails `409` on acknowledged reminder |
| P2-7 | File Evidence & Two-Tab Revision Conflicts (`P2-FL-01`, `P2-CF-01`) | Done | 2 Pass | 0 Fail, 2 Minor | Upload/download/archive & two-tab `409` conflicts passed; **Minor defect**: post-archive completion screen queries `/api/finance/command-operations/:id` (`404`) and renders `← Back to deposit account` |
| P2-8 | Phase 2 Cleanup & Verification | Done | Full P2 cleanup | 0 Errors | Voided signed P2 lease, archived all P2 entities, cleared `/settings/recovery` (`0 forms`), restored baseline Settings; `0` console errors & `0` failed requests |

## Phase 2 Detailed Step Logs

_(Results are appended as each step completes; every failure/defect includes numbered Steps to Reproduce, Expected Result, and Actual Result.)_


### P2 Step 1: Office, Ownership & Shared Identities (`P2-OF-01`..`P2-OW-03`)

- **Console errors**: `0`
- **Active `[UI-TEST-P2]` entities retained**:
  - Office Property: `[UI-TEST-P2] Harbor Plaza` (`884e800a-be8e-40ff-b76e-91602fb21378`, `Suites` layout, 60% Summit Holdings / 40% You)
  - Active Suites: `[UI-TEST-P2] Suite 200` (`2bdc2082-ace3-46bd-b433-a378bf22a395`, Vacant / Open for leasing now), `[UI-TEST-P2] Suite 201` (`bf9fe293-2f0d-4800-9f5f-c86485b23d8d`), `[UI-TEST-P2] Suite 100`
  - Shared Party: `[UI-TEST-P2] Summit Holdings` (`54c57b05-613d-4463-afe1-8d9a2fbdaa30`, `Active · Owner · Provider · Tenant`)

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `P2-OF-01` | PASS *(minor)* | Created `Office` property with `Individually rented suites`; tab rendered `Suites`; added `Suite 200` & `Suite 201`, edited/classified/archived/restored `Suite 201`. See Defect P2-1 below (`Classify suite` requires manual today's date). |
| `P2-OF-02` | PASS | Scheduled future `Occupied` change (`2026-12-15`) on `Suite 200`, verified `Reschedule occupancy` (`2026-12-20`) and `Cancel scheduled occupancy` cleared it back to `Vacant`. |
| `P2-OW-01` | PASS | Created `[UI-TEST-P2] Summit Holdings` inline in `Change ownership`; `60%+20%` and `60%+50%` blocked with `"Ownership shares must total 100% when every share is recorded."`; saved `60%` / `40%` and verified `Former` history showed `You (100%)`. |
| `P2-OW-02` | PARTIAL | On `/parties?identity=54c57b05-...`, removing primary email while secondary existed blocked (`409`); `Make primary` switched primary; old email edited and archived into `Archived contacts (1)`. See Defects P2-2 & P2-3 below. |
| `P2-OW-03` | PASS | Added Tenant and Provider roles via `/parties?identity=54c57b05-...` -> `More actions`; rename propagated immediately across `/owners` and `/tenants`; restored original name. |

#### P2 Step 1 Defects (Reproduction Steps)

1. **[Low] `P2-OF-01` — `Classify suite` does not pre-fill `Effective date` despite stating today's date**
   - **Steps to Reproduce**: (1) Open `/properties/884e800a-be8e-40ff-b76e-91602fb21378/units`. (2) Click `Review status` for a suite (`/properties?workflow=portfolio.space.classify&target=...`). (3) Expand `Occupancy`, choose `Vacant` without typing into `Effective date (required)`, and click `Save classification`.
   - **Expected Result**: Form pre-fills `2026-11-24` (matching header `"Classification takes effect today: 2026-11-24"`) or does not require manual re-entry.
   - **Actual Result**: Validation rejects submission until `Effective date (required)` is manually typed.
2. **[Medium] `P2-OW-02` — `/owners/:id/details` omits contact details and any link to `/parties?identity=:id`**
   - **Steps to Reproduce**: (1) Open `/owners/54c57b05-613d-4463-afe1-8d9a2fbdaa30/details`.
   - **Expected Result**: Displays owner contact details or a direct `Manage contact details` link to `/parties?identity=:id`.
   - **Actual Result**: Only renders `Relationships`; no contact details, edit buttons, or `/parties` link exist.
3. **[Low/Medium] `P2-OW-02` / `P2-OW-03` — `/parties?identity=:id` fires `GET /api/tenants/:id -> 404` and shows `← Back to Tenants` for an Owner-only party**
   - **Steps to Reproduce**: (1) For a party with only the `Owner` role (no Tenant role), navigate to `/parties?identity=<id>`.
   - **Expected Result**: Page loads without failed network requests and shows `← Back to Owners` (or generic `← Back`).
   - **Actual Result**: `GET /api/tenants/<id>` returns `HTTP 404 Not Found` on load, and the top back link reads `← Back to Tenants`.


### P2 Step 2: Provider Depth & Official ID Gate (`P2-PR-01`, `P2-PR-02`)

- **Console errors**: `0`
- **Active `[UI-TEST-P2]` entities retained**:
  - Provider: `[UI-TEST-P2] Summit Holdings` (`54c57b05-613d-4463-afe1-8d9a2fbdaa30`, Official ID `License · US / OR · Ending in 8842`, Category `HVAC / A/C`, active Services/Areas/Work History/Reputation Links)
  - Maintenance Issue: `[UI-TEST-P2] Suite 200 HVAC damper noisy` (`17d23ff4-94fd-43e2-a326-6aa5a107bf69`) on `[UI-TEST-P2] Harbor Plaza` / `[UI-TEST-P2] Suite 200`, with `[UI-TEST-P2] Summit Holdings` assigned.

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `P2-PR-01` | PASS *(2 minor)* | Full Add/Edit/Archive/Restore verified for `Services`, `Service areas`, `Work history`, and `Reputation links`. `Category assignment` assigned & archived cleanly (requires Reason). See Minor UX Defects P2-4 & P2-5 below. |
| `P2-PR-02` | PASS | Before adding Official ID, `Assign provider` showed inline warning and blocked with `HTTP 409` (`"Record at least one official ID for this provider before assigning maintenance work. Only masked details are needed."`). After saving Official ID (`License · US / OR · 8842`), resuming from `/settings/recovery` succeeded (`Provider assignments (1)`). |

#### P2 Step 2 Minor Defects (Reproduction Steps)

4. **[Low] `P2-PR-01` — No `Restore` button for archived Provider Category Assignment**
   - **Steps to Reproduce**: (1) Open `/providers/54c57b05-613d-4463-afe1-8d9a2fbdaa30/details`. (2) Assign a category (`HVAC / A/C`), then archive the assignment with a reason. (3) Toggle `Show archived records` (`?history=true`).
   - **Expected Result**: Archived category assignment offers a `Restore` action matching `manual/operation-index.md` (`Restore category assignment`) and the other provider sub-records.
   - **Actual Result**: Shows `Assignment archived` with no `Restore` button (must re-assign via `Add category`).
5. **[Low] `P2-PR-01` — Reputation link `Source name` input stays active for known `Source kind` values**
   - **Steps to Reproduce**: (1) Open `Add reputation link` on a provider. (2) Choose `Source kind = Google`, type a value into `Source name`, and submit.
   - **Expected Result**: `Source name` is hidden or disabled when a known source kind (`Google`, etc.) is selected.
   - **Actual Result**: Field remains editable and fails on submit with `HTTP 422`: `"Known reputation sources cannot have a source name."`.


### P2 Step 3: Leasing & Inspections Depth (`P2-LS-01`..`P2-LS-04`)

- **Console errors**: `0`
- **Active `[UI-TEST-P2]` entities retained**:
  - Tenant: `[UI-TEST-P2] Casey Brooks` (`471b0d5c-0dd6-4f17-99f6-09b84c6d0059`, Driver's license `US / OR` ending `5519`)
  - Signed Commercial Lease: `b9648cb6-05fd-4395-afab-2c6e40bd0656` on `[UI-TEST-P2] Harbor Plaza` / `[UI-TEST-P2] Suite 200` (`Dec 1, 2026 – Nov 30, 2027`, USD `2,750.00/mo`, due day 5, security deposit `USD 2,500.00`)
  - Exercised Renewal Option: `69ca1b5e-449f-4388-a31c-51e439e7e8a7`
  - Corrected Move-in Inspection (`Finalized`): `c83ce8d0-c75d-492d-b351-d5e42b37c9e9` (superseding `1667ec13-3edd-41fc-83dd-24b4b9428576`)

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `P2-LS-01` | PASS | Tested `Change rent terms` (`2500 -> 2750`, due day 5), `Add`/`Edit`/`Remove participant`, `409` Official ID gate on tenant, `400` Commercial business signatory gate, and per-role Official ID requirement on `[UI-TEST-P2] Summit Holdings` before signing cleanly. |
| `P2-LS-02` | PASS | Ran `Add renewal option`, `Edit renewal option`, and `Decide renewal option` (`Exercised`); confirmed `Void lease` (`lease.void`) IS exposed on Signed leases (confirming Phase 1's finding that only Draft leases lack Void). |
| `P2-LS-03` | PASS | Created template-backed Move-in inspection (`[UI-TEST] Standard Move-In`), ran `Edit inspection checklist` (updated `Kitchen`, added `Reception`), `Record inspection acknowledgments`, and `Finalize inspection`. |
| `P2-LS-04` | PASS | Verified `Review condition comparison` blocks (`409`) without finalized post-move-out; ran `Correct finalized inspection` and finalized replacement (original auto-transitioned to `Superseded`); verified `Post move out` finalization blocks (`409`) without confirmed move-out. |


### P2 Step 4: Money Depth (`P2-MN-01`..`P2-MN-05`)

- **Console errors**: `0`
- **Results (`P2-MN-01`..`P2-MN-04` completed; `P2-MN-05` running)**:

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `P2-MN-01` | PASS | Synchronized lease `b9648cb6-...` (prorated Dec 1–4 USD 366.67, Dec 5 USD 2,750, Jan 5 USD 2,750); recorded partial payment (`4405ebd6`) & multi-period payment (`9c93aa71`); voided both receipts; verified `Review payment timing` (`409` on non-ended expectation); voided Jan 5 expectation (`1ec07570`). |
| `P2-MN-02` | PASS | Verified future-start lease guard (`409`), scheduled prepaid check (`9a68c7ba`), acknowledged reminder (`afc1fa0b`), scheduled eligible check (`a32a6e83`), deposited (`1625b551`), returned NSF (`a32a6e83` Returned, `1625b551` Voided, expectation Unpaid), replaced (`4117849c` Scheduled, `a32a6e83` Replaced), and voided `4117849c`. |
| `P2-MN-03` | PASS | Created Paid expense `54a85c9c-...` (USD 300 on Suite 200 / Summit Holdings), ran `Edit expense context`, recorded USD 50 refund (verified Reporting `Net recorded expenses` dropped USD 300 -> USD 250 / portfolio USD 14,208 -> USD 14,158), then ran `Void expense refund` and `Void expense`. |
| `P2-MN-04` | PASS | Created deposit account `0e900eeb-...` (USD 2,500), recorded USD 2,500 receipt, verified `409` timing override guard, prepared settlement `92b71db4-...`, added/edited deduction (`USD 200`), linked expectation deduction source (`ae745062-...`), added/deleted interest credit (`USD 4.11`), approved (`USD 2,300` refund due), recorded USD 2,300 refund, and completed settlement (`Status: Completed`, `Unresolved balance: No`). |
| `P2-MN-05` | PARTIAL / FAIL | Create (`0a75e91f-...`), Edit while Pending, and Reject (`67821393-...`) all passed. **Blocker**: `Verify owner rent report` could not be submitted because `Save verify owner rent report` remained permanently `disabled` in both Create and Adopt modes (see Defect P2-6 below). Also `maskedReference` was not retained (Defect P2-7). |

#### P2 Step 4 Defects (Reproduction Steps)

6. **[High / Blocker] `P2-MN-05` — `Save verify owner rent report` submit button stays permanently `disabled` in both Create and Adopt modes**
   - **Steps to Reproduce**:
     1. Open a Pending owner rent report (`/money?record=report&id=0a75e91f-26ef-4b94-bde4-82a44d12cda1`, USD 366.67 on lease `b9648cb6-...`).
     2. Click **Verify owner rent report** (`/money?workflow=owner_rent_report.verify&target=0a75e91f-26ef-4b94-bde4-82a44d12cda1`).
     3. Path A: Select **Create a receipt with explicit allocations**, set `Allocations 1 -> Amount minor` = `36667`, select `Dec 1, 2026 · USD 366.67 outstanding` (Remaining balance shows `USD 0.00`), check **I confirm this lifecycle change**, and enter **Review note (required)**.
     4. Path B: Discard draft, reopen Verify, select **Adopt an existing compatible receipt**, choose a matching receipt (`USD 366.67 · Bank transfer`), check **I confirm this lifecycle change**, and enter **Review note (required)**.
   - **Expected Result**: `Save verify owner rent report` becomes enabled when all required fields are valid and submits the verification request.
   - **Actual Result**: `<button type="submit" disabled>Save verify owner rent report</button>` stays `disabled` in both Path A and Path B with no validation error shown (and clicking one mode radio disables both mode radios).
7. **[Medium] `P2-MN-05` — `Masked reference` is silently dropped on Create/Edit owner rent report**
   - **Steps to Reproduce**:
     1. Open `/money?workflow=owner_rent_report.create` (or `.patch`).
     2. Fill all required fields plus `Masked reference` = `[UI-TEST-P2] Ref-001` and submit.
   - **Expected Result**: `maskedReference` is persisted and displayed on the report and edit form.
   - **Actual Result**: `POST /api/owner-rent-reports` (`201`) returns `maskedReference: null` and the Edit form shows `Masked reference` empty.

### P2 Step 5: Maintenance Depth (`P2-MT-01`..`P2-MT-03`)

- **Console errors**: `0`
- **Issue exercised**: `[UI-TEST-P2] Suite 200 HVAC damper noisy` (`17d23ff4-94fd-43e2-a326-6aa5a107bf69`, returned to `Open` at end of step).

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `P2-MT-01` | PASS | Leaving `Reporter correction reason` blank kept `Save issue changes` disabled; changing to future-lease tenant blocked (`409`); updating description + reporter to active owner `[UI-TEST-P2] Summit Holdings` with reason saved cleanly (`200`) while keeping report time, property, and status unchanged. |
| `P2-MT-02` | PASS *(minor)* | Recorded Quotes A & B, withdrew Quote B (`Withdrawn`), ended initial assignment, assigned Summit Holdings from Quote A, tested `Avoid` provider (`Rose City HVAC (Demo)`) override guard + confirmation/reason, restored provider to `neutral`, and reassigned Summit Holdings. *(Minor: starting a second workflow immediately after completing a previous one occasionally surfaced a stale recovery revision `409`, resolved by discarding and reopening.)* |
| `P2-MT-03` | PASS | Scheduled, rescheduled (`2026-11-26 14:00–16:00`), and completed appointment; recorded & voided cost context (`USD 450`); recorded & linked paid expense (`b5326e43-...`), archived association while confirming Finance expense stayed `Active`, then voided Finance expense; recorded work journal entry; tested `Start work` -> `Return to open`. |


### P2 Step 6: Tasks, Waiting, Reminders, Conversations & Retained Sources (`P2-TK-01`..`P2-TK-05`)

- **Console errors**: `0`
- **Results**:

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `P2-TK-01` | PASS | Quick add all-day task (`4d3857d1-...`), DST-skipped time (`2026-03-08T02:30 America/Los_Angeles`) rejected inline while preserving input, timed task (`af8daed3-...`), filters, `Start`, `Edit`, `Cancel`, `Reopen`, and `Delete task` all passed. |
| `P2-TK-02` | PASS *(2 defects)* | `Set waiting context` surfaced live on Home `Waiting` (`1 item`); `Reschedule follow-up` and `Clear waiting context` (clearing Home `Waiting` to `0`) worked. See Defects P2-8 (`Clear follow up` 422) & P2-9 (stale recovery `409 -> 404`) below. |
| `P2-TK-03` | PARTIAL | Added 2 reminders, ran `Acknowledge reminder` and `Dismiss reminder`. **Defect P2-10**: `Delete task` stayed enabled on an open task with an `acknowledged` reminder, then failed with `409`. Completed task cleanly instead. |
| `P2-TK-04` | PASS | Created Draft conversation (`bbba52bc-...`), ran `Edit conversation draft`, `Record conversation`, and `Correct recorded conversation` (`cae96b3c-...`, original marked `Superseded`, original timestamp preserved). |
| `P2-TK-05` | PASS | On `/conversations?intake=true`, verified `Import source evidence` opens, ran `Retain source` (`aceac6f4-...`), `Correct source` (`Version 2`), `Dismiss source`, `Reopen source`, `Supersede source` (`cf2bfdc8-...`), and all status/kind/channel filters. |

#### P2 Step 6 Defects (Reproduction Steps)

8. **[Medium] `P2-TK-02` — Checking `Clear follow up` on `Reschedule follow-up` fails `HTTP 422` unless `"Leave ... unchanged / omit"` checkboxes are also manually checked**
   - **Steps to Reproduce**:
     1. Open a waiting task with a scheduled follow-up (`/tasks?record=task&id=af8daed3-...`).
     2. Click **Reschedule follow-up** (`/tasks?workflow=task.waiting.reschedule&target=af8daed3-...`).
     3. Check **Clear follow up** and click **Save reschedule follow-up** without manually checking `Leave follow up at unchanged / omit` and `Leave follow up timezone unchanged / omit`.
   - **Expected Result**: Checking `Clear follow up` automatically omits `followUpAtUtc` / `followUpTimezone` and saves cleanly (`Not scheduled` / `Unscheduled`).
   - **Actual Result**: Recovery PUT still sends `followUpAtUtc` and `followUpTimezone` alongside `clearFollowUp: true`, causing `POST /api/operator/recovery/<id>/attempt` to fail with `HTTP 422`: `"Complete a valid owning command before starting an attempt."`. Manually checking both omit boxes works around it.
9. **[Medium] `P2-TK-02` / `P2-TK-03` — Repeating a workflow on the same task hits stale recovery `409`, and `Keep my edits with this reviewed revision` hits `404`**
   - **Steps to Reproduce**:
     1. Complete `Reschedule follow-up` (or `Add task reminder`) on a task, then immediately reopen the same workflow on that task and edit fields.
     2. When the revision-conflict banner appears (`HTTP 409` on `PUT /api/operator/recovery/<id>`), click **Review current source** → **Keep my edits with this reviewed revision**.
   - **Expected Result**: Reopening a workflow after a clean completion starts a fresh draft at the latest revision (no stale `409`), and `Keep my edits with this reviewed revision` recovers cleanly without `404`.
   - **Actual Result**: `PUT /api/operator/recovery/<id>` returns `409`, and clicking `Keep my edits with this reviewed revision` triggers `GET /api/operator/recovery/<id> -> 404 ("Recovery record was not found.")` + `422` on `/attempt` until `Discard` is clicked.
10. **[Low/Medium] `P2-TK-03` — `Delete task` remains offered for open tasks with an `acknowledged` reminder, then fails `HTTP 409`**
    - **Steps to Reproduce**:
      1. On an open task with an `acknowledged` reminder, expand **Delete task**, confirm, and submit.
    - **Expected Result**: Either `Delete task` succeeds for acknowledged reminders, or the UI disables/explains the restriction before submission.
    - **Actual Result**: `DELETE /api/tasks/<id>` returns `HTTP 409`: `"Only open Tasks without non-dismissed reminders can be deleted."`.


### P2 Step 7: File Evidence & Two-Tab Revision Conflicts (`P2-FL-01`, `P2-CF-01`)

- **Console errors**: `0`
- **Results**:

| ID | Result | Evidence & Notes |
| --- | --- | --- |
| `P2-FL-01` | PASS *(minor)* | Uploaded `p2-evidence.txt` (`183 B`, `e63c624b-...`) on issue `17d23ff4-...`, downloaded cleanly (`200`), and archived evidence link (`2d272950-...`) with metadata/reason retained in history. See Defect P2-11 below. |
| `P2-CF-01` | PASS *(minor)* | **Test A (Settings)**: Stale Tab 2 save hit `409`, preserved choices, and surfaced `Load current preferences` without clobbering Tab 1. **Test B (Edit issue)**: Stale Tab 2 save hit `409`, preserved Tab 2's input, and did not clobber Tab 1's `[Tab 1 edit]`. *(Minor: `Review current source` on conflicted `Edit maintenance issue` did not render a current-source summary panel.)* |

#### P2 Step 7 Defects (Reproduction Steps)

11. **[Low/Medium] `P2-FL-01` — Archiving a Maintenance issue evidence link returns `404` on `/api/finance/command-operations/:id` and renders `← Back to deposit account`**
    - **Steps to Reproduce**:
      1. Attach a supporting file to a maintenance issue (`/maintenance?record=issue&id=17d23ff4-...`).
      2. Click **Archive evidence association**, check confirmation, enter an archive reason, and click **Save archive evidence link**.
    - **Expected Result**: Completion screen loads operation details cleanly and offers `← Back to maintenance issue`.
    - **Actual Result**: The archive succeeds on the backend, but the completion screen calls `GET /api/finance/command-operations/<op-id>` (`HTTP 404 Not Found`), displays `"Your change is complete, but its details could not be loaded"`, and renders `"← Back to deposit account"`.


### P2 Step 8: Phase 2 Cleanup & Verification

- **Cleanup completed (100% of `[UI-TEST-P2]` entities)**:
  - Maintenance issue `17d23ff4-94fd-43e2-a326-6aa5a107bf69`: **Resolved**
  - Owner rent report `0a75e91f-26ef-4b94-bde4-82a44d12cda1`: **Rejected**
  - Retained source `cf2bfdc8-22e6-4845-b669-b0f2b1c6d0d9`: **Dismissed**
  - Signed lease `b9648cb6-05fd-4395-afab-2c6e40bd0656`: **Voided** via `Void lease` (`Status: void`, `Occupancy state: ended`) — also confirming `P2-LS-04` execution end-to-end
  - Archived: `[UI-TEST-P2] Harbor Plaza`, `[UI-TEST-P2] Casey Brooks`, and `[UI-TEST-P2] Summit Holdings` (both Tenant and Provider roles)
  - `/settings/recovery`: **`0 forms`**; `/settings`: baseline (`Light`, `5 min`, default 9-tab navigation)
- **Final Active Counts (`0` active `[UI-TEST-P2]` records across all tabs)**:
  - `Properties`: `15` active (`0` `[UI-TEST-P2]`), `Owners`: `10` active, `Tenants`: `13` active (`0` `[UI-TEST-P2]`), `Leasing`: `10` signed (`0` `[UI-TEST-P2]`), `Maintenance`: `9` open (`0` `[UI-TEST-P2]`), `Providers`: `20` active (`0` `[UI-TEST-P2]`), `Tasks`: `0` open `[UI-TEST-P2]`, `Home` `Recorded money` (Nov 1–30): `USD 21,000.00` rent, `USD 13,908.00` expenses, `USD 7,092.00` net (exact baseline match).
- **Console / Network Errors on Final Sweep**: `0` console errors, `0` failed requests (`status >= 400`).

---

## Phase 2 Consolidated Defects Summary

| # | Priority | Test ID | Area | Summary |
| --- | --- | --- | --- | --- |
| P2-6 | **High / Blocker** | `P2-MN-05` | Money (`owner_rent_report.verify`) | `Save verify owner rent report` stays permanently `disabled` in both Create and Adopt modes (and clicking one mode radio disables both). |
| P2-2 | **Medium** | `P2-OW-02` | Owners (`/owners/:id/details`) | Owner `Details` tab omits contact details and any link to `/parties?identity=:id`. |
| P2-7 | **Medium** | `P2-MN-05` | Money (`owner_rent_report.create/patch`) | `Masked reference` is silently dropped (`POST` returns `maskedReference: null`, Edit form shows empty). |
| P2-8 | **Medium** | `P2-TK-02` | Tasks (`task.waiting.reschedule`) | Checking `Clear follow up` fails `HTTP 422` unless both `Leave ... unchanged / omit` checkboxes are also manually checked. |
| P2-9 | **Medium** | `P2-TK-02`/`03` | Tasks Recovery | Repeating a workflow on the same task hits stale recovery `409`, and `Keep my edits with this reviewed revision` hits `GET -> 404` + `422` until `Discard`. |
| P2-3 | **Low/Medium** | `P2-OW-02`/`03` | Shared Identity (`/parties?identity=:id`) | Fires `GET /api/tenants/:id -> 404` on load and displays `← Back to Tenants` when the party has only the `Owner` role. |
| P2-10 | **Low/Medium** | `P2-TK-03` | Tasks (`task.delete`) | `Delete task` stays offered on open tasks with an `acknowledged` reminder, then fails `HTTP 409`. |
| P2-11 | **Low/Medium** | `P2-FL-01` | Evidence Archive (`file.link.archive`) | Post-archive completion screen from Maintenance calls `GET /api/finance/command-operations/:id` (`404`) and renders `← Back to deposit account`. |
| P2-1 | **Low** | `P2-OF-01` | Properties (`portfolio.space.classify`) | `Classify suite` states `"Classification takes effect today: 2026-11-24"` yet leaves `Effective date (required)` blank. |
| P2-4 | **Low** | `P2-PR-01` | Providers | Archived category assignment has no `Restore` button (must re-assign via `Add category`). |
| P2-5 | **Low** | `P2-PR-01` | Providers (`provider.reputation_link.add`) | `Source name` stays editable for known `Source kind` (`Google`), then fails `422` on submit. |
