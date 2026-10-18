# Tenant profiles

## Responsibility

A Tenant profile designates an existing shared Party and owns tenant-specific notes, state and contact preference. It is independent of the Lease participant record: a tenant can exist before signing or after move-out, and profile creation does not assign a lease.

## Workflows and guards

Create with a new Party or designate a saved Party through `/api/tenants/from-party/{id}`. Keep duplicate handling in the shared identity boundary. The preferred contact must be an eligible active method belonging to that Party. Updates and archive/restore use the Tenant-owned revision/key contract and immutable result lookup.

Archival checks active Lease participation through transaction-aware guards; historical participation remains readable. Lease participants own their role and effective interval. Shared Party identity and contact edits use [Parties](parties.md), rather than accepting copied identity fields on the Tenant profile.

## Official identification

A profile may be saved without official identification. Before executing a Lease, every participant must have at least one recorded official ID; Leasing checks the Tenant-owned projection on the same writer connection, in one bounded participant-set query. Original execution receipts replay before checking mutable eligibility again. This is a recording prerequisite, not identity/authenticity verification or a legal-compliance certification.

`officialIds` contains at most ten masked records: passport, driver's license, state ID, national ID or business registration (for organization tenants), uppercase two-letter issuing country, optional uppercase issuing state/region, exactly four ASCII alphanumeric trailing characters, and optional ISO expiration date. Full numbers, images and arbitrary extra fields are not accepted. Expiration is recorded metadata, not automatic document verification. Duplicate masked identities are rejected.

The Tenant profile owns the list, stored as bounded JSON in `tenant_profiles.official_ids_json`. Creation may include it; profile patches replace it explicitly (an empty list clears it). Existing Tenant revision, stale-conflict, idempotency, no-op and immutable-receipt contracts apply. Changes and their masked contextual history commit atomically; general activity redacts the entire list. The field is not a search key or shared Party contact. Backup/restore preserves masked records, revisions, receipts and correlated audits; retained validation reconstructs them from command history. The current greenfield baseline must be rebuilt after this schema change; no compatibility migration is provided.

## API and history

`/api/tenants` supports profile operations and list/detail. Its operation ID/key endpoints recover original committed results. Role designation, profile changes and lifecycle transitions retain correlated audit events and portable snapshots. Browser role forms preserve explicit source identity and distinguish Party revision from Tenant revision.

## Browser workflow boundary

Tenant profile/contact-preference and lifecycle forms reuse Party identity and owning Tenant receipts. Source participant/context checks remain in the backend; browser designation does not independently infer Lease participation. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/tenants/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/tenants/application).
- [HTTP contracts](../../application/apps/server/app/modules/tenants/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/tenants/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `tenant_profiles`, `tenant_command_operations` | [sqlalchemy_models.py](../../application/apps/server/app/modules/tenants/infrastructure/sqlalchemy_models.py) |

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_command_readiness.py](../../application/apps/server/app/modules/tenants/tests/test_command_readiness.py).
- [test_tenants.py](../../application/apps/server/app/modules/tenants/tests/test_tenants.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
