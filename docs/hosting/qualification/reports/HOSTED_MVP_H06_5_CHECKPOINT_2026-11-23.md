# HOSTED-001 Slice H06.5 Checkpoint — Pilot 0 UI & UX Polish (Operator + Admin-lite + Central)

**Date:** 2026-11-23  
**Slice:** H06.5  
**Owning Design:** [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md)  
**Owning Delivery Plan:** [delivery-plan.md](../../design/mvp/delivery-plan.md#implementation-slices)  
**Operations Runbook:** [H06_5_PILOT0_UI_VERIFICATION_RUNBOOK.md](../../runbooks/H06_5_PILOT0_UI_VERIFICATION_RUNBOOK.md)  
**Branch:** `hosted_mvp`

---

## 1. Completed Deliverables

1. **Real Support Contact on Sign-In & Error Surfaces (`central/main.tsx`, `admin/main.tsx`):**
   - Captured and rendered `supportContact` on [central/main.tsx](../../../../application/apps/web/src/central/main.tsx) and surfaced `supportContact` directly in [admin/main.tsx](../../../../application/apps/web/src/admin/main.tsx) sign-in error states.

2. **Operator Pre-Maintenance Banner, `Updating your workspace` Draft-Preserving UX & Pilot 0 Disclosure (`hosted-settings.tsx`, `shell.tsx`, `workspace-gate.tsx`):**
   - Exported `HostedMaintenanceBanner` from [hosted-settings.tsx](../../../../application/apps/web/src/app/hosted-settings.tsx) and mounted it in [shell.tsx](../../../../application/apps/web/src/app/shell.tsx) above `#workspace-content` (never unmounting active forms), rendering either a scheduled pre-maintenance window banner or `"Updating your workspace"` with draft-preservation guidance.
   - Added `503 maintenance_in_progress` handling in [workspace-gate.tsx](../../../../application/apps/web/src/app/workspace-gate.tsx) showing `"Updating your workspace"` and local draft preservation.
   - Added formatted maintenance window boundaries and the explicit D4 Pilot 0 disclosure (*Free invitation-only pilot · Best-effort support · 24-hour nightly backup objective with platform-managed encryption keys · Shared announced maintenance window · No contractual SLA*) in [hosted-settings.tsx](../../../../application/apps/web/src/app/hosted-settings.tsx), with zero paid-upgrade controls advertised.

3. **Admin-lite Cohort Health, Headroom & Maintenance Summary Card (`AdminWorkspace.tsx`):**
   - Added `data-testid="admin-cohort-overview"` summary strip in [AdminWorkspace.tsx](../../../../application/apps/web/src/admin/AdminWorkspace.tsx) surfacing total/active/needs-attention cohort counts, protected vs degraded/unavailable backup health, host capacity/headroom profile (`Capacity review required` when unavailable), and shared Pilot 0 maintenance window status.

4. **Responsive & Theme Playwright Verification (`hosted-settings.spec.ts`, `admin-lite.spec.ts`):**
   - Added Playwright checks verifying Operator maintenance/updating UX + Pilot 0 disclosure and Admin-lite cohort overview across `390px`, `900px`, and `1440px` viewports in both Light and Dark color schemes with zero horizontal overflow.

---

## 2. Validation Results

- **Frontend lint, format & typecheck (`application/`):** `npm run lint` (0 warnings), `npm run format:check` (Prettier clean), `npm run typecheck` (212 source files) — **All passed**.
- **Playwright component tests:** `npx playwright test --config playwright.components.config.ts hosted-settings.spec.ts admin-lite.spec.ts hosted-recovery.spec.ts` — **10/10 passed**.
