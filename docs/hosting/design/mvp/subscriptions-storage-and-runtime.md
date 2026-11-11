# Subscriptions, storage and runtime behavior

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/README.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

In this guide: [Subscription and storage workflows](#subscription-and-storage-workflows) · [Upgrades, downgrades and payment failures](#upgrades-downgrades-and-payment-failures) · [What storage means and how it is enforced](#what-storage-means-and-how-it-is-enforced) · [Per-tier sizing acceptance](#per-tier-physical-storage-sizing-acceptance) · [Operator account UI](#operator-account-ui) · [Idle workspaces, sessions and multiple devices](#idle-workspaces-sessions-and-multiple-devices)

## Subscription and storage workflows

<a id="6-subscription-and-storage-workflows"></a>

Use Stripe Checkout/Billing/Customer Portal for monthly USD subscriptions. Defer annual
plans, coupons and custom commercial contracts. Verify signatures and current provider
state; a successful browser return is not payment proof. Show prorated upgrade charges
before acceptance. Prices/tax configuration must be verified before real charging.

### Upgrades, downgrades and payment failures

| Event | Required behavior |
| --- | --- |
| Upgrade | Check/reserve applicable capacity, obtain operator payment authorization, confirm payment, then apply/verify allowance, recovery and warm-runtime policy through one durable operation. Show Applying until effective facts are verified. |
| Upgrade failure | Preserve the last verified effective settings and retry/reconcile the original operation. Conclusively undelivered benefits require provider compensation and notice. Unknown outcomes require reconciliation before blindly refunding or reversing a change. |
| Downgrade | Schedule at next renewal. Warn if usage exceeds the target. At the effective date apply the reduced product entitlement while retaining existing data; use a safe temporary physical ceiling until usage fits. Do not silently keep charging the old plan. |
| Renewal payment failure | Existing paid subscribers receive a seven-day payment grace with provider retries/notices. Then Free restrictions apply without deleting records. A failed first-time upgrade never receives unconfirmed paid benefits. |
| Cancellation | Stop renewal; preserve paid benefits to the paid-period end, then Free rules. Existing backups retain their promised expiry; new points follow Free cadence/retention. Cancellation is not account deletion or logout. |

Reserve capacity before checkout where feasible, but reconcile delayed payment and
reservation expiry; do not overcommit or lose the charge if the browser closes.
Provider status, desired plan, last verified effective entitlement and operation state
are separate facts. Receipt/audit and observed revisions determine Applied, not an
editable plan badge. New policy cannot override a later account disable or maintenance gate.

### What storage means and how it is enforced

Count business database usage and retained managed files using the owning logical
usage definition, without counting shared file content twice. Do not meter attachments
alone or double-count database/WAL representations of the same committed state.
Include retained history/versions; archiving does not free retained bytes. Keep billing
usage reproducible and reconcilable, not a rounded `du -sh` scan after each edit.

Exclude backups, scratch, hosted authentication/control and physical database/allocation
headroom from advertised usable storage, but reserve and monitor them in host budgets.
Use bounded application growth reservations plus qualified filesystem hard byte/inode
limits for private persistent trees. Ext4 project quotas are the preferred candidate
for H02 evaluation based on the [selectively imported qualification work](implementation-contracts.md#h02-project-quota-reuse-contract), subject
to fresh native Docker/GCP proof; historical success is not runtime qualification.
Docker memory/CPU limits do not enforce bind-mounted workspace storage. Do not create
an OS/filesystem/image per operator solely to express a tier. Qualify the chosen host
quota mechanism, attribution, restart/restore and escape prevention before activation.

Protect applied policy with the same trust separation as access. Internal
`access_meta.effective_policy_id`, `usable_bytes` and `policy_revision` are changed
only through authenticated, fenced policy-application commands backed by admitted
control-plane authority and verified results. No portal/public API directly edits
them or accepts a caller-supplied entitlement. A paid subscription request is not
proof that a benefit has been authorized and applied.

The privileged host independently enforces physical byte/inode ceilings. Operator
containers cannot change quotas, project assignments or protected policy configuration;
host operations must not trust their reported tier as authorization to raise limits.
Reconcile local applied state with Admin intent and protected host observations;
unexpected divergence raises an actionable alert and external containment when
compromise is suspected. Retain data during investigation. A compromised process
could bypass local logical admission within its existing physical ceiling, including
reserved headroom: project quotas bound this damage, not guarantee exact logical
entitlement enforcement. Externally controlled paid capabilities must likewise use
trusted entitlement checks, never the local policy ID alone. H02/H04 and later paid
slices must test tampered fields, forged policy commands, stale changes and attempted
quota escalation before their respective capabilities are enabled.

Warn around 80% and 95%. At the allowance, retain login, billing repair, reads/exports,
backups and supported storage-reducing actions. Reject unadmitted growth clearly while
preserving form input. Safe cleanup/accounting uses bounded operational headroom; there
is no unlimited “small edit” exemption. Kernel exhaustion/commit failures still require
owning transaction rollback, cleanup and uncertain-result handling.

A smaller product allowance can coexist temporarily with larger physical limits for
retained over-quota data after downgrade. Track that commitment explicitly and block
additional growth. Never lower kernel ceilings below actual usage or erase files to
force a downgrade. Apply increases before promising usable capacity; fence/drain and
verify decreases in the safe order. Larger tiers do not automatically lift individual
request/file limits; those remain qualified API/workload limits.

### Per-tier physical storage sizing acceptance

A logical allowance does not determine a physical ceiling by a fixed multiplier.
Before admitting a tier, qualify a versioned physical storage profile for that
allowance on the supported application/schema, filesystem/quota and host configuration.
A successful workload at arbitrarily chosen trial limits proves only that workload
and enforcement boundary; it does not derive or qualify production tier sizing.

| Tier | Exact logical allowance | Required delivery gate |
| --- | --- | --- |
| Free / Pilot 0 | 50,000,000 bytes | H04 qualifies the workspace/control/scratch profile; H05 qualifies backup/restore reservations; H06 requires both before invitations. |
| Paid 1 | 200,000,000 bytes | H08 qualifies this tier's physical profile and paid recovery/retention reservations before tier activation. |
| Paid 2 | 1,000,000,000 bytes | H08 independently qualifies this tier's physical profile and paid recovery/retention reservations before tier activation. |

No production byte or inode ceiling is established for any tier by the existing
256-MiB/8,192-inode workspace trial. Do not scale those constants to derive paid-tier
limits, copy the small fault-test limits, or claim that a measured host population
qualifies its advertised usable storage. Shared mechanisms may reuse unchanged
proof, but each tier needs its own measured sizing evidence and supported-workload bounds.

#### Measured peaks and justified margins

For each tier, record all of the following in its profile/evidence:

- Exact logical accounting definition and a reconciled workspace at its full logical
  allowance. Cover database-heavy, retained-file-heavy and many-small-file/history
  shapes; record record/file sizes/counts and all supported operation/concurrency bounds.
- Observed allocated-byte **and inode high-water marks for each private tree**,
  using kernel/filesystem allocation accounting rather than apparent file length or
  a post-operation directory total. Include filesystem rounding, database/index/free-page
  allocation, WAL/journals, retained versions and live/deleted-open files without
  double-counting the same committed logical state.
- Peaks during supported writes/updates, uploads/publication/rollback, checkpointing,
  exports, cleanup and maintenance. Exercise the largest admitted operations and
  allowed overlap with backup/recovery work; include compaction/rebuild only if supported.
  Capture temporary peaks, not just settled size after cleanup. Unsupported operations
  or larger workloads remain explicitly unavailable until separately qualified.
- Separate control, scratch, shared-host/image/log, backup staging/retention and restore
  destination commitments. Backup bytes stay excluded from operator logical quota,
  but their real physical locations still need bounded reservations. Identify which
  peaks overlap; do not omit them or charge the same storage twice.
- A nonzero byte margin and inode margin with an explicit rationale: repeated-run
  variation, declared growth/transaction bounds, allocation granularity and required
  safe failure/cleanup work. A round number or unexplained percentage is not evidence.

Derive each tree's proposed bounds from those observations:

```text
physical byte ceiling = round_up(measured peak allocated bytes + justified byte margin,
                                 enforced quota allocation unit)
physical inode ceiling = measured peak allocated inodes + justified inode margin
```

Record the terms, units, rounding and resulting enforced values independently for
workspace, control and scratch. The measured peak already includes logical data and
its physical overhead; do not add the logical allowance a second time. Record host-wide
and off-host recovery budgets separately. Retain source/image/schema/tool/host pins,
workload procedure, raw observations, failures, profile revision and evidence hashes.

#### Byte/inode exhaustion and recovery checks

Test the proposed real limits on isolated synthetic storage with the supported native
runtime; tiny fault fixtures alone do not qualify tier sizing. Acceptance requires:

1. Supported workloads at the full logical allowance fit the proposed physical byte
   and inode ceilings with the declared operational reserve. If they do not, revise
   the profile or explicitly qualify/document supported workload limits before activation;
   do not silently turn an internal inode bound into an advertised file/property cap.
2. Logical-limit growth is rejected while safe reads/export, supported cleanup and
   protection operations remain usable. Independently force **physical byte exhaustion**
   with inode capacity remaining, and **inode exhaustion** with byte capacity remaining,
   in workspace, control and scratch. Verify actual kernel refusal and attribution,
   including deleted-open charging and WAL/journal failure paths.
3. Failed writes/commits preserve acknowledged database/file data, audit/receipt
   consistency, original operation identity and valid reopen/integrity checks. Verify
   staged-publication cleanup or explicit unresolved cleanup state; no success metadata
   for unretained bytes, duplicate effects, silent deletion or fresh empty initialization.
4. Cleanup/reclaim and retry remain bounded: release resources only after verified
   cleanup, reconcile uncertain original results before retry, and prove the permitted
   workflow can resume without consuming its safety reserve indefinitely. Retain
   over-quota downgrade data; never lower a ceiling below observed use.
5. Reopen/restart and the supported backup/restore flow preserve ownership and limits.
   Restore staging/retention must fit their separate reservations. Test stale/missing
   sizing evidence, unknown or insufficient host commitments and competing admissions;
   they must remain pending/unavailable rather than overcommit or reuse the same hold.

Settings continues to show **logical usage and allowance**, not physical headroom as
extra usable storage. Admission/upgrade UI must not offer an unqualified tier as ready.
Exhaustion or unavailable capacity uses plain-language status, retains form input and
provides original-submission reconciliation; it must not display unknown usage as zero
or suggest buying more logical storage to conceal an inadequately sized physical profile.
Include focused operator/Admin browser checks with the owning workflow delivery.

Provisioning and tier-change reservations pin the reviewed logical allowance,
physical profile revision and sizing-evidence identity to the original operation;
retries cannot select a different profile or spend the same host headroom twice.

The [validation matrix](validation.md#required-validation-matrix) and
[delivery gates](delivery-plan.md#implementation-slices) consume this requirement.
Changing tier allowance, supported workload, relevant schema/image or storage configuration
requires applicable remeasurement/requalification before promising that capacity.

### Operator account UI

Settings shows plan, one workspace usage/allowance indicator, freshness, remaining space,
backup protection state, upgrade/change/cancel controls and pending operation status.
Both portals use async reads with retained stale values, independent errors and bounded
visible-page polling. Unknown is not zero; payment-confirmed is not Applied. Refresh
never resets a form, scroll or selection, and never submits another consequential action.
Use existing light/dark, responsive and keyboard-accessible UI patterns.

## Idle workspaces, sessions and multiple devices

<a id="7-idle-workspaces-sessions-and-multiple-devices"></a>

Free containers may suspend after approximately 15 minutes without human activity;
paid containers stay warm initially. Automatic polling does not count as human activity.
Track activity across all devices with bounded ephemeral/control observations rather
than turning every request into business history. No suspension while admitted writes,
uploads, exports or owned background work still require the runtime.

A persistent gateway validates the intended assignment, starts the registered container
once through a deduplicated wake operation, and shows a safe waking page. Private
business content is unavailable until source checks pass. Target a few-second wake;
measure it under cold starts, simultaneous demand, image availability and contention.
On wake failure provide status/retry without resubmitting the original write. Before a planned stop/suspension, finish protection of all admitted business/file
changes and persist the checkpoint. No workspace writes occur while stopped; an
unchanged stopped workspace needs no repeated full upload. On wake/restart reconcile
actual source/file generations and catch up unprotected changes before claiming health.
External monitoring alerts on stale/unknown dirty protection; it does not run routine
workspace backups. H11 must qualify this stop/wake contract before enabling suspension.

Multiple devices retain full permissions but not last-writer-wins behavior. Stale saves
conflict, preserve input and provide comparison/review. Independent records remain
independently editable. Shared unfinished forms require explicit ownership/takeover
where applicable; opening a tab never silently steals another device's edit authority.
Do not add offline mutation queues or automatic replay after reconnect, wake or upgrade.

