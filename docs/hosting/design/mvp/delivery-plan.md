# Delivery plan and Pilot 0

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/overview.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

In this guide: [Suggested delivery and acceptance order](#suggested-delivery-and-acceptance-order) · [Pilot 0 — capacity-qualified Free operators](#pilot-0--capacity-qualified-free-operators) · [Implementation slices](#implementation-slices) · [Live Architecture](../../ARCHITECTURE.md) · [Operations Handbook](../../operations/README.md)

## Suggested delivery and acceptance order

<a id="11-suggested-delivery-and-acceptance-order"></a>

This sequence is scheduled as HOSTED-001 in the [backlog](../../../FEATURE_BACKLOG.md). Start H01 below; Pilot 0 is the first usable release milestone. Tenant and owner portals follow in PORTAL-001/002, outside hosting acceptance.

1. Prove container/private storage isolation, persistent SQLite, gateway/subdomain
   routing and identity handoff; measure the small-host workload and gross cost.
2. Prepare Admin-lite creation/invitations, Free nightly recovery, basic Settings
   usage and a full operator/control-plane restore rehearsal. Bounded manual operations
   may support this stage; complete automatic provisioning remains a subsequent target.
3. Run **Pilot 0: invited operators within qualified capacity, Free plans only**, under the operating
   rules and acceptance gates below. Observe real use and operational cost before
   investing in subscriptions and wider automation.
4. Complete automated provisioning and verified quota enforcement, paid recent
   recovery and retention, billing inbox/reconciliation, self-service plan changes,
   compensation and failure states. Do not charge for a benefit before it can
   actually be delivered and verified.
5. Deliver independent update scheduling, canary rollout, schema-safe recovery,
   idle suspension/wake, operator notices and representative multi-device acceptance.
6. Run the paid pilot, validate repeat use/payment/support effort, then expand
   admission toward measured 100-operator capacity within the spending envelope.

### Pilot 0 — capacity-qualified Free operators

Pilot 0 is an invitation-only learning stage. Five operators are an initial qualification
target, not a hard-coded cap; Admin may add more dynamically within verified capacity. It uses
the Free 50 MB workspace allowance, nightly verified off-host backups and seven
nightly recovery points. No paid enrollment, Stripe integration, checkout or billing
credentials are needed. Show **Free pilot**, usage and support/recovery information
in Settings; do not expose paid upgrade controls as available.

Admission is capacity-based, not an operator-count constant. Admin-lite Add operator
requires a [qualified Free storage profile](subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance) before invitations, then
checks current warm-runtime memory/CPU/IO headroom, physical byte/inode commitments,
backup retention and restore staging capacity, support effort and the approved spend
envelope. Count active, pending and unknown provisioning commitments; retained disabled
data still consumes disk/backup capacity. Persist the reviewed capacity-profile/evidence
reference and admitted resource commitment in the provisioning operation's typed request.
Serialize admission in the control transaction so concurrent Add actions cannot spend
the same headroom. Unknown effects retain their commitments until reconciled.

Admin may invite another operator without a code/configuration change to a hard-coded
cohort size when that admission fits the current qualified profile. If measurements no
longer cover the proposed population or protection/support is degraded, show Capacity
review required, keep the request pending and qualify additional capacity first. No
silent overcommit, automatic VM purchase or broader H07 scheduler is required: Pilot 0
may use a supported manual capacity review with recorded evidence. Extra operators
remain Free, warm and in the same announced maintenance window. Five real invitees
remain the minimum adoption-evidence target, not an admission ceiling; do not wait for
paid automation or completion of the four-week demand review merely to add an operator
that already fits qualified capacity.

| Area | Pilot 0 delivery |
| --- | --- |
| Admin-lite provisioning | Admin records the verified operator assignment, slug, Free allowance and operation status, then runs a supported provisioning action/script. Show Pending/Ready/Needs attention and safe retry status. Manual completion is acceptable; no generic shell or Docker socket in the public Admin process. Retain original operation/resource identities so a retry cannot duplicate a workspace or enable an uncertain result. |
| Onboarding and isolation | Keep dedicated containers/private SQLite/files, managed identity, registered-origin routing and host-only sessions. Business access stays disabled through preparation/seeding and readiness checks. Admin may manually verify readiness; the invited verified identity must still claim the correct assignment. |
| Backups and recovery | The operator service runs nightly consistent database-and-file capture with verified off-host manifests/checkpoints and external protection alerts. Rehearse operator and control-plane restore, including recovery without the failed host, before admitting real records. Operator chooses/authorizes workspace recovery; the internal engine executes it, through authenticated recovery mode with no offline operator restore/decrypt command and no separate approval; retain the source, validate the restored destination and fence the old writer before reopening. |
| Releases | Use one announced maintenance window for the whole cohort. Notify all admitted operators, preserve unfinished input, drain admitted work across devices, capture a verified pre-update recovery point and apply a pinned compatible release. No per-operator window preferences or scheduling automation. Preserve post-reopen writes; a maintenance window does not make destructive rollback safe. |
| Runtime | Keep all admitted containers running within qualified host capacity. No idle suspension or wake automation; polling and concurrent devices do not trigger lifecycle changes. Monitor health and use documented restart handling. |
| Manual operations | Provisioning completion, exceptions, recovery and maintenance may be handled manually through restricted supported tools. Record who acted, result/unknown state, elapsed time and follow-up; manual handling does not bypass identity, isolation, source fences, safe retries or backup verification. |
| Storage and cost | Show measured usage/freshness and enforce bounded storage admission through qualified limits or conservative supported write gates. Monitor physical headroom and alert before exhaustion; do not rely only on a scan after a write. Record gross cloud spend before credits, retained backup bytes/traffic, support incidents and Admin minutes per operator/task. Full automated tier changes and quota reconciliation follow in step 4. |

Pilot admission requires the isolation/identity proofs from step 1, a successful
nightly backup and rehearsed restore, supported safe provisioning/retry, sufficient
capacity for the admitted continuously running container population, and a named operational owner.
Manual work must be visible and repeatable through a short runbook, not unrecorded
changes to authority or resource ownership.

Review activation, weekly repeat use, backup freshness, restore results, user friction,
Admin time and before-credit spend with this cohort. Use the four-week repeat-use
measurement above; payment conversion is evaluated only in the later paid pilot.
Proceed to step 4 when observed demand and operating effort justify the investment;
otherwise revise or stop admissions. No paid feature or 100-operator capacity claim
follows from Pilot 0 alone.

### Implementation slices

**Slices `H01–H06` (Pilot 0) are complete and LIVE / GO** (6/6 live GCP launch-day gates passed 2026-11-24; see [Live Architecture](../../ARCHITECTURE.md), [Operations Handbook](../../operations/README.md), and [H06.10 Exit Review](../../qualification/reports/HOSTED_MVP_H06_10_EXIT_REVIEW.md)). Slices **`H07–H12`** remain planned and are gated on the 4-week Pilot 0 repeat-use evaluation; complete a detailed design for each slice before implementation.

| Slice | Status | Delivery and implementation boundary | Acceptance before proceeding |
| --- | --- | --- | --- |
| H01–H06 | **Done (Pilot 0 LIVE / GO)** | Baseline contracts, Docker/ext4 `prjquota`/Caddy/guardian host foundation, managed identity (`admin.epmdemo.xyz` + `login.epmdemo.xyz`, Google + TOTP MFA, `100/day` & `90/24h` mail ceiling), Admin-lite & Free 50 MB admission, encrypted Cloudflare R2 + Cloud KMS off-host recovery (`SO_PEERCRED` `epm-backup-proxy`), nightly schedulers, async summary relay, shared maintenance notice, GCP observability & `$250/mo` budget, and 6/6 live GCP launch-day gates. | Complete 4-week Pilot 0 repeat-use evaluation (`>= 5` genuine invitees, `>= 3` weekly recurring users for 4 consecutive weeks, 0 unresolved critical isolation/data-loss defects, verified nightly backup + live restore drill, gross spend `<= $250/mo` before credits) before expanding into H07+. |
| H07 | Planned | Automated provisioning and control reconciliation, plus programmatic transactional mail. Durable jobs/reservations, typed restricted agent, verified source receipts, deduplicated invites and automatic claim/readiness activation; Admin retry/reconciliation UI. Own durable job/claim, reservation, effect-receipt and reconciliation schema additions. | Interrupted effects, duplicate clicks, stale workers and later disable preserve ownership and one outcome. No second manual Admin completion required on normal onboarding; no network/host operation under a DB writer lock. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H08 | Planned | Full tier enforcement and paid recovery readiness. 50 MB/200 MB/1 GB logical usage, application reservations plus qualified kernel ceilings, downgrade overage handling, paid recovery cadence/retention, both-portal usage/health views. Use test entitlements until billing qualifies. Own tier-policy/allocation, usage/reservation, overage and paid-retention schema additions. | Independently qualify 200,000,000-byte and 1,000,000,000-byte physical profiles under the [per-tier sizing criteria](subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance): measured allocated-byte/inode peaks, justified margins, real-limit exhaustion/rollback and paid recovery-reserve checks. Reconcile metering/physical attribution; safe commit rollback and retained over-quota data; reserved operational headroom; verified 15-minute recent-point objective, 24-hour fine-grained and 30/90-day daily history. Do not sell unproven protection. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H09 | Planned | Stripe operator subscriptions and Settings change/cancel UI. Checkout, verified inbox/provider reconciliation, desired/effective plan, prorated upgrades/capacity, compensation, scheduled downgrade/cancel and renewal grace. Own provider inbox, subscription projection, effective-entitlement and compensation-operation schema additions. | Sandbox duplicate/out-of-order events, lost browser return, delayed/failed payment, unapplied paid benefits and grace end all reconcile safely. No initial paid benefits without confirmed payment. Real charging requires explicit release approval and published qualified prices. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H10 | Planned | Independent Admin and per-operator release operations; define future Tenant/Owner release contracts. Admin qualified release/canary/bounded rollout, operator suggested window/time zone/deferral and notices, drain across devices, compatible image/schema checks, safe pre-upgrade recovery. Own release compatibility, update preference/schedule and rollout-operation schema additions. | Qualify old/new component and API/schema combinations; one component update leaves other compatible assignments unchanged. Failed canary halts its rollout; unfinished input survives; admitted work drains; no second writer; automatic data rollback only before post-reopen writes. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H11 | Planned | Free idle suspension/wake. All-device human activity, owned-work gates, gateway deduplicated wake, safe waking/error UI and independent due-work scheduling. Own runtime desired/observed state, wake-operation and bounded activity-state schema additions where durable state is required. | Polling never keeps a workspace alive; no suspended admitted work; wake/reboot storms bounded; no automatic write replay. Measure cold/warm latency; paid stays warm initially. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H12 | Planned | Paid pilot and capacity qualification (including Google OAuth Production verification). Real-use/operator support evidence, complete monitoring/runbooks, measured admission/spending envelopes and staged growth toward 100. | Approve real charges separately; verify at least five genuine invitees/three weekly users for four weeks and at least one informed paid subscriber. Test approximately 20 active of 100 plus bursts, warm mix, restore and costs; revalidate tier profiles/reserves for the admitted workload/population and do not claim unmeasured capacity. |
