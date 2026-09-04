# Feature Backlog

## How to use this backlog

Each item has a stable identifier, phase, delivery sequence, outcome, and ordered dependencies. New ideas should be added here before being surfaced in the product.

The sequence column gives the recommended delivery order. The dependency column contains only hard prerequisites and lists them from left to right in the preferred implementation order; it does not imply that each prerequisite depends on the one before it. `None` marks a true starting point.

The MVP is a single-user application that runs locally. It has no application authentication, cloud account, remote portal, or shared workspace. The product owner runs setup scripts for each MVP user; self-service installation and update flows are out of scope. Connections to Gmail, Outlook.com/Hotmail, and an SMS provider use provider authorization stored on the local device; they do not create application users. Voice notes are recorded or imported locally and do not require an external account.

## MVP — Local single-user

| Sequence | ID | Area | Outcome | Ordered hard dependencies |
| ---: | --- | --- | --- | --- |
| 1 | LOCAL-001 | Local data | Create one persistent, configurable external workspace for the operator's structured records, separate from the Git-maintained application checkout, with a stable ID and versioned non-secret manifest. | None |
| 2 | LOCAL-002 | Local data | Back up, export, validate, and restore the complete local workspace—SQLite data, live journal state where applicable, and workspace-relative attachments—in a versioned portable package that excludes external-account credentials. | LOCAL-001 |
| 3 | AUDIT-001 | Audit | Preserve when sensitive financial, lease, owner, vendor, issue, and ingestion records changed and retain their prior values. | LOCAL-001 |
| 4 | FILE-001 | Files | Store lease documents, receipts, issue photos, quotes, message attachments, and other files locally with portable references. | LOCAL-001 |
| 5 | TASK-001 | Tasks | Create local tasks and reminders with due dates, statuses, and related records. | LOCAL-001 |
| 6 | PORT-001 | Portfolio | Mark properties as self-owned, managed for a client, or mixed. | LOCAL-001 |
| 7 | PORT-002 | Inventory | Create and manage single-family homes, condos, townhomes, offices, and office suites. | PORT-001 |
| 8 | PORT-003 | Inventory | Show occupancy and availability by property and space. | PORT-002 |
| 9 | TEN-001 | People | Keep tenant contacts and lease participants. | PORT-001 |
| 10 | LEASE-001 | Leases | Record lease terms, deposits, dates, documents, and renewal dates. | FILE-001, PORT-002, TEN-001 |
| 11 | VEND-001 | Providers | Maintain and search providers by service, location, past work, references, and preferred/avoid status. | PORT-001 |
| 12 | VEND-002 | Providers | Store Google, Yelp, Angi, and other reputation links with notes and last-checked dates. | VEND-001 |
| 13 | FIN-001 | Money | Create recurring rent expectations and track full, partial, late, and missed payments. | AUDIT-001, LEASE-001 |
| 14 | FIN-002 | Money | Record expenses with category, property, vendor, receipt, and date. | AUDIT-001, FILE-001, PORT-002, VEND-001 |
| 15 | FIN-003 | Money | Show portfolio and property income, expenses, and money remaining. | FIN-001, FIN-002 |
| 16 | COM-001 | Communications | Log owner and tenant communication and rent/renewal follow-up. | TASK-001, TEN-001 |
| 17 | MAINT-001 | Repairs | Log property issues, priority, status, appointments, and cost. | FILE-001, TASK-001, PORT-002 |
| 18 | MAINT-004 | Repairs | Attribute issues to an owner, tenant, manager, or staff reporter throughout intake, communication, and reporting. | COM-001, MAINT-001 |
| 19 | MAINT-002 | Repairs | Compare quotes and assign a selected provider. | FILE-001, VEND-001, MAINT-001 |
| 20 | MAINT-003 | Repairs | Keep an append-only work journal. | AUDIT-001, MAINT-001, MAINT-002 |
| 21 | OWNER-003 | Owner management | Record rent an owner reports receiving directly, attach supporting evidence, and verify it without double-counting income. | AUDIT-001, FILE-001, PORT-001, FIN-001 |
| 22 | OWNER-004 | Owner management | Record and track a rental, lease, tenant, or vacancy concern raised by an owner. | TASK-001, PORT-001, COM-001 |
| 23 | OWNER-002 | Owner management | Calculate, approve, and record owner disbursements with property, period, amount, date, method/reference, and status. | AUDIT-001, FIN-003, OWNER-003 |
| 24 | LIST-001 | Listings | Create rental listings, export publish-ready content, and record manually published links and status. | FILE-001, PORT-002, PORT-003 |
| 25 | LEAD-001 | Leads | Track lead source, pipeline stage, notes, and next action. | TASK-001, LIST-001 |
| 26 | LEAD-002 | Leads | Schedule and record showings. | TASK-001, LEAD-001 |
| 27 | LEAD-003 | Leads | Track offers, counteroffers, and accepted terms, including offers made without a prior showing. | AUDIT-001, LEAD-001 |
| 28 | ADJ-001 | Rent strategy | Show upcoming rent-review dates and record a manual proposed adjustment. | AUDIT-001, TASK-001, LEASE-001, FIN-001 |
| 29 | DASH-001 | Dashboard | Provide an initial action dashboard for overdue rent, repairs, showings, expiring leases, owner actions, and key money totals. | TASK-001, PORT-003, FIN-001, MAINT-001, LEAD-002 |
| 30 | RPT-001 | Reports | Provide occupancy, rent roll, delinquency, income/expense, owner balance/disbursement, leasing, and repair reports. | PORT-003, FIN-003, MAINT-001, OWNER-002, LEAD-001 |
| 31 | RPT-002 | Reports | Let every summary number drill into its source records. | RPT-001 |
| 32 | DASH-002 | Dashboard | Connect dashboard metrics and action cards to filtered report drill-downs. | DASH-001, RPT-002 |
| 33 | AI-GOV-001 | AI governance | Require operator approval, preserve retained source records separately from editable AI output, record review decisions, and enforce configurable limits for AI-assisted actions. | AUDIT-001, FILE-001 |
| 34 | INGEST-001 | Issue ingestion | Normalize source messages, attachments, voice-note metadata, and transcripts into a local issue inbox with source IDs, thread or recording metadata, processing status, original-message links where applicable, and idempotent deduplication. | AUDIT-001, FILE-001, COM-001 |
| 35 | ISSUE-AI-001 | AI issue intake | Detect likely property issues and produce a concise draft summary, description, reporter, category, urgency, and requested action from message text or a voice transcript. | MAINT-001, AI-GOV-001, INGEST-001 |
| 36 | ISSUE-AI-002 | AI issue intake | Suggest property, space, tenant, and reporter matches and flag possible duplicate or existing issues. | PORT-002, TEN-001, MAINT-004, ISSUE-AI-001 |
| 37 | INGEST-002 | Issue ingestion | Let the operator compare every AI draft with its source message or voice transcript, then approve, edit, link, or dismiss it before an issue record is created or updated. | MAINT-001, INGEST-001, ISSUE-AI-001, ISSUE-AI-002 |
| 38 | VOICE-001 | Voice intake | Record or import a standalone audio voice note locally without recording phone calls, send it for transcription, and retain recording or import metadata without requiring permanent audio storage. | INGEST-001 |
| 39 | VOICE-AI-001 | AI voice intake | Transcribe and summarize a voice note, retain an editable transcript and confidence indicators, allow retry or manual correction, and send the result through issue extraction, matching, duplicate detection, and operator review without requiring retention of the source audio after successful transcription. | AI-GOV-001, ISSUE-AI-001, ISSUE-AI-002, INGEST-002, VOICE-001 |
| 40 | CONN-001 | Connections | Connect external mail and SMS-provider accounts and store revocable credentials in the local operating system's secure credential store. | LOCAL-001, AUDIT-001 |
| 41 | GMAIL-001 | Gmail ingestion | Read selected Gmail messages and attachments into the local issue inbox using a connected Google account. | CONN-001, INGEST-001, INGEST-002 |
| 42 | OUTLOOK-001 | Outlook ingestion | Read selected Outlook.com/Hotmail messages and attachments into the local issue inbox using a connected Microsoft account. | CONN-001, INGEST-001, INGEST-002 |
| 43 | SMS-001 | SMS ingestion | Poll a connected SMS provider or import forwarded text messages into the local issue inbox without requiring an application-hosted inbound endpoint. | CONN-001, INGEST-001, INGEST-002 |
| 44 | DASH-003 | Dashboard | Surface unprocessed sources, AI drafts awaiting review, low-confidence transcripts or matches, and ingestion failures on the local dashboard. | DASH-001, INGEST-002, VOICE-AI-001, GMAIL-001, OUTLOOK-001, SMS-001 |
| 45 | LOCAL-003 | Local setup | Provide product-owner-run scripts and a checklist to initialize or restore an MVP user's external workspace, select and validate its location, save a machine-local workspace locator, and verify readiness; warn against the Git checkout and unsupported cloud-sync locations. This is not a self-service installer or updater. | LOCAL-001, LOCAL-002, FILE-001 |
| 46 | LEAD-004 | Applications | Record applications connected to leads, including lawful employment or business information, rental references, intended occupants, and occupancy needs; protected familial-status information must not be used as an approval criterion. | AUDIT-001, FILE-001, COM-001, LEAD-001 |
| 47 | APP-FIN-001 | Applicant financials | Record applicant-provided income, recurring obligations, credit score with source and date, and asset summaries; attach bank, brokerage, or other supporting statements with consent, redacted account identifiers, verification status, and a retention or deletion date. | AUDIT-001, FILE-001, LEAD-004 |
| 48 | APP-DEC-001 | Lease approval | Record consistent approval criteria, the human decision and reasons, reviewer, date, conditions, and any required consumer-report adverse-action follow-up without using protected characteristics. | AUDIT-001, LEAD-004, APP-FIN-001 |
| 49 | VEND-CAT-001 | Provider categories | Classify providers with configurable categories such as legal, landscaping, electrical, HVAC/A/C, appliance repair, plumbing, and general maintenance. | VEND-001 |
| 50 | JUR-001 | Jurisdiction rules | Record each property's applicable rent-adjustment notice rules with jurisdiction, rule type, authoritative source link, effective date, last-verified date, and operator confirmation. | AUDIT-001, PORT-002, LEASE-001 |
| 51 | ADJ-002 | Rent strategy | Calculate the notice deadline for a proposed rent adjustment from the confirmed jurisdiction rule, create advance alerts, and record notice delivery and the effective-dated rent change; present this as a planning aid rather than legal advice. | TASK-001, ADJ-001, JUR-001 |
| 52 | ISSUE-AI-003 | AI issue diagnosis | Suggest likely causes, clarifying questions, urgency, safety or emergency escalation, and the appropriate provider category for an operator-approved issue; label the result as advisory and require operator review. | AI-GOV-001, MAINT-001, ISSUE-AI-001, ISSUE-AI-002 |
| 53 | ISSUE-AI-004 | AI provider suggestions | Suggest suitable saved providers using category, service area, preferred or avoid status, references, reputation notes, and past work journals, and explain the ranking without contacting or assigning anyone automatically. | VEND-001, VEND-002, MAINT-003, ISSUE-AI-003, VEND-CAT-001 |
| 54 | FIN-006 | Payment methods | Record the expected and actual rent-payment method, such as external automatic bank payment, check, cash, or other, using masked references and without initiating or storing bank credentials. | AUDIT-001, LEASE-001, FIN-001 |
| 55 | FIN-007 | Prepaid checks | Record a schedule of future-dated prepaid rent checks, remind the operator when the current check may be deposited, and track deposited, returned, voided, or replaced status without counting income before deposit is confirmed. | TASK-001, FIN-001, FIN-006 |
| 56 | DOC-001 | Documents | Maintain approved, versioned document templates with jurisdiction and usage metadata. | AUDIT-001, FILE-001, LEASE-001 |
| 57 | DOC-AI-001 | AI documents | Draft leases, addenda, notices, and other documents from approved templates. | AI-GOV-001, DOC-001 |
| 58 | DOC-AI-002 | AI documents | Summarize contracts, leases, obligations, dates, and missing information. | FILE-001, LEASE-001, AI-GOV-001 |
| 59 | DOC-AI-003 | AI documents | Compare document versions and explain material changes. | FILE-001, DOC-AI-002 |
| 60 | MKT-AI-001 | AI marketing | Draft rental-listing copy from verified property details. | LIST-001, AI-GOV-001 |
| 61 | AI-REC-002 | AI recommendations | Assist with maintenance triage and vendor selection, and improve issue diagnosis and provider recommendations using internal history, recorded reputation data, accumulated repair outcomes, response times, costs, and live reputation data when a future integration makes it available. | VEND-002, MAINT-003, ISSUE-AI-003, ISSUE-AI-004, AI-GOV-001 |

