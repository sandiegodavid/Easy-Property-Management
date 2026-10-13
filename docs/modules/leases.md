# Leases, renewals and termination

## Responsibility and records

Leases owns a contract for one rentable Space, effective term snapshots, Tenant participants and roles, renewal options, and negotiated termination cases/proposals. Files owns documents. Inspections owns condition evidence. Portfolio owns physical occupancy; Finance owns money expectations and actual receipts.

Contract start/end and actual occupancy/move-out are separate. Term and occupancy end boundaries are exclusive; conversion to an inclusive last financial responsibility date belongs to Finance. A signed contract ending does not automatically declare the Space vacant.

## Lifecycle and coordination

Drafts can be edited and their initial terms/participants maintained. Execution checks active property/rentable Space, required terms and participant roles, active Tenant profiles and a valid nonoverlapping occupancy timeline. Missing inspections generate attention without blocking truthful execution or move-out.

Execute/end/terminate/void and renewal transitions coordinate through the Portfolio-owned complete source-timeline operation. The Lease revision protects contractual state and the independent Space revision protects occupancy. Domain effects, timeline, immutable command result and correlated audits commit or roll back together. A missing or incompatible owned timeline conflicts; it is never guessed or incrementally patched into a false success.

Renewal options record proposed dates, decision/deadline context and operator decisions. Renewal does not silently overwrite prior terms or prior financial expectations. A termination case records the request, versioned proposals, acceptance and explicit completion. Accepted fee/rent-responsibility terms are context for separate Finance workflows, not automatic payment or receivable creation.

## Documents, reads and recovery

`/api/leases` provides draft and lifecycle commands, participant and renewal children, termination cases, detail and a bounded `/directory`. Literal directory/operation routes precede dynamic record routes. Mutation responses expose the original operation identity; key/ID lookup returns committed original results after later lifecycle changes.

Lease documents use registered File link policies and retain evidence history. Child commands verify membership and share Lease revision. Inspection revision remains independent, and an Inspection failure cannot erase an already committed Lease.

## Developer workflow

Start with Lease use cases and the Portfolio source-timeline port. Read [Inspections](inspections.md) for walkthrough attention, [Finance](finance.md) for explicit rent synchronization, and [Files](files.md) for document publication. Preserve independent authority and avoid implicit finance or inspection writes during contract changes.

DASH-001's [lease attention reader](../../application/apps/server/app/modules/leases/infrastructure/attention_reader.py) supplies bounded review facts on the caller's read transaction using Portfolio-owned calendar/occupancy relations. An exercised renewal is not a confirmed successor; recorded move-out closes review. See the [Slice 6 validation matrix](../active/DASH-001_CONTRACT_EXAMPLES.md#slice-6-lease-review-attention) for eligibility, continuation and query bounds.

## Browser workflow boundary

Lease browser workflows cover residential/commercial drafts, participants, USD rent/deposit terms, execution, renewal, termination negotiation/completion and move-out with independent Lease/Space revision checks. Milestones distinguish contractual dates from physical occupancy. Current Space status is a separate bounded read with its own unavailable state; its failure does not hide Lease facts. Inspection attention remains in the existing related-inspections section. Rent setup remains an explicit Finance step. Bounded directory continuations retain filters on changed-view restart.

Lease and termination-case document panels open the shared, context-bound FILE-001 upload form. Unfinished forms require the original bytes to be reselected; interrupted responses reconcile the original operation instead of uploading again. Upload completion returns to Lease detail without changing its revision or lifecycle. Active unavailable documents remain visible without a download action; metadata/history is fetched only when selected and retains archived associations. Termination detail displays request explanations, proposal versions, fees, conditions, access arrangements and decision dates without inferring an agreement or move-out. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md).

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/leases/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/leases/application).
- [HTTP contracts](../../application/apps/server/app/modules/leases/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/leases/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `leases`, `lease_command_operations`, `lease_term_versions`, `lease_participants`, `lease_renewal_options`, `lease_termination_cases`, `lease_termination_proposals` | [sqlalchemy_models.py](../../application/apps/server/app/modules/leases/infrastructure/sqlalchemy_models.py) |

## Validation

LEASE-001 acceptance was completed on October 12, 2026. The [completed acceptance record](../archive/designs/LEASE-001_DESIGN_COMPLETED_2026-10-12.md) contains the focused validation matrix and command results. Executable specifications:

- [test_command_readiness.py](../../application/apps/server/app/modules/leases/tests/test_command_readiness.py).
- [test_leases.py](../../application/apps/server/app/modules/leases/tests/test_leases.py).
- [leasing-inspections.spec.ts](../../application/apps/web/tests/leasing-inspections.spec.ts).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Browser acceptance is recorded in [browser validation](../ui/validation.md). Separate Inspection and Finance backlog acceptance remains in [active work](../active/README.md).
