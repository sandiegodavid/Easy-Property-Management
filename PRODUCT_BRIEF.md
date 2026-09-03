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

## Design principles

- Prefer plain language: “Money received,” “Still due,” “Needs attention,” and “Service providers.”
- Keep familiar accounting and property-management concepts available when they help experienced users make decisions.
- Make the dashboard an actionable inbox, not a wall of charts.
- Preserve context while drilling down: portfolio → property → space → lease → source record.
- Keep one primary action per screen and use guided, forgiving workflows.
- Pair every status color with clear text and an icon where useful.
- Every aggregate report must open the records behind the number.
- AI may draft and summarize, but users must approve anything sent, signed, or committed.

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
8. **Repairs** — owner- or tenant-raised issue intake, reporter attribution, priority, quotes, assignment, cost, and work journals.
9. **Service providers** — services, past work, preferred/avoid status, references, and external-review links.
10. **Reports** — occupancy, rent roll, delinquency, income/expenses, owner balances/disbursements, leasing funnel, and repair cost, all with drill-down.

Owners and tenants may submit rent receipts or property issues through a lightweight secure intake flow; a manager may also record the report on their behalf. A full self-service portal is not required for the MVP.

## Explicit MVP boundaries

The MVP does not include:

- Online rent payments, autopay, bank feeds, or reconciliation.
- Automated email/SMS sending or full tenant/owner portals.
- Listing syndication, applications, screening, or e-signature.
- AI-generated contracts, leases, listing copy, schedules, or negotiation messages.
- Live reputation aggregation from Google, Yelp, Angi, or other third parties.
- Multi-unit apartment-building operations.
- Trust accounting, automated bank movement for owner disbursements, full bookkeeping, or commercial CAM reconciliation. The MVP calculates, approves, and records disbursements but does not initiate the transfer.

## Core data-model decisions

- A property may be self-owned, client-managed, or both through an explicit relationship record.
- A shared “space” concept supports homes, condos, townhomes, office suites, and later apartment units.
- One party/contact model supports owners, tenants, prospects, vendors, and companies in different roles.
- Financial entries use dated source records and drill-down allocations; settled records are voided/reversed rather than deleted.
- Owner-reported rent receipts record who reported them, when they were reported, how the owner received the funds, supporting evidence, and verification status so income is not counted twice.
- Owner disbursements retain the property, accounting period, amount, approval, payment date, method/reference, and status.
- Rent changes are effective-dated; historical rent is not overwritten.
- Every rental or property issue records the reporter and reporter role—owner, tenant, manager, or staff—along with its category and communication history.
- Work journals and key communication events are append-only history.
