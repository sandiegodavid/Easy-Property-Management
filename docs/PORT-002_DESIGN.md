# PORT-002 — Property and Space Inventory Design

## Purpose

`PORT-002` turns the property identity established by `PORT-001` into usable rental inventory. An operator can classify a property as a single-family home, condo, townhome, or office, then describe the rentable space or spaces within it.

The result is a stable, plain-language place to attach leases, listings, maintenance, payments, and occupancy. PORT-002's own delivery boundary stopped before deciding whether a space was vacant, occupied, or available; PORT-003 subsequently added those independent status records without requiring leases.

## Scope

PORT-002 provides:

- A required property type for new properties: **Single-family home**, **Condo**, **Townhome**, or **Office**.
- One or more named rentable spaces for each active property.
- Guided inventory layouts:
  - A single-family home, condo, or townhome has one required **Whole home** space.
  - An office can have one **Whole office** space or multiple **Office suite** spaces.
- Space details needed across later modules: a display label, optional suite or floor reference, optional internal notes, and active/archived status.
- Property-detail inventory cards and a portfolio list that make the type and space count easy to scan.
- Atomic, append-only audit history for property-type and space changes.

Use **Property type** and **Rentable spaces** in the UI. “Inventory,” “entity,” and “relationship” are internal terms rather than operator-facing labels.

## Explicit boundaries

PORT-002 does not provide:

- Apartment buildings, apartment units, buildings with common-area inventory, or unit numbering conventions. Those are a future extension; this design must not reserve apartment-specific fields or overload office suites as apartment units.
- Occupancy, vacancy, availability dates, tenants, prospects, leases, rent, deposits, expenses, or billing. `PORT-003`, `TEN-001`, and `LEASE-001` own those concepts.
- Square footage, bedrooms, bathrooms, amenities, market-rent estimates, photos, listing copy, geocoding, or zoning data.
- Splitting or merging a space after it has acquired dependent records. A later dedicated inventory-reconfiguration workflow can handle that safely.
- Legal determinations about what constitutes a dwelling, suite, lawful occupancy, or a rentable area.

## Product decisions

### Property and space are different things

A **property** remains the address and ownership/management record from PORT-001. A **rentable space** is what later workflows lease, list, repair, and report on.

Examples:

| Operator sees | Property type | Spaces created |
| --- | --- | --- |
| A detached house rented as one home | Single-family home | `Whole home` |
| A condo rented as one residence | Condo | `Whole home` |
| A townhome rented as one residence | Townhome | `Whole home` |
| A small office rented to one business | Office | `Whole office` |
| An office building with suites 100 and 200 | Office | `Suite 100`, `Suite 200` |

An office with suites is still one property with several spaces. It is not a collection of unrelated property records. A residential property cannot gain a second space in this item.

### Inventory layout is selected at creation

The **Add property** flow asks for property type and then shows a small layout choice only for offices:

1. **Rent the whole office** creates one `whole_office` space.
2. **Rent office suites separately** requires one or more suite labels and creates one `office_suite` space per label.

Residential types always create exactly one `whole_home` space. This makes the common workflow fast while preventing the operator from accidentally creating two independently rentable “homes” under one property.

The layout cannot be changed by editing a label. Before a future split/merge feature exists, changing an office from whole-office to suites, or the reverse, requires archiving the old property and creating a correctly structured replacement only when there are no dependent records. This avoids silently moving future lease or money records to the wrong space.

### Archival

Spaces are retained rather than deleted. An archived space remains visible in history but cannot be selected for new work.

- A space may be archived only with explicit confirmation.
- A property may be archived only after all of its spaces are archived, or through a confirmed **Archive property and its spaces** action that archives every active space in the same transaction.
- A space cannot be restored while its property is archived.
- PORT-003 now prevents archival of occupied spaces and spaces with scheduled occupancy transitions. `LEASE-001` will add guards for active lease records.

## Data model

PORT-002 extends the existing `properties` table and adds `spaces`. All identifiers are stable UUIDs.

### `properties` additions

| Field | Rules and meaning |
| --- | --- |
| `property_type` | Required enum: `single_family_home`, `condo`, `townhome`, or `office`. It is an operational classification, not a legal conclusion. |
| `inventory_layout` | Required enum: `single_space` for residential properties; `whole_office` or `office_suites` for offices. It preserves the original intended space structure. |

Because this is a greenfield product, new properties are classified explicitly when created. The application must never infer a residential or commercial type from an address or name.

### `spaces`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID. |
| `property_id` | Required reference to the owning property. |
| `space_kind` | `whole_home`, `whole_office`, or `office_suite`; consistent with the property type and inventory layout. |
| `display_name` | Required, trimmed operator-facing label, such as `Whole home` or `Suite 100`. |
| `suite_or_floor` | Optional short reference, useful for office suites. It is not an apartment-unit field. |
| `notes` | Optional internal notes. |
| `status` | `active` or `archived`. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

Constraints and application rules enforce:

