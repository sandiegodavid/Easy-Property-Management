# Live UI Interaction Test Results — `https://demo-a.epmdemo.xyz/`

- **Plan:** [interaction-test-plan.md](interaction-test-plan.md)
- **Remediation Plan:** [LIVE_UI_INTERACTION_REMEDIATION_PLAN.md](../active/LIVE_UI_INTERACTION_REMEDIATION_PLAN.md)
- **Date:** 2026-11-25
- **Target:** `https://demo-a.epmdemo.xyz/` (Hosted Pilot 0 Operator workspace, release `pilot0-20261124-review` / `hosted_mvp @ 5ed202f5`)
- **Status:** Completed (Phase 1 + Phase 2 + Cleanup)

---

## 1. Executive Summary

| Phase | Scope | Pass | Partial | Fail | Blocked | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| **Phase 1** | Global Shell, Settings/Hosted Settings, Providers, Tenants, Properties, Owners, Leasing, Money, Maintenance, Home (`G-01`..`H-05`) | 32 | 8 | 2 | 1 | Fails: `G-06` (invalid routes return `503` JSON), `H-04` (Home `"View all..."` links no-op). Blocked: `S-03` (AI disabled in Free pilot). |
| **Phase 2** | Office multi-suite, Ownership shares, Shared `/parties`, Official ID gates, Deep Leasing/Inspections/Money/Maintenance/Tasks/Conversations, Two-tab conflicts (`P2-OF-01`..`P2-CF-01` + extra depth) | 8 | 7 | 1 | 0 | Fail: `P2-PR-02` (`Full ID number (optional)` triggers `PUT /api/operator/recovery/... -> 422` and blocks Provider Official ID save). |

---

## 2. Phase 1 Test Matrix (`G-01`..`H-05`)

