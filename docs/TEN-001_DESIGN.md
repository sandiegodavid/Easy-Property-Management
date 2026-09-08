# TEN-001 — Tenant Contacts and Lease-Participant Foundation

## Purpose

`TEN-001` gives the operator a reliable local record for people and organizations who may become, or already are, tenants. It builds on the shared party identity created by `PORT-001`, so an owner, tenant, vendor, or later applicant is never copied into competing contact tables.

The feature is deliberately useful before leases exist: the operator can keep a tenant contact card, record safe contact preferences, and mark a party as tenant-ready. `LEASE-001` then attaches one or more of those parties to a specific lease with lease-owned participant roles and dates.

## Scope

TEN-001 provides:

- A tenant profile for an existing individual or organization party.
- Multiple local contact methods for a tenant, including email and phone.
- A preferred contact method and a plain-language do-not-contact flag for each tenant profile.
- Tenant profile archive and restore actions that preserve history.
- Search and list views by tenant name, contact value, and active/archived state.
- A stable tenant-party identifier and participant-ready contract for `LEASE-001`.
- Correlated, append-only audit history for every tenant profile and contact-method mutation.

TEN-001 does not provide:

- A lease, tenancy start/end date, unit assignment, rent, deposit, balance, notice, or legal occupancy determination. These belong to `LEASE-001` and `FIN-001`.
- Applications, screening reports, credit scores, bank statements, employment details, familial-status information, approval decisions, or adverse-action workflows. These belong to `LEAD-004`, `APP-FIN-001`, `APP-DEC-001`, and `SCREEN-001`.
- Sending messages, syncing external accounts, or delivery tracking. `COM-001`, `COM-002`, and connection work own those behaviors.
- A tenant portal, authentication, or shared access.
- AI-generated tenant profiles or inferred contact preferences.

## Core product decisions

### Reuse shared parties

The shared `parties` module owns the canonical identity table and reusable identity model. Its existing `party_kind` continues to describe whether the party is an individual or organization; it does not become a tenant/owner/vendor enum. Portfolio and tenant features depend on this shared boundary rather than importing each other's infrastructure.

TEN-001 adds tenant-specific records that reference `parties.id`. A party may have more than one business role over time, such as a client owner for one property and a tenant contact for another. Role records avoid duplicated names, phone numbers, and audit histories.

### A tenant profile is not a lease participant

A tenant profile means the party is eligible to be selected for a future lease or communication workflow. It does not claim that the party occupies a particular space.

`LEASE-001` creates the lease-owned participant relationship. That relationship will reference `tenant_profiles.party_id`, assign a lease role such as primary tenant, co-tenant, guarantor, or business signatory, and own effective dates and obligations. TEN-001 must not create a placeholder lease-participant table without a lease foreign key.

### Contact data stays purposeful and local

Each tenant contact method has a type, normalized lookup value, display value, optional label, and lifecycle state. The operator enters and maintains it manually. No external verification, messaging consent law determination, device contact import, or automatic outreach is implied.

The profile-level preference is `email`, `phone`, or `none`. The selected method must be active and belong to that profile. A `do_not_contact` flag prevents later communication modules from treating the profile as an ordinary outreach target; it does not erase the historical record.

## Data model

All IDs are UUIDs. Timestamps are timezone-aware UTC text, consistent with the existing local workspace contract.

### `tenant_profiles`

| Field | Rules and meaning |
| --- | --- |
| `party_id` | Primary key and foreign key to `parties.id`. One tenant profile per party. |
| `preferred_contact_method_id` | Optional foreign key to an active method owned by the profile. |
| `do_not_contact` | Required boolean, default `false`. |
| `notes` | Optional internal contact context, capped at 4,000 characters. It must not contain screening or protected-class decision data. |
| `created_at`, `updated_at` | Required UTC timestamps. |
| `archived_at` | Null while active; set only through the archive action. |

### `tenant_contact_methods`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID primary key. |
| `party_id` | Required foreign key to `tenant_profiles.party_id`. |
| `method_kind` | Required enum: `email` or `phone`. |
| `display_value` | Required operator-facing contact value. |
| `normalized_value` | Required trimmed and normalized lookup value. Email uses Unicode-normalized, case-folded text; phone keeps digits with an optional leading `+`. |
| `label` | Optional short label such as `Mobile` or `Work`. |
| `status` | Required enum: `active` or `archived`. |
| `created_at`, `updated_at`, `archived_at` | Lifecycle timestamps. |

The database enforces uniqueness of `(party_id, method_kind, normalized_value)` for active methods. It permits the same person to have an email and phone, and permits an archived contact value to be retained in history. A tenant profile cannot point its preference at an archived or another party's method; the application validates this within the same write transaction.

## Business rules and workflows

### Create or designate a tenant

The operator may create a new individual or organization party and tenant profile in one transaction, or designate an existing active party as a tenant. The resulting party, profile, and initial contact methods share one correlation ID and audit trail.

Creating a profile requires a nonblank display name through the shared party command. Contact methods are optional, because an operator may know a tenant's name before having reliable contact details.

