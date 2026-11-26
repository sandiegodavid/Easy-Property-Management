# Hosted Operator Post-Deployment Workflow Smoke Tests — Design

**Status:** Implemented & Verified (2026-11-26)  
**Date:** 2026-11-25 (verified 2026-11-26)  
**Applies To:** Hosted Operator (`epm-pilot0-operator` on `https://demo-a.epmdemo.xyz` and local Docker test container `http://localhost:18802`)  
**Related Docs:** [Hosted Live Architecture](../hosting/ARCHITECTURE.md) · [Pilot 0 Release Rollout](../hosting/operations/pilot0-release-rollout.md) · [Local Dev & Qualification](../hosting/operations/local-dev-and-qualification.md) · [UI Interaction Test Plan](../ui/interaction-test-plan.md)

---

## 1. Goal & Scope

Define **5 fast, deterministic, self-cleaning end-to-end workflow smoke tests** (`SMOKE-01` through `SMOKE-05`) to run against a **Hosted Operator** instance immediately after every deployment (and optionally against the local containerized test environment before rollout) to verify application health across the full vertical stack:

- **Container & ingress boundary** (SPA delivery, security headers, invalid-route fallback, health probes)
- **Hosted identity & write-fence contracts** (`__Host-epm-session`, `x-epm-csrf`, `x-epm-draft-lease`, `x-epm-prepared-form`, idempotency keys)
- **Read aggregation & SQLite CTE integrity** (Home dashboard, collection drill-downs, global search, Property/Owner multi-source overviews)
- **Stateful CRUD & draft recovery** (create, partial-draft resume, validation, edit, persistence across reload, archive/void cleanup)
- **Financial ledger, reporting parity & logical storage accounting** (Money writes, Reporting parity with Home, Free v1 50 MB usage accounting)
- **Cross-module operational workflows** (Maintenance issue → appointment scheduling → Home calendar reflection → appointment finish)

### Target Budget & Execution Envelope

- **Total runtime target:** `<= 90 seconds` end-to-end (serial execution on one canary Operator workspace so active counts and storage accounting stay deterministic).
- **Target workspace guardrail:** Run **only** against a designated synthetic/canary Operator workspace (e.g., `https://demo-a.epmdemo.xyz` in Pilot 0 or `http://localhost:18802` locally). **Never** run mutating smoke tests against a real customer workspace.
- **Explicit non-goals:** Does not replace full qualification suites (`qualify_h05_recovery.py`, `qualify_h06_*`), full Phase 1/2 UI interaction audits, or destructive backup/restore drills. Never executes irreversible actions (no same-day signed leases that trigger the intentional same-day void guard, no live restore, no Admin retirement).

---

## 2. Shared Execution & Safety Contracts

Every smoke test inherits these mandatory invariants:

1. **Synthetic Naming & Correlation:** All created records use a unique run prefix `[SMOKE-<YYYYMMDD>-<shortId>]` (e.g., `[SMOKE-20261125-a1b2]`) and deterministic `uuid5` idempotency keys derived from the run ID and step label.
2. **Global Observability Gates (all 5 workflows):**
   - Zero uncaught browser console errors or unhandled promise rejections.
   - Zero unexpected HTTP `5xx` responses (and zero raw `503 Workspace access is unavailable` on valid or invalid HTML routes).
   - Zero `source_read_unavailable` / `"This source is unavailable"` degraded sections on Home, Property Overview, or Owner Overview.
   - Zero leaked secrets or unredacted stack traces in UI or API responses.
3. **Guaranteed Cleanup (`finally` phase):**
   - Archive or void every `[SMOKE-*]` entity created by the run (tenant, expense, maintenance appointment, maintenance issue).
   - Discard any residual draft in `/settings/recovery`.
   - Post-run assertion: `/settings/recovery` shows `0` unfinished forms, active portfolio/tenant/issue counts match pre-run baseline, and current-month Reporting totals match pre-run baseline.
4. **Authentication Modes:**
   - **Local Docker (`http://localhost:18802`):** Uses `/__local__/sign-in` (mints a real `hosted-access.sqlite` session cookie).
   - **Live Hosted Canary (`https://demo-a.epmdemo.xyz`):** Uses a pre-authenticated Playwright `storageState` (or interactive canary login via `login.epmdemo.xyz`) — never bypasses hosted identity or weakens origin/CSRF enforcement.

---

## 3. The 5 Post-Deployment Workflow Smoke Tests

### `SMOKE-01`: Hosted Boundary, Session, Settings & SPA Fallback

