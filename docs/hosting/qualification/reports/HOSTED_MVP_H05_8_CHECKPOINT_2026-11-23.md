# HOSTED-001 Slice H05.8 Checkpoint — Operator & Admin Recovery UI

**Date:** 2026-11-23  
**Slice:** H05.8 (`HOSTED_MVP_H05_DESIGN.md` Section 7)  
**Status:** Complete

## Summary of Changes

1. **Operator Data & Backup + Minimal Recovery Mode UI**:
   - Exported `hostedCsrfToken()` from `application/apps/web/src/app/hosted-session-state.ts`.
   - Added `application/apps/web/src/app/hosted-recovery.tsx` (`HostedRecovery`) operating exclusively on `/api/hosted/recovery/*` with zero business API calls:
     - Honest status + icon pairing for `Protected` (`healthy`), `Protected — unchanged since verified point` (`unchanged`, preserving actual `lastCapturedAt` / `lastVerifiedAt` / `lastCheckedAt`), `Degraded` (`overdue`), `Unknown`, and `Unavailable`.
     - Minimal Recovery Mode banner (`mode === "recovery"`), interrupted-restore lookup (`CHECK_RESTORE`), pending-acceptance action (`AcceptRestore`), and catalog reconstruction (`POST /api/hosted/recovery/reconstruct`).
     - Complete restore flow: verified own-workspace point list (latest selected by default, incompatible points disabled) → `PreviewRestore` (with automatic focus transfer to confirmation heading) → fresh strong step-up token input + explicit rollback confirmation → single-use `ConfirmRestore` → `GET /api/hosted/recovery/operations/{operationId}` status lookup → `AcceptRestore`.
     - Zero paid-upgrade, billing, plan-change, or personal-schedule controls.
   - Mounted `<HostedRecovery embedded />` inside `application/apps/web/src/app/hosted-settings.tsx` while preserving all existing H04 settings behavior.
2. **Admin-lite Backup Status, Repair Runtime & Control Recovery UI**:
   - Extended `application/apps/web/src/admin/admin-api.ts` with `AdminControlPoint`, `AdminControlRecoveryStatus`, `AdminControlPreview`, and `formatProtectionLabel()`.
   - Added `application/apps/web/src/admin/AdminRecovery.tsx` (`AdminRecovery`) operating independently of `admin.sqlite` on `/api/admin/recovery/*` (status, catalog reconstruction, verified control point selection, preview with focus transfer, bootstrap Google + TOTP MFA step-up confirmation, confirm, and accept; zero customer-workspace access).
   - Updated `application/apps/web/src/admin/AdminWorkspace.tsx`:
     - Displays `workspace_recovery_status` (`Protected`, `Protected — unchanged`, `Degraded`, `Unavailable`, `Unknown`) with freshness timestamps in both Directory and Operator Detail.
     - Added **Runtime repair** card in Operator Detail with explicit confirmation checkbox, `POST /api/admin/operators/{operatorId}/repair-runtime`, and `GET /api/admin/operations/{operationId}` original-operation status lookup — exposing zero customer-workspace restore or plaintext export controls.
     - Added **Control recovery** toolbar button to open `AdminRecovery`.
3. **Playwright Component Tests**:
   - Added `application/apps/web/component-tests/hosted-recovery.html`, `hosted-recovery-fixture.tsx`, and `hosted-recovery.spec.ts` covering Operator minimal recovery mode (`390px`), degraded/overdue honesty & catalog reconstruction (`900px`), and Admin-lite protection status + repair runtime + Admin Control Recovery (`1440px`), keyboard focus transfer, and zero business API calls in recovery mode.

## Validation Results

- `cd application && npm run lint`: **Passed** (0 errors, 0 warnings).
- `cd application && npm run format:check`: **Passed** (all matched files use Prettier code style).
- `cd application && npm run typecheck`: **Passed** (212 source files).
- `cd application && npx playwright test --config playwright.components.config.ts hosted-recovery.spec.ts hosted-settings.spec.ts admin-lite.spec.ts`: **8 passed** (0 failures).
