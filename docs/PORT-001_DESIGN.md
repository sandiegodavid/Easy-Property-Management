# PORT-001 — Portfolio Ownership Context Design

## Purpose

`PORT-001` establishes the local portfolio as the shared foundation for the rest of the product. An operator can add a property and clearly identify whether they own it themselves, manage it for one or more client owners, or have both relationships.

This makes the core distinction visible before leases, rent, expenses, owner reporting, and disbursements arrive. It is deliberately a small portfolio foundation, not a complete property, contact, accounting, or tenancy module.

## Scope

PORT-001 provides:

- A property identity with a human-friendly name, a US structured address, an address-derived US IANA time zone, an active/archived status, and optional internal notes.
- A lightweight reusable party record for client owners: individual or organization, display name, optional email, and optional phone.
- Explicit active ownership relationships between a property and either the local operator or a client-owner party.
- A derived, readable ownership context for every active property:
  - **Self-owned**: active local-operator ownership and no active client-owner relationship.
  - **Managed for an owner**: one or more active client-owner relationships and no active local-operator ownership.
  - **Mixed**: both active local-operator and client-owner relationships.
- Property list and detail views with ownership-context filters and a plain-language ownership card.
- Append-only audit history for property, party, and ownership-relationship changes.

The local workspace has one operator and no application login. “Self” always means that local operator; it does not create a second account or permission role.

### What “mixed” means

**Mixed** means the local operator is also an owner while managing the property with or for one or more other owners. For example, an operator owns half of a duplex with a sibling, collects rent, arranges repairs, and maintains the records for both owners. The property is mixed because it has both a local-operator ownership relationship and a client-owner relationship.

Mixed does not mean a property is both residential and office, and it does not apply merely because a fully client-owned property has multiple client owners. Later owner accounting can use these explicit relationships to distinguish each owner's records; PORT-001 does not infer ownership percentages or legal rights.

## Explicit boundaries

PORT-001 does not provide:

- Property type, rentable-space, suite, unit, occupancy, vacancy, or availability management. Those belong to `PORT-002` and `PORT-003`.
- Tenants, prospects, vendors, or general contact roles beyond the small owner-party foundation. `TEN-001` adds reusable party-owned multi-value contact methods and role/contact guard protocols, and `VEND-001` moves the remaining reusable identity routes into the dedicated `parties` API module so they are not portfolio-owned.
- Ownership percentages, legal beneficial-ownership determinations, management agreements, management fees, owner balances, disbursements, or trust accounting.
- Leases, expenses, payments, owner-reported rent, reports, portal access, authentication, or multi-user permissions.
- Deletion of business records. Properties and ownership relationships are archived or ended, preserving history.

The displayed ownership context is an operational label, not a legal opinion about title or authority.

## Data model

PORT-001 introduces a generic foundation that later party, leasing, provider, and owner-management work can extend instead of replacing.

### `parties`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID. |
| `party_kind` | `individual` or `organization`. |
| `display_name` | Required, trimmed, nonblank display name. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

PORT-001 stores identity only. TEN-001 adds party-owned `party_contact_methods` and explicitly removes redundant scalar email and phone fields from the current greenfield baseline.

### `properties`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID. |
| `display_name` | Required operator-facing label, such as “Maple Street home.” |
| `address_line_1`, `address_line_2`, `city`, `region`, `postal_code`, `country_code` | US structured address; line 1, city, region, postal code, and the fixed `US` country code are required. The UI uses local formatting rules but stores no geocoding result. |
| `time_zone` | Required canonical US IANA identifier inferred from the structured address, such as `America/Los_Angeles`; it is returned to clients but is not directly writable. |
| `notes` | Optional internal note, not a legal property description. |
| `status` | `active` or `archived`. An archived property is read-only for new operational records until restored. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

The database requires `time_zone` to be non-null and nonblank. The application validates the resolver result against the runtime IANA database before persistence, and the exact-schema validator requires the field and constraint. Only the canonical zone identifier is portable workspace data; resolver indexes and intermediate address matches are application resources, not workspace records.