| ID | Area / Scenario | Status | Notes |
| --- | --- | --- | --- |
| **G-01** | Landing `/` → `/home` redirect, query params, 9 tabs, hosted banner | **Pass** | Redirected to `/home?horizonDays=7&fromOn=2026-11-01&throughOn=2026-11-30`; 8 primary tabs + Settings + hosted status banner present. Minor skeleton overlap & sidebar bottom text clipping (Defects #15, #16). |
| **G-02** | `Ctrl+K`/`Cmd+K` → `/search`, 1-char prompt, `Alder`, archived toggle, open result, back | **Partial** | Clicking `Search (Ctrl/⌘ K)` link & all search behaviors passed; pressing `Control+k` or `Meta+k` on `/home` did not navigate to `/search` (Defect #9). |
| **G-03** | Unfinished forms (`/settings/recovery`): auto-save, resume, discard | **Partial** | Auto-save and listing worked; same-tab resume hit `POST /api/hosted/drafts/.../lease -> HTTP 409` requiring `Take over editing`, and `Submission needs checking` rows could not be checked/discarded directly from `/settings/recovery` due to `HTTP 409` (Defect #7). |
| **G-04** | Theme Light → Dark → reload → Light | **Pass** | Dark theme persisted across reload and restored cleanly to Light. |
| **G-05** | Mobile `<768px` drawer & no horizontal overflow; desktop `More` menu | **Pass** | `390px` mobile viewport had zero horizontal overflow and working Navigation drawer; desktop hidden nav moved to `More`. |
| **G-06** | Invalid routes `/nonexistent-route` & `/properties/not-a-uuid/overview` → `Page unavailable` | **Fail** | Returned raw `HTTP 503` JSON `{"message":"Workspace access is unavailable."}` instead of `Page unavailable` + `Return Home` (Defect #3). |
| **S-01** | Appearance & Home auto-refresh persistence + restore defaults | **Pass** | Persisted across reload and restored to `Every 5 minutes (default)`. |
| **S-02** | Navigation order & visibility + `Restore defaults` | **Pass** | Reorder, hide, `More` overflow, and `Restore defaults` passed. |
| **S-03** | `/settings/ai` Destination, pause, sub-sections, `Drafts for review` | **Blocked** | Hosted Free pilot disables AI: `"AI connections are not enabled for the Free pilot. Contact the administrator."` |
| **Hosted Settings** | `/settings` storage refresh, recovery status refresh, recovery points radio list | **Pass** | Non-destructive hosted controls (`Refresh storage usage`, `Refresh recovery status`, verified recovery points) worked cleanly. |
| **PR-01** | Providers filters / `More filters` / pagination | **Pass** | `Preferred` → 5, `More filters` options, `Clear filters` → 20 (single page of 20 seeded items). |
| **PR-02** | `[UI-TEST] Acme Plumbing` create/edit/preference/category/reference/archive | **Pass** | End-to-end CRUD + archive verified. Console/UX defects noted (Defects #17, #18). |
| **PR-03** | Provider Categories CRUD (`/settings/provider-categories`) `[UI-TEST] Calibration` | **Pass** | Create → edit → archive verified (routes under `/providers?workflow=provider.category.*`). |
| **T-01** | Tenants search vs browse & `Include archived tenants` | **Pass** | Browse listed 12 tenants; Search `"Alex"` → 1 match; `Include archived tenants` toggled cleanly. |
| **T-02** | Create `[UI-TEST] Jordan Avery` (validation + happy path) | **Pass** | Empty submit alert `"Choose or enter display name."`; created cleanly. |
| **T-03** | Tenant edit / contact / official ID | **Partial** | Name edit routed to `/parties?workflow=party.patch` & returned to `/parties` instead of `/tenants`; `Official identification` card lacks an `Add official ID` button (buried in `Edit tenant preferences`, Defect #10). |
| **T-04** | Tenant archive & restore `[UI-TEST] Jordan Avery Edited` | **Pass** | Archived and restored to Active (and re-archived in final cleanup). |
| **P-01** | Properties filters & quick links | **Pass** | `Occupied` → 9, `About leasing status` popover, `Managed for owner` → 7. Quick-filter bar clips at `1280×800` (Defect #16). |
| **P-02** | Create `[UI-TEST] Cedar Duplex` (validation + happy path) | **Pass** | Empty validation + full creation with unit/ownership/initial status passed (recovered from transient `HTTP 503` during submit, Defect #8). |
| **P-03** | All 8 property detail sub-tabs + `View in Money` | **Partial** | All 8 sub-tabs and `View in Money` opened; `Tasks` section failed (`"This source is unavailable."`, Defect #6), `Documents` is an unimplemented placeholder, and `Property setup` clips offscreen at `1280×800` (Defect #16). |
| **P-04** | Units CRUD (`[UI-TEST] Unit A`, leasing status) | **Pass** | Edited `Whole home` → `[UI-TEST] Unit A` and verified immediate update. |
| **P-05** | Property setup edit (`[UI-TEST] Cedar Duplex Edited`), ownership split, archive | **Pass** | Edited name, split ownership 80% You / 20% Casey Quinn (Demo), and archived cleanly. |
| **P-06** | Coverage (`/coverage/property/:id/maintenance`) | **Pass** | Loaded maintenance coverage review page cleanly. |
| **O-01** | Owners filters & `Owner concerns` link | **Pass** | Filters & link to `/maintenance?tab=concerns` passed. Address card stray comma noted (Defect #18). |
| **O-02** | All 7 owner detail sub-tabs + `View in Money` | **Partial** | All 7 sub-tabs & `View in Money` worked; `Tasks` section on Owner Overview also failed (`"This source is unavailable."`, Defect #6). |
| **O-03** | Owner edit / contact lifecycle (Casey Quinn) | **Pass** | Added, edited, and removed temporary phone contact cleanly. |
| **L-01** | Leasing status filters / pagination / detail | **Pass** | 9 signed leases, filters, and `Riverbend Condo 101` detail verified. |
| **L-02** | Create/edit/lifecycle `[UI-TEST]` lease (validation, dates, Signed, Void) | **Partial** | Invalid date range validation, edit notes, execute to Signed, and Void lease passed; `Create lease draft` has no default move-in date or timezone label and exposes raw UUID / minor-unit inputs without pickers (Defect #18). |
| **L-03** | Lease documents & inspection creation | **Pass** | Uploaded `ui-test-lease-doc.txt`, verified on lease, created & edited Move-in inspection draft (`PUT /api/operator/recovery/... -> 422` on empty Observations 1, Defect #14). |
| **L-04** | Inspection Templates (`/leasing?templates=true`) CRUD | **Pass** | Created, edited, and archived `[UI-TEST] Standard Walkthrough Edited` (same `422` auto-save on empty Observations 1). |
| **M-01** | Money: `rent` filters, `Include voided history`, detail | **Pass** | Filters, toggle, and Rent due detail verified. |
| **M-02** | Money: `receipts` filters & detail | **Pass** | Filters and receipt detail verified. |
| **M-03** | Money: `expenses` filters, pagination, create/void `[UI-TEST] Plumbing parts` | **Pass** | Filters, `Next money page`, create (`USD 125.50`), and void verified. |
| **M-04** | Money: `deposits` filters, detail, create deposit account | **Partial** | Filters, detail, and empty validation passed; `Create deposit account` exposes only raw UUID fields (`Lease term id`, `Lease id`) with no pickers even from a lease-filtered view (Defect #18). |
| **M-05** | Money: `checks` filters & empty state | **Pass** | Filter URL sync and empty state verified. |
| **M-06** | Money: `reports` filters, create & reject `[UI-TEST]` owner rent report | **Pass** | Created `USD 1,500.00` report linked to `[UI-TEST]` lease & Casey Quinn and rejected it cleanly (raw UUID/minor-unit UX, Defect #18). |
| **M-07** | Money: `categories` CRUD `[UI-TEST] Testing Fees` → archive | **Pass** | Create, edit, and archive passed (archived item stayed listed in Shared expense categories). |
| **M-08** | Money: `reporting` (`2026-11-01`..`2026-11-30`), Home parity, invalid range | **Pass** | Matched Home (`Rent received USD 21,000.00`, `Expenses paid USD 13,908.00`); invalid range alert `"The start date must be on or before the end date."` |
| **MT-01** | Maintenance filters & `More filters` | **Pass** | Filters and `More filters` worked cleanly. |
| **MT-02** | Report/edit/transition `[UI-TEST] Leaky Faucet` → `In progress` → `Cancel` | **Pass** | Validation, create, edit (High), `Start work` → `In progress`, and `Cancel issue` passed. |
| **MT-03** | Maintenance sub-workflows (quote, appointment, `/tasks`, `/conversations`) | **Partial** | Quote, appointment, and `/tasks` follow-up creation & completion passed (`Starts at utc` / `Ends at utc` mislabel); `Create conversation` failed with `"Participants has too many or too few entries."` while `Participants` is not labeled `(required)` (Defect #5). |
| **MT-04** | Owner concerns (`/maintenance?tab=concerns`) CRUD & filters | **Pass** | Create, edit, dismiss, and `Status=Dismissed` filter passed. |
| **H-01** | Home filters & URL sync | **Pass** | Horizon/date/property filters updated URL & `Clear filters` reset. ~200px blank vertical gap in Filters (Defect #15). |
| **H-02** | Home manual Refresh | **Pass** | Refresh button disabled during fetch and re-enabled cleanly on completion. |
| **H-03** | Home work queue sub-tabs (`Needs action`/`Waiting`/`Upcoming`) & expand | **Pass** | Sub-tabs and item expansion passed. Calendar card clips vertically (Defect #4). |
| **H-04** | Home full collection drill-downs (`/home/collections/*`) | **Fail** | Clicking `"View all Calendar and appointments (4 items)"` and `"View all Information review (19 items)"` on `/home` failed to navigate (URL stayed `/home`), even though direct URLs return HTTP 200 (Defect #4). |
| **H-05** | Home Recorded money & Vacant rental units links | **Pass** | Navigated to `/money?tab=reporting&metric=rentReceived` and `/home/inventory?occupancy=vacant`. |

---

## 3. Phase 2 Test Matrix (`P2-OF-01`..`P2-CF-01`)

| ID | Area / Scenario | Status | Notes |
| --- | --- | --- | --- |
| **P2-OF-01** | Office property `[UI-TEST-P2] Harbor Plaza` (multi-suite), `Add`/`Edit`/`Classify`/`Archive`/`Restore` suites (`Suite 200`, `Suite 201`) | **Partial** | Create, Add, Edit, Classify, Archive, and Restore passed. `Correct occupancy` landed on post-save dead-end screen (Defect #12). |
| **P2-OF-02** | `Suite 200` future occupancy (`2026-12-10`), `Scheduled occupancy`, `Reschedule` (`2026-12-15`), `Replace`, `Cancel` | **Pass** | All 4 lifecycle transitions succeeded. Minor UX: `Replace` starts with blank `Effective date`; confirmation renders raw lowercase enums (`vacant`, `occupied`, `unknown`). |
| **P2-OW-01** | `Change ownership` + inline `Create a new owner` (`[UI-TEST-P2] Summit Holdings`), `60%+60%` validation, `50%+50%` verification | **Partial** | Validation and `50%+50%` save passed; Properties list & Owner `Relationships` updated immediately. Property Overview `Owners` stayed stale (`You 100%`) after `Back to property` until reload (Defect #12). |
| **P2-OW-02** | Contact details (`primary@summit.test`, `secondary@summit.test`), remove-Primary guard (`409`), `Make primary`, archive & restore | **Pass** | All checks passed (minor checkbox alignment & raw lowercase enums). |
| **P2-OW-03** | `/parties` shared identity across Owners, Providers (`Add provider role`), and Tenants (`Use identity as tenant`) | **Partial** | `Add provider role` worked cleanly and shared `Active Owner Provider Tenant` badges verified. `Use identity as tenant` is missing from `More actions` on `/parties?identity=...` (Defect #10). |
| **P2-PR-01** | Provider `Add`/`Edit`/`Archive`/`Restore` for `Services`, `Service areas`, `Work history`, `Reputation links`, and `Category assignment` | **Partial** | All 5 sub-entities passed lifecycle CRUD. Newly assigned category did not appear on Provider detail after `Back to provider` until reload (Defect #12). |
| **P2-PR-02** | Official ID gate (`[UI-TEST-P2] NoID Electric`), `Full ID number`, `Show/Hide ID number`, `Assign provider` unblock | **Fail** | Blocking `Assign provider` without Official ID passed (`409`), and saving Official ID without `Full ID number` unblocked it. Entering any value in `Full ID number (optional)` failed `PUT /api/operator/recovery/... -> 422` and blocked submit (Defect #1). |
| **P2-LS-01** | Lease draft, `Change rent terms`, `Add`/`Edit`/`Remove` participant, Official ID gate on `Record signed lease`, execute | **Pass** | All steps passed (including Commercial `Business signatory` validation & Official ID gate). `Add lease participant` requires raw `Tenant party id` UUID. |
| **P2-LS-02** | Signed lease `Add`/`Edit`/`Decide` renewal option (`Exercised`) | **Pass** | All 3 renewal option actions succeeded cleanly. |
| **P2-LS-03** | Move-in inspection draft, edit checklist, attach evidence, finalize, `Correct finalized inspection` & finalize, move-out draft & `Review condition comparison` | **Partial** | Move-in draft, edit, evidence upload, acknowledge, finalize, and correction + re-finalization passed. Move-out finalization blocked by same-day/future move-out guard (`409`). Top `← Back to inspection` link after correction still pointed to superseded ID (Defect #13). |
| **P2-LS-04** | `Void lease` exposure and execution (`b313ff3b`) | **Pass** | `Void lease` exposed on both Draft and Executed leases and voided cleanly. |
| **P2-MN-01** | Partial payment, mismatched allocation validation, `Allocate remaining…` multi-period payment, `Review rent timeliness`, `Void rent expectation` | **Partial** | Partial payment (`$1,000`), mismatched total validation, `Allocate remaining…` (`$2,000` split across Dec/Jan), and `Void rent expectation` passed. `Mark missed` / `Clear missed` blocked (`409: "Only ended unpaid expectations may be marked missed."`) because no ended unpaid expectations exist in demo workspace. |
| **P2-MN-02** | Prepaid check `Schedule`, `Deposit`, `Return`, `Replace` | **Pass** | All 4 lifecycle states passed on active lease `b479d9e8`. Future lease `9977909c` offered its participant in dropdown then failed `409` on submit (Defect #14). |
| **P2-MN-03** | Paid expense (`$500`), `Edit expense context`, `Record expense refund` (`$150`), Reporting parity, `Void expense refund` | **Pass** | Passed end-to-end; Reporting `Net recorded expenses` dropped `$14,408 -> $14,258` on refund and reverted on void. |
| **P2-MN-04** | Deposit account (`8fd0b6bf`), held receipt (`$2,400`), full settlement lifecycle (`Prepare` → `Deduction`/`Credit`/`Source` → `Approve` → `Refund` → `Complete`) | **Pass** | Full settlement lifecycle completed cleanly (`Unresolved balance: No`). Minor raw snake_case enums and raw `Source id` UUID field. |
| **P2-CF-01** | Cross-tab draft edit authority takeover & stale-revision conflict (`Edit service`) | **Pass** | Stale-revision `409` detected and resolved via `Review current source`; cross-tab takeover via `/settings/recovery` rejected displaced tab's save. |
| **Extra P2** | Owner report `Verify`, Maintenance depth, Conversations & Retained sources, Tasks depth | **Partial** | Owner report Verify, Tasks full lifecycle (including `Delete task`), and Retained source `Retain`/`Dismiss` passed. Found `Finish appointment` (`409`, Defect #2), `Correct work entry` (dead-end, Defect #12), and `Create conversation` empty `Entity id` (`403`, Defect #5). |

---

## 4. Detailed Confirmed Findings

### P1 — Functional Blockers & Broken Workflows

1. **`P2-PR-02` — `Full ID number (optional)` breaks draft recovery & blocks Provider Official ID save (`HTTP 422`)**
   - **URL:** `https://demo-a.epmdemo.xyz/providers?workflow=provider.update&target=<providerId>`
   - **Steps to Reproduce:**
     1. Open a provider → `Edit provider` → `Add official ID`.
     2. Select `ID kind = License`, `Country = US`, `Region = OR`, and enter any value in `Full ID number (optional)` (e.g., `CCB-987654`).
     3. Click `Save provider profile changes`.
   - **Expected:** Recovery draft syncs cleanly and `Save provider profile changes` persists the Official ID with `Full ID number` masked behind `Show ID number`.
   - **Actual:** `PUT /api/operator/recovery/...` fails with **`HTTP 422: "Recovery payload does not match the registered form."`** and blocks submission (no `PATCH` request sent). Omitting `Full ID number` and filling only `Last four` saves cleanly.

2. **`Maintenance` — `Finish appointment` (`Record outcome`) always fails with `HTTP 409`**
   - **URL:** `https://demo-a.epmdemo.xyz/maintenance?workflow=maintenance.appointment.finish&target=<appointmentId>`
   - **Steps to Reproduce:**
     1. Open a maintenance issue with a scheduled appointment → `Record outcome`.
     2. Check `I confirm this lifecycle change`, enter `Reason`, and click `Save finish appointment` (tested both `Completed` and `Cancelled`).
   - **Expected:** Appointment transitions to `Completed` or `Cancelled`.
   - **Actual:** `POST /api/maintenance-appointments/:id/complete` (and `/cancel`) fails immediately with **`HTTP 409: "This editor no longer owns the saved form."`** because `x-epm-draft-lease` / `x-epm-prepared-form` headers are omitted.

3. **`G-06` — Invalid & deep-link routes return raw `HTTP 503` JSON instead of `Page unavailable`**
   - **URLs:** `/nonexistent-route`, `/properties/not-a-uuid/overview`, `/maintenance/:id/details`, `/money/expenses/:id/details`, `/leases/:id/overview`, `/coverage/property/:id/overview`
   - **Steps to Reproduce:** Navigate directly to any of the URLs above while `/home` returns `200 OK`.
   - **Expected:** SPA renders `Page unavailable` with a working `Return Home` link (or loads valid deep-link views).
   - **Actual:** Raw **`HTTP 503 Service Unavailable`** JSON `{"message":"Workspace access is unavailable."}`.

4. **`H-03`, `H-04` — Home `"View all..."` links fail to navigate & `"Calendar and appointments"` card clips vertically**
   - **URL:** `https://demo-a.epmdemo.xyz/home`
   - **Steps to Reproduce:**
     1. Load `/home` at `958×978` or `1280×800` and inspect `"Calendar and appointments"`.
     2. Click `"View all Calendar and appointments (4 items)"` or `"View all Information review (19 items)"`.
   - **Expected:** Card displays items without cutting off text, and clicking `"View all..."` navigates to `/home/collections/appointments` and `/home/collections/information_review`.
   - **Actual:** Card container (`174px`–`199.5px` height) clips item 1 (`284px` tall) and hides remaining items; clicking either `"View all..."` link leaves the URL at `/home` without navigating (direct navigation to `/home/collections/*` returns `200`).

5. **`MT-03`, `Conversations` — Selecting `Links → Entity type` before `Entity id` locks `Create conversation` (`HTTP 403`) & unlabeled required `Participants`**
   - **URL:** `https://demo-a.epmdemo.xyz/conversations?workflow=communication.create`
   - **Steps to Reproduce:**
     1. Open `Create conversation` → `Add links entry` → select `Entity type = Maintenance issue` while `Entity id` is empty.
     2. Also submit `Create conversation` with `Participants` empty.
   - **Expected:** Lookup waits for a valid `Entity id`; `Participants` is labeled `(required)`.
   - **Actual:** Fires `GET /api/maintenance-issues/` → **`HTTP 403`**, permanently locking the form with `"Could not load the property's time zone. Reload the form to try again."` Submitting with empty `Participants` fails with `"Participants has too many or too few entries."` without a `(required)` label.

6. **`P-03`, `O-02` — `Tasks` section unavailable on Property & Owner Overview**
   - **URLs:** `/properties/:id/overview`, `/owners/:id/overview`
   - **Expected:** Property/Owner-scoped tasks render cleanly.
   - **Actual:** Renders `"This source is unavailable. Other sections remain independent."` (`availability: "unavailable"`, `reasonCode: "source_read_unavailable"`). Clicking `Retry section` does not recover it.

---

### P2 — Hosted Resilience, Navigation, State & Validation

7. **`G-03` — Draft recovery same-tab lease `409` & stuck `Submission needs checking` discard**
   - **URL:** `/settings/recovery`
   - **Endpoint:** `POST /api/hosted/drafts/{id}/lease -> HTTP 409`
   - **Actual:** Same-tab `Continue editing` opens the form locked (`"Editing is unavailable here"`) until clicking `Take over editing`; clicking `Discard` or `Check submission` on `Submission needs checking` rows fails with `409 ("This editor no longer owns the saved form")` until opened via `View submission` + `Take over editing`.

8. **Intermittent hosted `HTTP 503` on session & draft endpoints**
   - **Endpoints:** `GET /api/hosted/session`, `POST /api/hosted/drafts/{id}/lease`, `POST /api/operator/recovery/{id}/reconcile`
   - **Actual:** Periodically interrupts active workflows with `"Workspace sign-in / Sign-in verified"` or `"Saved form edit authority"` overlays and occasionally leaves `Loading displayed ...` stuck until reload.

9. **`G-02` — Keyboard shortcut `Ctrl+K` / `Cmd+K` does not open Search**
   - **URL:** `/home`
   - **Actual:** Pressing `Control+k` or `Meta+k` produces no navigation (only clicking `Search (Ctrl/⌘ K)` works).

10. **`T-03`, `P2-OW-03` — Missing `Use identity as tenant` on `/parties`, missing Tenant `Add official ID` button, and Tenant name-edit return route**
    - **URLs:** `/parties?identity=<id>`, `/tenants?identity=<id>`
    - **Actual:** `/parties` `More actions` omits `Use identity as tenant` (only reachable via direct `/tenants?workflow=tenant.designate&target=<id>`). Tenant `Official identification` card has no `Add official ID` button (buried in `Edit tenant preferences`). `Edit name and identity` routes to `/parties` and returns to `/parties` instead of `/tenants`.

11. **`P2-OF-01`, `Maintenance` — Dead-end post-save screens on `Correct occupancy` & `Correct work entry`**
    - **Actual:** Both save cleanly but land on stale error alerts (`"This occupancy period is no longer in the displayed timeline."` / `"Select an effective entry from this journal page for correction."`) with no `Back` link.

12. **`P2-OW-01`, `P2-PR-01` — Stale parent views immediately after `Back to property` / `Back to provider`**
    - **Actual:** Property Overview `Owners` stayed at `"1 owner · You 100%"` after saving `50%/50%` ownership, and Provider `Categories` stayed `"None recorded."` after assigning `HVAC / A/C`, until a full reload.

13. **`P2-LS-03` — `Correct finalized inspection` top `← Back to inspection` link points to superseded ID**
    - **Actual:** Top back link pointed to superseded ID `56bad2ce`, whereas bottom `Back to inspection` pointed to new corrected ID `5d9ce027`.

14. **`L-03`, `L-04`, `P2-MN-02` — Auto-save `422` on empty observation rows & ineligible future-lease prepaid check payer**
    - **Actual:** Clicking `Add observations entry` in Inspection Draft / Template immediately fires `PUT /api/operator/recovery/{id} -> HTTP 422`. `Schedule prepaid check` offers a participant from a future-dated signed lease in `Payer party id`, then rejects submit with `409: "Prepaid-check payer must be an active lease participant."`

---

### P3 — Layout, Form UX, Copy & Console Hygiene

15. **`G-01`, `H-01` — Home Filters vertical gap & loading skeleton overlap**
    - **Actual:** ~200px blank vertical gap separates `"Property"` label from its `<select>` in Home `Filters`; gray loading skeletons overlap `"Calendar and appointments"` and `"Information review"` headings.

16. **`G-01`, `P-01`, `P-03`, `M-01`..`M-08` — Horizontal/vertical clipping at `1280×800` & oversized `<select>` controls**
    - **Actual:** `/properties` quick-filter bar clips on the right; `/properties/:id/*` clips `Property setup` offscreen; `/money` clips `Expense categories` and pushes `Reporting` offscreen (filter bars wrap with zero row gap); left sidebar clips bottom line of `"Backups are managed by the administrator."`; oversized vertical `<select>` controls on `Create conversation`, `Retain source`, `Edit task`, `Add task reminder`, `Set waiting context`, and `Terminate lease`.

17. **`All routes`, `PR-02` — Persistent CSP console error & uncaught recovery console error**
    - **Actual:** Every route logs `Loading the script '[redacted-url]' violates the following Content Security Policy directive: "script-src 'self'"`; `PR-02` logged `Uncaught Error: Recovery accepts JSON fields only. Files and credentials need reselection.`

18. **`L-02`, `M-04`, `M-06`, `O-01`, `MT-03`, `P2-MN-04` — Auto-generated form UX, raw UUID/minor-unit inputs & copy bugs**
    - **Actual:**
      - `Create lease draft` lacks default move-in date / timezone label, orders End before Start, and exposes raw UUID (`Tenant party id`, `Space id`) & minor-unit integer inputs (`Base rent minor`, `Agreed security deposit minor`).
      - `Create deposit account`, `Record owner rent report`, `Add lease participant`, and settlement deduction `Source id` expose raw UUID / minor-unit inputs without pickers.
      - Multiple Create forms show pre-checked `Clear *` checkboxes and `"Unsaved changes"` on initial load; raw snake_case/lowercase enums (`single_family_home`, `supporting_document`, `missing_post_move_out_inspection`, `not_applicable`, `vacant`, `cleaning`); Appointment detail labels `America/Los_Angeles` times as `"Starts at utc"` / `"Ends at utc"`; `"Void rent expectation"` confirmation link reads `"Back to deposit account"`; `/owners` property subtitle renders `"730 Demo Sequoia Way · , · Portland · Active"`; `Verify owner rent report` submit button stays disabled with 0 evidence and no inline explanation; archived provider appeared in `Browse owners` existing-party picker.

---

## 5. Cleanup Verification

- **`/settings/recovery`:** Verified **`0 forms`** (`No unfinished forms on this page.`).
- **`/settings`:** Restored to defaults (`Light` theme, `Every 5 minutes (default)` auto-refresh, default navigation order).
- **Cleaned up synthetic records:** All Phase 1 `[UI-TEST]` records archived/voided/dismissed/cancelled; Phase 2 `[UI-TEST-P2]` providers, tasks, issues, expenses, scheduled check, deposit settlement, retained source, and leases `9977909c` / `b313ff3b` cleaned up.
- **Remaining active record (expected business guard):** Executed same-day lease `b479d9e8-9b4b-4929-b998-b3de1f03134e` (`[UI-TEST-P2] Harbor Plaza` / `[UI-TEST-P2] Summit Holdings`) could not be voided (`HTTP 409: "A same-day lease cannot be voided once payments or finalized inspections exist."`) or terminated same-day (`HTTP 400: "Actual move-out must follow occupancy start."`).
