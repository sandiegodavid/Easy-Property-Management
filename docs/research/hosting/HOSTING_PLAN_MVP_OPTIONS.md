# Hosting plan - MVP cost and performance options

Date: October 23, 2026

Status: Recommendations for discussion; not implemented capabilities and not changes to approved backlog scope. Companion to the [commercial Hosting Plan](Hosting_Plan.md) and [Hosting plan improvements](HOSTING_PLAN_IMPROVEMENTS.md). Those two documents cover the target architecture and the start-smaller sequence; this note adds options neither of them contains, scoped to the MVP: lower fixed cost, and better capacity and latency from the per-workspace SQLite architecture as it already exists.

Prices were checked against provider pages and current pricing trackers on October 23, 2026. Recheck before provisioning; the commercial plan's prices date from mid-2026 summaries and at least one of them (Hetzner, below) no longer holds.

## 1. Recommended MVP bundle: about USD 24-29 per month

The commercial plan's Phase 1 table totals about USD 75 per month. Most of the difference is fixed services bought before the phase that needs them. The alternative bundle below keeps every architectural decision in the plan (per-tenant containers, per-workspace SQLite, Litestream replication, portability) and changes only where things run for the MVP:

| Line | Choice | Monthly cost |
| --- | --- | --- |
| Tenant host | One 4 GB VM (DigitalOcean SFO at USD 24, or AWS Lightsail at USD 20) running the tenant containers, the control plane, and the reverse proxy | USD 20-24 |
| Control plane database | Postgres in a container on the same host, nightly dump to object storage. Defer the managed instance (USD 15 in the plan) until billing is live. | USD 0 |
| Ingress and TLS | Cloudflare Tunnel: no public ports on the VM, TLS handled at the edge | USD 0 |
| App shell and marketing site | Cloudflare Pages, same as the plan's static-site line | USD 0 |
| Attachments | Cloudflare R2 from day one (the files module already speaks S3), served by presigned URL | about USD 0-2 |
| Backups | Litestream plus daily snapshots to R2 (separate provider from the VM host, as the plan requires) | included above |
| Provider backups | Dropped once the R2 restore drill passes (see section 2) | USD 0 |
| Monitoring | Healthchecks.io for backup-age and replication-lag pings; UptimeRobot or Better Stack free tier for external uptime; status page on Pages | USD 0 |
| Domain and misc | Unchanged from the plan | about USD 5 |
| **Total** | | **about USD 24-29** |

At 10 tenants that is about USD 2.50-3.00 per tenant against the plan's USD 7.50, leaving almost the whole USD 12.50 per-customer funding-model allowance for managed AI and tools.

Tradeoffs, stated plainly:

- Single host: already accepted in the commercial plan for pilots; the blast radius is unchanged.
- The control-plane database is self-managed. It holds accounts, billing metadata, and the tenant registry only; it is small, dumped nightly, and largely rebuildable from the registry and provider records. The managed instance becomes worth its price when billing is live and the registry is load-bearing.
- Cloudflare becomes the ingress dependency. It is DNS-deep only: removing Tunnel and Pages restores direct hosting in an afternoon, so the plan's replaceable-providers rule still holds.

## 2. Cost options

### Attachments in R2 from day one

The plan stores attachments on the tenant volume and syncs them to object storage with a separate tool (restic or rclone), because Litestream covers only the database. Storing attachments in R2 directly removes three costs at once: the attachment-sync machinery in the backup design, VM disk growth (attachments are the part of a workspace that grows), and VM bandwidth for uploads and downloads. R2 pricing is USD 0.015 per GB-month with zero egress fees and a free tier of 10 GB storage plus 1M write and 10M read operations per month, so at MVP scale this line is effectively free; restore drills also download for free, which B2's free-egress cap (3x stored data) does not guarantee once drills are frequent. The recovery design still needs the plan's referenced-file verification step; it just runs against R2 instead of a synced volume.

### Hetzner is not the US budget option anymore

The plan lists Hetzner as the later cost-saving alternative, with two 2026 price rises noted. Current state: the cheap ARM line (CAX21: 4 vCPU, 8 GB, EUR 10.99 per month) is EU-only, and the US locations (Ashburn, Hillsboro) carry only the x86 CPX line at prices above DigitalOcean - CPX21 (3 vCPU, 4 GB) lists at USD 37.49 per month in the US against DigitalOcean's USD 24 for 4 GB. An EU host would also add about 80-150 ms to every US operator interaction. Recommendation: keep Hetzner for staging or remove it from the provider table; in the US, Lightsail (USD 20 for 4 GB) is the real price alternative to DigitalOcean.

### Density is the per-tenant lever

