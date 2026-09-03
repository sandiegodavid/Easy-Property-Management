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

## Future accessibility for complete beginners

Later phases may support users with little or no accounting or property-management experience through guided setup, plain-language explanations, contextual checklists, safe defaults, and step-by-step workflows. This should add a beginner-friendly layer without removing the professional detail that experienced operators rely on.

## MVP modules

1. **Home** — overdue rent, urgent repairs, upcoming showings, expiring leases, and money summary.
2. **Properties** — owned versus managed relationship, property type, spaces, occupancy, and history.
3. **Tenants and leases** — contacts, terms, deposits, balances, dates, and document storage.
4. **Payments and expenses** — expected, received, partial, late, and outstanding rent; owner-reported rent receipts; expenses, vendors, categories, and receipts.
5. **Owner management** — owner balances, funds due, manual disbursement approval and recording, and owner-raised rental concerns.
6. **Listings and leads** — manual listing creation, lead pipeline, showing schedule, offers, and counteroffers.
7. **Communications and reminders** — owner and tenant interaction history, rent reminders, renewal follow-up, and completion status.
8. **Issue inbox** — ingest issue messages and attachments from connected Gmail, Outlook.com/Hotmail, and SMS sources, plus locally recorded or imported voice notes, into a local review queue.
9. **AI-assisted issue intake** — transcribe and summarize voice notes; detect likely property issues; extract the description and reporter; suggest the property, tenant, category, urgency, and next action; and flag possible duplicates for operator review.
10. **Repairs** — operator-approved owner- or tenant-raised issues, reporter attribution, priority, quotes, assignment, cost, and work journals.
11. **Service providers** — services, past work, preferred/avoid status, references, and external-review links.
12. **Reports** — occupancy, rent roll, delinquency, income/expenses, owner balances/disbursements, leasing funnel, and repair cost, all with drill-down.

Because the MVP is local and single-user, the operator records or approves rent receipts and rental/property issues reported by owners or tenants and identifies who raised each item. Messages may arrive through connected external accounts, but owners and tenants do not sign in to the application. Direct application forms and portals belong to the future SaaS offering.

Connecting Gmail, Outlook.com/Hotmail, or an SMS provider uses that provider's authorization and does not create application user accounts. Connection credentials remain local, are excluded from portable backups, and must be reauthorized after restore or migration.

Standalone voice notes may be recorded in the application or imported as audio files. The MVP does not record phone calls. After successful transcription, the source audio does not need to be retained. The application keeps the recording or import metadata, editable transcript, AI summary, confidence information, and operator decision.

## Explicit MVP boundaries

The MVP does not include:

- Online rent payments, autopay, bank feeds, or reconciliation.
- Application authentication, multiple application users, shared cloud workspaces, application-hosted remote intake, or tenant/owner portals. External mailbox and SMS-provider authorization is permitted for ingestion.
- Automated email/SMS sending.
- Listing syndication, applications, screening, or e-signature.
- AI-generated contracts, leases, listing copy, schedules, or negotiation messages.
- Live reputation aggregation from Google, Yelp, Angi, or other third parties.
- Multi-unit apartment-building operations.
- Trust accounting, automated bank movement for owner disbursements, full bookkeeping, or commercial CAM reconciliation. The MVP calculates, approves, and records disbursements but does not initiate the transfer.

## Core data-model decisions

- A property may be self-owned, client-managed, or both through an explicit relationship record.
- The MVP has one local workspace and one operator, with no authentication or cloud dependency.
- A shared “space” concept supports homes, condos, townhomes, office suites, and later apartment units.
- One party/contact model supports owners, tenants, prospects, vendors, and companies in different roles.
- Financial entries use dated source records and drill-down allocations; settled records are voided/reversed rather than deleted.
- Owner-reported rent receipts record who reported them, when they were reported, how the owner received the funds, supporting evidence, and verification status so income is not counted twice.
- Owner disbursements retain the property, accounting period, amount, approval, payment date, method/reference, and status.
- Rent changes are effective-dated; historical rent is not overwritten.
- Every rental or property issue records the reporter and reporter role—owner, tenant, manager, or staff—along with its category and communication history.
- Every ingested message retains its source, source identifier, sender, received time, attachments, sync state, and link to the original source; deduplication prevents the same message from creating multiple issues.
- Voice-note intake retains the recorder, recorded or imported time, processing status, and editable transcript without requiring the source audio to remain after successful transcription.
- AI issue suggestions retain their transcript when applicable, concise summary, extracted fields, confidence, source message when applicable, possible matches, duplicate candidates, and the operator's approve/edit/dismiss decision.
- Work journals and key communication events are append-only history.
- Records use stable identifiers and portable formats so a future migration can preserve relationships, financial totals, attachments, ingested-message history, voice-note transcripts and AI output, and review decisions when moving a local workspace to the SaaS offering. External account credentials are never migrated and must be reauthorized.
