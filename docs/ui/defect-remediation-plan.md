# UI Defect Remediation Plan (Phase 1 & Phase 2)

- **Source Test Plan**: [interaction-test-plan.md](interaction-test-plan.md)
- **Source Test Results**: [interaction-test-results.md](interaction-test-results.md)
- **Date**: 2026-11-24
- **Status**: Completed & Live-Verified (Slices 1–7 implemented, validated, and verified live on `http://127.0.0.1:8001`)
- **Scope**: All 26 actionable defects and usability gaps discovered across Phase 1 (14 actionable; single-unit residential `P-02` confirmed intentional per `manual/portfolio-and-people.md`) and Phase 2 (11), plus 1 `manual/` documentation drift item.

---

## 1. Approved Decisions (Slice 4)

The following domain-policy decisions were approved on 2026-11-24:

1. **Draft Lease Void (`L-02`) — Approved**: Allow `LeaseService.void` to void `draft` leases (setting `status = "void"` and retaining history) so operators can retire mistaken drafts from `Lease actions`.
2. **Same-Day Executed Lease Cancellation (Phase 1 Step 6) — Approved**: Allow `LeaseService.void` when `lease.occupancy_starts_on == today` **if** no non-voided rent receipts, deposit receipts, or finalized inspections exist yet (safely reverting lease-owned occupancy).
3. **Delete Task with Acknowledged Reminder (`P2-TK-03`) — Approved (Option A)**: Preserve the strict backend audit rule (`Only open Tasks without non-dismissed reminders can be deleted.`) and hide/disable `Delete task` in the UI with an inline explanation whenever `status !== "open"` or non-dismissed reminders exist.

---

## 2. Implementation Slices

Each slice is cohesive, independently verifiable, and ordered from highest user impact to lowest.

### Slice 1 — Blockers, HTTP 500 & Silent Data Loss (P0 / P1)

| Defect ID | Severity | Root Cause (Verified File & Line) | Planned Fix |
| --- | --- | --- | --- |
| `MT-02` | **High** | `application/apps/server/app/bootstrap/operator_recovery.py:117-128` builds `IssueCreate` without catching `MaintenanceError` (`models.py:178-185`: `categoryDetail` only allowed when `category == "other"`), causing unhandled HTTP `500` on `/attempt` and trapping `Discard…` in `recovery.ts:516-522, 568-579`. Also `maintenance-create-fields.tsx:30` always renders `categoryDetail`. | 1. Wrap `command(IssueCreate, values)` in `operator_recovery.py:117-128` to catch `(ValueError, TypeError, KeyError)` and return structured `422` `OperatorError` with the domain message.<br>2. In `maintenance-create-fields.tsx` / `fields.tsx`, only render `categoryDetail` when `category === "other"` and clear it when switching away from `"other"`. |
| `G-06` | **High** | `application/apps/server/app/platform/web_delivery.py:114-154, 193-212` (`PackagedWebMiddleware`) only serves `index.html` for a strict regex allowlist; unknown routes (`/nonexistent-route`) and invalid UUIDs (`/properties/not-a-uuid/overview`) fall through to FastAPI JSON `404`. | Serve `index.html` for non-`/api/*`, non-asset browser `GET`/`HEAD` requests accepting `text/html` so React Router renders `"Page unavailable"` with `"Return Home"` while keeping `/api/*` returning JSON `404`. |
| `P2-MN-05` (Verify blocker) | **High** | `application/apps/web/src/workflows/money-command.tsx:666` sets `<fieldset disabled={!!selectedMode}>` (permanently locking both mode radios after first click). `money-command.tsx:731-733` + `owner-report-context.tsx:12-26` silently disable `Save verify owner rent report` when `Number(report.evidenceCount) < 1` without rendering the blocking message `"Attach available evidence before verification; a claim alone is not income."`. | 1. Remove `disabled={!!selectedMode}` on the mode `<fieldset>` (only disable while submitting) and reset mode-specific fields cleanly when switching modes.<br>2. Render `ownerVerificationProblem(...)` inline above the submit button (and show an actionable hint / attach-evidence link on `money-records.tsx:297` when `evidenceCount < 1`). |
| `P2-MN-05` (`maskedReference`) | **Medium** | `application/apps/web/src/workflows/fields.tsx:161-165` deletes `maskedReference` and `paymentMethodLabel` whenever `paymentMethodKind` changes; in `owner_rent_report.create`/`.patch`, alphabetical schema order renders `maskedReference` before `paymentMethodKind`. | Stop deleting `maskedReference` (and `paymentMethodLabel` unless incompatible) when `paymentMethodKind` changes; only clear `otherPaymentMethodNote` when switching away from `"other"`. |

