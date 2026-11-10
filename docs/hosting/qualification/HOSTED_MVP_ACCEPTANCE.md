# Fresh hosted MVP acceptance register

Updated November 10, 2026. **Design accepted; fresh-MVP implementation and deployment
acceptance not established.** This register follows the
[Hosted MVP design](../design/HOSTED_MVP_DESIGN.md), not the older demo checkpoint.
HOSTED-001 now schedules implementation; documentation establishes no code, cloud resource or passed test.

## Evidence baseline

The current `hosted_mvp` checkout has local application/hosted-access foundations
and older deployment tooling. Prior A/B process/loop-image, Cloudflare Access and
manual recovery tests apply to their named releases only. They do not establish
this design's Docker isolation, central login/subdomains, subscription lifecycle,
unattended incremental recovery or automated provisioning/upgrades.

No fresh-MVP checks were run by the documentation task. Record new proof below
only with exact code/image/schema, host/storage/runtime, provider configuration,
dataset/workload, time, actual results and remaining limits. Separate component,
native and deployed/end-user checks. A skipped test is not a passing gate.

## Stage-specific release gates

| Stage | Required evidence | Status |
| --- | --- | --- |
| H01–H05 preparation | Private container/storage and identity proofs; Admin-lite safe provisioning/claim/retry; Free 50 MB admission/usage; nightly verified off-host database/files and control recovery; rehearsed restore; warm-container capacity for the admitted population (initial proof target: five). | Not established |
| H06 — Pilot 0 | Invited Free operators within qualified capacity; prove a sixth operator can be admitted when capacity permits, concurrent admissions cannot reuse headroom, and insufficient/unknown capacity stays pending; one announced maintenance window with safe drain/recovery; named support and manual-operation runbook; recorded gross spend/Admin minutes; monitored backup-point age. No Stripe, paid enrollment, idle-wake or individual scheduling. | Not established |
| H07–H12 — Full hosted target | Automatic onboarding, paid quota/recovery/billing, independent release scheduling, idle-wake, paid pilot and measured expansion. Apply the detailed gates below to each admitted capability. | Not established |
| Portal follow-up | PORTAL-001/002, FIN-009 and PAY-001/002 source/privacy/payment/browser gates; not hosting completion or Pilot 0 scope. | Not established |

Free Pilot 0 invitations require the first two rows, not paid billing or wake automation.
The three-weekly-users/four-weeks demand measure applies to Pilot 0; paid conversion
is assessed only after paid plans launch. Retain stage labels on evidence; a manual
Pilot 0 proof cannot qualify a later automated effect without its own tests.

## Ordered acceptance gates

| Gate | Required result | Current fresh-target status |
| --- | --- | --- |
| Runtime isolation and persistence | Private Docker instances, one SQLite writer, correct persistent mounts, non-root/runtime and host-agent boundary; restart preserves data and quota ownership. | Not established |
| Gateway and identity | Registered flat subdomains, unknown-host denial, central Google/email callback, secure one-use handoff, host-only sessions and MFA-protected separate Admin. | Not established |
| Small-host capacity/cost | Empty/representative data, background jobs, paid warm residency and Free wake measured; gross launch budget $250/month before credits, no unsupported admission. | Not established |
| Admin onboarding | Add operator admits one durable job; readiness/verified backup precedes invitation; exact identity claim activates automatically; failures stay safely pending. | Not established |
| Free recovery | Consistent database/file capture, nightly/seven-point policy, unattended keys, degraded-status alerts and successful operator-authorized separate-destination restore without Admin approval; preview/recent-auth, safe fencing/validation, scoped status and optional manual executor attribution. | Not established |
| Control recovery | Off-host registry/ownership/configuration/release/billing references and recoverable keys; recovery works without hosted Admin and cannot revive sessions/stale grants. | Not established |
| Metering/enforcement | Reproducible logical allowance, protected physical byte/inode limits, bounded reserves, quota/commit failure handling and safe over-allowance reads/cleanup. | Not established |
| Paid recovery | Actual completed off-host-point age meets recent 15-minute objective; fine-grained 24 hours then daily 30/90-day history, valid incremental chains and measured retained bytes/traffic. | Not established |
| Billing/application | Confirmed payment before verified application; duplicate/out-of-order events and interrupted effects reconcile; scheduled downgrade/cancellation, renewal grace and compensation preserve data. | Not established |
| Admin/operator UI | Independent async usage/plan/protection/progress, desired versus Applied, stale/unknown behavior, upgrade controls, keyboard/themes/narrow layouts and retained forms. | Not established |
| Idle/multi-device behavior | Activity across devices, no polling-induced residency, independent backup jobs, deduplicated wake, stale-edit/takeover handling and no automatic command replay. | Not established |
| Independent releases | Immutable approved canary/batches, operator schedule/default/time zone, activity/drain, schema checks, compatibility and recovery without erasing post-reopen writes. | Not established |
| Operational handover | Executable installation/runbooks, scoped credentials, alerts/mail, incidents, deliberate retirement and support-access audit; restore-time objective measured without claiming a contractual SLA. | Not established |
| Pilot demand | Pilot 0: at least five genuine invitees and three recurring weekly users for four weeks; later paid pilot: one informed paid subscriber; no unresolved critical isolation/data-loss defect. | No pilot evidence recorded here |
| Growth toward 100 | Measured paid/free/warm mix, approximately 20 active plus bursts/multi-device wake, safe commitments and $300/month gross target before credits. No hidden concurrency entitlement limit. | Not established; expand only as demand justifies |

The [design validation matrix](../design/HOSTED_MVP_DESIGN.md#required-validation-matrix)
owns detailed happy-path, invalid-combination, idempotency, rollback, schema,
backup/restore, query-budget and UI cases. Apply it across the gates instead of
creating a second conflicting checklist. Host size, quota/backup tool and mail
selection require proofs; do not infer them from illustrative cloud prices.

## How to record future results

For each gate, link a dated report with tested identity/workload and safe artifact
hashes, actual observed output, failures and scope limitations. Preserve failed
captures; new code/configuration needs new proof rather than relabeling old runs.
Keep secrets and real customer data outside reports. Do not automatically mark
backlog completion from this register; owning implementation/feature acceptance
and authorization remain separate.

Before Pilot 0 invitations, complete its runtime, identity, Admin-lite/UI, storage
and recovery gates. Before charging, additionally complete paid automation, billing,
benefit application and protection gates. Launch only
benefits that can be delivered. Growth gates can follow measured demand; they
are not a reason to pre-provision for 100 operators.
