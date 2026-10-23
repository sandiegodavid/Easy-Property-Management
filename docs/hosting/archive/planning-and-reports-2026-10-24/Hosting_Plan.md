# Hosting plan: local use, two-operator demo, and hosted MVP

Updated October 23, 2026.

Status: consolidated planning baseline incorporating the product owner's approved conflict resolutions. This document incorporates and replaces the former hosting-plan improvements and MVP-options notes, which have been removed. It does not provision infrastructure, authorize public activation, or mark planned capabilities as delivered.

## 1. Scope and decision hierarchy

Support US customers managing US properties. There is **no additional geographic restriction on storage, backups, processing, identity services, or other providers**. Choose a US compute region for operator latency and operational simplicity, not as a data-residency guarantee. Do not purchase regionalization services or impose US-only backup placement for a requirement the product does not have.

Cover three operating modes:

| Mode | Intended use | Hosting and identity | Status |
| --- | --- | --- | --- |
| Local | One operator manages their own supported portfolio on their computer | Loopback application, external local workspace, no application account or cloud dependency for manual workflows | Current core product |
| Two-operator demo | Two invited operators, each with a separate persistent synthetic portfolio and multiple devices | Existing Google Cloud VM, separate Unix users/processes/workspaces, qualified Cloudflare Access and tunnel boundary | Private deployment exists; public-access implementation and deployed acceptance remain incomplete |
| Hosted MVP | A bounded cohort of customers, with one operator per isolated customer workspace and access from multiple devices | Reuse the qualified application and operating pattern, with customer onboarding, isolation, recovery and support gates | Planned; the demo is not evidence of production readiness |

A hosted MVP is an additional delivery stage, not a redefinition of the local MVP. Shared portfolios, multiple seats and enterprise infrastructure are outside this plan.

The [product brief](../../../PRODUCT_BRIEF.md), [architecture](../../../ARCHITECTURE.md), [decisions](../../../DECISIONS.md), and [backlog](../../../FEATURE_BACKLOG.md) remain the product and implementation authorities. The [public-access plan](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) owns the detailed demo slices and release gates. The [Google Cloud deployment record](../../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md) records the actual private installation.

The existing Hosting_Plan.pdf represents the earlier commercial proposal and is not an updated rendering of this document.

## 2. Recommended baseline

Use the smallest operational footprint that passes measured capacity and recovery checks:

- Keep the existing Google Cloud Oregon VM for the two-operator demo. Do not move providers or downsize solely to save a few dollars before qualification.
- Keep one application process/writer per workspace, local SQLite and local attachments, and one combined frontend/backend release.
- Use Cloudflare Access and one named tunnel with fixed per-workspace routes after the application authorization boundary and operator workflows pass acceptance.
- Store completed, application-encrypted recovery archives in a private Cloudflare R2 Standard bucket, separate from the compute provider.
- Keep hosted identity bindings and revocation state outside portable business workspaces. Restoring records must never restore usable authorization.
- Provision the initial hosted cohort administratively. Defer billing, a managed control-plane database, relays and a separate AI gateway.
- Use measured memory, contention, storage growth and operator latency to decide capacity. No fixed number of workspaces per host is established.

No paid load balancer, Kubernetes, serverless rewrite, warm standby, multi-region deployment, or separate application-shell host is required initially.

## 3. Local operation

Local manual workflows must continue to work without login, hosted configuration, Cloudflare or an Internet connection.

The product owner performs setup using the supported scripts. Each operator chooses an external workspace directory outside the source checkout. SQLite and managed attachments stay together under the workspace contract; file links use stable identities and supported relative locations.

Preserve the loopback Host/Origin protections. The explicit local-client header expresses command-line intent and is not remote authentication. Do not expose the local server by rewriting transport headers or relaxing its checks.

Use the existing complete encrypted backup/export and restore workflows. Optional automatic local backups use the supported OS credential-store contract; that does not establish an unattended secret-store solution for a headless server. Synchronize only completed encrypted archives, never the live SQLite workspace.

Transfers between local and hosted operation use a controlled, validated export/restore workflow. They are not a raw copy of an open database. Preserve stable IDs, relationships, financial totals, attachments and audit history. Reestablish external authorization separately.