---

### Slice 2 — Operator Recovery & Stale Revision Engine (P1)

| Defect ID | Severity | Root Cause (Verified File & Line) | Planned Fix |
| --- | --- | --- | --- |
| `L-02` (opaque `422`) | **Medium** | `application/apps/server/app/bootstrap/operator_recovery.py:149-154` catches `LeaseError` (`ValueError`) and replaces `"Contract end date must follow its start date."` with `"Complete a valid owning command before starting an attempt."`. `leasing.tsx:727-773` has no client-side date-order check. | 1. Preserve safe domain `ValueError` validation messages in `operator_recovery.py:149-154` instead of replacing them with a generic string.<br>2. Add client-side `contractEndsOn > contractStartsOn` validation in `leasing.tsx` so errors appear inline before submission. |
| `P2-TK-02` / `P2-TK-03` (`409 -> 404`) | **Medium** | `application/apps/web/src/workflows/command.tsx:661-668` explicitly excludes `*command-source` queries from post-success invalidation, so repeating a workflow on the same task uses a stale `expectedRevision` (`409`). Then `command.tsx:1474-1508` calls `GET /api/operator/recovery/{id}` for the never-created record (`404`). | 1. Invalidate (or mark stale & refetch on mount) `*command-source` queries after a command completes so subsequent workflows load the latest revision.<br>2. Track whether the recovery record has ever been persisted before calling `GET /api/operator/recovery/{id}` in `"Keep my edits with this reviewed revision"`. |
| `PR-02`, `T-02`, `L-03`, `MT-02` (autosave `422`) | **Medium** | `use-recoverable-form.tsx:48-53` + `command.tsx:501-505` send incomplete/partially-typed fields and strict sub-objects to `PUT /api/operator/recovery/{id}`, where `recovery_schemas.py:128-146` rejects them with `422` (e.g., `TenantCreateForm.officialIds` using strict `OfficialIdRequest` at `identity_forms.py:76`, partial `Decimal`/date/UUID fields). | 1. Use all-optional draft-safe Pydantic sub-models for recovery schemas (starting with `OfficialIdDraftForm` in `identity_forms.py`).<br>2. In `command.tsx` / `fields.tsx` (`clean`), omit incomplete sub-objects or client-invalid partial primitives during debounced autosave (while still validating strictly on submit). |

---

### Slice 3 — Workflow State, Lifecycle & Cross-View Consistency (P1 / P2)

| Defect ID | Severity | Root Cause (Verified File & Line) | Planned Fix |
| --- | --- | --- | --- |
| `H-03` / `M-05` | **Medium** | `prepaid_check_service.py:446-450` calls `tx.dismiss_prepaid_check_reminder(...)` (`finance/infrastructure/unit_of_work.py:751-768`), which dismisses only the `TaskReminder` row and leaves the owning `"Deposit prepaid check"` `Task` in `status = 'open'`, so `attention_reader.py:194-220` keeps surfacing it in Home `Upcoming`. | Cancel the owning `"Deposit prepaid check"` `Task` (alongside dismissing its `TaskReminder`) in `unit_of_work.py:751-768` when a prepaid check is voided, deposited, or replaced. |
| `S-03` | **Medium** | `ai_governance/application/service.py:1135-1151` allows `built_in_enabled=True` with `default_connection_id=None` (`200 OK`), while `ai-governance.tsx:109-113` collapses `activeMode` to `"off"` whenever `defaultConnectionId` has no matching connection, and lines `432-463` leave radios enabled when `registeredAdapters` is empty. | 1. Backend: reject `built_in_enabled=True` without an enabled registered connection (`422` / `409`).<br>2. Frontend: disable `"On this device"` and `"Cloud service"` radios with inline helper text when no adapters/connections are available, and never display `"AI destination settings saved."` when the effective state stays `"Off"`. |
| `P2-TK-02` (`Clear follow up`) | **Medium** | `work-command.tsx:262-263` pre-fills `followUpAt` and `followUpTimezone`; toggling `clearFollowUp` in `fields.tsx` does not omit them, so `toPayload`/`toBody` (`command.tsx:141-198`) sends both alongside `clearFollowUp: true`, triggering backend `422` (`tasks/api/router.py:616-623`). | When `clearFollowUp` is checked in `task.waiting.reschedule`, automatically clear/omit `followUpAt` and `followUpTimezone` from the submitted payload and disable those inputs while checked. |
| `P2-FL-01` (`file.link.archive`) | **Low/Medium** | `workflow-result.ts:106` and `saved-command.tsx:104` only check `form === "file.upload"`, so `file.link.archive` falls through to `GET /api/finance/command-operations/{key}` (`404`) and default `"deposit"` back link (`← Back to deposit account`). Backend `files/api/router.py:201-205` already serves `FileArchiveResponse` on `GET /api/files/commands/by-key/{key}`. | Update `workflow-result.ts:106` and `saved-command.tsx:104` to handle `form.startsWith("file.")` (both `file.upload` and `file.link.archive`), resolving the back link from `returnTo` (`← Back to maintenance issue` / owning entity). |

