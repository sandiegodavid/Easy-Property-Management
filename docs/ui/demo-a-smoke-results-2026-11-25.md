# Demo A live smoke results, November 25, 2026

The canary ran on `pilot0-20261125-tasks` at [Demo A](https://demo-a.epmdemo.xyz). The first failure stopped the serial suite. SMOKE-02 through SMOKE-05 ran individually afterward. The qualification gate is **failed**. No release was registered and no inspector rollout was started.

| Check | Result | Observed failure |
| --- | --- | --- |
| SMOKE-01 | Fail | Hosted support contact differs from the design. |
| SMOKE-02 | Fail | Search shortcut left the browser on Home. |
| SMOKE-03 | Fail | Test reached its 45-second limit and the cleanup session request did not complete. |
| SMOKE-04 | Fail | Reporting summary request returned HTTP 403. |
| SMOKE-05 | Fail | Properties request returned HTTP 401. |

## Reproduction and evidence

1. **Support contact.** Sign in and open [Home](https://demo-a.epmdemo.xyz/home). Run SMOKE-01 and inspect the administrator-contact meta tag. Expected the administrator contact specified in the smoke design. Actual value was the Demo A account address. The test stopped before the Settings API assertion. No failing HTTP status or console error was captured at this assertion.
2. **Search shortcut.** Open [Home](https://demo-a.epmdemo.xyz/home), cycle through the work queue tabs, then press Command+K on macOS. Expected navigation to `/search`. The test stayed on `/home` for ten seconds. No failing HTTP status or console error was captured at this assertion.
3. **Tenant and cleanup timeout.** Run SMOKE-03 from [Tenants](https://demo-a.epmdemo.xyz/tenants), which attempts draft save and resume before tenant and lease writes. Expected the workflow and its cleanup to complete. Actual result was a timeout, with the final error pointing to the cleanup `GET /api/hosted/session`. No response status was captured. The timeout does not isolate the initial stall. A follow-up UI check found no smoke-tagged entries in Unfinished forms or the filtered Tenants directory. No lease cleanup outcome was independently confirmed.
4. **Reporting boundary.** Run SMOKE-04 from authenticated Home. Expected a reporting baseline from `GET /api/financial-reporting/summary?fromOn=2026-11-01&throughOn=2026-11-25&propertyState=all`. The request returned HTTP 403 with `hosted_route_forbidden`. The check stopped before creating an expense.
5. **Maintenance preflight.** Run SMOKE-05 from authenticated Home. Expected `GET /api/properties` to return the property directory. It returned HTTP 401 with `hosted_session_required`. The check stopped before creating an issue or appointment.

Failure screenshots were captured locally. The tests stopped before their final console assertions, so console cleanliness remains unverified. Full traces were disabled for this run. See the [remediation plan](../active/DEMO_A_SMOKE_REMEDIATION_PLAN.md).

## Retry with fresh sign-in

Sign-in succeeded in plain Chromium with recording disabled. All five checks ran independently and reproduced the failures above, including the 45-second tenant timeout and the Reporting 403 and Properties 401 responses. Follow-up browser checks found no visible smoke-tagged entries in Unfinished forms, the filtered Tenants directory, or Leasing. The qualification gate remains failed.
