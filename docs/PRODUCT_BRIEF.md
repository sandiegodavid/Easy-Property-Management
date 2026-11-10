# Property Management Product Brief

## Product purpose

Create an easy-to-use web application for independent landlords and property managers to run small portfolios without technical skills. The product should respect and leverage users' existing accounting and property-management knowledge rather than hiding useful professional concepts.

The product should make three questions easy to answer:

1. What needs my attention now?
2. How is the money doing?
3. What should happen next for each property, tenant, lead, or repair?

## Target customer

Independent landlords and property managers typically responsible for roughly 1–50 rentable spaces. This describes the target customer, not a hosted property/space entitlement.

They do not need technical skills, but they are expected to have practical accounting and/or property-management experience in the initial release.

They may manage:

- Properties they own themselves.
- Properties owned by clients.
- A mix of both.
- Single-family homes, condos, townhomes, and offices in the initial release.

## MVP promise

From one dashboard, a user can see what money is due, what is vacant, what needs attention, and drill into the underlying property, tenant, transaction, lead, or repair.

The implemented core is a local, single-operator application with no required cloud account or login, local records and attachments, and backup/export and restore. Product-owner setup scripts remain available. Preserve this free local offering without requiring hosted billing or adding local/cloud synchronization.

The [hosted MVP design](hosting/design/HOSTED_MVP_DESIGN.md) defines the fresh hosted direction: an Admin portal, automated operator onboarding, subscriptions, backups and independently scheduled releases, initially on Google Cloud with Cloudflare. It is a design and qualification target, not a claim that these services are deployed or that planned services are already implemented. The backlog now schedules HOSTED-001, then PORTAL-001/002.

## First hosted release — Pilot 0

HOSTED-001 starts at H01 and releases Pilot 0 at H06: five invited operators on Free 50 MB workspaces, Admin-lite provisioning, nightly verified off-host backups with rehearsed restore, continuously running containers and one announced maintenance window. No Stripe, paid plan enrollment, per-operator update scheduling or idle-wake automation. Manual handling is acceptable where ownership, safe retry and operational time/cost are recorded. Isolation, identity and recovery checks still precede real records. Later hosted slices deliver the full catalog and automation below.

## Hosted offering and future tenant payments

One verified operator identity owns one hosted workspace and one subscription. The same operator can work from multiple devices with full business permissions, subject to account, maintenance, storage and record-revision checks. There are no staff roles or shared credentials. Admin provisions operators within measured capacity; the target grows from a few toward 100 operators, without a fixed operator count or property/space allowance.

The provisional monthly USD catalog is:

| Benefit | Free | Paid 1 — $10/month | Paid 2 — $20/month |
| --- | --- | --- | --- |
| Usable workspace storage | 50 MB | 200 MB | 1 GB |
| Backups | Nightly; seven nightly points | Recent 15-minute recovery-point target; fine-grained last 24 hours, then daily through 30 days | Recent 15-minute recovery-point target; fine-grained last 24 hours, then daily through 90 days |
| Runtime | May suspend after about 15 minutes without human activity; wake on access | Keep warm initially | Keep warm initially |
| Supported imports, when implemented | Included | Included | Included |
| Tenant portal/payments | Not included | Intended future benefit | Intended future benefit |

Storage uses decimal bytes (50,000,000 / 200,000,000 / 1,000,000,000) and counts business database usage plus retained managed files, including retained versions, without double-counting shared content or database/WAL representations. There is no separate attachment allowance. Backups, temporary processing, authentication/control state and physical headroom have separate host reservations. Prices, allowances and recovery objectives require measurement and publication approval; they are not authorization to charge or contractual service guarantees. Imports and tenant payments are not yet delivered and must not be advertised as available. Initially, paid value is storage and stronger recovery; Free still includes export and recovery assistance.

Admin invites an operator into a dedicated container with private persistent SQLite/files and a per-operator subdomain. Default to an empty workspace; a synthetic portfolio is optional. Business access remains disabled during setup. Managed Google sign-in or email-link login verifies the invited identity; successful claim activates access automatically after readiness and off-host recovery checks. Admin access is separate and requires MFA. Central login hands off to an exact registered operator origin with host-only sessions; knowing a subdomain does not grant access.

