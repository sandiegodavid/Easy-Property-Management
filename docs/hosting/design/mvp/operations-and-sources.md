# Monitoring, operations and source references

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/README.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

In this guide: [Monitoring, reliability and cost qualification](#monitoring-reliability-and-cost-qualification) · [Primary-source constraints used in this design](#primary-source-constraints-used-in-this-design)

## Monitoring, reliability and cost qualification

<a id="10-monitoring-reliability-and-cost-qualification"></a>

Use in-app status and transactional email for invitations, subscriptions, quotas, updates
and relevant recovery notices. Admin gets actionable infrastructure, failed provisioning,
backup and rollout alerts. Deduplicate repeats and send recovery notices; do not rely on
an operator visiting the app to detect a failed backup. Select a transactional-mail
provider with measured delivery/quota/cost before launch; do not build an SMTP service.

Measure per-host/container memory, CPU, disk/inodes, IO, restarts, wake/read/write latency,
job queues, backup-point age, restore duration, retained recovery bytes and service cost.
Product adoption metrics distinguish real recurring work from demos/polling. Keep logs
and traces bounded, access-controlled and free of session credentials, full request
bodies, document contents and unnecessary financial/customer details. Exclude advertising
tracking and session recording from this scope.

Before selecting host sizes/qualified population, measure empty and representative
portfolios, all tiers, paid warm residency, multi-device activity, 20 active operators
at the 100-registered stage, bursts and simultaneous wake-ups, imports/uploads when
supported, updates, backup/restore and control-plane overhead. Record dataset, workload,
limits, concurrency, p95 latencies and failure behavior. No capacity claim follows from
idle RAM, container count or a successful small synthetic seed alone.

Cost worksheet must include persistent and retained inactive data, backup cadence and
retention, deduplication under realistic changes, GCP-to-R2 traffic, auth/email limits,
monitoring/log retention and billing-provider charges. Forecast the all-paid/warm case
as well as a mostly-Free cohort. If targets do not fit, present the measured tradeoff
for approval rather than quietly weakening an entitlement or overcommitting the host.

## Primary-source constraints used in this design

<a id="12-primary-source-constraints-used-in-this-design"></a>

- [Docker production Compose](https://docs.docker.com/compose/how-tos/production/) and
  [restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/):
  single-server deployment is supported; intentional stops and crashes need distinct policy.
- [Docker daemon access](https://docs.docker.com/engine/security/protect-access/): protect
  management authority; do not expose its socket to public app processes.
- [SQLite WAL](https://www.sqlite.org/wal.html): live WAL participants must share a host;
  network-file sharing is not a transparent path to multiple writers/hosts.
- [GCP persistent storage](https://docs.cloud.google.com/compute/docs/disks/persistent-disks)
  and [supported container deployment](https://docs.cloud.google.com/compute/docs/containers/deploying-containers):
  persistent data is separate from container lifecycle; use supported installation tooling.
- [Cloudflare wildcard DNS](https://developers.cloudflare.com/dns/manage-dns-records/reference/wildcard-dns-records/),
  [Universal SSL coverage](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/limitations/)
  and [Tunnel configuration](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/):
  qualify flat-host coverage and independently reject unknown wildcard-matched hosts.
- [Google OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
  [Firebase email links](https://firebase.google.com/docs/auth/web/email-link-auth) and
  [session cookies](https://firebase.google.com/docs/auth/admin/manage-cookies): exact
  callback/authorized-domain rules and supported credential/session lifetimes apply.
- [Identity Platform pricing](https://cloud.google.com/identity-platform/pricing) and
  [Firebase limits](https://firebase.google.com/docs/auth/limits): verify actual provider
  class, email delivery and billing-enabled project limits, not MAU alone.
- [Stripe subscriptions](https://docs.stripe.com/billing/subscriptions/webhooks),
  [pending updates](https://docs.stripe.com/billing/subscriptions/pending-updates) and
  [customer portal](https://docs.stripe.com/customer-management): asynchronous provider
  facts require verified events and reconciliation; EPM still owns effective entitlements.
- [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
  [Compute pricing](https://cloud.google.com/products/compute/pricing/general-purpose),
  [disk pricing](https://cloud.google.com/compute/disks-image-pricing),
  [network pricing](https://cloud.google.com/vpc/network-pricing), and
  [Stripe pricing](https://stripe.com/billing/pricing): recheck exact region/account,
  retained bytes, traffic and provider fees before approving the financial model.