## Next — Connected local features

| Sequence | ID | Area | Outcome | Ordered hard dependencies |
| ---: | --- | --- | --- | --- |
| 62 | PAY-001 | Payments | Accept online rent payments and autopay through an external payment provider. | AUDIT-001, FIN-001 |
| 63 | FIN-004 | Money | Connect bank feeds and reconcile them against manually recorded or online transactions. | AUDIT-001, FIN-001, FIN-002, FIN-003 |
| 64 | FIN-005 | Money | Create recurring expenses and payable reminders. | TASK-001, FIN-002 |
| 65 | COM-002 | Communications | Send scheduled email/SMS reminders through connected accounts and track delivery. | TASK-001, COM-001, CONN-001 |
| 66 | COM-003 | Communications | Sync calendar availability for showings and maintenance appointments. | CONN-001, MAINT-001, LEAD-002 |
| 67 | OWNER-001 | Owner management | Generate owner statements from verified income, expenses, balances, and disbursements. | FIN-003, OWNER-002 |
| 68 | OWNER-005 | Owner management | Calculate management fees using configurable agreements and rules. | AUDIT-001, FIN-003, OWNER-002 |
| 69 | LIST-002 | Listings | Syndicate listings to rental marketplaces. | LIST-001 |
| 70 | SCREEN-001 | Screening | Request, receive, and record third-party tenant-screening reports with applicant consent, report source, dispute information, and adverse-action details when the report affects the decision. | AUDIT-001, LEAD-004, APP-DEC-001 |
| 71 | SIGN-001 | E-signature | Send lease documents for signature and preserve the signed version and audit evidence. | AUDIT-001, FILE-001, LEASE-001, LEAD-004 |
| 72 | SHOW-AI-001 | AI scheduling | Suggest showing times and draft confirmations or rescheduling messages. | LEAD-002, COM-002, COM-003, AI-GOV-001 |
| 73 | NEG-AI-001 | AI negotiation | Draft offers and counteroffers within user-defined rent, term, and concession limits. | AUDIT-001, LEAD-003, AI-GOV-001 |
| 74 | NEG-AI-002 | AI negotiation | Summarize negotiation history and compare human- or AI-authored proposals. | LEAD-003, AI-GOV-001 |
| 75 | AI-REC-001 | AI recommendations | Recommend rent adjustments and renewals from approved inputs. | ADJ-001, RPT-002, FIN-004, AI-GOV-001 |
| 76 | AI-REC-003 | AI recommendations | Flag vacancy and delinquency risk from financial, occupancy, and lead history. | LEAD-001, RPT-002, FIN-004, AI-GOV-001 |
| 77 | VEND-003 | Providers | Send quote requests directly to selected providers. | VEND-001, MAINT-001, MAINT-002, COM-002 |
| 78 | VEND-005 | Provider discovery | Find external providers by trade and service area and save candidates to a shortlist. | VEND-001 |
| 79 | OFFICE-001 | Commercial | Allocate office-specific operating expenses and track contractual rent adjustments. | PORT-002, LEASE-001, FIN-002, ADJ-001 |