### `property_ownerships`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID. |
| `property_id` | Required reference to `properties`. |
| `owner_kind` | `local_operator` or `client_owner`. |
| `party_id` | Required for `client_owner`; null for `local_operator`. |
| `starts_on`, `ends_on` | Effective-date range. `ends_on`, when present, must not precede `starts_on`. A null end date is active. |
| `created_at`, `ended_at` | UTC record timestamps. Ending a relationship sets its end date; rows are never repurposed. |

Database constraints enforce the owner-kind/party pairing, prevent duplicate active local-operator ownership for one property, and prevent an archived party from being added as a new client owner. The application derives the ownership context from active rows; it does not store a separate mutable `mode` field that could drift from the relationships.

Future modules may add ownership share, management agreement, owner statement, and disbursement tables. They must reference these stable property and party IDs and must not infer financial rights from PORT-001’s operational labels.

## Business rules and workflows

### Add a property

The primary action is **Add property**. The short guided form asks for a property label, US address, and “How do you manage this property?” A transaction-independent address-time-zone resolver behind a Portfolio application port derives one canonical US IANA zone from a bundled local US address/postal data set; no address is sent to an external service and no geocoding result is retained. If the address is insufficient or resolves ambiguously, creation stops and asks the operator to complete or correct the structured address rather than guessing a zone. International address and time-zone support is deferred.

1. **I own it** creates an active `local_operator` ownership row.
2. **I manage it for an owner** requires one or more client owners. The operator can select a saved party or add a basic owner identity inline; reusable contact methods are party-owned by TEN-001 rather than copied into portfolio records.
3. **Both** creates the local-operator row and one or more client-owner rows.

Changing an address reruns the same resolver and stores the new inferred zone in the property/audit snapshot. Previously recorded local dates remain unchanged; future date-relative views use the new property zone. The UI warns before saving a time-zone change when lease or finance records exist.

The form explains the consequence in plain language, for example: “Managed for an owner — future owner statements and disbursements can be linked to this owner.” It must not ask the operator to understand database roles or legal ownership terminology.

### Change ownership context

The property detail page shows current owners and an **Update ownership** action. A change creates or ends effective-dated relationship rows in one transaction rather than overwriting an old relationship. The operator chooses an effective date and confirms the new active set before saving.

The application rejects a change that would leave an active property with no active ownership relationship. It also prevents archiving a party while that party has an active property ownership relationship; the operator must end or replace the relationship first.

### Archive a property

Archive is a confirmation-based state change, not deletion. PORT-001 permits it only when the operator confirms that new work should stop. Later modules add stricter guards for active leases, open balances, listings, and issues. Restore returns the property to `active` and is audited.

## User experience

The initial **Portfolio** screen has one simple list. Each row shows:

- Property label and formatted address.
- A text-and-icon ownership badge: **Self-owned**, **Managed for owner**, or **Mixed**.
- Current owner names when client owners exist.
- Active or archived state.

Filters are **Active**, **Archived**, **Self-owned**, **Managed**, and **Mixed**. The empty state explains that a property is the starting point for later spaces, leases, maintenance, and reporting.

The property detail screen has two initial sections:

1. **Property details** — identity, address, notes, and status.
2. **Ownership and management** — current context, owner contacts, effective dates, and a read-only history link.

Use “owner” and “managed for” in labels. Reserve jargon such as “party” and “relationship” for developer-facing APIs and internal documentation.

## API contract

