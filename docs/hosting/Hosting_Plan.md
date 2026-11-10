# Hosting plan: local product and fresh hosted MVP

Updated November 10, 2026. The confirmed
[Hosted MVP design](design/HOSTED_MVP_DESIGN.md) owns the current hosting direction,
workflows and acceptance requirements. This overview aligns the documentation;
it does not implement or deploy the design, change backlog scope, or mark an item
delivered. The [previous plan](archive/2026-11-10-pre-mvp-alignment/Hosting_Plan.md)
is preserved as superseded context.

## Product and delivery scope

| Offering | Current direction |
| --- | --- |
| Local | Optional free single-operator launch using the shared business core; no hosted login/subscription enforcement or local/cloud synchronization. |
| Fresh hosted MVP | Invited operators with isolated Docker containers, persistent SQLite/files and individual public subdomains; multiple devices have full permission within one workspace. |
| Earlier synthetic demo | Dated process/Unix-user/loop-image deployment and tests. Retained as historical evidence, not the new deployment template or current capacity proof. |

Support US customers/properties without an additional data-residency restriction.
One operator identity maps to one workspace/subscription. Admin chooses how many
operators to admit within measured capacity; there is no two-operator requirement
or fixed rentable-space allowance. Empty workspace is the default. Synthetic seed
contents, if used, are optional per operator and excluded from adoption metrics.

Hosting scope includes Admin UI, invitations and automatic onboarding, identity,
subscription billing, storage metering/enforcement, backups/recovery, monitoring,
idle wake and independent release management. **Imports are outside this task and
will be available to all tiers when implemented. Tenant/owner portals and property
payments follow hosting through PORTAL-001/002 and PAY-001/002.** Neither feature may be advertised as available merely because its
future entitlement is decided. Their updated scope and dependencies are recorded in the backlog.

## First release: Pilot 0

