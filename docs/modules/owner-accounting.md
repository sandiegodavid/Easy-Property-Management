# Owner-reported rent

## Responsibility and money boundary

An owner rent report preserves one client owner's claim of one payment for one Lease/date, its evidence and verification decision. A pending/rejected report is provenance, not received income. Finance remains the sole receipt/allocation authority.

The selected client-owner relationship must be effective on the payment date. Historical relationships/Parties may remain truthful context. Local-operator ownership has no Party ID and uses ordinary Finance receipts; mixed ownership requires selection of the specific client owner and implies no percentage entitlement.

## Verification

The operator either adopts one active compatible Finance receipt or explicitly creates one through Finance's transaction port. Match Lease, date, USD amount, recipient and immutable actual-method snapshot exactly. Creation supplies valid allocations and the expected rent-ledger revision. A likely existing receipt must be reviewed; this workflow cannot override duplication as an independent payment.

Report verification, any new Finance receipt/allocations, command result and audit commit in one immediate transaction. Original key recovery must not count money again. Files belong to the report as supporting evidence and never automatically verify the claim.

## Lifecycle and correction

Pending reports can be patched. Verified/rejected records preserve the decision. A later voided receipt leaves the report historically verified but financially ineffective; reads disclose the receipt's current status. Replacement lineage cannot branch. A verified replacement must correspond to the active Finance replacement receipt and its voided predecessor.

## API and interpretation

`/api/owner-rent-reports` supplies create/edit/verify/reject/detail/list; `/api/owner-rent-report-operations/{key}` recovers committed results. Owner summaries count the linked receipt once. Statements, fees, distributable balances and disbursements are separate planned capabilities and are not computed by this report module.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/owner_accounting/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/owner_accounting/application).
- [HTTP contracts](../../application/apps/server/app/modules/owner_accounting/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/owner_accounting/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `owner_rent_reports`, `owner_rent_report_operations` | [sqlalchemy_models.py](../../application/apps/server/app/modules/owner_accounting/infrastructure/sqlalchemy_models.py) |

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_owner_accounting.py](../../application/apps/server/app/modules/owner_accounting/tests/test_owner_accounting.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Browser acceptance is tracked separately in [active UI delivery](../active/UI-001_IMPLEMENTATION_MATRIX.md).
