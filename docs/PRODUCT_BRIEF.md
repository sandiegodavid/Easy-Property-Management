# Property Management Product Brief

## Product purpose

Create an easy-to-use web application for independent landlords and property managers to run small portfolios without technical skills. The product should respect and leverage users' existing accounting and property-management knowledge rather than hiding useful professional concepts.

The product should make three questions easy to answer:

1. What needs my attention now?
2. How is the money doing?
3. What should happen next for each property, tenant, lead, or repair?

## Target customer

Independent landlords and property managers responsible for roughly 1–50 rentable spaces.

They do not need technical skills, but they are expected to have practical accounting and/or property-management experience in the initial release.

They may manage:

- Properties they own themselves.
- Properties owned by clients.
- A mix of both.
- Single-family homes, condos, townhomes, and offices in the initial release.

## MVP promise

From one dashboard, a user can see what money is due, what is vacant, what needs attention, and drill into the underlying property, tenant, transaction, lead, or repair.

The MVP is a single-user application that runs locally for the operator. It requires no account or login, stores its records and attachments locally, and provides backup/export and restore. The product owner sets up each MVP user's local instance with operator-run setup scripts; self-service installation and update flows are not required. Authentication, shared cloud workspaces, and remote user access belong to a future SaaS offering.

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

Database references to attachments use workspace-relative paths so the whole workspace can be moved, restored, exported, or later migrated to SaaS without rewriting machine-specific absolute paths. Provider credentials and tokens remain in the operating system credential store, keyed to the workspace ID; they are not written to the manifest, database export, or backup.

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
- Voice-note audio is an input to transcription rather than a required permanent record; retain the editable transcript, AI summary, and operator review history.
- Residential lease decisions use consistent, documented criteria and must not use familial status or another protected characteristic. Household information is limited to lawful occupancy and lease-administration needs.
- Applicant credit and financial evidence is collected for a stated purpose with consent, redacted where practical, and assigned a retention or deletion date.
- Jurisdiction-based notice alerts show the rule source, effective date, and last verification and require operator confirmation; they are planning aids, not legal advice.
- AI issue diagnosis and provider suggestions are advisory, surface possible safety or emergency escalation, and never contact or assign a provider without operator approval.

## Future accessibility for complete beginners

Later phases may support users with little or no accounting or property-management experience through guided setup, plain-language explanations, contextual checklists, safe defaults, and step-by-step workflows. This should add a beginner-friendly layer without removing the professional detail that experienced operators rely on.

## MVP modules

1. **Home** — overdue rent, urgent repairs, upcoming showings, expiring leases, and money summary.
2. **Properties** — owned versus managed relationship, property type, spaces, occupancy, and history.
3. **Tenants and leases** — contacts, terms, deposits, balances, dates, document storage, rent-adjustment notice deadlines, and effective-dated changes.
4. **Payments and expenses** — expected, received, partial, late, and outstanding rent; payment methods and prepaid-check deposit reminders; owner-reported rent receipts; expenses, vendors, categories, and receipts.
5. **Owner management** — owner balances, funds due, manual disbursement approval and recording, and owner-raised rental concerns.
6. **Listings, leads, and applicants** — manual listing creation, lead pipeline, showing schedule, offers and counteroffers, applications, lawful applicant qualification records, supporting financial evidence, and human approval decisions.
7. **Communications and reminders** — owner and tenant interaction history, rent reminders, renewal follow-up, and completion status.
8. **Issue inbox** — ingest issue messages and attachments from connected Gmail, Outlook.com/Hotmail, and SMS sources, plus locally recorded or imported voice notes, into a local review queue.
9. **AI-assisted issue intake and maintenance guidance** — transcribe and summarize voice notes; detect likely property issues; extract the description and reporter; suggest the property, tenant, category, urgency, likely causes, clarifying questions, and next action; flag possible duplicates; assist with maintenance triage and vendor selection; and improve recommendations from internal history, repair outcomes, response times, costs, and recorded reputation data. Live reputation data may enrich recommendations when a later integration is available.
10. **Repairs** — operator-approved owner- or tenant-raised issues, reporter attribution, priority, quotes, assignment, cost, and work journals.
11. **Service providers** — configurable service categories, past work, preferred/avoid status, references, and external-review links.
12. **Reports** — occupancy, rent roll, delinquency, income/expenses, owner balances/disbursements, leasing funnel, and repair cost, all with drill-down.
13. **AI-assisted documents and marketing** — maintain approved document templates; draft leases, addenda, notices, and listing copy; summarize obligations and missing information; and compare document versions, always subject to operator review.

