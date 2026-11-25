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

## Updated suite against the live canary

The updated suite exposed a false sign-in signal. Chromium reached `/home` but the captured state contained zero cookies. The page at that URL showed **Start sign-in** rather than the Operator workspace. Browser fetch and Playwright’s API client both received 401 from Settings or session-dependent reads. The live Admin database still showed Demo A active, enabled, and healthy at its current access epoch.

| Check | Latest diagnostic result |
| --- | --- |
| SMOKE-01 | The public HTML served a support contact different from the smoke design. Authenticated Settings checks were not reached. |
| SMOKE-02 | No Search shortcut was available on the sign-in screen. The result does not reproduce a shortcut defect in an authenticated workspace. |
| SMOKE-03 | The unauthenticated workflow timed out. No authenticated tenant or lease workflow was reached. |
| SMOKE-04 | The new route was not validated with a signed-in session. The new authentication guard observed 401 from Settings and stopped before Finance mutations. |
| SMOKE-05 | The new authentication guard observed the same 401 and stopped before Maintenance mutations. |

To reproduce the harness problem, open Demo A in a clean browser context and inspect `/home` before completing sign-in. Expected an authenticated API response before saving storage state. Actual behavior was a public sign-in shell at the watched URL. The smoke harness now checks `GET /api/hosted/settings` before running workflow assertions. No application console verdict is available from this unauthenticated attempt. No smoke mutations were verified. Screenshots were retained locally for the failed assertions.
## Signed-in Chrome manual verification

| Check | Result | Evidence |
| --- | --- | --- |
| SMOKE-01 | Fail | Workspace loaded, Settings showed the 50 MB Free plan and 8.69 MB used. The displayed support contact was the Demo A account rather than the expected administrator address. Anonymous API and SPA fallback assertions were not repeated. |
| SMOKE-02 | Pass for the manual read path | Home showed the work queue and summaries. Command+K opened Search, Alder returned matching records, and the property and owner overviews opened. |
| SMOKE-03 | Partial | Saved and resumed a tagged tenant draft, confirmed the name survived recovery, created the tenant, and archived it. Editing and lease draft creation/void were not exercised. |
| SMOKE-04 | Pass for the manual ledger path | The form rejected zero. A synthetic $12.34 expense raised the Home Expenses paid total from $13,908.00 to $13,920.34. Voiding it restored $13,908.00. |
| SMOKE-05 | Blocked at appointment entry | Created a synthetic issue. The appointment form reported a missing start time after browser-driven date input. Calendar and finish were not reached. The appointment draft was discarded and the issue cancelled. |

