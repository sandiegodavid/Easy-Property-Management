# Feature Backlog

## How to use this backlog

Each item has a stable identifier, phase, delivery sequence, outcome, and ordered dependencies. New ideas should be added here before being surfaced in the product.

Dependencies are listed from left to right in the recommended implementation order. They represent prerequisites that must be usable before the dependent item is considered complete. `None` marks a true starting point.

## MVP

| Sequence | ID | Area | Outcome | Ordered dependencies |
| ---: | --- | --- | --- | --- |
| 1 | PORT-001 | Portfolio | Mark properties as self-owned, managed for a client, or mixed. | None |
| 2 | PORT-002 | Inventory | Create and manage single-family homes, condos, townhomes, offices, and office suites. | PORT-001 |
| 3 | PORT-003 | Inventory | Show occupancy and availability by property and space. | PORT-002 |
| 4 | TEN-001 | People | Keep tenant contacts and lease participants. | PORT-001 |
| 5 | LEASE-001 | Leases | Record lease terms, deposits, dates, documents, and renewal dates. | PORT-002 → TEN-001 |
| 6 | VEND-001 | Providers | Maintain services, past work, references, and preferred/avoid status. | PORT-001 |
| 7 | VEND-002 | Providers | Store Google, Yelp, Angi, and other reputation links with notes and last-checked dates. | VEND-001 |
| 8 | FIN-001 | Money | Create recurring rent expectations and track full, partial, late, and missed payments. | LEASE-001 |
| 9 | FIN-002 | Money | Record expenses with category, property, vendor, receipt, and date. | PORT-002 → VEND-001 |
| 10 | FIN-003 | Money | Show portfolio and property income, expenses, and money remaining. | FIN-001 → FIN-002 |
| 11 | COM-001 | Communications | Log owner and tenant communication and rent/renewal follow-up. | PORT-001 → TEN-001 |
| 12 | MAINT-001 | Repairs | Log issue, reporter, reporter role, priority, status, appointment, and cost. | PORT-002 |
| 13 | MAINT-004 | Repairs | Distinguish owner-raised, tenant-raised, manager-raised, and staff-raised property issues throughout intake, communication, and reporting. | COM-001 → MAINT-001 |
| 14 | MAINT-002 | Repairs | Compare quotes and assign a selected provider. | VEND-001 → MAINT-001 |
| 15 | MAINT-003 | Repairs | Keep an append-only work journal. | MAINT-001 → MAINT-002 |
| 16 | OWNER-003 | Owner management | Let an owner report rent received directly, attach supporting evidence, and track verification without double-counting income. | PORT-001 → FIN-001 |
| 17 | OWNER-004 | Owner management | Let an owner raise and track a rental, lease, tenant, or vacancy concern. | PORT-001 → COM-001 |
| 18 | INTAKE-001 | Intake | Provide lightweight secure forms for owners and tenants to report receipts or issues without requiring a full portal. | MAINT-004 → OWNER-003 → OWNER-004 |
| 19 | OWNER-002 | Owner management | Calculate, approve, and record owner disbursements with property, period, amount, date, method/reference, and status. | FIN-003 → OWNER-003 |
| 20 | LIST-001 | Listings | Create a rental listing and hosted share page. | PORT-002 → PORT-003 |
| 21 | LEAD-001 | Leads | Track lead source, pipeline stage, notes, and next action. | LIST-001 |
| 22 | LEAD-002 | Leads | Schedule and record showings. | LEAD-001 |
| 23 | LEAD-003 | Leads | Track offers, counteroffers, and accepted terms. | LEAD-001 → LEAD-002 |
| 24 | ADJ-001 | Rent strategy | Show upcoming rent-review dates and record a manual proposed adjustment. | LEASE-001 → FIN-001 |
| 25 | RPT-001 | Reports | Provide occupancy, rent roll, delinquency, income/expense, owner balance/disbursement, leasing, and repair reports. | PORT-003 → FIN-003 → OWNER-002 → LEAD-003 → MAINT-003 → ADJ-001 |
| 26 | RPT-002 | Reports | Let every summary number drill into its source records. | RPT-001 |
| 27 | DASH-001 | Dashboard | Surface overdue rent, repairs, showings, expiring leases, owner actions, and key money totals. | RPT-001 → RPT-002 |

## Next

