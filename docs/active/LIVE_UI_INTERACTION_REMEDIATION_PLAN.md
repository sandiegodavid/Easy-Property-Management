# Live UI Interaction Review Remediation Plan (`demo-a.epmdemo.xyz`)

**Date:** 2026-11-25
**Branch:** `hosted_mvp` (`5ed202f5`)
**Live Release Tested:** `pilot0-20261124-review` (`https://demo-a.epmdemo.xyz/`)
**Test Plan:** [interaction-test-plan.md](../ui/interaction-test-plan.md) (Phase 1 `G-01`..`H-05` + Phase 2 `P2-OF-01`..`P2-CF-01`)
**Findings & Test Results:** [live-interaction-test-results-2026-11-25.md](../ui/live-interaction-test-results-2026-11-25.md)
**Status:** Ready for Implementation (4 batches / 12 slices)

---

## 1. Review Baseline & Scope

Full Phase 1 and Phase 2 interactive browser verification against the live hosted Pilot 0 workspace (`https://demo-a.epmdemo.xyz/`) completed on `2026-11-25`:

- **Phase 1 (`G-01`..`H-05`):** 32 Pass · 8 Partial · 2 Fail (`G-06`, `H-04`) · 1 Blocked (`S-03`, AI disabled by Free pilot policy)
- **Phase 2 (`P2-OF-01`..`P2-CF-01` + extra depth):** 8 Pass · 7 Partial · 1 Fail (`P2-PR-02`)
- **Workspace cleanup state:** `/settings/recovery` verified at `0 forms`, `/settings` restored to defaults, all `[UI-TEST]` records cleaned up; 1 `[UI-TEST-P2]` same-day lease (`b479d9e8` on `[UI-TEST-P2] Harbor Plaza` / `[UI-TEST-P2] Summit Holdings`) remains active due to the intentional same-day activity void/termination guard.

This plan organizes all confirmed defects into **4 risk-ordered batches**. Each slice should be implemented as one cohesive change with focused unit/integration tests, lint/format/typecheck gates per [AGENTS.md](../../AGENTS.md), and live browser re-verification on the target test IDs.

---

## 2. Batch 1 — P1 Functional Blockers & Broken Workflows

### Slice 1.1 — Fix Provider `Full ID number (optional)` Recovery & Save (`P2-PR-02`) — **Pending**
- **Symptom:** On `/providers?workflow=provider.update&target=<providerId>`, entering any value in `Full ID number (optional)` triggers `PUT /api/operator/recovery/...` → **`HTTP 422: "Recovery payload does not match the registered form."`** and blocks `Save provider profile changes` (no `PATCH` request is sent). Omitting `Full ID number` and filling only `Last four` saves cleanly, leaving `Show ID number` / `Hide ID number` untestable.
- **Root-Cause Investigation Targets:**
  - Frontend workflow form / recovery payload serializer (`application/apps/web/src/workflows/` and recovery draft hook) — verify whether secret/sensitive `Full ID number` fields are excluded from recovery or mismatched with the registered recovery schema.
  - Backend recovery schema validation for `provider.update` / official IDs (`application/apps/server/app/modules/`).
- **Acceptance Criteria:**
  - Entering `Full ID number (optional)` does not trigger a `422` recovery error and saves cleanly on `Save provider profile changes`.
  - Saved full ID number stays masked by default and toggles cleanly via `Show ID number` / `Hide ID number`.
  - Sensitive full ID values are never persisted in unredacted draft recovery storage if excluded by policy (handle cleanly without blocking submit).

### Slice 1.2 — Fix `Finish appointment` (`Record outcome`) Missing Draft/Prepared Headers (`Maintenance`) — **Pending**
- **Symptom:** On `/maintenance?workflow=maintenance.appointment.finish&target=<appointmentId>`, submitting `Save finish appointment` (both `Completed` and `Cancelled`) fails immediately with **`HTTP 409: "This editor no longer owns the saved form."`** on `POST /api/maintenance-appointments/:id/complete` and `/cancel` because the client omits `x-epm-draft-lease` / `x-epm-prepared-form` headers.
- **Acceptance Criteria:**
  - `maintenance.appointment.finish` attaches the active draft lease and prepared form headers on both `/complete` and `/cancel` submissions.
  - Both `Completed` and `Cancelled` outcomes succeed cleanly and update the appointment and issue journal.

