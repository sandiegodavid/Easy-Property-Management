# Shared parties and contacts

## Responsibility and identities

A Party is one reusable person or organization identity. Tenant and Provider profiles add roles without copying names or contact data. Client-owner status comes from Portfolio relationships. The local operator is represented explicitly where required and is not synthesized as an owner Party.

Contact methods are multi-valued Party-owned records. Scalar Party email/phone fields are absent. Role-specific preferred methods reference exact contact IDs; editing a display name does not rewrite historical role or payment snapshots.

## Workflows

Create a Party, or select an existing one before designating a role. Duplicate warnings require deliberate selection/confirmation; they never silently merge identities. Identity and contact create/edit/archive/restore commands have durable receipts and displayed revision checks. Contact mutations validate Party ownership, exact method identity and active preference references.

Party archival consults every registered active-role guard inside the writer transaction. Contact archival consults reference guards, so an active preferred method cannot disappear through a side door. Bootstrap composes these protocols; Parties does not import Tenant or Provider persistence models.

## API and disclosure

`/api/parties` owns identity and `/api/parties/{id}/contact-methods` owns contacts. `/operations/{id}` and `/operations/by-key/{key}` recover original responses. Global activity uses the registered redacted policy; contextual detail/history supplies permitted data. Shared identities survive role archival and remain retained for historical references.

Read-only `GET /api/parties/selection` supplies bounded identity-only choices for owning workflows such as deposit payer/recipient selection. It defaults to 25, caps at 100, excludes archived identities unless explicitly requested, supports Unicode-normalized name search and uses the same stable ID ordering for cursor comparison and continuation. Each page is one SQL query with LIMIT before hydration; it loads no contact or role records.

Read [Tenants](tenants.md), [Providers](providers.md) and [Portfolio](portfolio.md) for role-specific eligibility and relationship rules.

## Browser workflow boundary

Shared Party/contact forms retain identity/duplicate guards and source revisions. Tenant and Provider designation reuse shared identity through owning commands; saved forms and original-result recovery preserve child membership. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/parties/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/parties/application).
- [HTTP contracts](../../application/apps/server/app/modules/parties/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/parties/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `parties`, `party_command_operations`, `party_contact_methods` | [sqlalchemy_models.py](../../application/apps/server/app/modules/parties/infrastructure/sqlalchemy_models.py) |

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_contact_commands.py](../../application/apps/server/app/modules/parties/tests/test_contact_commands.py).
- [test_identity_commands.py](../../application/apps/server/app/modules/parties/tests/test_identity_commands.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