| Sequence | ID | Area | Outcome | Ordered dependencies |
| ---: | --- | --- | --- | --- |
| 28 | PAY-001 | Payments | Accept online rent payments and autopay. | LEASE-001 → FIN-001 |
| 29 | COM-002 | Communications | Send scheduled email/SMS reminders and track delivery. | COM-001 → FIN-001 → ADJ-001 |
| 30 | COM-003 | Communications | Sync calendar availability for showings and appointments. | MAINT-001 → LEAD-002 → COM-002 |
| 31 | FIN-004 | Money | Connect bank feeds, reconcile transactions, and manage recurring expenses. | FIN-001 → FIN-002 → FIN-003 → PAY-001 |
| 32 | PORTAL-001 | Portal | Give tenants a full self-service portal. | TEN-001 → LEASE-001 → FIN-001 → COM-001 → INTAKE-001 |
| 33 | OWNER-001 | Owner management | Generate owner statements, calculate management fees, and provide a full owner portal. | PORT-001 → FIN-003 → OWNER-003 → OWNER-002 → COM-001 → INTAKE-001 |
| 34 | LIST-002 | Listings | Syndicate listings to rental marketplaces. | LIST-001 |
| 35 | LEAD-004 | Leads | Support applications, screening, and e-signatures. | LEASE-001 → LEAD-001 → LEAD-002 → LEAD-003 |
| 36 | DOC-AI-001 | AI documents | Draft leases, addenda, notices, and other documents from approved templates. | LEASE-001 |
| 37 | DOC-AI-002 | AI documents | Summarize contracts, leases, obligations, dates, and missing information. | LEASE-001 |
| 38 | DOC-AI-003 | AI documents | Compare document versions and explain material changes. | LEASE-001 → DOC-AI-002 |
| 39 | MKT-AI-001 | AI marketing | Draft rental-listing copy from verified property details. | LIST-001 |
| 40 | SHOW-AI-001 | AI scheduling | Suggest showing times and draft confirmations or rescheduling messages. | LEAD-002 → COM-002 → COM-003 |
| 41 | NEG-AI-001 | AI negotiation | Draft offers and counteroffers within user-defined rent, term, and concession limits. | LEAD-003 |
| 42 | NEG-AI-002 | AI negotiation | Summarize negotiation history and compare proposals. | LEAD-003 → NEG-AI-001 |
| 43 | VEND-003 | Providers | Send quote requests directly to selected providers. | VEND-001 → MAINT-001 → MAINT-002 → COM-002 |
| 44 | OFFICE-001 | Commercial | Support office operating expenses and basic rent-adjustment planning. | PORT-002 → LEASE-001 → FIN-002 → ADJ-001 |

## Later

| Sequence | ID | Area | Outcome | Ordered dependencies |
| ---: | --- | --- | --- | --- |
| 45 | APT-001 | Apartments | Model multi-unit apartment buildings and units. | PORT-002 |
| 46 | APT-002 | Apartments | Support building-wide rent rolls, renewals, and bulk actions. | PORT-003 → LEASE-001 → FIN-001 → APT-001 |
| 47 | APT-003 | Apartments | Manage common areas, shared assets, parking, storage, utilities, and amenities. | FIN-002 → MAINT-001 → APT-001 |
| 48 | APT-004 | Apartments | Handle turnovers, make-ready workflows, and bulk tenant notices. | COM-002 → APT-001 → APT-002 → APT-003 |
| 49 | ACCT-001 | Accounting | Add trust accounting, automated owner fund transfers, and full bookkeeping. | OWNER-002 → FIN-004 → OWNER-001 |
| 50 | OFFICE-002 | Commercial | Add CAM/NNN reconciliation, escalations, and advanced lease options. | FIN-004 → OFFICE-001 |
| 51 | VEND-004 | Providers | Integrate live external review sources and reputation monitoring. | VEND-002 → VEND-003 |
| 52 | RPT-003 | Reports | Build custom reports, saved views, scheduled exports, and owner dashboards. | RPT-001 → RPT-002 → OWNER-001 |
| 53 | PLATFORM-001 | Platform | Add advanced roles, approval workflows, bulk import, and public API. | RPT-002 → PORTAL-001 → OWNER-001 |
| 54 | AI-REC-001 | AI recommendations | Recommend rent adjustments and renewals from approved inputs. | ADJ-001 → FIN-004 → DOC-AI-002 → OFFICE-001 |
| 55 | AI-REC-002 | AI recommendations | Assist with maintenance triage and vendor selection. | VEND-002 → MAINT-003 → VEND-003 → VEND-004 |
| 56 | AI-REC-003 | AI recommendations | Flag vacancy and delinquency risk. | RPT-002 → FIN-004 → LEAD-004 |
