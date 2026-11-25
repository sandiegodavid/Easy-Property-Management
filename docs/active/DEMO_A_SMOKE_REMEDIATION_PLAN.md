# Demo A smoke remediation plan

Status on November 25, 2026. The five-check gate is blocked. See the [live results](../ui/demo-a-smoke-results-2026-11-25.md) and [smoke design](HOSTED_OPERATOR_POST_DEPLOY_SMOKE_DESIGN.md).

| Batch | Slice | Acceptance and validation |
| --- | --- | --- |
| 1 | Confirm the intended support contact and verify the shortcut in the deployed browser. Determine whether each mismatch is in deployment configuration, the app, or the test. | SMOKE-01 and SMOKE-02 pass using the intended contact and a real supported shortcut. |
| 1 | Compare the Reporting and Properties requests with those made by the hosted SPA. Reproduce the auth and route failures with the supported session flow. | SMOKE-04 uses the supported reporting read. SMOKE-05 reaches the maintenance workflow with an authenticated request. |
| 2 | Locate the tenant test stall and give cleanup its own bounded time. Verify cleanup with the exact run prefix across forms and records. | SMOKE-03 completes, and a controlled mid-test failure proves cleanup. Finance and Maintenance smoke checks verify their own cleanup. |
| 3 | Rerun all five checks against the exact candidate digest, then register that release and roll out the inspector. | All five pass on the candidate. Admin refresh displays source-owned access and usage. The inspector rollout passes the post-deployment gate. |
