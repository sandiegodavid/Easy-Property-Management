# Tenant profiles

## Responsibility

A Tenant profile designates an existing shared Party and owns tenant-specific notes, state and contact preference. It is independent of the Lease participant record: a tenant can exist before signing or after move-out, and profile creation does not assign a lease.

## Workflows and guards

Create with a new Party or designate a saved Party through `/api/tenants/from-party/{id}`. Keep duplicate handling in the shared identity boundary. The preferred contact must be an eligible active method belonging to that Party. Updates and archive/restore use the Tenant-owned revision/key contract and immutable result lookup.

Archival checks active Lease participation through transaction-aware guards; historical participation remains readable. Lease participants own their role and effective interval. Shared Party identity and contact edits use [Parties](parties.md), rather than accepting copied identity fields on the Tenant profile.

## API and history

`/api/tenants` supports profile operations and list/detail. Its operation ID/key endpoints recover original committed results. Role designation, profile changes and lifecycle transitions retain correlated audit events and portable snapshots. Browser role forms preserve explicit source identity and distinguish Party revision from Tenant revision.

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

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Browser acceptance is tracked separately in [active UI delivery](../active/UI-001_IMPLEMENTATION_MATRIX.md).