**Purpose:** Confirm the deployed Operator container is live, serving the new frontend bundle with hosted metadata and security headers, exposing accurate Free v1 Settings/Storage/Protection data, and handling unknown routes via the SPA fallback rather than raw `503`.

| Step | Action | Verification / Pass Criteria |
| --- | --- | --- |
| 1.1 | Probe container/app health (`GET /health/live`, `GET /health/ready` when reachable from host/local) and navigate to `/` | `/` redirects (`307`) to `/home` with default `horizonDays`, `fromOn`, `throughOn` query params; HTML includes `<meta name="epm-deployment" content="hosted_managed">` and `<meta name="epm-administrator-contact" content="dctech92130@gmail.com">`. |
| 1.2 | Inspect response headers and compiled assets | `/assets/*.js` and `/assets/*.css` return `200`; `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Content-Security-Policy` are present; `__Host-epm-session` cookie is active. |
| 1.3 | Open **Settings** (`/settings`) and inspect `GET /api/hosted/settings` | `200 OK`; `surface === "operator_settings"`; Free v1 plan (`50,000,000` usable bytes) with non-negative `used_bytes`; protection status renders (`protected`/`healthy` on live canary with verified backup); real support contact (`dctech92130@gmail.com`) shown; zero paid-upgrade or Stripe billing buttons. |
| 1.4 | Navigate to `/nonexistent-route` and `/properties/not-a-uuid/overview` | Returns SPA `Page unavailable` HTML (`404`) with a working `Return Home` link — **never** raw `503 {"message":"Workspace access is unavailable."}` (regression guard for `G-06`). |
| 1.5 | Verify unauthenticated/invalid API boundary (separate cookieless context) | `GET /api/properties` without `__Host-epm-session` returns `401` (`hosted_session_required`), confirming the auth gate is active. |

---

### `SMOKE-02`: Home Dashboard, Global Search & Multi-Source Overview Read Parity

**Purpose:** Confirm core read projections, SQLite CTE queries, work-queue navigation, and search work cleanly against the deployed business SQLite schema.

| Step | Action | Verification / Pass Criteria |
| --- | --- | --- |
| 2.1 | Load `/home` and record baseline counts & `Recorded money` metrics | All Home widgets (`Needs action`, `Waiting`, `Upcoming`, `Calendar and appointments`, `Recorded money`, `Information review`) load with `200` responses and zero `source_read_unavailable` banners. |
| 2.2 | Switch work-queue sub-tabs (`Needs action` → `Waiting` → `Upcoming`), expand one summary bar, and click `"View all Calendar and appointments"` | Sub-tabs switch without error; summary bar expands inline; clicking `"View all..."` navigates to `/home/collections/appointments` with filters preserved (regression guard for `H-04` pointer-event/clipping bug). |
| 2.3 | Press `Ctrl+K` / `⌘+K` to open `/search`, enter 1 char (`a`), then `>=2` chars (a known seeded property name, e.g., `Alder`) | Shortcut navigates to `/search` (regression guard for `G-02`); 1-char input prompts for 2+ chars; `>=2` chars returns matching property/lease/owner results; clicking a property result opens `/properties/:id/overview`. |
| 2.4 | Inspect **Property Overview** (`/properties/:id/overview`) and navigate to a linked **Owner Overview** (`/owners/:id/overview`) | Every overview section — specifically including the **Tasks** section — renders cleanly with zero `source_read_unavailable` errors (regression guard for `P-03`/`O-02` SQLite CTE bug). |
| 2.5 | Open `/leasing` and `/providers` list views | Both return `200` and render seeded rows without console or contract errors. |

---

### `SMOKE-03`: Tenant Write, Draft Recovery Lease & Persistence Lifecycle

**Purpose:** Prove the entire hosted write fence (`__Host-epm-session` + `x-epm-csrf` + `x-epm-draft-lease` + `x-epm-prepared-form` + `idempotencyKey`), draft persistence/same-tab resume, validation, SQLite commit, and cleanup work end-to-end.