- A space belongs to exactly one property.
- An active property has at least one active space after the PORT-002 setup action completes.
- Active space labels are unique within their property, case-insensitively after trimming.
- A residential property has exactly one active `whole_home` space.
- A whole-office layout has exactly one active `whole_office` space.
- An office-suites layout has one or more active `office_suite` spaces and no whole-office space.
- An archived property has no active spaces.

The database enforces referential integrity, enum/check constraints, and active-label uniqueness. The application enforces cross-row layout rules in one immediate transaction, so a partially updated inventory cannot be observed.

## User experience

### Add property

The property form follows PORT-001’s name, address, and ownership section with **What kind of property is this?**

- **House**, **Condo**, and **Townhome** immediately preview “One rentable space: Whole home.”
- **Office** asks “Will you rent the whole office or individual suites?”
- For suites, the form starts with one suite row, makes its label required, and provides **Add another suite**.

The final confirmation states the resulting inventory in plain language: “This office will have 2 rentable suites: Suite 100 and Suite 200.”

### Property detail

Add a **Rentable spaces** section beneath Property details and Ownership and management. It displays the property type, layout, space count, and simple cards for each space. Each card shows the label, optional suite/floor reference, active/archived state, and later will host occupancy, lease, listing, repair, and financial summaries.

The initial portfolio list adds compact property-type text and a space count, for example “Office · 2 suites.” No vacancy color or availability claim appears until PORT-003.

## API contract

All endpoints require a ready workspace. Request models reject unknown fields, and application commands repeat essential validation for direct callers.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/properties` | Extend the PORT-001 create request with `propertyType`, `inventoryLayout`, and initial spaces; create property, ownerships, and spaces atomically. |
| `PATCH` | `/api/properties/{propertyId}` | Edit permitted property identity fields; property type and layout have a dedicated, guarded workflow rather than a casual patch field. |
| `GET` | `/api/properties/{propertyId}` | Return the existing property detail plus type, layout, and current spaces. |
| `POST` | `/api/properties/{propertyId}/spaces` | Add a suite only to an active office-suites property. |
| `PATCH` | `/api/spaces/{spaceId}` | Edit a space label, optional suite/floor reference, or notes. |
| `POST` | `/api/spaces/{spaceId}/archive` | Archive one space after explicit confirmation and applicable layout checks. |
| `POST` | `/api/spaces/{spaceId}/restore` | Restore a space only under an active compatible property. |
| `POST` | `/api/properties/{propertyId}/archive` | Require confirmation; optionally archive all active spaces in the same operation. |

PORT-002 introduced stable UUIDs and server-derived, non-writeable inventory fields. The current property-detail response is extended by PORT-003 with occupancy, availability, scheduled-transition, and status-summary fields.

## Audit, safety, and portability

Every create, edit, archive, restore, and layout-level operation writes the inventory rows and explicit `AUDIT-001` events in one immediate transaction. A multi-row action—such as creating an office and its suites or archiving a property and its spaces—shares one correlation ID.

Audit snapshots contain IDs, type/layout, lifecycle fields, and operator-entered inventory values. They do not contain credentials or occupancy assumptions. New tables and fields participate in exact current-schema validation and `LOCAL-002` backup, export, and restore validation.

## Implementation outline

1. Add portfolio SQLAlchemy models and one Alembic revision for property classification/layout and `spaces`, including exact module-owned schema validation.
2. Extend portfolio domain values with typed property-type, layout, and space commands; enforce cross-row layout invariants in the application service.
3. Extend the portfolio unit of work to load and mutate property inventory and append explicit correlated audit events atomically.
4. Extend typed FastAPI contracts; deliver the Property type and Rentable spaces UI sections in `UI-001`, immediately before `DASH-001`.
5. Update workspace/archive schema validation and add regression coverage for constraints, atomic audit rollback, archive/restore, and cross-row inventory rules.

## Acceptance criteria

PORT-002 is complete when:

1. An operator can create a house, condo, townhome, whole office, or office with separately named suites without technical terminology.
2. Each active property exposes a correct active space set consistent with its type and selected layout.
3. Residential properties cannot gain multiple active rentable spaces, and office-suite labels cannot duplicate within an office.
4. Space and property archival preserve history and cannot create an active space under an archived property.
5. Every inventory mutation is audited atomically with the affected property and space records under one correlation ID.
6. Properties and spaces survive backup/export/restore with stable IDs, relationships, and audit history.
7. No endpoint or UI claims that a space is vacant, occupied, or available before PORT-003 implements that lifecycle.

## Dependencies and follow-on work

PORT-002 requires `PORT-001`. It unlocks `PORT-003`, `LEASE-001`, `FIN-002`, `MAINT-001`, `LIST-001`, `JUR-001`, and `ISSUE-AI-002`.

Apartment buildings and apartment units remain a later extension. When introduced, they should add an explicit residential-building/unit model or a carefully versioned expansion of `spaces`; they must not reinterpret existing office-suite records.
