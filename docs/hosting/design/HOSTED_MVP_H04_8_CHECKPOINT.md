# HOSTED-001 H04.8 Implementation Checkpoint — Operator Settings & Storage-Limit UI

- **Date**: 2026-11-22
- **Slice**: `H04.8` (Operator Settings & storage-limit UI) from [`HOSTED_MVP_H04_DESIGN.md`](HOSTED_MVP_H04_DESIGN.md)
- **Status**: Complete

## Summary of Changes

1. **Hosted Operator Settings Panel** (`application/apps/web/src/app/hosted-settings.tsx`):
   - Added `HostedSettings`, rendered strictly when `managedHostedMode()` is true (local single-operator mode remains completely untouched and makes zero requests to `/api/hosted/settings`).
   - Fetches `GET /api/hosted/settings` (`credentials: "same-origin"`) and displays:
     - **Plan**: `Free pilot (50.00 MB logical storage)`.
     - **Storage usage**: progress bar, decimal MB used / usable / remaining, database and retained-file breakdown, active-write reservations when present, and `observed_at` freshness timestamp; renders honest `Unavailable` without fabricating zero bytes when `usage.state !== "ready"`.
     - **Backup protection**: renders honest `Unavailable — backup protection is not yet active.` when `protection.state !== "ready"` (never fabricating protected state or verified timestamps prior to H05).
     - **Support contact**: displays administrator contact from `Settings` payload.
     - **Maintenance notice**: rendered only when announced (`maintenance.state === "ready"` with message).
     - Explicit **Refresh storage usage** action; zero paid-upgrade, billing, plan-change, individual maintenance scheduling, or idle-wake controls.
2. **Settings Integration & Free Pilot Copy** (`application/apps/web/src/app/preferences.tsx`, `application/apps/web/src/app/shell.tsx`):
   - Mounted `<HostedSettings />` inside `PreferenceSettings` gated by `managedHostedMode()`.
   - Updated hosted AI disabled notices in `shell.tsx` from `"this demo"` to `"the Free pilot"` (per D10).
3. **Definite Pre-Mutation `507` Handling** (`application/apps/web/src/shared/mutations.ts`):
   - Added `isStorageQuotaRejection(status, code)` so `507 hosted_storage_quota_exceeded` / `hosted_storage_limit_exceeded` responses set `MutationFailure.outcomeUnknown = false`, preserving unfinished form input and surfacing clear Free 50 MB guidance instead of entering "outcome unknown" reconciliation mode.
4. **Playwright Component Tests** (`application/apps/web/component-tests/hosted-settings.html`, `hosted-settings-fixture.tsx`, `hosted-settings.spec.ts`):
   - Verified hosted mode rendering (plan, logical usage, breakdown, freshness, unavailable protection, support contact, zero upgrade/billing/wake controls).
   - Verified honest unavailable usage and maintenance notice display.
   - Verified local mode regression (no `HostedSettings` rendered and zero `/api/hosted/settings` requests).
   - Verified `507 hosted_storage_quota_exceeded` definite rejection preserves unfinished form input.

## Validation

- `cd application && npm run lint`: **Passed** (`0` errors, `0` warnings).
- `cd application && npm run typecheck`: **Passed** (`208` source files).
- `cd application && npx prettier --check ...` (all 7 changed/added files): **Passed**.
  - Note: repo-wide `npm run format:check` flags only pre-existing untouched `application/deploy/hosted-mvp/README.md`.
- `cd application && npm run build`: **Passed** (`contracts:check` + `@epm/web` Vite production bundle built in `303ms`).
- `cd application && npx playwright test -c playwright.components.config.ts apps/web/component-tests/hosted-settings.spec.ts`: **4 passed** (`2.1s`).

## Next Slice

- **H04.9**: Native Linux/Docker/GCP Free physical storage sizing qualification (3 workload shapes, justified byte/inode margins, independent byte & inode exhaustion/rollback/UI tests).