## Later — Local product extensions

| Sequence | ID | Area | Outcome | Ordered hard dependencies |
| ---: | --- | --- | --- | --- |
| 80 | APT-001 | Apartments | Model multi-unit apartment buildings and units. | PORT-002 |
| 81 | APT-002 | Apartments | Support building-wide rent rolls, renewals, and bulk actions. | PORT-003, LEASE-001, FIN-001, APT-001 |
| 82 | APT-003 | Apartments | Manage common areas, shared assets, parking, storage, utilities, and amenities. | FIN-002, MAINT-001, APT-001 |
| 83 | APT-004 | Apartments | Handle unit turnovers and make-ready workflows. | TASK-001, FIN-002, MAINT-001, APT-001 |
| 84 | APT-005 | Apartments | Send building-wide or selected-group tenant communications and notices. | TEN-001, COM-002, APT-001 |
| 85 | APT-006 | Apartments | Add apartment-specific vacancy, rent-roll, and renewal dashboards. | RPT-002, DASH-002, APT-001, APT-002 |
| 86 | APT-007 | Apartments | Allocate shared building expenses across units, owners, or leases. | FIN-002, FIN-003, APT-001 |
| 87 | APT-008 | Apartments | Add apartment listing syndication and route leads by building and unit. | LEAD-001, LIST-002, APT-001 |
| 88 | ACCT-001 | Accounting | Add trust accounting, automated owner fund transfers, and full bookkeeping. | AUDIT-001, FIN-004, OWNER-002 |
| 89 | OFFICE-002 | Commercial | Add CAM/NNN reconciliation, escalations, and advanced lease options. | FIN-004, OFFICE-001 |
| 90 | VEND-004 | Providers | Integrate live external review sources and reputation monitoring. | VEND-002 |
| 91 | RPT-003 | Reports | Build custom reports and saved report views. | RPT-002 |
| 92 | RPT-004 | Reports | Schedule report generation and delivery. | TASK-001, COM-002, RPT-003 |
| 93 | DATA-001 | Data | Import properties, contacts, leases, balances, and history from structured files into the local workspace. | AUDIT-001, FILE-001, PORT-002, TEN-001, LEASE-001, FIN-001 |
| 94 | BEGIN-001 | Beginner experience | Guide users with little accounting or property-management experience through initial setup. | LOCAL-001, PORT-001, PORT-002, TEN-001 |
| 95 | BEGIN-002 | Beginner experience | Explain accounting and property-management concepts contextually without removing professional detail. | BEGIN-001 |
| 96 | BEGIN-003 | Beginner experience | Provide step-by-step checklists, safe defaults, validation, and recovery guidance. | AUDIT-001, TASK-001, BEGIN-001 |

