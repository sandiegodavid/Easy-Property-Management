# Fresh hosted MVP acceptance register

Updated November 13, 2026. **Design accepted; fresh-MVP implementation and deployment
acceptance not established.** This register follows the
[Hosted MVP design](../design/HOSTED_MVP_DESIGN.md), not the older demo checkpoint.
HOSTED-001 schedules implementation; H01 preparation evidence does not establish
fresh runtime, cloud resources or deployment acceptance.

## Evidence baseline

The current `hosted_mvp` checkout has local application/hosted-access foundations
and older deployment tooling. Prior A/B process/loop-image, Cloudflare Access and
manual recovery tests apply to their named releases only. They do not establish
this design's Docker isolation, central login/subdomains, subscription lifecycle,
unattended incremental recovery or automated provisioning/upgrades.

H01 establishes no fresh-target runtime/native/cloud/end-user proof. Record new proof below
only with exact code/image/schema, host/storage/runtime, provider configuration,
dataset/workload, time, actual results and remaining limits. Separate component,
native and deployed/end-user checks. A skipped test is not a passing gate.

H01.1's [implementation baseline and ownership inventory](reports/HOSTED_MVP_H01_1_BASELINE_2026-11-10.md)
pins the clean implementation-start checkout, source hashes and H02–H05 delivery
owners. Its 42 passing existing hosted-access regressions establish only that focused
old-composition baseline; it establishes no fresh-target release gate.

H01.2's [schema-resource evidence](reports/HOSTED_MVP_H01_2_RESOURCES_2026-11-10.md)
establishes independent unavailable scaffolds and initialization/packaging contracts,
not owning tables or fresh-store readiness.

H01.3's [shared contract evidence](reports/HOSTED_MVP_H01_3_CONTRACTS_2026-11-10.md)
establishes bounded intent/outcome/read envelopes and deterministic hash/replay
comparisons only. H01.1–H01.3 are delivered. No durable effect deduplication, identity authorization or usable
hosted workflow is established by these unit contracts.

## Stage-specific release gates

