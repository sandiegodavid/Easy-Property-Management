# TEN-001 — Tenant Profiles, Party Contacts, and Lease-Participant Foundation

## Purpose

`TEN-001` gives the operator a reliable local record for people and organizations who may become, or already are, tenants. It builds on the shared party identity created by `PORT-001`, so an owner, tenant, vendor, or later applicant is never copied into competing contact tables.

The feature is deliberately useful before leases exist: the operator can keep a tenant contact card, record safe contact preferences, and mark a party as tenant-ready. `LEASE-001` then attaches one or more of those parties to a specific lease with lease-owned participant roles and dates.

## Scope

TEN-001 provides:

- A tenant profile for an existing individual or organization party.
- Multiple party-owned local contact methods, including email and phone, reusable by every role of that party.
- A preferred contact method and a plain-language do-not-contact flag for each tenant profile.
- Tenant profile archive and restore actions that preserve history.
- Search and list views by tenant name, active contact value, and tenant-profile active/archived state; archived contact values never affect normal search.
- A stable tenant-party identifier and participant-ready contract for `LEASE-001`.
- Correlated, append-only audit history for every tenant profile and contact-method mutation.

TEN-001 does not provide:

- A lease, tenancy start/end date, unit assignment, rent, deposit, balance, notice, or legal occupancy determination. These belong to `LEASE-001` and `FIN-001`.
- Applications, screening reports, credit scores, bank statements, employment details, familial-status information, approval decisions, or adverse-action workflows. These belong to `LEAD-004`, `APP-FIN-001`, `APP-DEC-001`, and `SCREEN-001`.
- Sending messages, syncing external accounts, or delivery tracking. `COM-001`, `COM-002`, and connection work own those behaviors.
- A tenant portal, authentication, or shared access.
- AI-generated tenant profiles or inferred contact preferences.

## Core product decisions

### Reuse shared parties and contacts

The shared `parties` module owns the canonical identity table, reusable identity model, and multi-valued contact methods. Its existing `party_kind` continues to describe whether the party is an individual or organization; it does not become a tenant/owner/vendor enum. Portfolio, tenant, provider, communication, and later role features depend on this shared boundary rather than importing each other's infrastructure.

TEN-001 adds tenant-specific records that reference `parties.id`. A party may have more than one business role over time, such as a client owner for one property and a tenant contact for another. Role records do not copy names or contact values. The former scalar `parties.email` and `parties.phone` fields are removed from the greenfield baseline; `party_contact_methods` is the only reusable contact source.

Every contact method belongs to a party, not to a tenant profile. A tenant profile may select one exact active party contact method as its preference, while provider, owner, and later roles can reuse the same record without copying its value or lifecycle history.

### A tenant profile is not a lease participant

A tenant profile means the party is eligible to be selected for a future lease or communication workflow. It does not claim that the party occupies a particular space.

`LEASE-001` creates the lease-owned participant relationship. That relationship will reference `tenant_profiles.party_id`, assign a lease role such as primary tenant, co-tenant, guarantor, or business signatory, and own effective dates and obligations. TEN-001 must not create a placeholder lease-participant table without a lease foreign key.

### Contact data stays purposeful and local

Each party contact method has a type, normalized lookup value, display value, optional label, optional phone extension, and lifecycle state. The operator enters and maintains it manually. No external verification, messaging consent law determination, device contact import, or automatic outreach is implied.

The profile-level preference is one exact `party_contact_methods.id` or `none`. `none` means no preference, not a prohibition on contact. The selected method must be active and belong to the profile's party. A `do_not_contact` flag blocks outbound sending but does not prevent incoming or manually logged communication and does not erase historical records.

When no exact preference exists, a later communication workflow may let the operator select another active email or phone owned by the party. Archived profiles and contact methods are excluded from normal recipient search. Existing communication history continues to display archived recipient snapshots, and a caller that already knows the stable party ID may explicitly associate a backdated historical communication with an archived party.

### Cross-module transactions and guards

Shared identity creation, party-contact mutation, role designation, and their audit events use application-level transaction protocols that operate on the caller's existing immediate SQLite transaction. A role module never imports another module's SQLAlchemy model or concrete repository to enforce a business rule.