---

### Slice 4 — Mistaken-Record Escape Hatches & Policy Alignment (P2)

*(Subject to confirmation of Section 1 decisions)*

| Defect ID | Severity | Root Cause (Verified File & Line) | Planned Fix |
| --- | --- | --- | --- |
| `L-02` (Draft void) | **Medium** | `leases/application/service.py:1308-1309` restricts `void()` to `executed` leases; `leasing.tsx:255-268` omits `lease.void` on draft leases. | Allow voiding `draft` leases in `LeaseService.void` (no occupancy/financial impact) and expose `Void lease` in `Lease actions` for `status === "draft"` in `leasing.tsx:255-268`. |
| Phase 1 Step 6 (Same-day lease) | **Medium** | `leases/application/service.py:1310-1311` blocks `void()` when `occupancy_starts_on <= today`, while `_close()` (`1607-1636`) requires `occupancy_starts_on < move_out <= today`, creating a same-day deadlock. | Permit `LeaseService.void` on `occupancy_starts_on == today` when no non-voided financial records or finalized inspections exist (reverting unit occupancy safely), and expose `Void lease` on that state in `leasing.tsx`. |
| `L-04` (Template archive) | **Medium** | `inspections/api/router.py:417-470` and contracts only define `inspection.template.create` and `inspection.template.patch`. | Add `archived_at` column + `archive`/`restore` endpoints on condition checklist templates, update `docs/database/` and contracts, and expose `Archive template` / `Restore template` on `/leasing?templates=true`. |
| `P2-TK-03` (`Delete task`) | **Low/Medium** | `work-records.tsx:213` renders `Delete task` unconditionally without checking `value.status === "open"` or non-dismissed reminders (`tasks/application/mutations.py:172-177`). | Lift/share task reminder state on task detail view and hide/disable `Delete task` with an inline explanation when `status !== "open"` or non-dismissed reminders exist. |

---

### Slice 5 — Owner, Party & Provider Navigation / UX (P2)

| Defect ID | Severity | Root Cause (Verified File & Line) | Planned Fix |
| --- | --- | --- | --- |
| `P2-OW-02` | **Medium** | `shell.tsx:296-322` fetches `GET /api/parties/{party_id}` but discards contacts; `context-reads.tsx:1214-1223` maps Owner `details` tab solely to `relationships`. | Display Owner contact details (or summary) and a direct **Manage contact details** link to `/parties?identity=${id}` (with `state.returnTo = /owners/${id}/details`) on `/owners/:id/details`. |
| `P2-OW-03` | **Low/Medium** | `identity.tsx:56-59` unconditionally fetches `GET /api/tenants/{party_id}` (`404` when party lacks Tenant role). `identity-detail.tsx:158` hardcodes fallback back-link `"/tenants"`. | 1. Gate the tenant query on `party.data.activeRoles?.includes("tenant")`.<br>2. Derive fallback `back` from `activeRoles` (`owner` -> `/owners`, `provider` -> `/providers`, default `/tenants`). |
| `G-03` | **Low** | `command.tsx:768` fallback only checks `provider.`, `lease.`, `inspection.`, defaulting `tenant.` / `party.` to `"/properties"`. | Add `tenant.` / `party.` -> `"/tenants"` (and pass explicit `returnTo` from `identity.tsx:149-169`). |
| `P2-PR-01` | **Low** | `providers.tsx:277-288` hides `provider.category_assignment.restore` inside a collapsed `<details>` (`collapsible={true}`); `fields.tsx` leaves `sourceName` editable when `sourceKind !== "other"` on `provider.reputation_link.add`. | 1. Render archived category assignment's `Restore` action directly visible under `Show archived records`.<br>2. Hide/disable and clear `sourceName` in `fields.tsx` when `sourceKind` is `"google"`, `"yelp"`, or `"angi"`. |