| Step | Action | Verification / Pass Criteria |
| --- | --- | --- |
| 3.1 | Open `/tenants`, click **Create tenant**, type partial name `[SMOKE-<id>] Jordan Avery` (contacts are optional by design), and navigate away to `/settings/recovery` | Partial draft is saved and listed under **Unfinished forms** (`Continue editing`). |
| 3.2 | Click **Continue editing** from `/settings/recovery` in the same browser tab | Draft resumes with entered values preserved and **zero** `HTTP 409` / `"Take over editing"` prompt (regression guard for `G-03` same-tab lease reuse). |
| 3.3 | Test a genuinely invalid submission (clear `Display name`, or add a contact row with a malformed email such as `not-an-email`) and submit | Inline validation blocks commit (`400`/`422`) without crashing or wiping typed form values. |
| 3.4 | Restore `[SMOKE-<id>] Jordan Avery` (and valid optional contact `smoke-<id>@example.invalid` if added) and submit **Create tenant** | `POST /api/tenants` returns `200`/`201` with valid `x-epm-csrf`, `x-epm-draft-lease`, and `x-epm-prepared-form` headers; shows committed tenant confirmation with link to tenant detail view. |
| 3.5 | Hard-reload the tenant detail page, edit display name to `[SMOKE-<id>] Jordan Avery Updated`, save, create and immediately **Void** a `Draft` lease linked to that tenant (proving Leasing write + clean draft-void lifecycle without triggering the same-day executed-lease guard), then **Archive** the tenant | Reload proves durable SQLite write; edit persists; `Draft` lease creates and voids cleanly; archived tenant disappears from default `/tenants?browse=true` list and appears only when `Include archived tenants` is checked; `/settings/recovery` returns to `0` unfinished forms. |

---

### `SMOKE-04`: Financial Ledger, Reporting Parity & Logical Storage Accounting

**Purpose:** Prove financial mutations commit atomically, reflect accurately across filtered ledgers and Reporting summaries (matching Home `Recorded money`), update Free v1 storage accounting cleanly, and roll back/void cleanly.

| Step | Action | Verification / Pass Criteria |
| --- | --- | --- |
| 4.1 | Open `/money?tab=reporting` for the current month (`YYYY-MM-01`..`YYYY-MM-DD`) and record baseline `Expenses paid` total; also capture `used_bytes` from `GET /api/hosted/settings` | Reporting loads with `200` and matches `Home → Recorded money` for the identical date range. |
| 4.2 | Open `/money?tab=expenses` → **Record paid expense**; attempt an invalid submission (amount `0` or negative) | Client/server validation rejects invalid amount (`400`/`422`) cleanly without creating a ledger row. |
| 4.3 | Record a valid paid expense of `$12.34` titled `[SMOKE-<id>] Filter Replacement` on a seeded property and expense category for today's date | `200`/`201`; expense appears in `/money?tab=expenses` with exact amount `$12.34` and persists across reload. |
| 4.4 | Re-open `/money?tab=reporting` (same current-month range) and `GET /api/hosted/settings` | `Expenses paid` increases by exactly `+$12.34` (matching Home `Recorded money`); `/api/hosted/settings` returns `200` with valid non-negative logical `used_bytes` under `50,000,000`. |
| 4.5 | Open the `[SMOKE-<id>]` expense detail view and **Void** it; re-check `/money?tab=expenses` and `/money?tab=reporting` | Voided expense is hidden when `Include voided history` is unchecked, visible when checked, and `/money?tab=reporting` `Expenses paid` returns to the exact pre-test baseline. |

---

### `SMOKE-05`: Maintenance Issue, Appointment Scheduling, Home Calendar & Finish Flow

**Purpose:** Prove multi-entity operational workflows across Maintenance, Appointments, and Home Calendar — specifically guarding against missing draft-lease/prepared-form headers on sub-workflow actions (`maintenance.appointment.finish`).

| Step | Action | Verification / Pass Criteria |
| --- | --- | --- |
| 5.1 | Open `/maintenance` → **Report maintenance issue** and create `[SMOKE-<id>] Smoke Valve Check` linked to an existing seeded property | `200`/`201`; issue opens in detail view with status `Open` and persists across reload. |
| 5.2 | Inside the issue detail view, schedule a **Maintenance appointment** for tomorrow (within the default 7-day Home horizon) | Appointment saves (`200`/`201`) and appears in the issue's appointment list and work journal. |
| 5.3 | Navigate to `/home` and inspect `Calendar and appointments` (and `/home/collections/appointments`) | The `[SMOKE-<id>]` appointment is visible on Home within the 7-day horizon with a working link back to the issue/appointment. |
| 5.4 | Open the appointment's **Finish appointment** workflow (`maintenance.appointment.finish`) and submit outcome `Cancelled` (or `Completed`) | `POST /api/maintenance-appointments/:id/cancel` (or `/complete`) attaches `x-epm-draft-lease` and `x-epm-prepared-form` and returns `200` — **never** `HTTP 409 "This editor no longer owns the saved form."` (regression guard for Slice 1.2). |
| 5.5 | Transition `[SMOKE-<id>] Smoke Valve Check` to `Cancelled` (or `Resolved`) and verify `/home` & `/settings/recovery` | Issue no longer appears in open `Needs action` queue; appointment clears from active `Calendar and appointments`; `/settings/recovery` shows `0` unfinished forms. |

