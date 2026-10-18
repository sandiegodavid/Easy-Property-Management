# Portfolio, people and providers

[Manual contents](README.md)

## Add a property and confirm its status

1. Open **Properties → Create property**.
2. Enter the display name, supported property type and US address, including **State**. The country is supplied automatically as US; review the derived property time zone.
3. Review the owner cards, then save. Keep **You** for a self-owned property. Use **Add owner** to search saved people and organizations as you type, browse 10 at a time, or **Create a new owner** with optional contact details. The same picker is used by **Change ownership**. Clear the search box to clear its results; there is no separate Search or Hide results action. Add the owner to the cards before saving the property form. Creating the property saves its new owners and contact details together. **Save unfinished form** retains your input without creating the property; saved forms remain accessible from **Unfinished forms** without a technical recovery section on the create page.
4. Open the property's **Overview** for a summary. Use **Property setup** for configuration and **Home**, **Office** or **Suites** for rental status, depending on the property's layout.
5. Record occupancy and leasing status through their distinct actions. Supply effective dates, reasons and confirmation as required; do not mark a property vacant merely because no lease was entered.
6. Complete related lease, rent and deposit setup, then resolve missing information shown in Information review.

Residential homes/condos/townhomes have one rentable home per property in the current model. An office property can be rented as a whole office or as separate suites. The tab uses **Home**, **Office** or **Suites** accordingly; individual suite names remain visible. Separate managed condo units may be separate properties sharing a building address. Multi-unit apartment-building operations are outside this release.

**Overview** shows the property address, compact occupancy/leasing status, review cards and Relationships. It also retains contextual Tasks, which have no dedicated property tab. Use **Home/Office/Suites**, **Leases**, **Money**, **Maintenance** and **Conversations** for their detailed records rather than looking for duplicate sections on Overview.

## Edit, classify and schedule changes

Use **Edit property** for the property record. In **Home**, **Office** or **Suites**, the corresponding **Edit home/office/suite** and **Start lease draft** buttons sit beside the rental name. Status actions and corrections appear beside the relevant occupancy or leasing information. Archive or Restore stays separate. **Scheduled occupancy** appears only when future changes exist, with Cancel, Replace, Reschedule and correction actions directly available. **History** is the only expandable section within each rental card. Check the effective date and current status before saving; corrections retain historical context and reasons. Occupancy marked **Managed by lease** must be changed through Leasing rather than conflicting manual status.

For a single home or whole office, use **Archive property** in **Property setup** rather than archiving its only rental unit. In a multi-suite property, **Archive suite** retires an individual suite while the property remains active; the archived suite offers **Restore suite** when permitted. Temporary vacancy or a pause in leasing should use occupancy or leasing status instead. Archiving retains history and can leave unresolved Home obligations. It is not deletion or proof that money is settled.

## Owners and ownership

Client owners use shared person/company identities. Create or select the identity, open the Property and choose **Change ownership**. Review the complete proposed relationship set/effective context before confirming; do not accidentally remove another retained relationship. Self-owned properties do not need a fabricated client-owner identity.

**Owners** lists client owners. Open one to review related Properties, Leases, Maintenance, Money and Conversations. Use current/former relationship filtering as available. To change actual property facts, follow its Property/source link. Owner money describes related whole-property activity; the app does not infer shares or distributable entitlement.

In a property's **Relationships** cards, select a client owner's name to open their workspace; **You** identifies local-operator ownership and has no profile link. In an owner's Relationships cards, select the property name to open that property.

## People, contacts and tenants

On **Property setup → Change ownership**, each selected owner shows their saved contact details. Use **Manage contact details** to edit the shared record. When adding a new owner, contact details are optional and save together with the ownership change.

You can keep multiple emails, phone numbers and mailing addresses for each person or organization. Each type has one **Primary** contact; the first is selected automatically. On **Add contact details**, existing contacts appear below the form with **Edit**, **Make primary** and **Remove** actions. Select **Make primary** and save to switch the primary for that type. If you want to remove a primary with alternatives, make another contact of the same type primary first. Removing the last entry is allowed. **Remove** archives the contact rather than deleting its history; archived contacts can be restored.

These contacts and primary choices are shared across owner, tenant and provider roles. A role's explicitly preferred contact remains a separate choice; primary changes do not replace it. Removing a preferred contact may require choosing a replacement or clearing that role preference.

On a tenant's detail page, **Add contact details** is beside **Contact details**, and **Edit tenant preferences** is beside **Tenant preferences**. Preferences include the contact to use and whether contact is allowed; notes can describe preferred contact times/time zone, communication channel, language or accessibility needs. **Archive tenant** below preferences archives the tenant role, not the shared person or organization.

Open **Tenants**, or `/tenants`. Tenant profiles and tenant actions use this path. Shared names and contact details used by owners, tenants and providers open their person record under `/parties`.

1. Search tenants by name (at least two characters), or choose **Browse tenants** to list tenants alphabetically, 20 per page. Search results update automatically; **Next tenants** continues either list. Select a tenant card to open their details. **Include archived tenants** adds historical records and starts again at the first page.
2. Use **Create tenant** next to the page heading for a new tenant.
3. For a person already recorded as an owner or provider, open their shared contact record and choose **Use identity as tenant**.
4. Add/edit contact methods and tenant preferences. Archive/restore individual contacts or roles using their own actions.
5. Review linked use before changing identity or lifecycle; editing a shared identity can affect several contexts.

A tenant role alone does not add a lease participant; use the Lease participant workflow. Archived identity/contact records remain historical and may still be referenced.

## Providers and categories

1. Open **Providers**; search by name or filter by category and preference. Cards show services, service areas and any preferred/avoid or archived status. **More filters** contains archive state, service, service area and references; **Clear filters** resets the list.
2. Use **Create provider** beside the heading. For a person or organization already recorded elsewhere, open their contact record and choose **More actions → Add provider role**.
3. Edit preference/avoid context and profile information.
4. Assign one or more active categories. **Manage provider categories** below the directory opens the separate catalog; it is also available in **Settings → Provider categories**.
5. Add services, service areas, work history, references and reputation links. Retain relevant dates and source URLs.
6. Archive/restore entries or category assignments individually; restore a category before reusing it where required.

Services are descriptive; provider categories are a separate shared catalog. Maintenance issue categories and expense categories are different lists. Preferred/avoid status informs selection; an avoided provider may require explicit override/reason in assignment. Provider history and reputation are recorded context, not live external reputation verification.

To hire for a repair, use the Maintenance quote/assignment workflow. Creating a provider, assigning a category or recording a paid expense does not assign them to an issue.