Settings shows workspace usage and subscription controls; Stripe Checkout/Billing/Customer Portal supplies the subscription payment flows. Apply upgrades only after verified payment and verified capacity/policy changes. Downgrades and cancellation take effect at paid-period end; existing paid subscribers have a seven-day renewal-payment grace. Retain data when Free or a smaller tier is over quota, block unadmitted growth, and preserve login, billing repair, reads/export, backups and supported cleanup. Already-promised backup expiry remains honored. Subscription cancellation, access disablement and workspace retirement are separate operations. Automated recovery requires Admin confirmation; release upgrades use suggested low-activity windows with operator scheduling and safe draining across devices.

[PAY-001](active/PAY-001_DESIGN.md) defines future hosted-only tenant rent payments, available to operators on either paid tier once separately qualified and delivered. Tenants have individual lease-scoped identities and no subscription charge. The intended feature covers rent balance, one-time bank payments, capped fixed-amount autopay, history/receipts and payment help. One verified owner/operator receives each lease's funds directly through the processor; recipient-paid processor fees are disclosed separately, with no initial EPM transaction markup. Choosing Stripe for operator subscriptions does not select or qualify a rent-payment processor. PORTAL-001 adds published lease terms, shared FIN-009 assessed late-fee explanations and tenant issue reporting. PORTAL-002 adds owner-scoped rent/fees/terms/payments, concern reporting and reports. General messaging and unrestricted document libraries remain later extensions. Both portals include matching operator workflows and use source-owned records; owner paid-tier inclusion is provisional until commercial confirmation.

Tenant payments and the tenant/owner portals follow the hosting task in the immediate backlog order, rather than gating Pilot 0. PAY-001 must consume the hosted identity and effective subscription capabilities rather than create a separate manual pilot-entitlement system. Tenant grants, payment authorization, reconciliation and recovery safeguards still require payment-specific implementation and acceptance. No design here authorizes real funds or claims deployed payment capability.

## Local workspace design

Application code is Git-maintained separately from each user's workspace. A workspace is an operator-selected external folder, never a subfolder of the application checkout, that contains the SQLite database, attachments, exports, and backups. This keeps real records out of Git while allowing the application, migrations, templates, and setup tools to be versioned normally.

The application stores only a small machine-local workspace locator in the operating system's application-settings location. It records the selected workspace path and recent workspaces; it does not contain the user's operating records. On first launch, or when the configured workspace is unavailable, the application offers **Create workspace** or **Open workspace** with an operating-system folder picker rather than silently creating a new empty database.

Each workspace has a small non-secret manifest and a portable layout:

```text
chosen-workspace/
├── workspace.json              # workspace ID, display name, format version
├── database/property-management.sqlite
├── files/                      # documents and attachments
├── exports/
└── backups/
```

Database references to attachments use workspace-relative paths so the whole workspace can be moved, restored, exported, or later migrated to SaaS without rewriting machine-specific absolute paths. For local use, provider credentials and tokens remain in the operating system credential store, keyed to the workspace ID; they are not written to the manifest, database export, or backup. Hosted deployments instead use protected platform secret/key custody, persistent private mounts and unattended encrypted off-host recovery under the hosted design; operators do not choose server paths or supply a passphrase for scheduled hosted backups.

The product-owner setup workflow selects the external location, validates that it is writable and not inside the Git checkout, initializes or restores the workspace, and records the selected path in the machine-local locator. It should warn against using a cloud-sync folder for a live SQLite database unless that configuration has been explicitly supported and tested.

Users can inspect, back up, open, or move the workspace through **Settings → Data & Backup**. Moving it is a guided copy-and-verify operation: pause writes, make a consistent backup, copy database and files, validate the new location, update the locator, reopen, and retain the old copy until the operator confirms it may be removed. While the database is live, backups use SQLite's consistent-backup mechanism rather than copying only the main database file.

## Design principles

