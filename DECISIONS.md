# Product Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| Serve independent landlords and property managers with approximately 1–50 rentable spaces. | Agreed | Keeps workflows practical and avoids enterprise-first complexity. |
| Run the MVP locally for one operator without authentication. | Agreed | The initial product should validate the core property-management workflows without SaaS account, hosting, or collaboration complexity. |
| Store MVP records and attachments locally with backup/export and restore. | Agreed | Local operation needs a clear durability and recovery path. |
| Defer authentication, cloud workspaces, and remote user access to a future SaaS offering. | Agreed | Identity and multi-tenancy are unnecessary for the single-user local MVP. |
| Support guided migration from local storage to the future SaaS offering. | Agreed | Users must be able to adopt the cloud product without re-entering records or losing financial history, attachments, or relationships. |
| Ingest issue messages from Gmail, Outlook.com/Hotmail, and SMS sources in the MVP. | Agreed | Owners and tenants often report issues through existing communication channels, so the local operator needs one review queue. |
| Treat external account authorization separately from application authentication. | Agreed | The local MVP has no application login, but it may connect to provider APIs using credentials stored only on the operator's device. |
| Keep AI-assisted issue ingestion human-controlled. | Agreed | AI may extract fields, suggest matches and urgency, and flag duplicates, but an operator must approve or edit a draft before it becomes an official issue. |
| Include standalone voice-note issue intake with AI transcription and summarization in the MVP, without phone-call recording. | Agreed | Operators need a fast way to capture their own notes after conversations, during inspections, and on property visits. |
| Do not require preservation of source voice-note audio after successful transcription. | Agreed | The retained transcript, summary, metadata, confidence information, and operator review history are sufficient for the planned workflow and reduce local storage use. |
| Exclude external account credentials from backup and SaaS migration. | Agreed | Provider tokens are device-sensitive secrets; restored or migrated workspaces must reauthorize each external account. |
| Support self-owned, client-managed, and mixed portfolios. | Agreed | Both relationships are central to the target customer. |
| Include owner balances and manual owner-disbursement tracking in the MVP. | Agreed | Managers need to account for funds due and paid to client owners from the beginning. Electronic fund movement remains a later integration. |
| Include owner-reported rent receipts in the MVP. | Agreed | Owners may receive rent directly; source and verification tracking prevent omissions and duplicate income. |
| Capture whether a property issue was raised by an owner, tenant, manager, or staff member. | Agreed | Source attribution affects communication, responsibility, follow-up, and reporting. |
| Have the local MVP operator record owner- and tenant-reported items with source attribution. | Agreed | Direct submissions require remote access and authentication controls and therefore belong to the future SaaS offering. |
| Support single-family homes, condos, townhomes, and offices in the MVP. | Agreed | Covers initial residential and office needs while keeping operating models manageable. |
| Defer multi-unit apartment-building operations. | Agreed | Apartment-specific needs such as common areas, bulk actions, and turnover workflows are not needed initially. |
| Use a shared property/space model that can later represent apartment units. | Agreed | Avoids a costly future data-model rewrite without exposing apartment complexity now. |
| Keep documents and showings in the MVP, but defer AI assistance. | Agreed | The base workflow matters first; AI is more valuable after templates, history, and approval controls exist. |
| Treat AI as a drafting and review assistant, never an autonomous sender or signer. | Agreed | Maintains operator control for contracts, marketing, scheduling, and negotiations. |
| Track external vendor reputation with links and user-entered observations before automating sources. | Agreed | Avoids dependency, cost, and terms-of-service risk in the MVP. |
| Make report drill-down mandatory. | Agreed | Trust in financial and operational reporting depends on seeing the source records. |
| Use plain-language labels rather than accounting or CRM jargon. | Agreed | The product is intended for nontechnical users. |