Because the MVP is local and single-user, the operator records or approves rent receipts and rental/property issues reported by owners or tenants and identifies who raised each item. Messages may arrive through connected external accounts, but owners and tenants do not sign in to the application. Direct application forms and portals belong to the future SaaS offering.

Connecting Gmail, Outlook.com/Hotmail, or an SMS provider uses that provider's authorization and does not create application user accounts. Connection credentials remain local, are excluded from portable backups, and must be reauthorized after restore or migration.

Standalone voice notes may be recorded in the application or imported as audio files. The MVP does not record phone calls. After successful transcription, the source audio does not need to be retained. The application keeps the recording or import metadata, editable transcript, AI summary, confidence information, and operator decision.

The MVP records payment methods, including externally arranged automatic bank payments, but does not initiate transfers or store online-banking credentials. Future-dated prepaid checks are tracked as a schedule and are not counted as received income until deposit is confirmed.

## Explicit MVP boundaries

The MVP does not include:

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
- The MVP has one local workspace and one operator, with no authentication or cloud dependency.
- The selected workspace path lives in a machine-local locator outside both Git and the workspace; the workspace itself has a stable ID and versioned, non-secret manifest.
- User data is stored in a configurable external workspace, with the SQLite database, its live journal files, attachments, exports, and backups kept together; application code must not infer this path from its Git checkout.
- Attachment references are workspace-relative. Workspace relocation and restore verify the complete database-and-files set before switching the locator.
- A shared “space” concept supports homes, condos, townhomes, office suites, and later apartment units.
- One party/contact model supports owners, tenants, prospects, vendors, and companies in different roles.
- Financial entries use dated source records and drill-down allocations; settled records are voided/reversed rather than deleted.
- Owner-reported rent receipts record who reported them, when they were reported, how the owner received the funds, supporting evidence, and verification status so income is not counted twice.
- Owner disbursements retain the property, accounting period, amount, approval, payment date, method/reference, and status.
- Rent changes are effective-dated; historical rent is not overwritten.
- Applicant records distinguish lawful occupancy and lease-administration information from protected characteristics, which are not approval criteria.
- Applicant financial records retain the stated purpose, consent, source, received and verified dates, redaction status, decision use, and retention or deletion date.
- Lease-approval decisions retain the criteria applied, reviewer, decision, reasons, conditions, and any consumer-report adverse-action follow-up.
- Rent-adjustment rules are versioned by jurisdiction, effective date, source, and last verification; alerts retain the rule version and operator confirmation used for the calculation.
- Rent receipts retain expected and actual payment methods. Future-dated checks remain scheduled instruments until their deposit is confirmed.
- Providers may have multiple configurable service categories, and AI suggestions retain their rationale, evidence, confidence, safety flags, and operator decision.
- Every rental or property issue records the reporter and reporter role—owner, tenant, manager, or staff—along with its category and communication history.
- Every ingested message retains its source, source identifier, sender, received time, attachments, sync state, and link to the original source; deduplication prevents the same message from creating multiple issues.
- Voice-note intake retains the recorder, recorded or imported time, processing status, and editable transcript without requiring the source audio to remain after successful transcription.
- AI issue suggestions retain their transcript when applicable, concise summary, extracted fields, confidence, source message when applicable, possible matches, duplicate candidates, and the operator's approve/edit/dismiss decision.
- Work journals and key communication events are append-only history.
- Records use stable identifiers and portable formats so a future migration can preserve relationships, financial totals, attachments, ingested-message history, voice-note transcripts and AI output, and review decisions when moving a local workspace to the SaaS offering. External account credentials are never migrated and must be reauthorized.
