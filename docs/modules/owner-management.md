# Owner operational concerns

## Responsibility

An owner concern is a distinct client-owner rental, Lease, Tenant or vacancy concern for a Property. It owns reporter context, raised-time evidence, status, handling and resolution. It does not own money, communications, Tasks or Lease/occupancy truth.

## Context and lifecycle

Select an effective client-owner Party for the raised context; retained historical selection follows explicit confirmation rules. Never fabricate a local-operator owner Party. Typed Space/Lease/Tenant context must belong to the selected Property and remain meaningful at the relevant date.

Statuses are `open`, `in_progress`, `resolved` and `dismissed`, with explicit reopening and reasons. Source-linked interactions are projected from Communications. Optional linked follow-up is a Task-owned action. Task completion never resolves the concern; resolving a concern never changes occupancy or Finance.

## Commands and reads

Create/patch/lifecycle/follow-up commands share concern revision, key and immutable original receipt. Validate cross-module context inside the writer transaction. Follow-up creation retains its Task effect with the concern command, not an independently guessed retry key. Lists/detail and batched source facts are bounded and retain historical context.

`/api/owner-concerns` supplies source workflows; ID/key operation endpoints provide recovery. General activity uses redacted policy and contextual history explains full decisions. [Operator](operator.md) composes owner views while this module retains source authority.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/owner_management/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/owner_management/application).
- [HTTP contracts](../../application/apps/server/app/modules/owner_management/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/owner_management/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `owner_concerns`, `owner_concern_follow_up_operations`, `owner_concern_command_operations` | [sqlalchemy_models.py](../../application/apps/server/app/modules/owner_management/infrastructure/sqlalchemy_models.py) |

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_command_readiness.py](../../application/apps/server/app/modules/owner_management/tests/test_command_readiness.py).
- [test_owner_concerns.py](../../application/apps/server/app/modules/owner_management/tests/test_owner_concerns.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Browser acceptance is tracked separately in [active UI delivery](../active/UI-001_IMPLEMENTATION_MATRIX.md).