### Maintain contact methods

The operator can add, edit, archive, and restore a tenant contact method. Editing creates an audit record with the former normalized and display values. A method referenced by the profile preference cannot be archived until the preference is changed or cleared in the same transaction.

### Set contact preference

The operator selects email, phone, or no preferred method. Email or phone requires exactly one active matching contact method. Setting `do_not_contact` retains the preference for context but later communication modules must honor the flag.

### Archive and restore

Archiving a tenant profile requires explicit confirmation. It archives no shared party and deletes no contact history. If an active or scheduled lease participant relationship exists after `LEASE-001`, archival is rejected with a conflict until that relationship is ended by the lease workflow. Restoring reactivates only the profile; individual contact methods retain their own states.

## API contract

All routes require a ready workspace. Request models forbid unknown fields; application commands independently enforce the same rules for non-HTTP callers.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/tenants` | Create an individual or organization party, tenant profile, and optional initial contact methods atomically. |
| `POST` | `/api/tenants/from-party/{partyId}` | Designate an existing active party as a tenant profile. |
| `GET` | `/api/tenants` | List tenant profiles with active/archived and text-search filters. |
| `GET` | `/api/tenants/{partyId}` | Return the tenant profile, shared identity, contact methods, and contact preference. |
| `PATCH` | `/api/tenants/{partyId}` | Update profile notes, preference, and do-not-contact status. |
| `POST` | `/api/tenants/{partyId}/contact-methods` | Add one contact method. |
| `PATCH` | `/api/tenants/{partyId}/contact-methods/{methodId}` | Edit a contact method. |
| `POST` | `/api/tenants/{partyId}/contact-methods/{methodId}/archive` | Archive one method with any required preference update. |
| `POST` | `/api/tenants/{partyId}/contact-methods/{methodId}/restore` | Restore one archived contact method after its tenant profile is active. |
| `POST` | `/api/tenants/{partyId}/archive` | Archive a tenant profile after explicit confirmation. |
| `POST` | `/api/tenants/{partyId}/restore` | Restore an archived tenant profile. |

Responses use explicit Pydantic models. They return stable IDs, party identity, tenant profile fields, and contact methods. They do not expose future lease, applicant, screening, financial, or portal fields.

Errors distinguish missing records (`404`), malformed requests (`422`), invalid business rules (`400`), and active lease/source conflicts (`409`).

## Audit, privacy, and portability

Each mutation writes its data rows and `AUDIT-001` change event in one immediate transaction. A multi-row create or preference change shares one correlation ID. Audit snapshots include stable IDs, lifecycle state, profile preference, and contact-method metadata and values because they are required to understand a contact change; snapshot policy redacts values in generalized activity presentations when the caller has no tenant-contact context.

Tenant contact data is stored only in the external local workspace. The current schema, encrypted backup, export, and restore validation include tenant profiles and contact methods. Files, message bodies, call recordings, source credentials, and account secrets are outside TEN-001.

## Implementation outline

1. Add tenant-profile and tenant-contact-method SQLAlchemy models to the current greenfield baseline and module-owned exact schema validation.
2. Add a `tenants` module with domain values, application commands, a transaction-oriented repository port, SQLite adapter, audit presentation policy, and typed FastAPI routes.
3. Reuse party creation and identity validation through a small application-level party port; do not import portfolio infrastructure into the tenant module.
4. Add atomic profile/contact/preference/archive workflows with explicit correlation IDs and controlled conflict errors.
5. Extend product-schema validation, encrypted archive validation, and backup/restore tests for the new tables.
6. Add tests for duplicate normalization, preference ownership and lifecycle rules, archive guards, audit rollback, filtering, API validation, and backup/restore.

## Acceptance criteria

TEN-001 is complete when:

1. An operator can create a tenant profile from a new or existing active party without duplicating the shared identity.
2. Tenant contact methods are normalized, searchable, lifecycle-managed, and unique per active tenant/type/value.
3. Preferences only select active, owned contact methods, and do-not-contact is retained as explicit local state.
4. Profile and contact mutations are atomic with correlated audit events and roll back if audit persistence fails.
5. Archive and restore preserve history and respect lease-participant guards once `LEASE-001` supplies them.
6. Typed API contracts reject malformed and unknown fields, distinguish 404/400/409 outcomes, and expose no screening or financial data.
7. Current-schema validation and encrypted backup/restore preserve tenant records, contact methods, and audit history.
8. The design leaves lease participation, occupancy, communication delivery, screening, finance, and portal access to their owning backlog items.

## Dependencies and follow-on work

TEN-001 requires `PORT-001` for the shared party identity and `AUDIT-001` for required history. It should use the existing `LOCAL-001` workspace and `LOCAL-002` protection capabilities without adding a new data location.

`LEASE-001` depends on TEN-001 and owns lease-participant records. `COM-001` uses tenant profiles and preferences to log communication. `ISSUE-AI-002` may suggest tenant matches but must not create or modify profiles without review. `PORTAL-001` adds tenant self-service only after security, authentication, lease, finance, and communication capabilities exist.