The `parties` application boundary owns registries for party-role activity guards and party-contact reference guards. TEN-001 registers an active-tenant-profile guard immediately: a shared party cannot be archived while its tenant profile is active. It also registers the tenant preferred-contact guard: a party contact method cannot be archived while an active tenant profile references it unless the preference is cleared or replaced in the same transaction. Later roles add guards through the same protocol without making `parties` depend on their infrastructure.

The required protocols have these responsibilities:

| Protocol | Responsibility |
| --- | --- |
| Party transaction operations | Load/create/update a party, load/mutate its contacts, find bounded active duplicate candidates, and append party/contact audit events using a caller-supplied transaction and correlation ID. |
| Party-role activity guard | Given the current transaction and party ID, report whether an active role blocks shared-party archival and return a domain-safe conflict reason. |
| Party-contact reference guard | Given the current transaction and contact-method ID, enumerate blocking active role preferences and validate/apply any role-owned resolution supplied with the archive command. |
| Lease-participation guard | Given the current transaction, tenant party ID, and effective local date, report current or future participation on an executed lease without exposing lease persistence types to TEN-001. |

Bootstrap supplies the concrete SQLite-aware implementations and guard registrations. A guard failure aborts the complete data-and-audit transaction and maps to `409`; infrastructure or audit failure also rolls back every coordinated change. Guards are evaluated again during the write transaction even when a preceding read or UI warning succeeded.

The contact-archive command carries optional typed `referenceResolutions`. Each resolution identifies its owning role and role record plus either a replacement contact-method ID or an explicit clear. TEN-001 defines the initial tenant resolution. Every reported active reference must have exactly one valid resolution; unknown, duplicate, cross-party, archived-replacement, or unhandled role resolutions are rejected. The role preference changes, contact archive, and all audit events then commit under one correlation ID.

## Data model

All IDs are UUIDs. Timestamps are timezone-aware UTC text, consistent with the existing local workspace contract.

### `tenant_profiles`

| Field | Rules and meaning |
| --- | --- |
| `party_id` | Primary key and foreign key to `parties.id`. One tenant profile per party. |
| `preferred_contact_method_id` | Optional foreign key to one active `party_contact_methods.id` owned by the same party. Null means no preference. |
| `do_not_contact` | Required boolean, default `false`. |
| `notes` | Optional internal contact context, capped at 4,000 characters. Operator guidance warns that screening and protected-class decision data do not belong here; arbitrary prose is not treated as a mechanically enforceable invariant. |
| `created_at`, `updated_at` | Required UTC timestamps. |
| `archived_at` | Null while active; set only through the archive action. |

### Party-owned `party_contact_methods`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID primary key. |
| `party_id` | Required foreign key to `parties.id`. |
| `method_kind` | Required enum: `email` or `phone`. |
| `display_value` | Required operator-facing contact value. |
| `normalized_value` | Required normalized lookup value. Email uses Unicode-normalized, case-folded text. Phone stores 7–15 ASCII digits with an optional leading `+`. |
| `extension` | Optional normalized phone extension of 1–6 ASCII digits; always null for email. |
| `label` | Optional short label such as `Mobile` or `Work`. |
| `status` | Required enum: `active` or `archived`. |
| `created_at`, `updated_at`, `archived_at` | Lifecycle timestamps. |

The database enforces uniqueness of `(party_id, method_kind, normalized_value, coalesce(extension, ''))` for active methods. It permits the same party to have multiple emails or phones, permits a shared main phone number with distinct extensions, and retains archived values in history. A database `CHECK` requires exactly `(status = 'active' AND archived_at IS NULL) OR (status = 'archived' AND archived_at IS NOT NULL)`. A second `CHECK` requires `extension IS NULL` for email rows. These constraints use explicit null predicates so SQLite cannot accept an invalid lifecycle row through three-valued `CHECK` evaluation.

Email validation is deliberately syntactic rather than a deliverability claim: normalize with NFKC, trim surrounding whitespace, require exactly one `@`, require a 1–64 character nonblank local part and a valid IDNA domain, reject whitespace and control characters, and cap the full address at 254 characters. The normalized lookup value case-folds the complete address.