- Prefer plain language: “Money received,” “Still due,” “Needs attention,” and “Service providers.”
- Keep familiar accounting and property-management concepts available when they help experienced users make decisions.
- Make the dashboard an actionable inbox, not a wall of charts.
- Preserve context while drilling down: portfolio → property → space → lease → source record.
- Keep one primary action per screen and use guided, forgiving workflows.
- Pair every status color with clear text and an icon where useful.
- Every aggregate report must open the records behind the number.
- AI may draft and summarize, but users must approve anything sent, signed, or committed.
- AI-created issue records remain drafts until the local operator reviews and approves them against the original message.
- The post-MVP voice-note extension treats audio as an input to transcription rather than a required permanent record; it retains the editable transcript, AI summary, and operator review history.
- Residential lease decisions use consistent, documented criteria and must not use familial status or another protected characteristic. Household information is limited to lawful occupancy and lease-administration needs.
- Applicant credit and financial evidence is collected for a stated purpose with consent, redacted where practical, and assigned a retention or deletion date.
- Jurisdiction-based notice alerts show the rule source, effective date, and last verification and require operator confirmation; they are planning aids, not legal advice.
- AI issue diagnosis and provider suggestions are advisory, surface possible safety or emergency escalation, and never contact or assign a provider without operator approval.

## Confirmed operator experience

The [UI-001 operator design](ui/operator-experience.md), confirmed September 23, 2026, defines the interaction contract: configurable Home, Properties, Owners, Leasing, Money, Maintenance, and Providers destinations; searchable property/owner directories; contextual workspaces; Light/Dark appearance; and inline disclosure through the entire non-editable summary bar. Inputs and commit actions appear only inside expanded content or dedicated workflow pages. Show the hint: “Click anywhere on an item’s summary bar to expand or collapse its details.”

Home separates actionable, waiting, and upcoming work, with visible appointments and information gaps. Waiting retains follow-up context without changing original deadlines or concealing urgent unresolved work. Information review distinguishes recorded information, missing required information, review needs, and justified non-applicability. Resumable drafts, source drill-down, and precise partial-success feedback support operator trust.

Planned post-MVP workflows include manual eviction/legal-matter preparation and process tracking with attorney/provider links, evidence, dated milestones, confirmed deadline sources, and explicit closure outcomes. It does not infer legal eligibility or automatically change leases, occupancy, or money. Property-linked HOA work covers violation notices and narrow coordination of an HOA-covered common-element repair: one Maintenance-owned case can appear across affected managed condo units while retaining every association contact and follow-up until physical verification. Standing rules management, architectural approvals, assessments, and broader HOA administration remain post-MVP.

Planned onboarding imports support Excel uploads and direct read-only Google Sheets snapshots for properties, owners, and providers on all tiers. These imports are not implemented and are outside the hosting task. The operator maps columns and relationships, reviews validation/duplicates, and confirms create/link/skip operations. Import does not silently merge or overwrite records, write to source sheets, or continuously synchronize. Broader lease/balance/history migration remains later scope.

## Future accessibility for complete beginners

Later phases may support users with little or no accounting or property-management experience through guided setup, plain-language explanations, contextual checklists, safe defaults, and step-by-step workflows. This should add a beginner-friendly layer without removing the professional detail that experienced operators rely on.

## Business modules and functional direction

This catalog describes business areas, not a claim that every workflow is delivered or an immediate hosting prerequisite. Use the backlog for current phase/status; HOSTED-001 and the tenant/owner follow-up define immediate delivery priority.

