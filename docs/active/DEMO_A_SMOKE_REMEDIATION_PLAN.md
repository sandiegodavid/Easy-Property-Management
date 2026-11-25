# Demo A smoke remediation plan

Status on November 25, 2026. The five-check gate is blocked. See the [live results](../ui/demo-a-smoke-results-2026-11-25.md) and [smoke design](HOSTED_OPERATOR_POST_DEPLOY_SMOKE_DESIGN.md).

Local Docker triage corrected stale Finance and Maintenance test contracts. All five now pass locally. The live support-contact mismatch, Search shortcut result, tenant timeout and Properties 401 have not been retested. Track the intermittent local Home cursor conflict if it recurs. [Local validation and checkpoint](../ui/local-docker-smoke-results-2026-11-25.md)

The next live attempt showed that `/home` can serve the sign-in screen without changing its URL. The suite now requires a successful Settings API read before evaluating workflows. Verify live sign-in before interpreting the previous Search and workflow failures as application defects. The public support-contact mismatch was reproduced independently. [Live diagnostic checkpoint](../ui/demo-a-smoke-results-2026-11-25.md#updated-suite-against-the-live-canary)

| Batch | Slice | Acceptance and validation |
| --- | --- | --- |
| 1 | Confirm the intended support contact and verify the shortcut in the deployed browser. Determine whether each mismatch is in deployment configuration, the app, or the test. | SMOKE-01 and SMOKE-02 pass using the intended contact and a real supported shortcut. |
| 1 | Compare the Reporting and Properties requests with those made by the hosted SPA. Reproduce the auth and route failures with the supported session flow. | SMOKE-04 uses the supported reporting read. SMOKE-05 reaches the maintenance workflow with an authenticated request. |
| 2 | Locate the tenant test stall and give cleanup its own bounded time. Verify cleanup with the exact run prefix across forms and records. | SMOKE-03 completes, and a controlled mid-test failure proves cleanup. Finance and Maintenance smoke checks verify their own cleanup. |
| 3 | Rerun all five checks against the exact candidate digest, then register that release and roll out the inspector. | All five pass on the candidate. Admin refresh displays source-owned access and usage. The inspector rollout passes the post-deployment gate. |
## Signed-in Chrome follow-up

See the [manual results](../ui/demo-a-smoke-results-2026-11-25.md#signed-in-chrome-manual-verification). Search and the manual Finance ledger flow worked. Prioritize the remaining slices below.

| Priority | Slice | Acceptance |
| --- | --- | --- |
| 1 | Confirm and align the configured support contact. | Demo A sign-in metadata and Settings show the approved administrator contact. |
| 1 | Recheck appointment start using the native picker. | A manually entered start saves, appears in Home, and can be finished. If it fails, retain the exact browser interaction and request evidence before fixing the app. |
| 2 | Complete the tenant edit and lease draft lifecycle checks. | The edit persists after reload, the draft lease can be voided, and only retained test history remains. |
| 2 | Verify session continuation and the remaining hosted boundary assertions. | Record the renewal trigger and verify signed-out route handling, SPA fallback, and relevant response headers. |

The follow-up verified tenant edit and lease cleanup, native appointment scheduling, Home calendar, and appointment/issue cancellation. Keep the support-contact fix open. Add a regression case for a maintenance issue created from a resumed draft after sign-in continuation. Its saved screen must link to the committed issue ID. Retain the cookieless 401 and both HTML fallback 404s as boundary checks. [Follow-up evidence](../ui/demo-a-smoke-results-2026-11-25.md#remaining-checks-in-signed-in-chrome)

### Support contact and saved-link fix checkpoint

Demo A’s support contact was changed in the Admin assignment and its running deployment configuration. The first restart encountered unprotected changes. A verified Demo A backup was captured and the container restarted. The resumed maintenance issue link now treats an empty source ID as absent and uses the committed issue ID. A focused Playwright regression saves and closes the draft, resumes it, submits it, and follows the saved screen’s link to the issue. The test, lint, formatting, and type checking passed. The frontend fix still needs a hosted rollout and canary verification.

Live verification found a separate startup blocker after the contact change. Admin and the Operator deployment file both contain the administrator email. Demo A’s verified recovery point is `eb738088-fd12-45b0-958c-9a434bf198d7`. The container still fails startup and public sign-in returns 502. Validation of a temporary database copy failed with “Correlated Lease workflow audit evidence is incomplete.” The retained validator requires a space-occupancy cancellation event for every lease void, while voiding an unsigned draft correctly emits only the lease void event. The smoke test created and voided an unsigned draft before restart. The database was not edited to bypass validation. Recovery requires a separately scoped Lease validator correction and hosted rollout, or explicit approval of a restore that could discard newer data.

### Lease validator and recovery deployment checkpoint

The Lease validator now recognizes an unsigned draft from its correlated prior snapshot and requires only its Lease void audit event. Executed voids still require the correlated portfolio receipt and occupancy evidence. The focused Lease regression and Ruff checks passed. The saved maintenance link regression and frontend lint, formatting, and type checks also passed.

The repair image passed SQLite quick check and product schema validation on a temporary copy of Demo A's live database before deployment. The image containing both fixes is running on Demo A with the original workspace. Container readiness and public sign-in returned HTTP 200. Signed-in Chrome opened Home and Settings, which showed the administrator email and a protected workspace. [Post-recovery canary evidence](../ui/demo-a-smoke-results-2026-11-25.md#post-recovery-canary-evidence)

WWJDF's support contact was updated in its Admin assignment and Operator configuration. A copy of its workspace database passed validation with its existing image. Its backup was verified unchanged before restart. After restart, readiness and public sign-in returned HTTP 200, and the sign-in metadata displayed the administrator email.

### Lease readiness follow-up

The renewal recovery test now checks the operator-facing validation message. The two termination tests advance the property-local date used by the service, covering all six previously failing termination cases. All 41 Lease readiness tests and both Ruff checks passed. The live canary reached Demo A but stopped at SMOKE-01 when the unauthenticated Playwright context received HTTP 401 from Settings. [Live rerun evidence](../ui/demo-a-smoke-results-2026-11-25.md#lease-readiness-follow-up-and-live-rerun)

### Signed-in Chrome rerun

See the [five-check manual matrix and cleanup evidence](../ui/demo-a-smoke-results-2026-11-25.md#signed-in-chrome-rerun-after-lease-readiness-fixes). Live draft void and the resumed maintenance saved link worked. The original Home and Reporting counts checked during the run were restored and recovery showed zero forms.

| Priority | Follow-up | Acceptance |
| --- | --- | --- |
| 1 | Reconcile the tenant smoke checklist with the product's contact requirements. | The supported form is tested with a genuinely invalid submission, and the expected validation and cleanup are explicit. |
| 2 | Isolate the expense validation message with a valid date and merchant. | Zero amount is rejected with field guidance and can be corrected without losing input. |
| 2 | Close outstanding verification on the repair image. | Complete hosted boundary assertions, seeded overview and directory checks, and voided-expense filtering. Record a full pass matrix. |