## 4. Two-operator demo

### Deployment shape

Retain the recorded Ubuntu 24.04 x86/64 installation in Google Cloud Oregon, with the current 4 GB E2 baseline, separate epm-a/epm-b service identities, private directories and independent synthetic workspaces. Confirm the actual machine and disk settings in Console when qualifying the release.

Keep two supervised services and one private application listener per workspace. Each public hostname must route only to its assigned process. Keep application ports closed publicly and retain administrator IAP SSH access. Carry the working per-account TMPDIR settings into service and administrator commands.

A hosted process replaces the corresponding local process. Never run a second server or additional Uvicorn workers against the same workspace. A single VM remains a shared failure domain, which operators must understand.

### Access and operator experience

The accepted design uses exact email allowlists, administrator-approved verified-subject enrollment, opaque revocable application sessions, exact HTTPS Host/Origin checks and session-bound CSRF. Authentication must protect APIs, search, recovery, original receipts, audit and file downloads before disclosure.

Keep host administration, credentials, arbitrary filesystem paths, portable restore and backup management outside ordinary operator authority. Hiding a control is not authorization.

Support explicit current-device and all-device logout, visible demo expiry and support contact, truthful save/error states, and safe same-identity reauthentication. Do not resubmit consequential commands automatically after an interrupted response or sign-in.

The accepted demo duration is fourteen days from enablement, with an eight-hour maximum application session bounded by the identity grant and demo expiry. Keep all records synthetic and external mail, payment and model dispatch disabled.

### Current implementation boundary

The latest public-access checkpoint records Slices 1–6 implemented, Slice 7 qualification in progress, and Slice 8 pending. The [real Linux SQLite FULL drill](../../qualification/reports/HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md), [systemd/50 MiB upload checks](../../qualification/reports/HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md), [actual R2 recovery/fresh-image qualification](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md), and [installed wheel/environment plus approved boot mount](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md) passed within their scratch scope. A/B returned on their unchanged private commands/configuration/workspace IDs after the approved reboot. The [operations runbook](../../operations/HOSTED_DEMO_OPERATIONS.md) identifies A/B hosted deployment and remaining physical fault/reset/rollback gates. This scoped evidence is not complete hosted acceptance. The installed private release must not become public merely because the tunnel or DNS works; completed recovery/deployment acceptance still precedes invitations.

Finish the existing slice sequence and its real-client acceptance before invitations. This consolidation does not restart that work or change its usage-stop checkpoint.

## 5. Hosted MVP

### Initial architecture

Retain the modular monolith and one isolated workspace per customer. One operator may use several devices; multiple people sharing a portfolio require later permission and collaboration work.

Reuse the qualified demo host where its measured capacity, isolation and funded operating period support the pilot. For a new host, DigitalOcean in a suitable US region is the default comparison; AWS Lightsail is an alternative. Avoid an unnecessary provider move when the existing Google Cloud deployment already meets the gates.

For real customer hosting, qualify per-workspace process/user/volume separation and resource limits. A container per workspace is the planned packaging/isolation option, not a capability supplied by merely wrapping the local server in an image. The two-user demo alone does not prove adversarial customer isolation.

Keep a minimal administrator-managed workspace/host registry and source-owned authorization stores. Start without a separate Postgres service. Revisit the control-plane database only when actual account, billing or placement needs justify it.

Keep SQLite, attachments, portable archives and owning domain transactions as the business authorities. A hosting registry must not become a second customer-record database.

### Onboarding and included UI

A usable hosted MVP includes provisioning the correct workspace, explicit identity approval, sign-in and reauthentication, logout/revocation, customer-facing expiry/maintenance states, and clear support/recovery expectations.

Include browser workflows for private files, search, saved forms and original-result recovery. Preserve dirty input on conflicts, reject stale editors, and prevent cross-workspace/session cache reuse. Follow the explicit claim/takeover contract wherever devices share a saved draft.

Do not imply self-service sign-up, billing, team roles or public owner/tenant portals. Customer onboarding remains administrator-run for the bounded cohort.

