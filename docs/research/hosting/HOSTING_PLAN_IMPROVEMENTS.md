# Hosting plan improvements

Date: October 15, 2026

Status: Recommendations for discussion and future design; not implemented capabilities or changes to approved backlog scope.

This note reviews the [commercial Hosting Plan](Hosting_Plan.md) and [Hosted Demo Design](../HOSTED_DEMO_DESIGN.md). The largest opportunities are simplifying initial deployment and strengthening recovery and concurrent editing. Retain the proposed per-workspace SQLite/container architecture, then add infrastructure when measured demand or a feature requires it.

## Cost, performance and operator experience

| Area | Recommendation | Benefit and tradeoff |
| --- | --- | --- |
| Initial cost | Start with one paid 2 GB VM for the two-operator demo. Defer managed Postgres, relay servers and a separate AI gateway until their features need them. | DigitalOcean currently lists 2 GiB at $12/month; backups and domain are additional. This is a starting size to validate, not a capacity guarantee. |
| Capacity planning | Replace “15 tenants per 4 GB host” with measured limits covering peak memory, concurrent requests, database lock waits and disk growth. | Property count alone poorly predicts load; imports and attachments can dominate. |
| Performance | Build releases off-host, stagger backups and background jobs, and bound expensive report/import concurrency. | Protects interactive requests before increasing compute spend. |
| Operator experience | Keep active workspaces running rather than sleeping demo instances during trial periods. | Predictable first-page loading is worth the modest compute cost. |
| Multiple devices | Refresh on focus/reconnect, retain dirty forms, and distinguish saved, saving, disconnected and outcome-unknown states. | Operators can understand whether changes persisted and avoid duplicate submissions. |
| Recovery | Restore complete, verified workspace recovery points containing the database, attachments and a manifest. | Database replication alone cannot establish that corresponding files are recoverable. |
| Operations | Use one immutable release bundle, supervised processes, external uptime checks and tested restore commands. | Reduces manual mistakes and recovery time. |

Pricing source: [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets), checked October 15, 2026. Recheck before provisioning. Keep one server process per workspace under the current workspace ownership model; adding workers is not a substitute for measuring bottlenecks.

## Reliability corrections for the commercial hosting plan

### Tenant moves require a controlled write handover

“Restore latest backup, then switch routing” can lose writes made during the move. Specify a protocol that drains writes, creates a final consistent recovery point, verifies the destination, fences the old instance against further writes, and then switches routing. Only one instance may accept writes for the workspace. Existing browsers must reconnect and reconcile outstanding commands using their original operation keys.

### Recovery targets must cover the whole workspace

If the database replicates every minute but attachments are backed up daily, “a few minutes of data loss” is not a whole-workspace guarantee. Track the latest recovery point for which all referenced files are available. Retain immutable attachment versions long enough to support retained database recovery points.

Define and monitor both database replication lag and complete-workspace recovery-point age. Measure recovery time using a fresh host and the complete release bundle, not just database download time. Validate the chosen replication configuration against [Litestream's documented caveats](https://litestream.io/tips/).

### Replication and deletion protection serve different purposes

Replication can faithfully replicate unwanted changes. Retained recovery points, protected backup credentials and independently recoverable encryption keys are necessary. A restore drill should exercise loss of both the host and its credentials. Recovery access must not depend exclusively on secrets stored on the failed host.

### Two relay instances do not establish durable delivery

Specify a durable event store, acknowledgement only after persistence, retry ownership, deduplication and dead-letter handling. Compare a managed queue with operating two relay VMs before choosing the topology. A managed queue can reduce server maintenance but introduces provider coupling; application-level idempotency remains necessary.

[Cloudflare Queues](https://developers.cloudflare.com/queues/) is one candidate for a separate evaluation, not a selected dependency. Evaluate retention, delivery semantics, payload limits, privacy requirements, cost and recovery behavior against the eventual relay contract.

## Simplifications for the hosted demo

### Introduce exclusive draft takeover only when needed

Keep revision checks mandatory. Introduce exclusive draft takeover only where devices actually share one recoverable draft. Independent device drafts plus conflict handling may suffice initially and avoid confusing “locked on another device” interactions. If cross-device draft continuation is promised, retain the explicit takeover behavior and stale-editor protection proposed in the demo design.

### Measure freshness polling before adding infrastructure

Start with one lightweight change check per visible browser, alongside focus/reconnect refresh. Measure its cost before introducing push notifications or snapshot infrastructure. Time-based deadlines still need refresh even when no records change. Background refresh must preserve dirty form values, and failed attention checks must not produce a reassuring all-clear.

## Commercial control-plane availability

Where safely possible, let existing authenticated use continue through transient control-plane failures by caching verified routing and entitlement information with explicit expiry and revocation rules. A billing-service outage should not immediately interrupt property management.

This requires a deliberate policy for which cached decisions remain valid and for how long. Do not bypass authorization when identity verification fails, accept stale revoked sessions indefinitely, or use an unverified tenant mapping. Authentication, billing and routing failures need distinct handling rather than a blanket fail-open policy.

## Recommended sequence

1. Establish two isolated workspaces on one paid VM.
2. Complete hosted authentication, safe concurrent edits and clear save/reconnect behavior before remote operator access.
3. Establish complete off-host backups and demonstrate a successful fresh-host restore.
4. Measure four simultaneous browser sessions alongside a backup/report workload, including memory peaks, lock waits and interactive latency.
5. Add capacity, managed databases or queue infrastructure when measured demand or a new feature requires them.

Prioritize recovery automation and operator confidence over small compute savings. No infrastructure has been provisioned or performance benchmarked by this recommendation, and neither source plan is modified by this note.