### Slice 1.3 — Fix Hosted SPA Fallback for Invalid & Deep-Link Routes (`G-06`) — **Pending**
- **Symptom:** Navigating directly to `/nonexistent-route`, `/properties/not-a-uuid/overview`, `/maintenance/:id/details`, `/money/expenses/:id/details`, `/leases/:id/overview`, or `/coverage/property/:id/overview` returns raw **`HTTP 503`** JSON `{"message":"Workspace access is unavailable."}` instead of rendering the SPA `Page unavailable` screen with `Return Home` (or loading valid deep links).
- **Root-Cause Investigation Targets:**
  - Hosted Operator web router / Caddy / FastAPI SPA route matching in `application/apps/server/app/modules/hosted_access/` and `application/apps/server/app/bootstrap/api.py`.
- **Acceptance Criteria:**
  - Valid client-side deep links serve the SPA HTML shell (`200`) for `Accept: text/html` requests and render the target page.
  - Invalid/unknown paths render the SPA `Page unavailable` fallback with a working `Return Home` link (never `HTTP 503 Workspace access is unavailable`).

### Slice 1.4 — Fix Home `"View all..."` Collection Links & Calendar Card Clipping (`H-03`, `H-04`) — **Pending**
- **Symptom:**
  - On `/home`, clicking `"View all Calendar and appointments (4 items)"` or `"View all Information review (19 items)"` leaves the URL at `/home` without navigating (even though direct navigation to `/home/collections/appointments` and `/home/collections/information_review` returns `200`).
  - The `"Calendar and appointments"` card container height (`174px`–`199px`) clips the first item (`284px` tall) vertically and hides remaining items.
- **Acceptance Criteria:**
  - Clicking every `"View all..."` link on `/home` navigates cleanly to `/home/collections/*` with active filters preserved.
  - Calendar card expands or scrolls cleanly without clipping item text or hiding actions.

### Slice 1.5 — Fix `Create conversation` Empty `Entity id` Lookup (`403`) & Required `Participants` Label (`MT-03`) — **Pending**
- **Symptom:** On `/conversations?workflow=communication.create`, selecting `Links → Entity type = Maintenance issue` while `Entity id` is still empty fires `GET /api/maintenance-issues/` → **`HTTP 403`**, permanently locking the form with `"Could not load the property's time zone. Reload the form to try again."` Additionally, `Participants` fails validation with `"Participants has too many or too few entries."` when empty despite not being labeled `(required)`.
- **Acceptance Criteria:**
  - Timezone lookup only fires once both `Entity type` and a non-empty valid `Entity id` are present.
  - `Participants` is clearly labeled `(required)` (or validated inline before submission without an opaque error).

### Slice 1.6 — Fix Property & Owner Overview `Tasks` Section (`source_read_unavailable`) (`P-03`, `O-02`) — **Pending**
- **Symptom:** On `/properties/:id/overview` and `/owners/:id/overview`, the `Tasks` section renders `"This source is unavailable. Other sections remain independent."` (`availability: "unavailable"`, `reasonCode: "source_read_unavailable"`). Clicking `Retry section` does not recover it.
- **Acceptance Criteria:**
  - Property Overview and Owner Overview `Tasks` sections load scoped tasks cleanly with zero `source_read_unavailable` errors.
  - Focused backend integration tests cover both Property and Owner overview task reads.

---

## 3. Batch 2 — P2 Hosted Draft Recovery, Resilience & Navigation/State Coherence

### Slice 2.1 — Fix Draft Recovery Same-Tab Lease `409`, `Submission needs checking` Discard & Intermittent Hosted `503`s (`G-03`) — **Pending**
- **Symptom:**
  - Resuming a draft from `/settings/recovery` via `Continue editing` in the same tab hits `POST /api/hosted/drafts/{id}/lease -> HTTP 409`, locking the form behind `Take over editing`.
  - Clicking `Discard` or `Check submission` on `Submission needs checking` rows in `/settings/recovery` fails with `HTTP 409 ("This editor no longer owns the saved form")` and leaves cards stuck until the user opens `View submission`, takes over editing, and discards inside the workflow view.
  - Intermittent `HTTP 503` responses on `GET /api/hosted/session`, `POST /api/hosted/drafts/{id}/lease`, and `POST /api/operator/recovery/{id}/reconcile` interrupt active workflows with `"Workspace sign-in / Sign-in verified"` overlays and occasionally leave `Loading displayed ...` stuck until reload.
