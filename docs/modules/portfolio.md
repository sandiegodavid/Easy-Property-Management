# Portfolio, ownership and occupancy

## Responsibility

Portfolio owns physical Properties and child Spaces, operational ownership relationships, occupancy timelines and availability intentions. Parties owns reusable person/organization identity; Leases owns contractual dates and participants. A property is a reporting boundary, while a Space is the independently rentable or operational unit.

## Properties and ownership

Properties use US addresses and locally resolved canonical US IANA zones. Supported classifications include homes, condos, townhomes and offices; multi-space inventory represents office suites without introducing apartment operations. An active property's ownership is `self_owned`, `managed_for_owner` or `mixed`, derived from effective relationships.

`local_operator` ownership has no Party ID. `client_owner` references a shared Party. Effective intervals include the start and exclude the end, evaluated on each property's local day. Ownership describes operating context, not percentage shares or legal entitlement. Replacing ownership retains prior relationships rather than overwriting history.

Property/Space inventory and lifecycle commands share the owning Property revision and immutable inventory receipts. Space occupancy/availability commands use the separate Space status revision. Keep these authorities distinct in forms and coordinated writes. Property archival retains history and records which child archival effects it caused; restoration follows those recorded effects and lifecycle guards.

## Occupancy and availability

Occupancy is an effective-dated timeline; availability is the operator's current intention. Occupied does not imply unavailable, and vacant does not imply listed. Return their separate current states, source identity, upcoming transitions and revision. Unknown or conflicting data must remain visible.

Manual commands support changes, current-period correction and scheduled cancellation/reschedule/replacement. Source-owned periods cannot be silently rewritten by a manual action. Validate the complete resulting timeline for overlap and source authority before persistence. Keep cancelled/superseded periods as history.

## Lease integration

The Portfolio-owned `PortfolioSourceTimelineService` receives one complete `SourceTimelineChangeSet`: replacements, inserts, source identity, expected Space revision, UUID key, correlation and semantic request context. It validates and applies the timeline on the caller's transaction, advances the Space revision once and retains one operation result. Lease execution, close, void and renewal use this boundary rather than coordinating raw period writes independently.

The outer Lease operation also validates its own Lease revision. A contract end does not establish physical vacancy; the recorded actual move-out supplies that boundary. Replays recover the original source-timeline/Lease result without reapplying changes.

## Read and API contracts

`/api/properties` and child `/spaces` operations own inventory. `/api/spaces/{id}/status`, occupancy and availability routes own operational status. Inventory and status operations have separate read-only ID/key lookup routes. Property lists and status summaries return bounded source facts; the [Operator module](operator.md) composes contextual directories and owner views.

## Code path for timeline work

Read [source_timeline.py](../../application/apps/server/app/modules/portfolio/application/source_timeline.py), then the Lease service call sites and the Portfolio unit of work. Preserve source ownership, the independent revisions, complete pre-write validation and one transaction across both modules.

## Browser workflow boundary

Portfolio browser forms cover Property/Space inventory, lifecycle, ownership and manual status with source revision review and original receipts. Property/Owner directories and workspaces use Operator compositions; progressive setup never infers vacancy or fabricates local-operator owner identity. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/portfolio/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/portfolio/application).
- [HTTP contracts](../../application/apps/server/app/modules/portfolio/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/portfolio/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `properties`, `portfolio_inventory_operations`, `property_ownerships`, `spaces`, `space_occupancy_periods`, `space_availability`, `space_status_operations` | [sqlalchemy_models.py](../../application/apps/server/app/modules/portfolio/infrastructure/sqlalchemy_models.py) |

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_command_readiness.py](../../application/apps/server/app/modules/portfolio/tests/test_command_readiness.py).
- [test_inventory_readiness.py](../../application/apps/server/app/modules/portfolio/tests/test_inventory_readiness.py).
- [test_portfolio.py](../../application/apps/server/app/modules/portfolio/tests/test_portfolio.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