## Future SaaS — Cloud, identity, and collaboration

| Sequence | ID | Area | Outcome | Ordered hard dependencies |
| ---: | --- | --- | --- | --- |
| 97 | SAAS-001 | Cloud platform | Host tenant-isolated cloud workspaces for the SaaS offering. | LOCAL-001 |
| 98 | SEC-001 | Authentication | Authenticate SaaS users and manage account recovery and sessions. | SAAS-001 |
| 99 | SEC-002 | Authorization | Enforce workspace roles and permissions for administrators, managers, accounting users, maintenance users, owners, tenants, and read-only users. | PORT-001, SEC-001 |
| 100 | SAAS-002 | Migration | Analyze a local workspace, verify its format, map it to a cloud account, and provide a dry-run migration plan that excludes external-account credentials. | LOCAL-002, SAAS-001, SEC-001 |
| 101 | SAAS-003 | Migration | Migrate local records, attachments, ingested-message history, voice-note transcripts and summaries, and AI review decisions while preserving stable IDs, relationships, audit history, and financial totals. | AUDIT-001, FILE-001, SAAS-002 |
| 102 | SAAS-004 | Migration | Validate migrated totals and record counts, support safe retry or rollback, and require external-account reauthorization. | SAAS-003 |
| 103 | SEC-003 | Secure intake | Issue expiring, scoped submission links and protect public intake with validation, rate limits, and an audit trail. | AUDIT-001, FILE-001, SEC-001, SEC-002 |
| 104 | INTAKE-001 | Intake | Let owners and tenants directly report rent receipts, rental concerns, and property issues without a full portal. | MAINT-004, OWNER-003, OWNER-004, SEC-003 |
| 105 | PORTAL-001 | Tenant portal | Give tenants a self-service portal for leases, balances, messages, and issues. | TEN-001, LEASE-001, FIN-001, COM-001, SEC-001, SEC-002, INTAKE-001 |
| 106 | PORTAL-002 | Owner portal | Give owners a portal for statements, balances, disbursements, fees, messages, receipts, and issues. | PORT-001, COM-001, OWNER-001, OWNER-005, SEC-001, SEC-002, INTAKE-001 |
| 107 | RPT-005 | Reports | Publish authenticated owner-facing dashboards. | RPT-002, OWNER-001, PORTAL-002 |
| 108 | PLATFORM-001 | Platform | Add advanced roles and configurable approval workflows. | AUDIT-001, SEC-002 |
| 109 | API-001 | Platform | Provide a secured public API and event webhooks. | AUDIT-001, SAAS-001, SEC-002, PLATFORM-001 |
