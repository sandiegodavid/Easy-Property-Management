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

The [DASH-001 attention reader](../../application/apps/server/app/modules/owner_accounting/infrastructure/attention_reader.py) supplies bounded pending-verification facts on the caller's read transaction, retaining historical owner and Lease context without treating reports as income. See the [Slice 7 validation matrix](../active/DASH-001_CONTRACT_EXAMPLES.md#slice-7-owner-report-and-concern-attention).

## Browser workflow boundary

Owner-report browser verification requires explicit receipt-adoption or receipt-creation choice and current report plus ledger revisions. Conflicts preserve review notes; matching receipts are counted once. Statements/disbursements/fees retain separate delivery scopes. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

Claim creation/edit review shows Property zone/current ownership choices, selected Party name/archive state and stored claim facts. Current Property ownership is not presented as historical eligibility: an ended Owner may be absent from that projection, while the server validates the retained identity's relationship on the payment date. Archived historical identities remain selectable by their contextual ID. No Owner Party is synthesized for Local operator ownership. Amounts display exact USD cents; pending/rejected claims create no income.

Verification offers only active receipt choices matching the report's date, amount, recipient and immutable method snapshot from a bounded 100-receipt page. Finance rechecks compatibility, allocations and exclusive report linkage. Creation review shows reported/allocated/remaining totals and prevents unmatched allocation totals. A duplicate conflict supplies bounded receipt drill-down links and a separate explicit adoption review, never an independent-payment override. Lost verification responses reconcile the original operation without a second receipt or dispatch.

Terminal correction starts a new report with predecessor Owner/date/method/source context prefilled; amount and report timestamp require fresh input. Detail links prior/replacement reports, the verified receipt and its successor. A verified predecessor's active receipt must be voided in Finance first; creation-mode verification prefills its exact replacement pointer. Report/evidence state refresh cannot erase the immutable committed-result view.

Evidence is uploaded independently and reviewed through Files metadata. Contextual archive uses File-link revision, confirmation and reason; the server protects the last active available link on verified reports. Active and archived evidence/history remain distinct, and unavailable content cannot be opened. The report directory combines status, Owner/Property/Lease scope, received-date range, active-evidence and linked-receipt-lifecycle filters. HTTP evidence query booleans are parsed from URL values; command body booleans remain strict. Page reads stay set-based without row-by-row detail queries.

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

OWNER-003 acceptance completed on October 13, 2026; see the [completed matrix](../archive/designs/OWNER-003_DESIGN_COMPLETED_2026-10-13.md). Browser review/filters are in [owner-report-context.tsx](../../application/apps/web/src/workflows/owner-report-context.tsx), coordinated verification in [money-command.tsx](../../application/apps/web/src/workflows/money-command.tsx), and real-workspace acceptance in [money.spec.ts](../../application/apps/web/tests/money.spec.ts).

- [test_owner_accounting.py](../../application/apps/server/app/modules/owner_accounting/tests/test_owner_accounting.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