All endpoints require a ready local workspace. Request models are typed Pydantic models; application commands repeat the core validation so direct callers cannot bypass it.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/properties` | Create a property with its inferred time zone and initial ownership set atomically. |
| `GET` | `/api/properties` | List properties with `status` and derived `ownershipContext` filters. |
| `GET` | `/api/properties/{propertyId}` | Return property identity, current ownerships, and current ownership context. |
| `PATCH` | `/api/properties/{propertyId}` | Change one or more editable identity fields. |
| `POST` | `/api/properties/{propertyId}/archive` | Archive only after an explicit confirmation. |
| `POST` | `/api/properties/{propertyId}/restore` | Restore an archived property. |
| `PUT` | `/api/properties/{propertyId}/ownerships` | Replace the active ownership set effective on a specified date by ending and creating relationships atomically. |
| `GET` | `/api/parties?activeOnly=true` | Find selectable client-owner contacts. |
| `POST` | `/api/parties` | Create a basic client-owner identity; TEN-001 later adds reusable party contact methods. |
| `POST` | `/api/parties/{partyId}/archive` | Archive a party only after confirmation and only if it has no current property ownership. |
| `POST` | `/api/parties/{partyId}/restore` | Restore an archived party. |

Stable UUIDs are returned in all records. Responses expose `ownershipContext` as one of `self_owned`, `managed_for_owner`, or `mixed` and expose the canonical `timeZone`; both are derived server-side and are not client-writeable fields.

## Audit, safety, and portability

Every property, party, and relationship mutation writes its domain row(s) and explicit `AUDIT-001` event(s) in one immediate SQLite transaction. A single create or ownership-change workflow shares one correlation ID across its property, party, and relationship events.

Audit snapshots include portable identifiers, the inferred US IANA time zone, and normal business fields, but never application credentials, geocoding results, or inferred legal conclusions. Relationship events retain effective dates and prior/current active sets so future owner accounting can explain which context applied. Party contact values are introduced and protected by TEN-001 rather than stored by portfolio.

The records live only in the workspace SQLite database. They participate in current-schema validation, `LOCAL-002` encrypted backup/export/restore, and future SaaS migration through stable IDs. No external owner portal, email, or financial integration is introduced.

## Implementation outline

1. Add SQLAlchemy models and one Alembic revision for the three tables, constraints, indexes, and exact module-owned schema validation.
2. Add portfolio domain values, the address-time-zone resolver port, and application commands for property creation, identity/status updates, ownership replacement, and party creation/archive.
3. Add a transaction-oriented portfolio unit of work that loads current state, persists the selected change, and appends all audit events under one correlation ID.
4. Add FastAPI request/response models and routes; deliver the Portfolio list/detail/create UI in `UI-001`, immediately before `DASH-001`.
5. Add current-format workspace/archive validation for the new tables and regression tests for atomic rollback, mode derivation, effective-dated changes, archive guards, and audit correlation.

## Acceptance criteria

PORT-001 is complete when:

1. An operator can create and find active self-owned, client-managed, and mixed properties without technical terminology.
2. Client-owner contacts can be selected or created inline, and every client-managed or mixed property shows its current owners.
3. Ownership context is always derived from validated active relationship rows; invalid pairings or an ownerless active property are rejected.
4. Ownership changes preserve prior effective-dated relationships instead of overwriting them.
5. Property, party, relationship, archive, and restore changes are audited atomically with one correlation ID per user operation.
6. Archived properties are retained, discoverable through an archived filter, and blocked from new operations according to this item’s scope.
7. Records survive LOCAL-002 backup/restore with stable IDs, relationships, and audit history intact.
8. Tests cover self-owned, managed, mixed, deterministic US address time-zone inference (including incomplete or conflicting US addresses), effective-dated transitions, direct-command validation, atomic audit rollback, and current-schema rejection.
9. Every property stores and returns one canonical US IANA time zone derived locally from its structured address; unresolved or conflicting US addresses are rejected rather than assigned a guessed zone.

## Dependencies and follow-on work

PORT-001 requires `LOCAL-001` for the workspace and `AUDIT-001` for the required history. It unlocks `PORT-002`, `TEN-001`, `VEND-001`, owner-management work, and later SaaS authorization. `PORT-002` adds property type and spaces to the same `properties` records rather than creating a competing property identity.
