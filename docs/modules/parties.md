# Shared parties and contacts

## Responsibility and identities

A Party is one reusable person or organization identity. Tenant and Provider profiles add roles without copying names or contact data. Client-owner status comes from Portfolio relationships. The local operator is represented explicitly where required and is not synthesized as an owner Party.

Contact methods are multi-valued Party-owned records. Scalar Party email/phone fields are absent. Role-specific preferred methods reference exact contact IDs; editing a display name does not rewrite historical role or payment snapshots.

Email, phone and `mailing_address` contacts may each have multiple active entries, with optional labels. Each populated type has exactly one Party-owned primary, shared across owner, tenant and provider roles. The first entry of a type is automatically primary; an explicit `isPrimary: true` add/update atomically demotes its predecessor, records both contact audit events, and advances the Party revision once. Initial multi-contact creation honors an explicit primary or chooses the first entry of each type. Tenant/Provider role-specific preferred-contact references remain separate and are never silently rewritten by a primary change.

Before archiving a primary with alternatives, select another primary of the same type. The last contact of a type may be archived; restoring it makes it primary only if the type has no active entries. Archived contacts are never primary. The current baseline and model use a partial unique primary index; retained validation additionally requires one primary per active type and matching audit history. Mailing addresses are optional multiline text (up to 1,000 characters), normalized per line; they have no phone extension. Contact commands retain revision checks, immutable replay receipts and privacy rules. A shared postal address alone does not identify a duplicate person.

Portfolio can create an inline owner with up to 100 contact entries in the same transaction as the ownership change. Contact validation, inserts and correlated contact audits must succeed before ownership commits; rollback removes all of them. Existing owners' active contacts are displayed in the ownership-change form and managed through the shared contact workflow. Ownership changes never silently edit an existing person's contacts.

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
- [test_owner_contacts.py](../../application/apps/server/app/modules/parties/tests/test_owner_contacts.py) covers multiline normalization, invalid addresses, multiple addresses with one primary, replay, atomic inline-owner creation, rollback and retained-data tampering.
- [test_primary_contacts.py](../../application/apps/server/app/modules/parties/tests/test_primary_contacts.py) covers each contact type, automatic selection, explicit switches, primary-removal guards, atomic rollback, malformed flags and retained-data tampering. The encrypted round-trip in `test_contact_commands.py` preserves multiple addresses, switched primaries, receipts and audit history. Browser tests in `workflows.spec.ts` cover add/edit/remove, primary switching, stale edits and interrupted-response recovery. Existing contact and inventory query-budget tests remain applicable: contact lists use bounded shared-identity reads, not one request per contact.

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