### Admission to a real-data pilot

Before onboarding real customer data, record successful tenant-isolation/security checks, capacity measurements, a complete off-host restore drill, support ownership, a funded operating period, and the privacy/retention/deletion terms. Select and qualify at-rest encryption and recoverable key custody before handling sensitive customer records.

Keep a current release and recovery point for a controlled rollback. No availability or recovery SLA follows automatically from the choice of cloud provider.

## 6. Files, ingress and provider choices

| Boundary | Initial choice | Reason and qualification |
| --- | --- | --- |
| Existing demo compute | Existing Google Cloud Oregon VM | Avoid re-provisioning during qualification; trial credits do not establish ongoing free operation |
| New hosted compute, if needed | DigitalOcean US region; Lightsail alternative | Compare total regional cost and measured performance before moving |
| Public access | Cloudflare Access and named tunnel | Simple fixed ingress; the app still verifies identity/session/workspace authority |
| Application delivery | Packaged frontend and API on the same public origin | One release, straightforward cookies/CSRF, no cross-origin routing layer |
| Live evidence | Local persistent files through owning authenticated APIs | Keeps current integrity, link and rollback behavior |
| Off-host archives | Private R2 Standard storage | Holds only completed encrypted application archives; use automatic/default location unless latency measurements justify a hint |
| Administrative state | Separate protected per-process SQLite | Keep sessions, grants and edit leases out of portable business backups |
| Monitoring | Minimal independent uptime check plus host/service and recovery-age alerts | Use eligible free services where sufficient, with no private payloads in probes or alerts |