1. **Home** — overdue rent, urgent repairs, upcoming showings, expiring leases, money summary, and a simple value snapshot showing tracked income, estimated cost avoided and time saved, retention, and issue-resolution speed. Metrics show their source records and clearly label estimates and operator-configured baselines.
2. **Properties** — owned versus managed relationship, property type, spaces, occupancy, and history.
3. **Tenants, leases, and condition reports** — contacts, terms, agreed deposits, dates, document storage, effective-dated changes, and evidence-backed pre-move-in/post-move-out walkthroughs.
4. **Payments, deposits, and expenses** — expected, received, partial, late, and outstanding rent; payment methods and prepaid-check deposit reminders; security-deposit receipt and operator-approved settlement; owner-reported rent receipts; expenses, vendors, categories, and receipts.
5. **Owner management** — owner balances, funds due, manual disbursement approval and recording, and client-owner-raised general rental, lease, tenant, and vacancy concerns.
6. **Listings, leads, and applicants** — manual listing creation, lead pipeline, showing schedule, offers and counteroffers, applications, lawful applicant qualification records, supporting financial evidence, and human approval decisions.
7. **Communications and reminders** — a manual local owner/tenant interaction ledger, typed property/lease/rent context, and task-based rent or renewal follow-up. It records completed or received contacts; it does not send or ingest messages in this slice.
8. **Issue inbox** — ingest issue messages and attachments from connected Gmail, Outlook.com/Hotmail, and SMS sources, plus locally recorded or imported voice notes, into a local review queue.
9. **AI-assisted issue intake and maintenance guidance** — transcribe and summarize voice notes; detect likely property issues; extract the description and reporter; suggest the property, tenant, category, urgency, likely causes, clarifying questions, and next action; flag possible duplicates; assist with maintenance triage and vendor selection; and improve recommendations from internal history, repair outcomes, response times, costs, and recorded reputation data. Live reputation data may enrich recommendations when a later integration is available.
10. **Repairs** — operator-approved owner- or tenant-raised issues, reporter attribution, priority, quotes, assignment, cost, and work journals.
11. **Service providers** — configurable service categories, past work, preferred/avoid status, references, and external-review links.
12. **Reports** — occupancy, rent roll, delinquency, income/expenses, owner balances/disbursements, leasing funnel, and repair cost, all with drill-down.
13. **AI-assisted documents and marketing** — maintain approved document templates; draft leases, addenda, notices, and listing copy; summarize obligations and missing information; and compare document versions, always subject to operator review.

In the local single-operator application, the operator records or approves rent receipts and rental/property issues reported by owners or tenants and identifies who raised each item. Owners and tenants do not sign in to the local application. The hosted MVP adds managed operator access; tenant access remains deferred. PAY-001 supplies the paid payment engine for PORTAL-001; PORTAL-002 supplies owner access. The initial portal plan includes their required workflows and source prerequisites after hosting.

Connecting Gmail, Outlook.com/Hotmail, or an SMS provider uses that provider's authorization and does not create application user accounts. Connection credentials remain local, are excluded from portable backups, and must be reauthorized after restore or migration.

Standalone voice notes may be recorded in the application or imported as audio files. The MVP does not record phone calls. After successful transcription, the source audio does not need to be retained. The application keeps the recording or import metadata, editable transcript, AI summary, confidence information, and operator decision.

The current operator application records payment methods, including externally arranged automatic bank payments, without initiating transfers or storing online-banking credentials. Planned hosted PAY-001 adds processor-mediated collection through its separate tenant authorization boundary. A future-dated prepaid check covers one complete rent-expectation period, creates a property-local deposit reminder, and is not counted as received income until a confirmed correlated receipt/allocation handoff. Returned, voided, and replacement checks retain history without storing raw check or bank data.

## Local offering boundaries

These boundaries apply to the local operator offering. The hosted design separately includes managed operator identity, subscriptions, automated provisioning/recovery and operational email. PAY-001 defines deferred hosted tenant rent payments, individual tenant access and payment-specific transactional email; FIN-004 separately owns planned bank feeds/reconciliation. The backlog schedules hosted and portal delivery explicitly; design approval alone does not establish payment availability.