---

**Verification Status (2026-11-26):** Passed 5/5 checks with full cleanup on local Docker (`http://localhost:18802`, `npm run test:smoke`) and on the live Pilot 0 canary (`https://demo-a.epmdemo.xyz` running `epm-pilot0-operator:pilot0-20261126-canary`, `sha256:bbbbc05c88fc6c5ac623fdbbda82d26f9829a8d54032a883964f7be451997fc8`).

## 4. Test & Validation Matrix

| Validation Area | Covered By | Concrete Assertion |
| --- | --- | --- |
| **Happy paths** | `SMOKE-01`..`05` | Authenticated shell, settings, dashboard/search/overviews, tenant CRUD, expense CRUD + reporting parity, maintenance issue + appointment finish all succeed (`200`/`201`). |
| **Invalid combinations** | `SMOKE-01` (1.4, 1.5), `SMOKE-02` (2.3), `SMOKE-03` (3.3), `SMOKE-04` (4.2) | Unknown routes return SPA `404` (not `503`); unauthenticated `/api/properties` returns `401`; 1-char search prompts cleanly; malformed tenant email and `<= 0` expense amount reject with `400`/`422` without losing form state. |
| **Idempotency & retry behavior** | `SMOKE-03` (3.2, 3.4), `SMOKE-04` (4.3), `SMOKE-05` (5.4) | Same-tab draft resume reuses lease via `renew: true` without `409`; deterministic `idempotencyKey` prevents duplicate records on retry; transient `503` retry logic does not hang UI loaders. |
| **Transaction rollback / cleanup** | `SMOKE-03` (3.5), `SMOKE-04` (4.5), `SMOKE-05` (5.4, 5.5) | Invalid submissions leave zero partial rows; post-test archive/void/cancel leaves active counts, reporting totals, and `/settings/recovery` (`0 forms`) identical to pre-run baseline. |
| **Persistence / schema validation** | `SMOKE-01` (1.1), `SMOKE-03` (3.5), `SMOKE-04` (4.3), `SMOKE-05` (5.1) | Container startup passes `validate_schema` (`HOSTED_ACCESS`, `business`); hard page reloads confirm committed SQLite reads across requests. |
| **Backup / restore readiness** | `SMOKE-01` (1.3) | `/api/hosted/settings` reports `protection` section state (`protected`/`healthy` on live canary) confirming verified off-host backup freshness without triggering a destructive restore during smoke checks. |
| **Query-budget / N+1 constraints** | `SMOKE-02` (2.1, 2.4), `SMOKE-04` (4.4) | Home, Property Overview, Owner Overview, and Reporting load within the 90-second total suite budget (`< 3s` per screen) with zero SQLite compound-SELECT/CTE failures (`source_read_unavailable`). |

---

## 5. Rollout Integration & Pass/Fail Gate

1. **Pre-Rollout (Local Container Gate):** Run `SMOKE-01`..`05` against `http://localhost:18802` (`deploy/hosted-mvp/local-test/compose.yaml`) before building and uploading release tarballs to `epm-h02-host`.
2. **Post-Rollout (Live Canary Gate):** Immediately after rolling `epm-pilot0-operator:<RELEASE_TAG>` onto `epm-h02-host`, run `SMOKE-01`..`05` against the designated canary workspace (`https://demo-a.epmdemo.xyz`) before rolling remaining Pilot 0 operator containers or marking the release complete.
3. **Failure Policy:**
   - Any failure in `SMOKE-01`..`05` **halts rollout** to additional operator containers.
   - Capture the Playwright trace/screenshot, failing URL, HTTP status, and console errors; run cleanup if aborted mid-test; and roll back the canary container to the previous pinned image digest if the defect is release-introduced.

---

## 6. Approved Decisions (2026-11-25)

1. **Execution Harness (Approved):** Implemented as a dedicated Playwright suite (`application/playwright.smoke.config.ts` + `application/apps/web/tests-hosted/operator-smoke.spec.ts`, npm script `npm run test:smoke`) parameterized by `EPM_SMOKE_BASE_URL` (default `http://localhost:18802`) and `EPM_SMOKE_STORAGE_STATE` (optional for live canary auth).
2. **Canary Workspace (Approved):** `https://demo-a.epmdemo.xyz` is the designated Pilot 0 post-deploy smoke canary (paired with `http://localhost:18802` pre-rollout).
3. **Leasing Coverage (Approved):** `SMOKE-02` verifies `/leasing` read health and `SMOKE-03` creates and immediately voids a `Draft` lease (cleanly voidable, never leaving an active same-day lease behind).