The difference between a USD 20 and a USD 24 host is noise next to tenants per host. The server is one Python process per workspace; measure its real resident memory per workspace, set container memory limits from that measurement, and size the host from the result (the improvements note's measured-capacity point, applied to the buying decision). If a workspace process idles at 200 MB, a 4 GB host with OS, proxy, and control plane fits about 10-12 active workspaces; the plan's 15-per-4 GB figure should be treated as unproven until measured.

### Drop provider backups after the drill

The plan already says provider snapshots are a convenience, not the recovery plan, but still budgets them at +20 percent of host cost in every phase. Once a fresh-host restore from R2 has been demonstrated (the improvements note's step 3), that line buys nothing the recovery design does not already provide. Delete it at that point rather than by default.

## 3. Capacity options (performance)

### SQLite read scaling inside the workspace process

Reads dominate this application: directories, detail pages, Home. The largest capacity lever that does not touch the architecture is how each workspace process uses SQLite: WAL mode with a small pool of read-only connections behind a single writer, so reads proceed concurrently instead of serializing behind one shared connection. Pair it with a deliberate pragma pack per workspace database: synchronous NORMAL (safe under WAL), a busy_timeout of about 5 seconds so brief write contention waits instead of returning lock errors, and explicit mmap_size and cache_size instead of the small defaults. Multi-seat write contention is a Phase 4 concern in the roadmap; read concurrency is available now for configuration-level effort.

### Cache Home aggregates keyed on workspace revision

The needs-attention counts and money totals on Home are the most-viewed and most-computed numbers in the app, and the server already tracks workspace revisions for its recovery and attention machinery. Cache the aggregate response per workspace and invalidate on any write to that workspace. Home is every session's landing page; this takes its cost off the database almost entirely, and the invalidation signal already exists.

### One-time index audit on the hot lists

Run EXPLAIN QUERY PLAN over the queries behind the rent-due list, the needs-attention views, and the money-by-period lists against a seed scaled to about 10x the demo data. Missing indexes and N+1 patterns are cheapest to find before a pilot's real data finds them, and the demo seed makes the test data reproducible.

### Isolate background work with CPU shares

The improvements note says to bound expensive report and import concurrency. The concrete mechanism: run reports, imports, and snapshot jobs in a container with a lower cgroup CPU share than the interactive tenant containers, at most one job per workspace at a time. Interactive latency then survives a co-tenant's year-end report on the same host.

## 4. Latency options (performance)

### Serve the app shell from the edge

The plan already puts the marketing site on Cloudflare Pages. Extend that to the application bundle itself: hashed, immutable assets served from the nearest edge location, so first load no longer depends on a shared-CPU VM's bandwidth or disk. The API stays on the VM behind a proxied subdomain, same-origin.

### Presigned URLs take the VM out of the file path

With attachments in R2 (section 2), uploads and downloads go browser-to-R2 directly via presigned URLs. For a property-management workload - leases, inspection photos, scanned documents - file transfer is the heaviest traffic the VM would otherwise carry, in both latency and CPU. Generate thumbnails at upload time and serve those in grids; originals only on open.

### Pin the region to the pilot cohort

One region, chosen for the first customers: SFO is about 15 ms from San Diego against about 70 ms cross-country. Do not split tenants across regions at MVP; the control plane's registry already records placement, so regional growth later is a placement decision, not a redesign.

### Freshness as a revision poll

The improvements note recommends one lightweight change check per visible browser, measured before adding push infrastructure. Concretely: a single endpoint returning the workspace's current revision vector (about 100 bytes, ETag-friendly), with a full refetch only when it changes. That makes the check cheap enough to run every few seconds per browser without measurable host load, and it covers the time-based-deadline refresh the note requires.

## 5. What not to chase for the MVP

- Kubernetes or any orchestrator: on one host it costs more to run than the application.
- A serverless rewrite: per-workspace SQLite files do not fit the function model, and the local/hosted same-format guarantee is worth more than the savings.
- Multi-region or warm standbys: Phase 6 concerns in the plan's own rollout table.
- Oracle Cloud's free ARM tier for production: the capacity is real, but free-tier instances can be reclaimed; it is fine for CI and staging.
- Fly.io as primary: the plan's reliability assessment stands.

## 6. Sources

- DigitalOcean Droplet pricing: https://www.digitalocean.com/pricing/droplets
- Hetzner price adjustment, June 15 2026 (CAX availability EU-only; US CPX pricing): https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- Cloudflare R2 pricing (USD 0.015 per GB-month, zero egress, free tier): https://developers.cloudflare.com/r2/pricing/
- Litestream documented caveats: https://litestream.io/tips/