- Initiating online rent payments or autopay, bank feeds, or reconciliation. The MVP may record an externally arranged automatic-payment method.
- Application authentication, multiple application users, shared cloud workspaces, application-hosted remote intake, or tenant/owner portals. External mailbox and SMS-provider authorization is permitted for ingestion.
- Automated email/SMS sending.
- Listing syndication, automated or third-party tenant-screening integrations, or e-signature. Manual application and approval records are included.
- AI-assisted showing coordination, negotiation drafting, rent or renewal recommendations, and vacancy or delinquency risk scoring. AI-assisted documents and listing drafts are included with operator approval.
- Live reputation aggregation from Google, Yelp, Angi, or other third parties.
- Multi-unit apartment-building operations.
- Trust accounting, automated bank movement for owner disbursements, full bookkeeping, or commercial CAM reconciliation. The MVP calculates, approves, and records disbursements but does not initiate the transfer.

## Core data-model decisions

- A property may be self-owned, client-managed, or both through an explicit relationship record.
- Local use has one workspace and one operator, with no required authentication or cloud dependency. Hosted use assigns one verified operator identity to one private workspace/subscription; multiple devices share full business permissions with revision conflicts rather than silent last-writer-wins saves.
- The selected workspace path lives in a machine-local locator outside both Git and the workspace; the workspace itself has a stable ID and versioned, non-secret manifest.
- Local user data is stored in a configurable external workspace, with the SQLite database, its live journal files, attachments, exports, and backups kept together; application code must not infer this path from its Git checkout. Hosted workspaces use platform-assigned private persistent directories outside container images, with separately reserved control/scratch capacity and verified encrypted off-host recovery. Replacing a container does not delete its workspace.
- Attachment references are workspace-relative. Workspace relocation and restore verify the complete database-and-files set before switching the locator.
- A shared “space” concept supports homes, condos, townhomes, office suites, and later apartment units.
- The US-only MVP requires US property addresses and stores one canonical US IANA time zone inferred locally from each structured address; date-relative lease, finance, task, and reporting behavior uses that property zone rather than the server process's ambient time zone. International addresses, time zones, and currencies are deferred.
- One party/contact model supports owners, tenants, prospects, vendors, and companies in different roles.
- Financial entries use dated source records and drill-down allocations; settled records are voided/reversed rather than deleted.
- Owner-reported rent receipts record who reported them, when they were reported, how the owner received the funds, supporting evidence, and verification status so income is not counted twice.
- Owner disbursements retain the property, accounting period, amount, approval, payment date, method/reference, and status.
- Rent changes are effective-dated; historical rent is not overwritten.
- Applicant records distinguish lawful occupancy and lease-administration information from protected characteristics, which are not approval criteria.
- Applicant financial records retain the stated purpose, consent, source, received and verified dates, redaction status, decision use, and retention or deletion date.
- Lease-approval decisions retain the criteria applied, reviewer, decision, reasons, conditions, and any consumer-report adverse-action follow-up.
- Rent-adjustment rules are versioned by jurisdiction, effective date, source, and last verification; alerts retain the rule version and operator confirmation used for the calculation.
- Rent receipts retain an immutable actual payment-method snapshot; the product does not maintain an expected payment method. Future-dated checks remain scheduled instruments until their deposit is confirmed.
- Move-in and move-out condition reports preserve separate observations and supporting files for the lease's space. Comparisons may identify possible damage or maintenance needs, but only a separate operator-reviewed financial workflow may approve a security-deposit deduction or refund.
- Providers may have multiple configurable service categories, and AI suggestions retain their rationale, evidence, confidence, safety flags, and operator decision.
- Every rental or property issue records the reporter and reporter role—owner, tenant, manager, or staff—along with its category and communication history.
- Every ingested message retains its source, source identifier, sender, received time, attachments, sync state, and link to the original source; deduplication prevents the same message from creating multiple issues.
- Voice-note intake retains the recorder, recorded or imported time, processing status, and editable transcript without requiring the source audio to remain after successful transcription.
- AI issue suggestions retain their transcript when applicable, concise summary, extracted fields, confidence, source message when applicable, possible matches, duplicate candidates, and the operator's approve/edit/dismiss decision.
- Work journals and key communication events are append-only history.
- Records use stable identifiers and portable formats so a future migration can preserve relationships, financial totals, attachments, ingested-message history, voice-note transcripts and AI output, and review decisions when moving a local workspace to the SaaS offering. External account credentials are never migrated and must be reauthorized.