Phone input may contain an optional leading `+`, spaces, parentheses, periods, slashes, or hyphens around the main number. It must normalize to 7–15 ASCII digits. The markers `x`, `ext`, `extension`, or `#` may introduce a 1–6 digit extension, which is stored separately. Vanity letters and other free text are rejected. These rules validate usable structure only; they do not verify ownership or reachability.

A tenant profile cannot point its preference at an archived method or a method belonging to another party. The application validates ownership, activity, and reference guards within the same write transaction.

## Business rules and workflows

### Create or designate a tenant

The operator may create a new individual or organization party and tenant profile in one transaction, or search for and designate an existing active party as a tenant. The resulting party, profile, initial party contact methods, and audit events share one correlation ID.

Creating a profile requires a nonblank display name through the shared party command. Contact methods are optional, because an operator may know a tenant's name before having reliable contact details.

The UI searches active parties before offering creation. The server independently checks proposed active contacts. An exact normalized email match, or an exact normalized phone-and-extension match, against another active party returns `409 possible_duplicate_party` with bounded candidate party IDs. The operator must select an existing party or deliberately retry with `confirmedNewParty: true`. A display-name match and a same-main-number/different-extension match are nonblocking warnings shown before submission. No name or contact match ever merges identities automatically.

### Maintain contact methods

The operator can add, edit, archive, and restore a party-owned contact method through the shared party boundary. Editing creates an audit record with the former normalized and display values. Normal tenant and party searches use active methods only. Archived values remain visible through explicit history and to records that already reference them, but do not silently make a party match normal search.

A method referenced by any active role preference cannot be archived until every reference is changed or cleared in the same transaction. TEN-001 supplies the first contact-reference guard for `tenant_profiles.preferred_contact_method_id`.

### Set contact preference

The operator selects one exact active party contact method or no preferred method. Setting `do_not_contact` retains that preference for context. COM-001 may continue to log incoming and historical communication, while every outbound delivery workflow must reject sending until the flag is cleared.

### Archive and restore

Archiving a tenant profile requires explicit confirmation. It archives no shared party and deletes no contact history. A current or future participant on an `executed` lease blocks archival until that participation is ended by the lease workflow. A participant on an editable `draft` lease does not block archival; lease execution revalidates that every participant profile is active. Restoring reactivates only the profile; party contact methods retain their own states.

Archiving the shared party is a separate, stricter action. The party-role guard rejects it while the tenant profile is active, independently of lease participation. The operator must archive the tenant role first and satisfy its lease guard before the shared identity can be archived.

## API contract