R2 supports jurisdictional placement, but this product does not require it. Automatic placement and optional location hints serve performance needs; a hint is not a residency guarantee. See [R2 data location](https://developers.cloudflare.com/r2/reference/data-location/).

Do not configure R2 as the existing live S3 file adapter just because both use an S3-compatible API. The current [File adapter](../../../../application/apps/server/app/modules/files/infrastructure/content_store.py) requires bucket versioning and exact VersionId behavior. R2 live-file use, browser presigned transfers and thumbnails need a separately qualified contract and are deferred.

A US origin alone does not imply geographically restricted edge processing or metadata. Cloudflare treats tunnel connector placement, traffic processing and metadata localization as separate controls. No such residency guarantee is required or claimed here. See [Cloudflare Zero Trust localization](https://developers.cloudflare.com/data-localization/how-to/zero-trust/).

Use globally delivered public assets only where Access behavior and cache rules are qualified. Public marketing hosting can be separate, but moving the application to Pages with an API on another subdomain would introduce a different origin and is not the initial plan.

## 7. Complete recovery and controlled handover

### Recovery unit and custody

Back up a validated SQLite-consistent database, every required attachment and a manifest together. Database replication alone is not a complete workspace recovery point.

Encrypt archives before upload. Keep upload credentials outside application workspaces and unavailable to the application service accounts. Keep recovery passphrases and the administrator recovery information independently recoverable after host loss.

Back up protected deployment configuration and necessary enrollment information separately in an administrator-encrypted bundle. Exclude usable sessions, token hashes, Access grants, connector/model credentials and edit leases. Require fresh authorization after restore.

### Initial schedule and retention

For the demo, the named administrator performs daily application-consistent encrypted backups and verifies publication, retaining seven successful daily recovery points per workspace. Stagger A/B maintenance and record how long each interruption lasts. Do not depend on an unqualified headless keyring.

Use that simple, explicitly supervised recovery model for an initial bounded hosted pilot only if its disclosed recovery window and operational workload are acceptable. Automation requires a qualified server secret-store and monitoring contract before anyone calls it unattended.

Report the actual age of the latest complete verified recovery point. A daily policy allows up to twenty-four hours of edits at risk only while verification is current; otherwise disclose the older point and act on the failure. Do not promise minutes of whole-workspace data loss.

Keep the latest verified point when a new backup fails. Verify a fresh-host restore, including archive authentication, retained-data validation, attachments, stable IDs and financial totals, before pruning or claiming recovery readiness.

### Optional layers

Litestream is deferred until a measured recovery requirement justifies continuous database replication. Qualify its encryption, database compatibility and attachment recovery together before changing the recovery claim. [Litestream's caveats](https://litestream.io/tips/) are part of that evaluation.

Provider snapshots may provide a distinct convenience or recovery layer. Keep or remove them according to demonstrated coverage, restore time and cost after an independent restore drill. Neither keeping snapshots nor removing them is an automatic rule.

Do not adopt the earlier 14-day/8-week/12-month commercial retention proposal as an MVP commitment. The hosted pilot must explicitly disclose retention and deletion handling, including retained backups.

### Workspace move or reset

1. Enter disclosed maintenance and stop/drain writes.
2. Create and verify the final complete recovery point.
3. Restore into a new private destination and validate the compatible release and data.
4. Fence the old writer and invalidate stale runtime/session continuations.
5. Switch the fixed routing/binding explicitly, then verify the new workspace and fresh authorization.
6. Have browsers reconcile uncertain operations with their original keys.

Only one workspace instance may accept writes. Do not overwrite a live SQLite file or silently switch routing while writes continue.

## 8. Performance, concurrency and freshness

Keep the existing WAL/deferred-read/immediate-write model and five-second busy timeout. Inspect actual connection settings and query plans before tuning. Do not enable synchronous=NORMAL, mmap/cache changes or a new read-pool design as unmeasured defaults, and do not reduce acknowledged financial durability to improve a benchmark.

Use set-based owning projections and query budgets. Run representative hot-list query plans against a reproducible larger seed before adding caches. Measure process memory, CPU throttling, storage growth, lock waits and p95 latency under at least four simultaneous browser sessions plus a bounded report and staggered backup.

Build releases off-host. Bound expensive work and stagger it to protect interaction. A separate report/import worker must not introduce another workspace writer or speculative job infrastructure.

Keep active pilot workspaces running during their advertised period. Consider a 2 GB host only after repeating qualification with at least 25% total memory headroom, no OOM/restart failures, and the same latency gates. Do not assume 10–12 or 15 workspaces fit on a 4 GB VM.

Preserve source revisions and original-key idempotency. Changed payloads using the same key must conflict; interrupted financial responses must reconcile rather than create another payment or expense. Background refresh must not overwrite dirty input.

Use one bounded fifteen-second change check per visible browser, with jitter/backoff and hidden-tab suspension, as specified by the demo plan. Keep independent focus/reconnect, periodic and property-local time-transition refresh. A revision alone cannot detect a deadline passing without a write.

Do not add a Home snapshot/cache initially. If measurements later justify one, scope it to the authorized workspace/runtime/filter/period and expire it on relevant time transitions as well as data changes.

Cache only qualified fingerprinted public assets. Keep private HTML, APIs, session responses, errors and downloads non-shared and no-store. Never bypass authentication or introduce a Cache Everything rule to improve apparent latency.

### Acceptance targets

The [public-access plan](../../design/HOSTED_DEMO_DESIGN.md#measurement-and-acceptance-targets) owns the detailed measurement protocol: at least fifty observations per operation/cache condition in three runs, with reference-network and actual-operator measurements distinguished.

| Measurement | Target to demonstrate |
| --- | --- |
| Warm authenticated ordinary read at origin | p95 at most one second, preserving owning query ceilings |
| Warm Home usable | p95 at most 1.5 seconds on the reference network |
| Cold assets and initial Home after identity sign-in | p95 at most three seconds desktop / five seconds mobile on the specified reference networks |
| Ordinary non-file mutation | p95 at most 1.5 seconds on the reference network |
| Incremental local authorization | p95 at most 20 ms; at most one indexed auth SELECT per protected request, without routine last-seen writes or remote introspection |

These are release targets, not measured results or universal network guarantees. Measure maintenance interruptions honestly.

## 9. Security and operations

- Apply least privilege to cloud, registrar, code and administrator accounts, with MFA where supported. Keep service identities and private directories separate.
- Store secrets outside images, source, logs and portable business archives. Qualify key recovery separately from host recovery.
- Use TLS, server-side capabilities, revocation and exact-origin CSRF. Deny ambiguous identity, host or workspace mappings.
- Keep customer evidence and sensitive command input out of infrastructure logs, analytics and alert payloads. Treat identifiers and request metadata as potentially identifying, not automatically harmless.
- Keep support access off by default, explicit, time-limited and audited. Maintain incident, credential-loss, export/deletion and recovery procedures.
- Monitor service health, backup age, disk/memory, errors and certificate/tunnel availability. The demo warns at 80% host disk use and enters write maintenance before 90%, with rollback/cleanup headroom.
- Enforce the accepted demo's 250 MiB whole-workspace budget, 50 MiB file ceiling and concurrent staging/reservation rules before public release. A displayed disk measurement is not quota enforcement.
- Deploy one immutable release with recorded source, dependencies, schema and checksums. Stage qualification before switching the owning process.
- Keep only the current greenfield schema. Do not add automatic startup migrations, schema compatibility layers or a migration fleet as part of this work. Verify release/data compatibility before a switch and retain the validated recovery path.
- State realistic support hours and name the person responsible for daily recovery checks and alerts. Do not imply 24/7 support or SOC 2 certification.

The app does not need native mail/SMS authorization, automatic sending or a managed AI gateway for this hosting scope. Manual entry and operator sending remain usable. Any optional assistant/model capability must follow its own approved governance and disclosure design; hosting does not authorize it.

## 10. Cost and capacity plan

### Current demo

Keep the accepted **USD 30/month infrastructure target**, before tax and domain registration. It includes actual compute, disk, IPv4, transfer and backup usage. It is a planning target, not a provider quote or enforced spending cap.

Record gross regional usage before trial credits, keep budget notifications, and review at least seven days before trial expiry. If ongoing operation is unfunded, take a final verified off-host backup and suspend deliberately. Do not describe a trial-funded VM as permanently free.

### Hosted MVP planning example

Use an equivalent 4 GB configuration for the first comparison, then qualify actual capacity:

| Item | Monthly planning amount | Basis |
| --- | --- | --- |
| DigitalOcean Basic Regular 4 GiB / 2 vCPU | USD 24 | Published reference price, subject to chosen region/availability |
| R2 archives and backup operations | USD 1–5 allowance | Estimate only; measure retained archive bytes, requests and restore traffic |
| Monitoring/logging | USD 0–5 allowance | Estimate only; free-tier eligibility and sufficient retention must be verified |
| Domain | USD 1–3 amortized allowance | Estimate only; use actual registration and renewal |
| Planning subtotal | USD 26–37 | Compute plus the stated allowances, not an all-inclusive quote |

DigitalOcean also lists a 2 GiB reference at USD 12, but that is a measured-downsize option, not the demo's starting instruction. [DigitalOcean pricing](https://www.digitalocean.com/pricing/droplets).

Lightsail's comparable Linux 4 GB bundle with public IPv4 lists USD 24/month. The earlier USD 20 figure must not stand in for that equivalent bundle. [Lightsail pricing](https://aws.amazon.com/lightsail/pricing/).

The subtotal excludes optional provider snapshots, additional volumes/hosts, excess transfer, paid identity/monitoring features, AI or integration usage, payment fees, taxes, support time and legal/compliance work. R2's allowances are account-wide and cannot be guaranteed per workspace. Verify [R2 pricing](https://developers.cloudflare.com/r2/pricing/) against actual use.

For a reused Google Cloud host, calculate its actual regional total instead of substituting the DigitalOcean example. No managed Postgres or dedicated relay/gateway host belongs in the initial subtotal.

The old USD 75 / 191 / 426 commercial table included different services and unproven density assumptions. It is not comparable to this scoped MVP subtotal and is retired. Model incremental hosts from measured capacity; do not publish per-customer costs using an assumed tenant count.

## 11. Delivery gates and validation

| Area | Required evidence |
| --- | --- |
| Local happy paths | Operator setup, manual workflows and complete backup/restore work without hosted login or cloud dependency |
| Hosted happy paths and UI | Assigned sign-in, records/files, multiple devices, visible save state, logout and support/expiry feedback |
| Invalid combinations and isolation | Wrong identity/audience/subject/host/workspace, missing CSRF, disabled/expired access and changed IDs fail before disclosure or mutation |
| Idempotency and retry | Original-key recovery yields one effect; changed payload conflicts; authorization precedes receipt lookup |
| Concurrency | Stale edits preserve input; explicit shared-draft takeover fences the former editor; no automatic offline replay |
| Transaction rollback | Domain changes, receipts and audit remain atomic; failed authorization/session setup grants no business authority |
| Persistence/schema | Current baseline and retained validators agree; restart does not revive revoked sessions |
| Backup/restore | Complete off-host archive restores stable IDs, attachments, relationships, totals and history; fresh authorization follows |
| Query budget and latency | Auth query ceiling, owning set-based budgets, time freshness and reference-network targets hold under measured load |
| Operations and faults | Reboot, full disk, identity/tunnel outage, failed backup/reset and rollback have tested, truthful states |

Sequence the work:

1. Preserve and validate local operation.
2. Finish the existing two-operator public-access slices in their recorded order.
3. Demonstrate current off-host recovery and four-browser behavior before invitations.
4. Run the synthetic demo and record operational workload, gross cost and latency.
5. Admit a bounded hosted MVP cohort only after its real-data security, onboarding, recovery and support gates pass.

Actual provider sign-in, cache behavior and fresh-host recovery require deployed evidence. Unit fixtures, a working DNS name or an HTML response do not establish release readiness.

## 12. Known later commercial gaps

Record these gaps without designing or purchasing their infrastructure now:

- Self-service accounts, billing/entitlements, durable account recovery and a larger placement/control plane.
- Multiple seats, shared-portfolio roles, stronger customer isolation evidence and privileged support controls.
- Qualified unattended recovery, tighter demonstrated RPO/RTO, fleet deployment/upgrades and sustainable support coverage.
- Any future relay/webhook delivery contract, including durable acknowledgement, retry/deduplication and dead-letter handling.
- Optional managed AI or other integrations with separately approved credential custody and cost controls.
- Higher availability, larger-scale unit economics, longer retention and customer-driven compliance/certification requirements.

The earlier 99.5% availability, minutes-level RPO and sub-hour host recovery figures are unproven commercial hypotheses, not commitments of the local product, demo or hosted MVP.

## 13. Consolidation record and references

The product owner approved the conflict resolutions and clarified that US scope means supported customers/properties only. Global services and storage remain eligible; operational simplicity is the selection criterion.

| Earlier disagreement | Consolidated decision |
| --- | --- |
| Demo versus commercial architecture | Three explicit modes; later commercial gaps only |
| 2 GB versus 4 GB host and assumed density | Keep the existing demo baseline; resize or add hosts from measurements |
| Managed versus colocated Postgres | Neither initially; retain minimal protected SQLite administration |
| Local files versus immediate R2/presigned transfer | Local live files, R2 encrypted archives, separately qualify future transfers |
| Database replication versus complete recovery | Daily verified complete recovery first; Litestream conditional |
| Automatic provider-backup removal | Evaluate distinct coverage and restore value before keeping or removing |
| SQLite tuning and revision-only caching | Preserve durability and time-aware live reads until evidence justifies changes |
| Pages/API subdomains called same-origin | Combined application origin initially |
| Migrations, native mail credentials and early relay/AI services | Outside current greenfield and hosting scope |
| Conflicting monthly totals | Explicit reference compute and allowances, without unproven density or omitted services |

The superseded companion notes have been removed. Their original content remains recoverable in Git history.

Planning sources: [product brief](../../../PRODUCT_BRIEF.md), [architecture](../../../ARCHITECTURE.md), [decisions](../../../DECISIONS.md), [backlog](../../../FEATURE_BACKLOG.md), [public-access implementation plan](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md), [Google Cloud deployment record](../../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md), and [cost/latency review](../../qualification/reports/HOSTED_DEMO_COST_LATENCY_REVIEW_2026-10-23.txt).

Provider documentation linked above was checked October 23, 2026. Recheck prices, account eligibility, supported features and operational terms before provisioning. This plan does not make legal or compliance claims.
