# Local Docker smoke results, November 25, 2026

Ran the [local Docker stack](../../application/deploy/hosted-mvp/local-test/README.md) with fresh synthetic data. The existing Operator volume failed startup with “Hosted workspace could not acquire its validated single-writer runtime.” A separate Compose project with fresh volumes started both services.

| Check | Initial reproduction | Final run |
| --- | --- | --- |
| SMOKE-01 | Pass | Pass, 2.3s |
| SMOKE-02 | Pass | Pass, 5.7s |
| SMOKE-03 | Pass | Pass, 4.8s |
| SMOKE-04 | Fail, obsolete reporting route | Pass, 1.2s |
| SMOKE-05 | Fail, obsolete appointment revision | Pass, 3.3s |

1. **Finance.** Sign in at `http://localhost:18802` and run the original SMOKE-04. Expected a reporting baseline. Actual `GET /api/financial-reporting/summary` returned 403 `hosted_route_forbidden`. The revised check uses `GET /api/money/properties`, requires an available operating total, checks the expense in the scoped Money directory, and verifies the total returns to baseline after voiding with the returned expense revision.
2. **Maintenance.** Run the original SMOKE-05 on the same host. Expected a scheduled appointment. Actual `POST /api/maintenance-issues/{id}/appointments` returned 409 `stale_revision` because the test sent zero for an existing issue. The revised check uses the issue revision, verifies the Home calendar row, and submits the finish form with both issue and appointment identifiers and the required confirmation.
3. **Intermittent Home conflict.** During one intermediate run, SMOKE-05 completed its workflow and cleanup, then failed its console assertion on HTTP 409 from `GET /api/operator/home/items?collection=needs_action&…`. Expected no console errors. The last full run did not reproduce it. The console guard remains active. The timing and root cause are unconfirmed.

The final serial run passed all five checks in 18 seconds, including the console and HTTP guards. Lint, formatting and type checking passed. The isolated test project and its synthetic volumes were removed. Pre-existing local volumes were preserved. No GCP requests were made by the test suite. See the [remaining remediation plan](../active/DEMO_A_SMOKE_REMEDIATION_PLAN.md).