All routes require a ready workspace. Request models forbid unknown fields; application commands independently enforce the same rules for non-HTTP callers.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/tenants` | Create an individual or organization party, tenant profile, and optional initial party contact methods atomically; supports deliberate `confirmedNewParty` override after duplicate review. |
| `POST` | `/api/tenants/from-party/{partyId}` | Designate an existing active party as a tenant profile. |
| `GET` | `/api/tenants` | List tenant profiles with active/archived and text-search filters. |
| `GET` | `/api/tenants/{partyId}` | Return the tenant profile, shared identity, contact methods, and contact preference. |
| `PATCH` | `/api/tenants/{partyId}` | Update profile notes, preference, and do-not-contact status. |
| `GET` | `/api/parties?search={text}&activeOnly=true` | Search/select an existing active identity and surface nonblocking name/contact candidates. |
| `POST` | `/api/parties/{partyId}/contact-methods` | Add one reusable party contact method. |
| `PATCH` | `/api/parties/{partyId}/contact-methods/{methodId}` | Edit one reusable party contact method. |
| `POST` | `/api/parties/{partyId}/contact-methods/{methodId}/archive` | Archive one method, optionally applying typed `referenceResolutions` for every active role preference in the same transaction. |
| `POST` | `/api/parties/{partyId}/contact-methods/{methodId}/restore` | Restore one archived party contact method after its party is active. |
| `POST` | `/api/tenants/{partyId}/archive` | Archive a tenant profile after explicit confirmation. |
| `POST` | `/api/tenants/{partyId}/restore` | Restore an archived tenant profile. |

Responses use explicit Pydantic models. They return stable IDs, party identity, tenant profile fields, and party-owned contact methods. They do not expose future lease, applicant, screening, financial, or portal fields. Duplicate conflicts use `{ "detail": { "code": "possible_duplicate_party", "candidatePartyIds": [...] } }`, capped at 10 active candidate IDs in stable display-name/ID order; they never disclose contact values or archived identities. `confirmedNewParty` is accepted only as an explicit boolean and bypasses this conflict without merging or modifying a candidate.

Errors distinguish missing records (`404`), malformed requests (`422`), invalid business rules (`400`), and duplicate, lifecycle, role/contact-reference, lease-participation, or concurrent-write conflicts (`409`).

## Audit, privacy, and portability

Each mutation writes its data rows and `AUDIT-001` change event in one immediate transaction. A multi-row party/profile/contact create or preference change shares one correlation ID. Audit entity types are `party`, `party_contact_method`, and `tenant_profile`; tenant-owned storage and `tenant_contact_method` events do not remain in the latest-only format. Audit snapshots include stable IDs, lifecycle state, profile preference, and contact-method metadata and values because they are required to understand a contact change; generalized activity redacts display values, normalized values, and phone extensions when the caller has no party-contact context.

Party contact and tenant-profile data are stored only in the external local workspace. The current schema, encrypted backup, export, and restore validation include tenant profiles, party contact methods, role/contact references, and their audit history. Files, message bodies, call recordings, source credentials, and account secrets are outside TEN-001.

## Implementation outline

1. Move all reusable contact values to party-owned `party_contact_methods`; remove scalar `parties.email`, scalar `parties.phone`, and tenant-owned contact storage from the current greenfield baseline.
2. Extend the `parties` application boundary with typed contact commands, duplicate-candidate lookup, caller-owned transaction operations, role-activity guards, and contact-reference guards. Domain modules depend on these protocols rather than importing another module's SQLAlchemy models or repositories.
3. Keep tenant profiles and their exact preferred-contact reference in the `tenants` module with a transaction-oriented port, SQLite adapter, audit presentation policy, and typed FastAPI routes.
4. Add atomic new-party/profile/contact creation, existing-party designation, preference changes, contact lifecycle, tenant lifecycle, and party-role guards with explicit correlation IDs and controlled conflicts.
5. Extend exact product-schema validation, encrypted archive validation, and backup/restore tests for party contacts, tenant profiles, references, and audit history.
6. Add tests for syntactic contact validation and extensions, active duplicate normalization, candidate review and explicit override, preference ownership, lifecycle CHECK constraints, party/contact guards, draft-versus-executed lease archival, audit rollback/correlation/redaction, active-only search, API validation, and backup/restore.

## Acceptance criteria

TEN-001 is complete when:

1. An operator can search/select an existing active party or deliberately create a new identity after reviewing duplicate candidates; identities are never merged automatically.
2. Party-owned contact methods are syntactically validated, normalized, active-only searchable, lifecycle-managed, and reusable by every role without copied scalar contact fields.
3. Tenant preferences select one exact active contact method owned by the party or express no preference; do-not-contact is retained as explicit outbound-delivery state.
4. Profile and contact mutations are atomic with correlated audit events and roll back if audit persistence fails.
5. Archive and restore preserve history; tenant-profile archive respects executed-lease participation, shared-party archive respects the active tenant role, and contact archive respects active preference references.
6. Typed API contracts reject malformed and unknown fields, distinguish 404/400/409 outcomes, and expose no screening or financial data.
7. Current-schema validation and encrypted backup/restore preserve parties, contact methods and extensions, tenant records, preference references, and audit history.
8. The design leaves lease participation, occupancy, communication delivery, screening, finance, and portal access to their owning backlog items.

## Dependencies and follow-on work

TEN-001 requires `PORT-001` for the shared party identity and `AUDIT-001` for required history. It should use the existing `LOCAL-001` workspace and `LOCAL-002` protection capabilities without adding a new data location.

`LEASE-001` depends on TEN-001 and owns lease-participant records. `VEND-001` depends on TEN-001 because it completes the dedicated parties API and must preserve the party-contact and guard protocols established here. `COM-001` uses tenant profiles and preferences to log communication; COM-002 owns outbound delivery enforcement. `ISSUE-AI-002` may suggest tenant matches but must not create, merge, or modify profiles without review. `PORTAL-001` adds tenant self-service only after security, authentication, lease, finance, and communication capabilities exist.
