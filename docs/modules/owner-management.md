# Owner operational concerns

## Responsibility

An owner concern is a distinct client-owner rental, Lease, Tenant or vacancy concern for a Property. It owns reporter context, raised-time evidence, status, handling and resolution. It does not own money, communications, Tasks or Lease/occupancy truth.

## Context and lifecycle

Select an effective client-owner Party for the raised context; retained historical selection follows explicit confirmation rules. Never fabricate a local-operator owner Party. Typed Space/Lease/Tenant context must belong to the selected Property and remain meaningful at the relevant date.

Statuses are `open`, `in_progress`, `resolved` and `dismissed`, with explicit reopening and reasons. Source-linked interactions are projected from Communications. Optional linked follow-up is a Task-owned action. Task completion never resolves the concern; resolving a concern never changes occupancy or Finance.

## Commands and reads

Create/patch/lifecycle/follow-up commands share concern revision, key and immutable original receipt. Validate cross-module context inside the writer transaction. Follow-up creation retains its Task effect with the concern command, not an independently guessed retry key. Lists/detail and batched source facts are bounded and retain historical context.

`/api/owner-concerns` supplies source workflows; ID/key operation endpoints provide recovery. General activity uses redacted policy and contextual history explains full decisions. [Operator](operator.md) composes owner views while this module retains source authority.

The [DASH-001 attention reader](../../application/apps/server/app/modules/owner_management/infrastructure/attention_reader.py) classifies unresolved concerns from explicit owning follow-up operations, with bounded Task/reminder previews and retained owner context. Generic related Tasks do not establish waiting; terminal concerns do not terminalize their Tasks. See the [Slice 7 validation matrix](../archive/validation/DASH-001_CONTRACT_EXAMPLES_COMPLETED_2026-10-14.md#slice-7-owner-report-and-concern-attention).

## Browser workflow boundary

Concern browser records provide context/history, lifecycle and linked follow-up through source commands and Operator recovery. Task completion never resolves a concern and resolution never changes Lease or Finance state. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

Create review distinguishes general rental from Space-required vacancy and Space/Lease-required Lease or Tenant concerns. Tenant concerns also require that Lease's participant. Bounded Property/Space choices include labeled archived context; exact Property/Owner/Lease reads show current source state without asserting historical eligibility. The server validates all references at the Property-local raised date. Backdated archived/ended selection requires explicit historical confirmation/reason; Local operator never becomes an Owner Party.

Duplicate conflicts show up to 20 candidate drill-downs. An explicit separate review carries requested context in transient router state, never narratives in the URL, and requires independent-concern confirmation/reason. It does not merge records or edit/reuse a locked original attempt. Dismissed concerns without a successor offer a reasoned target-correction workflow with context prefilled; the new concern may change its target and retains nonbranching predecessor/successor history.

Detail separates stored source/occupancy/availability snapshots from current source facts. It shows originating/corrected conversation links, bounded recent conversations and independent Task follow-ups. Start, resolve, dismiss and reopen remain explicit source commands; required receipt recovery handles interrupted follow-up creation without another Task. Directory filters include Owner/Property/Space/Lease/Tenant, type and local raised range, with persistence-owned pagination and no row detail fan-out.

OWNER-004's source workflow is complete. Home owner-action/concern presentation remains under [DASH-001](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md), as confirmed October 13, 2026; its existing attention reader is not a claim that Home browser presentation is delivered.

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

Source workflow acceptance completed October 13, 2026; see the [completed matrix](../archive/designs/OWNER-004_DESIGN_COMPLETED_2026-10-13.md). Review feedback is in [concern-context.tsx](../../application/apps/web/src/workflows/concern-context.tsx) and real-workspace browser proofs in [work.spec.ts](../../application/apps/web/tests/work.spec.ts).

- [test_command_readiness.py](../../application/apps/server/app/modules/owner_management/tests/test_command_readiness.py).
- [test_owner_concerns.py](../../application/apps/server/app/modules/owner_management/tests/test_owner_concerns.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
