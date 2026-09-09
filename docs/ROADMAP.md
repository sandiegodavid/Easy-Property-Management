# Product Roadmap

## Now — MVP foundation

The pre-UI phase is backend/API and validation work only. Do not begin React screens, shared web packages, or other UI development until `UI-001`, immediately before `DASH-001`, begins.

Deliver complete, understandable workflows for:

- A single local operator with no account or login.
- A configurable external local workspace for records and attachments, separate from Git-maintained application code, with backup/export and restore.
- Operator-run setup scripts to initialize or restore each user's local workspace, select data and backup locations, record its machine-local locator, and verify readiness.
- Portfolio setup for self-owned and client-managed properties.
- Single-family homes, condos, townhomes, and offices.
- Tenants, leases, pre-move-in/post-move-out condition reports, rent tracking, security-deposit settlement, recorded payment methods, prepaid-check deposit reminders, expenses, and basic communication history.
- Jurisdiction-sourced notice-deadline alerts and effective-dated rent adjustments with operator confirmation.
- Owner-reported rent receipts, owner balances, and manual owner-disbursement tracking.
- Operator-recorded owner/tenant reports with clear attribution for rental and property issues.
- Local ingestion of issue messages and attachments from connected Gmail, Outlook.com/Hotmail, and SMS sources.
- AI-assisted issue detection, structured field extraction, property/reporter matching, urgency suggestions, duplicate detection, advisory diagnosis, maintenance triage, and provider recommendations informed by internal history, outcomes, response times, costs, and recorded reputation data.
- Local voice-note recording/import with AI transcription, concise issue summaries, editable results, and review history.
- Listing, lead, showing, offer, application, applicant-financial, and human lease-approval tracking.
- Approved document templates plus AI-assisted document drafting, summarization, comparison, and rental-listing drafts with operator approval.
- Repair intake, quotes, configurable provider categories, vendor history, and work journals.
- Action dashboard and drill-down reporting.

Success means a small operator can complete the monthly rent, vacancy-to-lease, and repair-to-completion workflows without a spreadsheet.

## Next — Connect and assist locally

- Online payments, autopay, bank feeds, and recurring expenses.
- Email/SMS reminders, two-way communication, and calendar connections.
- Owner statements and management fees.
- Listing syndication, third-party tenant-screening integrations, and e-signatures.
- AI-assisted showing coordination and negotiation drafting with user approval.
- AI recommendations for rent adjustments, renewals, vacancy risk, and delinquency risk.
- Vendor quote requests and manually managed external reputation links.
- Basic commercial rent-adjustment planning and office operating-expense support.

## Later — Scale and optimize

- Multi-unit apartment-building support, including common areas, turnovers, and bulk actions.
- Trust accounting, automated owner fund transfers, advanced commercial leases, CAM/NNN reconciliation, and accounting integrations.
- Live reputation integrations and vendor monitoring.
- Custom reports, scheduled exports, advanced permissions, public API, and bulk imports.

## Future SaaS — Share and collaborate

- Cloud-hosted, tenant-isolated workspaces with authentication and user roles.
- A guided migration that moves local records and attachments to the cloud while preserving stable IDs, history, and financial totals.
- Migration of ingested-message history, voice-note transcripts and summaries, and AI review decisions, followed by explicit reauthorization of external accounts.
- Migration validation, retry, and rollback safeguards.
- Secure direct intake from owners and tenants.
- Full tenant and owner portals.
- Advanced approval workflows, public API access, and event webhooks.