1. **Support contact.** In signed-in Chrome on Demo A, open [Settings](https://demo-a.epmdemo.xyz/settings) and read Support contact. Expected the administrator address from the smoke design. Actual value was the Demo A account address. No failing HTTP status or console error was observed for this UI mismatch.
2. **Appointment input.** Open a tagged issue in [Maintenance](https://demo-a.epmdemo.xyz/maintenance), select **Schedule appointment**, enter a start with the browser tool, fill Purpose and submit. Expected an appointment saved confirmation. The native control accepted a value at one inspection, but validation said “Choose or enter starts at utc.” No appointment commit was observed. Browser-driven entry also required native keyboard changes to commit the Finance date, so this does not establish a defect when a person uses the native picker. Verify the picker by hand before changing the app.
3. **Session continuation.** While navigating Money → Reporting after saving the expense, Chrome showed **Sign-in verified** and paused workspace access. Clicking **Continue to workspace** restored access and allowed expense verification and cleanup. No HTTP status or endpoint was captured for the transition.

The console error read returned no entries at the end of the manual review. HTTP status and header coverage were not collected systematically. Cleanup confirmed the test tenant was archived, the test expense voided, the test issue cancelled, and Unfinished forms showed zero. The Chrome tab was returned to Home. This manual run does not clear the five-check qualification gate.

## Remaining checks in signed-in Chrome

| Check | Follow-up result | Evidence |
| --- | --- | --- |
| SMOKE-01 | Fail on support configuration | Unknown route and invalid property ID both returned HTTP 404 with an HTML Accept header. The fallback rendered Page unavailable in signed-in Chrome. Cookieless `GET /api/properties` returned 401. CSP, no-referrer and nosniff were present on both 404s. The earlier support-contact mismatch remains open. |
| SMOKE-02 | Previously verified | No rerun of the completed manual path. |
| SMOKE-03 | Manual lifecycle passed | Restored the tagged tenant, edited its name and verified it after reopening by URL. Created an unsigned lease, reopened it in Draft, voided it and rearchived the tenant. |
| SMOKE-04 | Previously verified | No rerun of the completed manual ledger path. |
| SMOKE-05 | Lifecycle passed with recovery defect | Native keyboard changes committed the appointment date. Scheduling succeeded, Home showed the appointment, and the finish flow cancelled it. The synthetic issue was also cancelled. |

1. **Broken link after resuming a maintenance draft.** In `/maintenance?workflow=maintenance.issue.create`, begin a tagged issue. After the sign-in continuation interrupts the submission, continue to the workspace and open the saved issue draft from `/settings/recovery`. Submit it and inspect **Back to maintenance issue**. Expected a detail link with the committed issue ID. Actual link was `/maintenance?record=issue&id=` despite “Maintenance issue saved.” Search by the exact tagged summary found the issue and opened its detail page. No HTTP status or endpoint for the submit was captured. The final Chrome console read returned no errors.
2. **Appointment input follow-up.** On a tagged issue, open Schedule appointment, fill the start, change the focused native date segment up and back down, and leave the field before submitting. The start persisted and the appointment was saved. This isolates the previous attempt to date-entry handling in the browser tool and does not reproduce a scheduling failure on this path.

The recovery queue showed zero forms. The test lease was voided, the tenant rearchived, and both appointment and issue cancelled. The Chrome tab was returned to Home. Full authenticated response-header and asset status checks were not collected. The live gate remains open because of the support contact mismatch and the broken saved link.

## Post-recovery canary evidence

Demo A started with image `sha256:765d0f62157233e00a12c0b6fecab9af1de4d33181ae22a274be89a71674fcad` after the image passed validation on a temporary database copy. The live workspace and its verified recovery point were preserved.

| Check | Result on the repair image |
| --- | --- |
| SMOKE-01 | Partial. Readiness and `/sign-in` returned 200, `/` returned 307, cookieless `/api/properties` returned 401, and both invalid HTML routes returned 404. Signed-in Settings showed the administrator email, storage usage, and protected backup status. |
| SMOKE-02 | Partial. Signed-in Home loaded in Chrome. Full navigation and read parity remain to be rerun. |
| SMOKE-03 | Pending live rerun. The local regression verified that an unsigned Lease draft can be voided and the database still passes schema validation. |
| SMOKE-04 | Pending live rerun. |
| SMOKE-05 | Pending live rerun. The focused Playwright test followed the saved screen's link from a resumed maintenance draft to the committed issue. |

This post-recovery check created no live test records. The five-check gate remains open.

## Lease readiness follow-up and live rerun

Ran all five checks with `EPM_SMOKE_BASE_URL=https://demo-a.epmdemo.xyz npm run test:smoke`. The Playwright context had no authenticated Demo A storage state. SMOKE-01 reached Home and received HTTP 401 from `GET /api/hosted/settings` before starting the authenticated checks. The serial suite skipped SMOKE-02 through SMOKE-05. No test records were created. The live gate remains open pending a signed-in Playwright context.

## Signed-in Chrome rerun after Lease readiness fixes

Manually exercised all five workflows on [Demo A](https://demo-a.epmdemo.xyz/) on November 25, 2026, Pacific time. Synthetic run prefix: `[SMOKE-20261125-e7a4]`.

| Check | Result | Evidence |
| --- | --- | --- |
| SMOKE-01 | Partial | Signed-in Settings showed the 50 MB plan, storage, protected status and the administrator contact. Both invalid URLs showed Page unavailable and Return Home worked. Fresh header, asset status and cookieless API assertions were outside this Chrome pass. |
| SMOKE-02 | Partial | Home loaded, Waiting and Upcoming switched, and the calendar collection opened. The keyboard shortcut opened Search, one character showed the minimum-length prompt, and Alder returned the correct property with a Tasks section and owner links. Owner, Leasing and Providers routes opened. This pass did not independently verify every section on those three pages. |
| SMOKE-03 | Failed checklist expectation | Saved and resumed the tenant draft with its name intact. A transient editing fence cleared, and a later session continuation preserved input. Name-only submission committed. The tenant edit persisted when reopening the record. A separate synthetic tenant was linked to an unsigned draft that was saved and voided. Both tenants were archived and appeared only with Include archived tenants enabled. |
| SMOKE-04 | Partial | Home and Reporting showed USD 13,908.00 for November. The zero-amount attempt was blocked, but displayed a generic recovery error and the date also had not been accepted, so zero-only validation was unverified. The valid expense persisted, raised both totals to USD 13,920.34, and was voided. Both totals returned to USD 13,908.00. Voided-history filtering was not explicitly retested. |
| SMOKE-05 | Passed core workflow | Saved and resumed a draft issue, submitted it, and followed Back to maintenance issue to the committed record. Scheduled an appointment without an end, found it on Home and in the calendar collection, opened it from the collection, and recorded its completed outcome. Cancelled the issue for cleanup. |

1. **Tenant submission accepts missing contact.** At `/tenants?workflow=tenant.create`, enter only a synthetic display name, save and close, resume, then click Create tenant. The checklist expects validation to block the incomplete submission. The app instead showed a committed tenant with a Back to tenant link. Determine whether contact is an intended requirement before changing product behavior or the checklist.
2. **Expense validation can surface a recovery payload error.** From Expenses, open Record paid expense, choose a property and category, enter a description and zero amount, and try to submit after attempting to enter the paid date. Expected field guidance. The observed form displayed “Recovery payload does not match the registered form.” The date was still blank after submission. Reproduce with a valid date and merchant to isolate the zero-amount case.

Final cleanup verified both test tenants archived, the unsigned lease voided, the expense voided, the appointment completed and the issue cancelled. Home returned to 11 items needing action, three calendar items, and USD 13,908.00 in expenses paid. Unfinished forms showed zero. History retains the test records. The browser log query returned no errors, but this manual pass did not capture request statuses or console output continuously. The five-check gate remains open.