- **Acceptance Criteria:**
  - Same-tab resume from `/settings/recovery` acquires/reuses the editor lease without forcing `Take over editing`.
  - `Discard` and `Check submission` on `Submission needs checking` rows succeed directly from `/settings/recovery`.
  - Identify and fix root cause of intermittent `503`s on hosted session/draft endpoints (e.g., lock contention, socket timeout, or retry/backoff handling) and ensure `Loading displayed ...` never hangs indefinitely on transient failure.

### Slice 2.2 — Fix Global `Ctrl+K` / `Cmd+K` Shortcut, Missing `/parties` `Use identity as tenant` Action & Tenant Routing (`G-02`, `T-03`, `P2-OW-03`) — **Pending**
- **Symptom:**
  - Pressing `Control+k` or `Meta+k` on `/home` does not navigate to `/search` (only clicking `Search (Ctrl/⌘ K)` works).
  - `/parties?identity=<id>` `More actions` menu omits `Use identity as tenant` (only reachable via direct `/tenants?workflow=tenant.designate&target=<id>`).
  - On `/tenants?identity=<id>`, `Official identification` states `"Record at least one official ID before executing a lease"` but provides no `Add official ID` button (buried in `Edit tenant preferences`); `Edit name and identity` routes to `/parties` and returns to `/parties` instead of `/tenants`.
- **Acceptance Criteria:**
  - `Ctrl+K` / `Cmd+K` navigates to `/search` (or focuses the search input) from any route.
  - `/parties?identity=<id>` exposes `Use identity as tenant` in `More actions` when the identity is not yet a tenant.
  - Tenant `Official identification` card exposes an `Add official ID` action, and `Edit name and identity` initiated from `/tenants` returns to `/tenants?identity=<id>`.

### Slice 2.3 — Fix Post-Save Dead Ends, Stale Parent Views & Superseded Inspection Back Link (`P2-OF-01`, `P2-OW-01`, `P2-PR-01`, `P2-LS-03`) — **Pending**
- **Symptom:**
  - `Correct occupancy` and `Correct work entry` save successfully but land on stale error messages (`"This occupancy period is no longer in the displayed timeline."` / `"Select an effective entry from this journal page for correction."`) with no `Back` link.
  - After saving `Change ownership` (`50%/50%`) and clicking `Back to property`, Property Overview `Owners` stayed stale (`You 100%`) until reload; after `Assign category` and `Back to provider`, Provider `Categories` stayed `"None recorded."` until reload.
  - After `Correct finalized inspection`, the top `← Back to inspection` link still pointed to the superseded inspection ID instead of the new corrected ID.
- **Acceptance Criteria:**
  - `Correct occupancy` and `Correct work entry` render a clean confirmation state with working `Back to property` / `Back to maintenance issue` links.
  - Parent property and provider views invalidate/refetch cached queries upon return from mutation workflows so updates appear immediately without reload.
  - `Correct finalized inspection` updates both top and bottom back links to the newly created corrected inspection ID.

### Slice 2.4 — Fix Auto-Save `422` on Empty Nested Rows & Future-Lease Prepaid Check Payer Filter (`L-03`, `L-04`, `P2-MN-02`) — **Pending**
- **Symptom:**
  - Clicking `Add observations entry` in Inspection Draft / Inspection Template immediately fires `PUT /api/operator/recovery/{id} -> HTTP 422` while the newly expanded observation fields are empty.
  - `Schedule prepaid check` offers a participant from a future-dated signed lease in `Payer party id`, then rejects submission with `409: "Prepaid-check payer must be an active lease participant."`
- **Acceptance Criteria:**
  - Adding an empty nested observation row does not trigger a `422` recovery save error.
  - `Schedule prepaid check` only offers eligible payers (or explains eligibility inline before submit).

---

## 4. Batch 3 — P3 Layout, Form UX, Copy & Console Hygiene

### Slice 3.1 — Fix Horizontal Clipping (`1280×800`), Home Filter Gap, Skeleton Overlap & Oversized Selects (`G-01`, `H-01`, `P-01`, `P-03`, `M-01`..`M-08`) — **Pending**
- **Symptom:**
  - At `1280×800`: `/properties` quick-filter bar clips on the right; `/properties/:id/*` clips `Property setup` offscreen; `/money` clips `Expense categories` and pushes `Reporting` offscreen (and filter bars wrap with zero row gap); left sidebar clips the bottom line of `"Backups are managed by the administrator."`
  - `/home`: ~200px blank vertical gap between `"Property"` label and `<select>` in `Filters`; loading skeletons overlap `"Calendar and appointments"` and `"Information review"` headings.
  - Oversized vertical `<select>` controls on `Create conversation`, `Retain source`, `Edit task`, `Add task reminder`, `Set waiting context`, and `Terminate lease`.
