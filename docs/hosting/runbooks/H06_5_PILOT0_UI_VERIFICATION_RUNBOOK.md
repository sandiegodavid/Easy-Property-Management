# H06.5 Operations Runbook — Pilot 0 UI Verification (Support Contact, Maintenance UX & Cohort Overview)

**Applies to:** HOSTED-001 Slice H06.5 (Operator, Admin-lite & Central web surfaces)  
**Checkpoint:** [HOSTED_MVP_H06_5_CHECKPOINT_2026-11-23.md](../qualification/reports/HOSTED_MVP_H06_5_CHECKPOINT_2026-11-23.md)  
**Related Runbooks:** [H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md](H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md) · [H06_4_SECURITY_HEADERS_AND_LOGGING_RUNBOOK.md](H06_4_SECURITY_HEADERS_AND_LOGGING_RUNBOOK.md)

---

## 1. Pre-Release Frontend Quality & Responsive Verification Gate

Run from `application/` before packaging Admin, Central, or Operator web bundles for `epm-h02-host`:

```bash
cd application
npm run lint
npm run format:check
npm run typecheck
npx playwright test --config playwright.components.config.ts \
  hosted-settings.spec.ts admin-lite.spec.ts hosted-recovery.spec.ts
```

This verifies:
- Zero ESLint warnings, Prettier formatting, and full TypeScript check (212 files).
- Operator `HostedSettings`, `HostedMaintenanceBanner`, `Updating your workspace` copy, Pilot 0 D4 disclosure, and zero paid-upgrade controls across `390px`, `900px`, and `1440px` in Light & Dark themes.
- Admin-lite `admin-cohort-overview` summary strip (cohort counts, protection health, host headroom, shared maintenance window) across `390px`, `900px`, and `1440px` in Light & Dark themes with zero horizontal overflow.

---

## 2. Live Deployed Browser Smoke Checklist

After deploying updated web bundles onto `epm-h02-host`:

1. **Support contact verification:**
   - Open `https://admin.epmdemo.xyz/` and `https://login.epmdemo.xyz/auth/start?flow=operator` — confirm the configured real `supportContact` appears on sign-in and error views (never a broken placeholder).
   - Open Operator **Settings → Workspace plan and storage** — confirm real `supportContact` and the Pilot 0 disclosure (*Free invitation-only pilot · Best-effort support · 24-hour nightly backup objective with platform-managed encryption keys · Shared announced maintenance window · No contractual SLA*) are visible, with zero billing/upgrade buttons.
2. **Admin-lite cohort overview:**
   - Sign in to `https://admin.epmdemo.xyz/` — confirm the top Cohort Health/Headroom/Maintenance overview card matches active/protected operator counts and qualified capacity profile (or displays `Capacity review required` when capacity observation is unavailable).
3. **Maintenance banner & draft preservation rehearsal:**
   - Publish `state: "announced"` to `/run/epm/maintenance-notice.json` (per [H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md](H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md)) and confirm the unobtrusive pre-maintenance banner appears in Operator shell without clearing an in-progress form.
   - Switch to `state: "in_progress"` and confirm `"Updating your workspace"` appears with draft-preservation guidance, then clear `{"active": false}` after the window ends.