---

### Slice 6 — Form Polish, Navigation Hygiene, Accessibility & Responsive Layout (P3)

| Defect ID | Severity | Root Cause (Verified File & Line) | Planned Fix |
| --- | --- | --- | --- |
| `M-06` | **Low** | `money.tsx:91-104` clones all query params on tab switch, carrying `status=voided` from `checks` into `reports`. | Reset tab-specific filter params (`status`, `settlement`, `timeliness`, `eligibility`, etc.) when switching Money tabs, preserving only shared scope params (`propertyId`, `ownerId`, `leaseId`). |
| `P2-OF-01` | **Low** | `portfolio.tsx:399-494` / `fields.tsx:206-209` seeds empty `{}` for `occupancy` in `portfolio.space.classify`, leaving `effectiveOn` blank despite displaying `"Classification takes effect today: YYYY-MM-DD"`. | Seed `occupancy.effectiveOn` with `source.data.space.effectiveLocalDate` when initializing/adding `occupancy` in `portfolio.space.classify`. |
| `P-02` | **Low** | `command.tsx:1079-1081` `<form>` lacks `noValidate`, so native HTML5 `required` on `property-edit-fields.tsx:105-107` intercepts submit before `<FormErrorSummary>` runs. | Add `noValidate` to `<form>` in `command.tsx:1079` so all workflows consistently use `"Please review your form"`. |
| `L-03` | **Low** | `inspections/api/router.py:179-186` (`AcknowledgmentResponse`) omits participant display name, forcing a 2-hop client waterfall (`inspections.tsx:263-292`) that shows `"Loading participant name…"`. | Include `participantDisplayName` in `AcknowledgmentResponse` (single server-side join/lookup) and render it directly in `InspectionAcknowledgments`. |
| `P-01` / `O-01` | **Low** | `context-reads.tsx:352-355` hardcodes plural `"properties"` / `"owners"` (same pattern in `money-reporting.tsx:171`, `portfolio-status.tsx:42-43`). | Pluralize accurately (`1 matching property`, `1 matching owner`, `1 active property`, `1 active rental unit`). |
| `H-01` | **Low** | `home-property-filter.tsx:132-136` applies `ui-sr-only` to the `Property` `<label>`, hiding it visually unlike sibling Home filter controls. | Make the `Property` `<label>` visible (remove `ui-sr-only`) so it aligns with `Upcoming horizon`, `Money from`, and `Money through`. |
| `G-05` | **Low** | `style.css:178-201` (`.property-status-tabs`) omits `max-width: 100%; min-width: 0;` and uses `flex-wrap: nowrap`, clipping mid-word at `375px`. | Add `max-width: 100%; min-width: 0;` (matching `.page-tabs`) and clean wrap/scroll behavior at `<768px`. |

---

### Slice 7 — Operator Manual Documentation Sync (P3)