- **Acceptance Criteria:**
  - Sub-tab bars and filter bars wrap or scroll cleanly with visible indicators and proper row gap at `1280×800`.
  - Sidebar footer text is never clipped at `800px` viewport height.
  - Home filter grid and loading skeletons align cleanly with no overlap or blank gaps; `<select>` controls use standard height.

### Slice 3.2 — Improve Auto-Generated Form UX, Labels, Enums & Console Hygiene (`L-02`, `M-04`, `M-06`, `O-01`, `PR-02`, `MT-03`) — **Pending**
- **Symptom:**
  - **Console errors:** Persistent CSP error (`Loading the script '[redacted-url]' violates "script-src 'self'"`) on every route; `Uncaught Error: Recovery accepts JSON fields only...` on `PR-02`.
  - **Raw UUID / minor-unit inputs:** `Create lease draft` (also missing default move-in date / timezone label and ordering End before Start), `Create deposit account`, `Record owner rent report`, `Add lease participant`, and settlement deduction `Source id` expose raw UUID textboxes and minor-unit integer inputs without pickers or currency formatting.
  - **Form defaults & copy:** Pre-checked `Clear *` checkboxes and `"Unsaved changes"` on initial load of Create forms; raw snake_case/lowercase enums (`single_family_home`, `supporting_document`, `missing_post_move_out_inspection`, `not_applicable`, `vacant`, `cleaning`); Appointment detail labels `America/Los_Angeles` times as `"Starts at utc"` / `"Ends at utc"`; `"Void rent expectation"` confirmation link reads `"Back to deposit account"`; `/owners` property subtitle renders stray comma (`"730 Demo Sequoia Way · , · Portland · Active"`); `Verify owner rent report` submit button stays disabled with 0 evidence and no inline explanation; archived provider appeared in `Browse owners` existing-party picker.
- **Acceptance Criteria:**
  - Zero console CSP or uncaught recovery errors across all routes.
  - Human-readable labels/pickers and currency inputs replace raw UUID/minor-unit fields where domain records are selectable, and `Create lease draft` defaults move-in date in the property's timezone.
  - All copy, enum labels, back links, and initial Create-form dirty states are clean and accurate.

---

## 5. Batch 4 — Tracked Deferred / Scope-Owned Items (Not Bugs in Current Slice)

- **Property `Documents` sub-tab (`P-03`):** Currently renders `"This workflow is scheduled for a later UI slice."` — track under its owning document-management UI slice rather than patching ad hoc.
- **`/settings/ai` (`S-03`):** Intentionally disabled on Free Pilot 0 tier (`"AI connections are not enabled for the Free pilot. Contact the administrator."`).

---

## 6. Validation Test Matrix

| Validation Area | Coverage Required Before Closing Plan |
| --- | --- |
| **Happy paths** | All Phase 1 & Phase 2 target IDs (`G-02`, `G-03`, `G-06`, `H-01`, `H-03`, `H-04`, `P-01`, `P-03`, `O-01`, `O-02`, `T-03`, `L-02`..`L-04`, `M-04`, `M-06`, `MT-03`, `PR-02`, `P2-OF-01`, `P2-OW-01`, `P2-OW-03`, `P2-PR-01`, `P2-PR-02`, `P2-LS-03`, `P2-MN-02`) pass cleanly. |
| **Invalid combinations** | Invalid routes (`/nonexistent-route`, `/properties/not-a-uuid/overview`), empty `Entity id` on `Create conversation`, empty nested observation rows, ineligible future-lease prepaid check payer, missing `Participants`. |
| **Idempotency & retry** | Draft recovery same-tab resume, `Submission needs checking` discard/reconcile, transient `503` recovery without stuck loading states, two-tab stale revision conflict (`P2-CF-01`). |
| **Transaction rollback / integrity** | `Finish appointment` (`complete`/`cancel`) atomic persistence with draft lease headers; Official ID save with `Full ID number` masked at rest and never leaked to recovery payloads. |
| **Persistence / schema validation** | Zero schema changes expected; verify existing 6-store contract remains untouched. |
| **Query-budget / N+1** | Property & Owner Overview `Tasks` section adheres to existing overview query budgets. |
| **Lint / format / typecheck** | `ruff check`, `ruff format --check` (changed Python files), `npm run lint`, `npm run format:check`, `npm run typecheck` (from `application/`). |