[HOSTED-001 H01–H12](design/HOSTED_MVP_DESIGN.md#implementation-slices) is now the immediate implementation plan. H06 releases Pilot 0 to invited Free operators within qualified capacity with Admin-lite provisioning, Free 50 MB usage safeguards, nightly verified off-host backups and rehearsed restore. Keep all containers running and use one announced maintenance window. No Stripe, paid enrollment, idle-wake or per-operator update scheduling. Manual completion/recovery/exception handling uses supported tools and records ownership, outcomes, Admin time and before-credit spend.

The full platform and catalog below describe subsequent H07–H12 targets. Pilot 0 must satisfy isolation, identity, safe retries, storage and recovery gates, but does not wait for those later automations. PORTAL-001/002 follow hosting and include rent/late fees/terms/payments, tenant issues and owner concerns/reports with shared source ownership.

## Platform baseline

Start on Google Compute Engine with persistent block storage, Docker Engine,
Artifact Registry and a restricted host agent. Keep one authoritative SQLite
writer per operator and data outside container writable layers. Use a shared
Cloudflare edge/Tunnel/gateway, exact registered-host routing and flat operator
subdomains. A container restart is not host/data high availability.

Use managed Google/email-link authentication with a fixed central login callback,
host-only operator cookies and separately MFA-protected Admin access. Stripe owns
billing facts; EPM owns assignment and verified effective entitlements. Cloudflare
Access is optional for the small Admin audience, not required for customer seats.
Do not expose the Docker socket to either public portal or operator containers.

The Admin DB owns metadata/desired state, protected inventory owns allocations,
and each source owns business/access state. Runtime configuration is a generated
projection. Durable jobs, revisions, fences and receipts reconcile effects rather
than claiming transactions span databases, Docker and cloud providers.

Kubernetes is deferred initially. Reconsider it when multi-host scheduling and
operating complexity justify it, rather than when an arbitrary account count is
reached. Host sizes, quota enforcement and backup tools require component proofs.

## Plans, recovery and budgets

| Benefit | Free | Paid 1 | Paid 2 |
| --- | --- | --- | --- |
| Provisional monthly price | $0 | $10 | $20 |
| Provisional usable storage | 50 MB | 200 MB | 1 GB |
| Protection | Nightly, seven nightly points | Recent 15-minute recovery-point target; fine-grained 24 hours then daily through 30 days | Same recent target, daily history through 90 days |
| Runtime | May sleep after about 15 minutes without human activity | Warm initially | Warm initially |

Storage covers database usage and retained managed content, not a separate
attachment entitlement. Backups, scratch, hosted control and physical overhead
have separately reserved operating budgets. Measure representative portfolios
before publishing prices/allowances. Recovery targets are engineering objectives,
not unconditional guarantees or a contractual SLA; four-hour recovery requires a
tested procedure available outside the failed host.

Launch budget is **$250/month before credits**; the growth target is **$300/month
before credits at 100 operators**. Google credits are temporary validation funding;
confirm their actual terms/end date. Include compute, disks, backups, auth/email,
networking and monitoring, and track payment-provider fees separately. No unlimited
free admission, unmeasured overcommit or silent budget increase.

At the 100-registered stage, qualify approximately 20 simultaneously active
operators, paid warm residency and bursts/multi-device wake-ups. This is a workload
target, not a permission limit at operator 21. Sleeping containers save memory,
not the cost of an otherwise running VM. Record actual gross unit economics.

## End-to-end operating rules

- Admin creates the assignment and provisioning job; invite only when readiness,
  isolation and an off-host recovery point pass. The matching verified operator
  claims it automatically without another routine Admin approval. Business access
  remains disabled throughout setup and exceptions.
- Upgrades require operator payment authorization and confirmed billing before
  verified application. Scheduled downgrades/cancellation apply at paid-period end;
  existing subscribers get seven-day failed-renewal grace. Retain records when
  over allowance; preserve reading/export and supported cleanup without silently
  deleting data or charging an unapproved old tier.
- Backups are unattended and encrypted with separately protected platform-managed
  keys, using qualified consistent database/file capture and incremental retention.
  Alert on completed off-host-point age, not just job execution. Degraded protection
  remains visible while the workspace stays usable.
- Operator selects and authorizes own-workspace restore with recent authentication
  and confirmation, without Admin approval. Safety gates validate a separate
  destination/switchover; Pilot 0 may use supported manual Admin execution. Restore control-plane mappings and recovery
  capability separately from business archives; never restore usable sessions or
  execute stale pending grants.
- Admin approves immutable qualified releases once. Operators accept a suggested
  inactive window, choose a time or update now; upgrades are independent, drain
  work and preserve acknowledged unfinished forms. Automatic rollback cannot
  erase writes accepted after reopening.
- Disable, subscription cancellation and retirement are different workflows.
  Retirement requires explicit confirmation/export opportunity, scheduled deletion
  and an initial seven-day recovery window; backup expiry is disclosed separately.
- Admin and operator portals show plan/usage, protection, release and operation status through
  bounded async reads. Desired settings, payment confirmation and verified Applied
  state are distinct. Unknown/stale values never become zero or success.

## Validation and demand gates

The [MVP acceptance register](qualification/HOSTED_MVP_ACCEPTANCE.md) tracks the
fresh target. Older demo qualification cannot qualify the new authentication,
Docker, subscription, unattended recovery or quota boundaries.

Pilot success: at least five genuine invitees, at least three doing recurring work weekly
for four consecutive weeks, at least one informed paid subscriber after paid launch, and no unresolved
critical isolation/data-loss defect. Track support effort and gross cost alongside
adoption. Validate interest before credits expire; pivot or redesign based on results.

Follow the [design's delivery and validation sequence](design/HOSTED_MVP_DESIGN.md#11-suggested-delivery-and-acceptance-order).
Code, schema, infrastructure and commercial readiness remain unproven until their
own evidence is recorded. The backlog schedules this work; documentation does not establish completion.
