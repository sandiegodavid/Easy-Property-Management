# Delivery plan and Pilot 0

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/README.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

In this guide: [Suggested delivery and acceptance order](#suggested-delivery-and-acceptance-order) · [Pilot 0 — capacity-qualified Free operators](#pilot-0--capacity-qualified-free-operators) · [Implementation slices](#implementation-slices) · [Where the hosted Operator portal is delivered](#where-the-hosted-operator-portal-is-delivered) · [H03 design and implementation order](#h03-design-and-implementation-order) · [Infrastructure topic guides](../../foundation/README.md)

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

Complete a detailed design for each slice before starting its implementation, covering schema, UI, infrastructure/setup and validation as applicable. H01 has a detailed design; [H02 has an accepted detailed design](../HOSTED_MVP_H02_DESIGN.md) and a [delivered scoped infrastructure handoff](../../qualification/reports/HOSTED_MVP_H02_11_HANDOFF.md); final artifact/release and H03–H05 workflow qualification remain open. [H03 has an accepted detailed design and ordered plan](../HOSTED_MVP_H03_DESIGN.md); D1–D16 are resolved, with implementation and qualification still pending. H04–H12 still require their own designs. Implement sequentially as cohesive backend/UI/operations changes. Each row depends on
its predecessor unless explicitly stated; no row is marked implemented here. Start with
current-checkout evidence, not implementation claims or schema resources from another
branch. Pilot 0 releases at H06; H07–H12 must not delay that learning milestone.

| Slice | Delivery and implementation boundary | Acceptance before proceeding |
| --- | --- | --- |
| H01 | [Baseline, schema and deployment contracts](../HOSTED_MVP_H01_DESIGN.md). Inventory `application/apps/server/app/modules/hosted_access`, `application/deploy/hosted-demo`, workspace backup services and existing hosted browser tests. Design the store ownership map and complete Pilot 0 schema for the Admin registry, protected inventory, effective hosted-access authority, separate Admin recovery and per-operator recovery stores, reusing business schema ownership. Define typed host-agent commands. Document tables/columns, constraints, indexes and initialization ownership; defer paid/automation-only tables to their owning slices. Record proof choices for quotas, backups, keys, mail and image packaging. | Review the Pilot 0 ER/relationship diagram, store/data dictionary and schema-resource plan; document reuse/gaps, resource ownership, exact capacity/accounting definitions and reproducible component-proof commands. No live deployment required to begin. Reject generic shell/path selection and public Docker access. |
| H02 | [Container, storage and gateway foundation](../HOSTED_MVP_H02_DESIGN.md), documented in the [topic-based foundation guides](../../foundation/README.md). Dedicated container/storage foundation on GCP with Cloudflare gateway. Package pinned application assets and owning schema resources; validate available fresh initialization/schema identity, persistent private workspace/control/scratch, registered subdomains and restricted host operations. Keep Pilot 0 runtimes warm. Reuse imported ext4 primitives/sandbox/harness through the [reuse contract](implementation-contracts.md#h02-project-quota-reuse-contract). Implement the accepted complete main-Admin structural closure, inventory UID/ingress/receipt records and guarded restart policy; keep candidate builds separate from qualified artifacts. | Fresh source-pinned native Linux, Docker and exact GCP quota/isolation/reboot proofs required; historical 8A pass is input only. Two isolated synthetic operators, persistence across replacement/reboot, external deny/unknown-host denial, one writer, bounded resources and measured warm-container headroom (initial proof target: five). Missing H03–H05 resources/assets remain unavailable; complete all-store/image qualification and promotion before H06. No customer records or open business ingress yet. |
| H03 | [Managed identity and central-login handoff](../HOSTED_MVP_H03_DESIGN.md). Admin MFA/sign-in shell, exact invited-identity claim, host-only source sessions, renewal/device management/logout and multi-device draft fencing, with their usable UI. Own access resources and accepted Admin identity-flow extensions, auth-only/shared-origin routing and scoped private identity/source transport; validate against the H02 baseline and H01 contracts. | Implement accepted D1–D16; qualify Google/email-link and actual Admin MFA, exact browser/origin/workspace binding, single-use/lost-response handoff, bounded provider revocation/outage and multi-device input preservation. H04 readiness/usage and H05 protection remain unavailable, never bypassed to demonstrate login. Local launch still works without cloud login. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H04 | Admin-lite and Free usage. Add/list/detail operator UI, default empty/optional synthetic portfolio, pinned Free 50 MB allowance, operation identities/status and supported manual provisioning completion/retry. Operator Settings shows Free pilot, usage/freshness and support; hide unavailable upgrades. Own Admin-lite provisioning/status and operation behavior on the H02-created Admin baseline, plus source Free usage/allocation resource delivery. | Pending → Ready/claim → Active only after source checks; no business access during setup/failure. Retried/unknown results do not duplicate resources. Safe growth rejection, retained reads/export/cleanup and physical headroom. Qualify the 50,000,000-byte tier with measured per-tree byte/inode peaks, justified margins and independent exhaustion/rollback/UI checks under the [sizing gate](subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance); arbitrary trial constants do not satisfy it. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H05 | Nightly verified off-host recovery. Consistent SQLite/files capture, encrypted key custody/catalog, seven nightly points, stale-backup alerts, separate Admin recovery DB/schema with its own backup checkpoints/operations/audit and main-Admin-DB-independent authentication, plus internal operator-authorized restore, recovery-mode UI with strong step-up and no offline workspace restore/decrypt command. Keep catalog/checkpoints/restore operations in private recovery storage outside business data; Admin observes async summaries, without approval or routine dispatch. Include recent-auth preview/confirmation, safe locator switch and interruption handling. Own recovery-point/manifest/catalog and restore-operation schema delivery. | Rehearsed data/files and host-loss/control restore including damaged main Admin DB, damaged Admin recovery DB and retained restore evidence; reject cross-store FKs/old-session authority and corrupt/missing objects, new fences/session revocation, retained pre-restore state, cross-operator denial, duplicate/conflicting restore handling and verified operator authorization; Admin outage independence, corrupt business-DB startup, crash mid-switch and denial when identity/runtime cannot be established; clean-runtime repair preserves IDs/data and requires operator-authorized restore into separate staging, never empty reinitialization. Measure backup/retention and restore-staging byte/inode peaks and justified physical reserves separately from logical allowance under the [sizing gate](subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance). Security review/negative tests gate restore availability. Verified point/commit coverage drives health, not job start time; proven unchanged state is shown separately from an unknown/stale source. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H06 | Pilot 0 release and operations. Admit genuine invited Free operators within qualified capacity; five is the initial test target, not a cap. One announced maintenance window, supported manual provisioning/recovery/exception handling, named support owner and cost/time worksheet. | H01–H05 proofs retained, including qualified Free physical sizing and backup/restore reservations; before-credit spend and Admin time observable; backup alerts and restore runbook usable. No Stripe, paid plan controls, individual update scheduling or idle/wake automation. Observe four-week recurring-use evidence before deciding to expand investment. |
| H07 | Automated provisioning and control reconciliation. Durable jobs/reservations, typed restricted agent, verified source receipts, deduplicated invites and automatic claim/readiness activation; Admin retry/reconciliation UI. Own durable job/claim, reservation, effect-receipt and reconciliation schema additions. | Interrupted effects, duplicate clicks, stale workers and later disable preserve ownership and one outcome. No second manual Admin completion required on normal onboarding; no network/host operation under a DB writer lock. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H08 | Full tier enforcement and paid recovery readiness. 50 MB/200 MB/1 GB logical usage, application reservations plus qualified kernel ceilings, downgrade overage handling, paid recovery cadence/retention, both-portal usage/health views. Use test entitlements until billing qualifies. Own tier-policy/allocation, usage/reservation, overage and paid-retention schema additions. | Independently qualify 200,000,000-byte and 1,000,000,000-byte physical profiles under the [per-tier sizing criteria](subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance): measured allocated-byte/inode peaks, justified margins, real-limit exhaustion/rollback and paid recovery-reserve checks. Reconcile metering/physical attribution; safe commit rollback and retained over-quota data; reserved operational headroom; verified 15-minute recent-point objective, 24-hour fine-grained and 30/90-day daily history. Do not sell unproven protection. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H09 | Stripe operator subscriptions and Settings change/cancel UI. Checkout, verified inbox/provider reconciliation, desired/effective plan, prorated upgrades/capacity, compensation, scheduled downgrade/cancel and renewal grace. Own provider inbox, subscription projection, effective-entitlement and compensation-operation schema additions. | Sandbox duplicate/out-of-order events, lost browser return, delayed/failed payment, unapplied paid benefits and grace end all reconcile safely. No initial paid benefits without confirmed payment. Real charging requires explicit release approval and published qualified prices. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H10 | Independent Admin and per-operator release operations; define future Tenant/Owner release contracts. Admin qualified release/canary/bounded rollout, operator suggested window/time zone/deferral and notices, drain across devices, compatible image/schema checks, safe pre-upgrade recovery. Own release compatibility, update preference/schedule and rollout-operation schema additions. | Qualify old/new component and API/schema combinations; one component update leaves other compatible assignments unchanged. Failed canary halts its rollout; unfinished input survives; admitted work drains; no second writer; automatic data rollback only before post-reopen writes. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H11 | Free idle suspension/wake. All-device human activity, owned-work gates, gateway deduplicated wake, safe waking/error UI and independent due-work scheduling. Own runtime desired/observed state, wake-operation and bounded activity-state schema additions where durable state is required. | Polling never keeps a workspace alive; no suspended admitted work; wake/reboot storms bounded; no automatic write replay. Measure cold/warm latency; paid stays warm initially. Pass the [schema acceptance contract](implementation-contracts.md#schema-ownership-and-acceptance-contract). |
| H12 | Paid pilot and capacity qualification. Real-use/operator support evidence, complete monitoring/runbooks, measured admission/spending envelopes and staged growth toward 100. | Approve real charges separately; verify at least five genuine invitees/three weekly users for four weeks and at least one informed paid subscriber. Test approximately 20 active of 100 plus bursts, warm mix, restore and costs; revalidate tier profiles/reserves for the admitted workload/population and do not claim unmeasured capacity. |

## Where the hosted Operator portal is delivered

Reuse the existing Operator frontend and business modules; do not build a second
portal. H02 supplies packaged candidates and isolated runtime/storage. H03 adds
hosted authentication, sessions, device management and draft fencing. H04 owns
composing that frontend and the existing business APIs with the provisioned workspace,
current source authority, qualified Free storage admission and Settings usage/status.
Its acceptance must exercise ordinary portfolio, money, maintenance and unfinished-form
workflows through the hosted composition, including two devices. H05 adds qualified
backup/recovery and completes protection prerequisites; H06 releases the portal to
real operators. H04's integration tests cannot substitute fixtures for missing H05
protection in a real deployment.

## H03 design and implementation order

<a id="h03-implementation-sequence"></a>

Use the [H03 detailed design](../HOSTED_MVP_H03_DESIGN.md) for current-code assessment,
workflows, accepted schema extensions, API/UI/private transport, setup and validation. Its
[twelve ordered work units](../HOSTED_MVP_H03_DESIGN.md#ordered-implementation-plan)
are the authoritative H03 implementation sequence: accepted contract/setup pins → owning
schemas → provider verification → Admin MFA/UI → invitations/flow receipts → protected
routing/relay → handoff/source issuance → current authority/renewal → device/security
UI → draft/local integration → candidate packaging → provider/browser qualification.

The plan includes dependency-aware identity cleanup, atomic active/expired renewal
admission under the session cap, and a concrete central-continuation/destination
round trip for cross-device email completion. These refine H03.2 and H03.5–H03.10;
they add no separate backlog or change H04/H05 activation gates.

[D1–D16](../HOSTED_MVP_H03_DESIGN.md#resolved-design-decisions) were accepted November
13, 2026. The sequence implements those decisions; provider/browser/native proof and
H04/H05 readiness remain independent gates. H03 is not implemented by this plan;
no backlog scope or live admission is changed.

## Infrastructure references

The [foundation design](../HOSTED_MVP_H02_DESIGN.md) owns accepted boundaries;
[topic guides](../../foundation/README.md) own implementation and operating navigation.