| Stage | Required evidence | Status |
| --- | --- | --- |
| H01–H05 preparation | Private container/storage and identity proofs; Admin-lite safe provisioning/claim/retry; Free 50 MB admission/usage; nightly verified off-host database/files and control recovery; rehearsed restore; warm-container capacity for the admitted population (initial proof target: five). | H02 infrastructure subset delivered; H03–H05 and final artifact acceptance not established |
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
| Runtime isolation and persistence | Private Docker instances, one SQLite writer, correct persistent mounts, non-root/runtime and host-agent boundary; restart preserves data and quota ownership. | H02 synthetic infrastructure subset delivered; final application/identity/drain integration and artifacts remain open |
| Gateway and identity | Registered flat subdomains, unknown-host denial, central Google/email callback, secure one-use handoff, host-only sessions and MFA-protected separate Admin. | H02 closed gateway/denial subset delivered; H03 identity/positive routing not established |
| Small-host capacity/cost | Empty/representative data, background jobs, paid warm residency and Free wake measured; gross launch budget $250/month before credits, no unsupported admission. | H02 two/five/six synthetic warm candidate measured; real admission, recovery jobs, cost and later paid/wake acceptance not established |
| Admin onboarding | Add operator admits one durable job; readiness/verified backup precedes invitation; exact identity claim activates automatically; failures stay safely pending. | Not established |
| Free recovery | Consistent database/file capture, nightly/seven-point policy, unattended keys, degraded-status alerts and successful operator-authorized separate-destination restore without Admin approval; preview/recent-auth, safe fencing/validation, scoped status and optional manual executor attribution. | Not established |
| Control recovery | Off-host registry/ownership/configuration/release/billing references and recoverable keys; recovery works without hosted Admin and cannot revive sessions/stale grants. | Not established |
| Per-tier physical storage sizing | [Measured peaks and justified margins](../design/mvp/subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance) for each 50 MB/200 MB/1 GB logical tier, per-tree actual byte/inode ceilings, independent real-limit exhaustion/rollback/retry/UI proofs and separate backup/restore reservations. Free must qualify before Pilot 0; paid tiers before activation. | Not established for any tier; existing 256-MiB/8,192-inode constants are synthetic trial inputs, not derived production sizing |
| Metering/enforcement | Reproducible logical allowance, protected physical byte/inode limits, bounded reserves, quota/commit failure handling and safe over-allowance reads/cleanup. | Not established |
| Paid recovery | Actual completed off-host-point age meets recent 15-minute objective; fine-grained 24 hours then daily 30/90-day history, valid incremental chains and measured retained bytes/traffic. | Not established |
| Billing/application | Confirmed payment before verified application; duplicate/out-of-order events and interrupted effects reconcile; scheduled downgrade/cancellation, renewal grace and compensation preserve data. | Not established |
| Admin/operator UI | Independent async usage/plan/protection/progress, desired versus Applied, stale/unknown behavior, upgrade controls, keyboard/themes/narrow layouts and retained forms. | Not established |
| Idle/multi-device behavior | Activity across devices, no polling-induced residency, independent backup jobs, deduplicated wake, stale-edit/takeover handling and no automatic command replay. | Not established |
| Independent releases | Immutable approved canary/batches, operator schedule/default/time zone, activity/drain, schema checks, compatibility and recovery without erasing post-reopen writes. | Not established |
| Operational handover | Executable installation/runbooks, scoped credentials, alerts/mail, incidents, deliberate retirement and support-access audit; restore-time objective measured without claiming a contractual SLA. | Not established |
| Pilot demand | Pilot 0: at least five genuine invitees and three recurring weekly users for four weeks; later paid pilot: one informed paid subscriber; no unresolved critical isolation/data-loss defect. | No pilot evidence recorded here |
| Growth toward 100 | Measured paid/free/warm mix, approximately 20 active plus bursts/multi-device wake, safe commitments and $300/month gross target before credits. No hidden concurrency entitlement limit. | Not established; expand only as demand justifies |