- Update [manual/daily-operation.md](../../manual/daily-operation.md#L42) to replace `"Current Home has a Property ID field rather than a name picker"` with the live Property dropdown behavior.
- Update [manual/operation-index.md](../../manual/operation-index.md), [manual/leases-and-inspections.md](../../manual/leases-and-inspections.md), and [manual/portfolio-and-people.md](../../manual/portfolio-and-people.md) to reflect Slice 4 & Slice 5 additions (draft/same-day lease void, inspection template archive/restore, Owner `Details` contact link).

---

## 3. Validation & Test Matrix

Per project guidance, every slice will be validated with focused tests before advancing:

| Validation Area | Coverage Across Slices |
| --- | --- |
| **Happy paths** | Maintenance issue create (`other` with `categoryDetail`, non-`other` without), SPA invalid route `"Page unavailable"`, Owner rent report verify (Create & Adopt with evidence) + `maskedReference`, `Clear follow up`, `file.link.archive` completion + back link, prepaid check void clearing Home `Upcoming`, Owner `Details` -> `/parties`, `Classify suite` pre-filled date, finalized inspection acknowledgments. |
| **Invalid combinations** | `maintenance.issue.create` non-`other` + `categoryDetail` (`422`, not `500`), `lease.create` `end < start` (domain message preserved), `owner_rent_report.verify` with `evidenceCount === 0` (inline explanation), `Settings -> AI` without adapters (disabled/rejected), `provider.reputation_link.add` known source kind (no `sourceName`), `task.delete` with non-dismissed reminder. |
| **Idempotency & retry behavior** | `MT-02` `422` no longer traps `Discard…` or `Retry same submission`; repeating task workflows cleanly loads fresh revision without stale `409 -> 404`; `file.link.archive` lookup by idempotency key succeeds on `/api/files/commands/by-key/{key}`. |
| **Transaction rollback** | Prepaid check void atomically dismisses reminder + cancels task; lease void rolls back cleanly on conflict; inspection template archive/restore is atomic. |
| **Persistence / schema validation** | Slice 4 inspection template `archived_at` schema + `docs/database/` dictionary/overview sync; recovery draft schemas accept partial input without `422`. |
| **Query-budget / N+1 constraints** | `L-03` eliminates the 2-hop client waterfall on `InspectionAcknowledgments`; `P2-OW-03` eliminates the wasted `GET /api/tenants/:id -> 404` request on Owner-only parties. |
| **Static & lint gates** | Python: `ruff check` & `ruff format --check` (`application/pyproject.toml`) on all changed `.py` files. Frontend: `npm run lint`, `npm run format:check`, `npm run typecheck` from `application/`. |
| **Live browser re-verification** | Re-run each affected Phase 1 & Phase 2 reproduction script against `http://127.0.0.1:8001` and update [interaction-test-results.md](interaction-test-results.md) to confirm every defect is resolved. |


---

## 4. Implementation Checkpoint (2026-11-24)

All 7 slices have been implemented and validated against static checks, contracts, and focused backend tests.

### Changed Files by Slice

- **Slice 1 — Blockers, HTTP 500 & Silent Data Loss**
  - `MT-02`: `application/apps/server/app/bootstrap/operator_recovery.py` (`_standalone_fingerprint` + `try/except` in `attempt_fingerprint`), `application/apps/web/src/workflows/fields.tsx` (hide/clear `categoryDetail` when `category !== "other"`).
  - `G-06`: `application/apps/server/app/platform/web_delivery.py` (`PackagedWebMiddleware._not_found_html` static HTML `404` `"Page unavailable"` + `Return Home` link for unknown non-API/non-asset HTML requests).
  - `P2-MN-05`: `application/apps/web/src/workflows/money-command.tsx` (removed `<fieldset disabled={!!selectedMode}>`, added inline evidence alert/link), `application/apps/web/src/workflows/owner-report-context.tsx` (rendered `ownerVerificationProblem` inline), `application/apps/web/src/workflows/fields.tsx` (preserved `maskedReference` and `paymentMethodLabel` when changing `paymentMethodKind`).
- **Slice 2 — Operator Recovery & Stale Revision Engine**
  - `L-02`: `application/apps/server/app/bootstrap/operator_recovery.py` (preserved domain `ValueError` validation messages), `application/apps/web/src/workflows/leasing.tsx` (client-side `contractEndsOn > contractStartsOn` check on `lease.create`).
  - `P2-TK-02` / `P2-TK-03`: `application/apps/web/src/workflows/command.tsx` (invalidated `*command-source` queries with `refetchType: "none"` after command completion; skipped `GET /api/operator/recovery/{id}` when no recovery record was persisted).
  - Autosave `422`: `application/apps/server/app/modules/operator/application/identity_forms.py` (`OfficialIdDraftForm`), `application/apps/server/app/modules/operator/application/provider_forms.py` (`ProviderOfficialIdDraftForm`).
- **Slice 3 — Workflow State & Cross-View Consistency**
  - `H-03` / `M-05`: `application/apps/server/app/modules/tasks/application/ports.py`, `application/apps/server/app/modules/tasks/infrastructure/transaction_operations.py` (`cancel_task_if_open`), `application/apps/server/app/modules/finance/infrastructure/unit_of_work.py` (`dismiss_prepaid_check_reminder` cancels the owning `"Deposit prepaid check"` task).
  - `S-03`: `application/apps/server/app/modules/ai_governance/application/service.py` (rejects `built_in_enabled=True` when `default_connection_id is None`), `application/apps/web/src/workflows/ai-governance.tsx` (disables unavailable destination radios and shows helper text).
  - `P2-TK-02`: `application/apps/web/src/workflows/fields.tsx` (auto-hides and clears `followUpAt`/`followUpAtUtc`/`followUpTimezone` when `clearFollowUp` is checked).
  - `P2-FL-01`: `application/apps/web/src/workflows/workflow-result.ts` (handles `form.startsWith("file.")` on `/api/files/commands/by-key/{key}`), `application/apps/web/src/workflows/saved-command.tsx` (maps `file.link.archive` back to the owning record via `returnTo`).
- **Slice 4 — Approved Escape Hatches & Policy Alignment**
  - `L-02` & Phase 1 Step 6: `application/apps/server/app/modules/leases/application/service.py` (enabled `LeaseService.void` on `draft` leases and same-day executed leases without settled payments or finalized inspections), `application/apps/web/src/workflows/leasing.tsx` (exposed `lease.void` on draft and same-day executed leases).
  - `L-04`: `application/apps/server/app/modules/inspections/api/router.py`, `application/apps/server/app/modules/inspections/application/service.py`, `application/apps/server/app/modules/operator/application/inspection_forms.py` (added `archived` support to `TemplatePatchRequest`, `patch_template`, and `TemplateForm`); regenerated `@epm/contracts` via `npm run contracts:generate`.
  - `P2-TK-03`: `application/apps/web/src/workflows/work-records.tsx` (`TaskDeleteAction` hides `Delete task` with an inline explanation when `status !== "open"` or non-dismissed reminders exist).
- **Slice 5 — Owner, Party & Provider Navigation / UX**
  - `P2-OW-02`: `application/apps/web/src/app/shell.tsx` (added **Manage contact details** link to `/parties?identity=:id` in the Owner header).
  - `P2-OW-03`: `application/apps/web/src/workflows/identity.tsx` (gated `GET /api/tenants/:id` on Tenant role or `/tenants` route), `application/apps/web/src/workflows/identity-detail.tsx` (role-aware fallback back link).
  - `G-03`: `application/apps/web/src/workflows/command.tsx` (mapped `tenant.` / `party.` fallback back link to `/tenants`).
  - `P2-PR-01`: `application/apps/web/src/workflows/providers.tsx` (rendered `Restore category assignment` directly visible as a button), `application/apps/web/src/workflows/fields.tsx` (hid/cleared `sourceName` when `sourceKind !== "other"`).
- **Slice 6 & Slice 7 — Form Polish, A11y, CSS & Manual Sync**
  - `M-06`: `application/apps/web/src/workflows/money.tsx` (cleared tab-specific query params on Money tab switch while preserving `propertyId`/`ownerId`/`leaseId`).
  - `P2-OF-01`: `application/apps/web/src/workflows/fields.tsx` (seeded `occupancy.effectiveOn` with today's local date on `Add occupancy`).
  - `P-02`: `application/apps/web/src/workflows/command.tsx` (added `noValidate` to `<form>`).
  - `P-01` / `O-01`: `application/apps/web/src/shared/context-reads.tsx` (singular/plural matching count).
  - `H-01`: `application/apps/web/src/shared/home-property-filter.tsx` (made `Property` `<label>` visible).
  - `G-05`: `application/apps/web/src/style.css` (added `display: flex; max-width: 100%; min-width: 0; white-space: nowrap;` to `.property-status-tabs`).
  - `manual/`: synced `manual/daily-operation.md`, `manual/portfolio-and-people.md`, and `manual/leases-and-inspections.md`.

### Validation Results

| Check | Command / Scope | Result |
| --- | --- | --- |
| Python lint | `ruff check --config pyproject.toml` on all 12 changed `.py` files | **PASS** |
| Python format | `ruff format --check --config pyproject.toml` on all 12 changed `.py` files | **PASS** |
| Focused backend tests | `pytest apps/server/app/platform/tests/test_web_delivery.py apps/server/app/modules/leases/tests/ apps/server/app/modules/inspections/tests/ -k "void or template or unknown_routes"` | **PASS** (16 passed) |
| Frontend lint | `npm run lint` (`eslint . --max-warnings 0`) | **PASS** (0 errors, 0 warnings) |
| Frontend typecheck | `npm run typecheck` | **PASS** (212 source files) |
| Contracts check | `npm run contracts:check` | **PASS** |
| Frontend formatting | `npx prettier --check` on all 17 changed frontend files | **PASS** |
| Live browser re-verification | Verified live on rebuilt `http://127.0.0.1:8001` (`0` console errors, `0` failed network requests, `/settings/recovery` `0 forms`) | **16/16 RESOLVED** (`G-06`, `MT-02`, `S-03`, `P2-MN-05`, `M-06`, `H-01`, `P-01`/`O-01`, `P-02`, `G-05`, `G-03`, `P2-OW-02`/`03`, `L-04`, `L-02`, `P2-TK-02`, `P2-TK-03`, `P2-FL-01`) |