The [design validation matrix](../design/mvp/validation.md#required-validation-matrix)
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

## H01.4 contract evidence

[Owning ports and compatibility fixtures](reports/HOSTED_MVP_H01_4_PORTS_2026-11-10.md)
cover Pilot 0 actions, separate recovery authority, registered host IDs and exact
manifest/schema/qualification comparisons. H01.1–H01.4 contract work is delivered;
every fresh-target release gate remains open. Contract fixtures are not native,
provider, persistence, private-transport authentication or end-user qualification.

## H01.5 proof specification handoff

[Six reproducible proof plans](specifications/README.md), their 67-case manifests,
[report format](specifications/REPORT_FORMAT.md) and
[packaging handoff](specifications/PACKAGING_HANDOFF.md) assign exact setup/workload/
negative-control/cleanup and input/evidence requirements to H02–H06. The
[H01.5 implementation evidence](reports/HOSTED_MVP_H01_5_PROOFS_2026-11-11.md) records
only focused document-contract/tooling tests. No proof executor, VM/provider/cloud
run, installed hosted artifact or usable UI is qualified. H01.1–H01.5 preparation work is delivered;
all stage-specific release gates remain open.

## H01.6 UI/API fixture handoff

[Strict synthetic state fixtures](fixtures/README.md) cover Admin list/add/detail
and Operator Settings/recovery, with [22 action mappings](fixtures/ACTION_MAP.md)
to owning commands/reads, authority, confirmation and H03/H04/H05 UI delivery.
[H01.6 evidence](reports/HOSTED_MVP_H01_6_UI_CONTRACTS_2026-11-11.md) records only
focused contract tests. No screen, browser acceptance, current grant, real read/query
budget or end-to-end workflow is established. H01.1–H01.6 preparation is delivered;
every fresh-target release gate remains open.

## H01.7 consolidated preparation handoff

[H01.7 validation and H02 handoff](reports/HOSTED_MVP_H01_7_HANDOFF_2026-11-11.md)
records **423 focused tests passed**, Ruff check/format check on all **35 H01 Python
files**, current schema ownership/documentation checks and unchanged historical
inputs. [Exact commands and tested source pins](reports/HOSTED_MVP_H01_7_VALIDATION_2026-11-11.json)
identify the local contract scope and two lifecycle-alignment source changes.
H01.1–H01.7 implementation preparation is delivered and ready for review; acceptance
of that implementation contract review is not asserted by this task. The
[H02 design decisions](../design/HOSTED_MVP_H02_DESIGN.md#resolved-design-decisions)
are now accepted; subsequent scoped H02 implementation evidence is recorded below.
Every stage-specific release gate above remains **Not established** by H01 preparation. No admission, restore, quota, billing or UI control
is enabled by H01 results.

## H02 acceptance boundary

H02's infrastructure subset requires current-source native/Linux-Docker/GCP proof,
private resource/UID/quota isolation, guarded restart and durable external ingress
denial. Its candidate images are not qualified hosted releases while H03–H05 schemas,
assets or behavior remain unavailable. Keep the complete image/all-store report
unavailable/not_run where applicable and repeat it on final owning-slice artifacts
before H06. No candidate-only result populates a fake qualified release or permits
customer admission. Scoped runtime/cloud evidence is recorded below; the design
alone establishes no acceptance. See the [topic-based foundation guides](../foundation/README.md).

## H02 consolidated infrastructure acceptance

The container/storage/gateway foundation is delivered within the accepted
infrastructure subset. [Qualification and handoff](../foundation/qualification-and-handoff.md)
consolidates **985 focused Python passes**, **four hosted-status browser passes**,
Ruff checks on **113 infrastructure Python files**, current-source native sandbox/
connected/ABI proofs and final closed-host verification. Exact sources/commands
remain in the [recorded validation manifest](reports/HOSTED_MVP_H02_11_VALIDATION.json).
The qualification VM/data disk are stopped and retained. No positive business
ingress, release grant or provider setting changed during consolidation.

| Topic | Current reference | Acceptance boundary |
| --- | --- | --- |
| Packaging and launch | [Guide](../foundation/packaging-and-launch.md) | Separate candidates and safe unavailable launch; final complete artifacts and application assets remain open. |
| Inventory and commands | [Guide](../foundation/inventory-and-host-commands.md) | Available Admin/inventory baselines, immutable effects/receipts and fences; authenticated owning workflows remain open. |
| Runtime and capacity | [Guide](../foundation/runtime-and-capacity.md) | Private writer/quota/sandbox and measured two/five/six candidate population; no durable admission or recovery authority. |
| Networking and access | [Guide](../foundation/networking-and-access.md) | Closed gateway/egress/service/secret boundary; positive identity access remains open. |
| Development and host operation | [Guide](../foundation/development-and-host-operations.md) | Isolated procedures and exact retained GCP setup/reboot; completed one-time reset is not ordinary setup. |
| Qualification and handoff | [Guide](../foundation/qualification-and-handoff.md) | Current scoped checks; older reboot/capacity/network records retain their original pins. |

The [runtime subset report](reports/HOSTED_MVP_H02_11_RUNTIME_SUBSET.json) covers every
specification case with explicit passed/not-run/unavailable results. Its overall
status remains **unavailable**, including H04's real concurrent admission. The
[final image/all-store report](reports/HOSTED_MVP_H02_11_IMAGE_ALL_STORES.json) is
**unavailable** until later owning baselines/assets exist. Both pass strict v1
format/coverage validation; valid evidence format does not grant release authority.
This is the intended D1/D2 scope boundary, not a silently omitted or passed gate.

H03 must deliver identity/access/assets; H04 real serialized admission/logical usage
and Admin/operator workflows; H05 recovery-owned resources/keys/restore. Then rebuild
and qualify final installed artifacts/all six stores before promotion and H06
invitations. Stage-specific release acceptance above remains **Not established**.
The handoff records exact owner inputs, commands, retained failures and runbooks.
