# Tenant and owner portal delivery plan

Status: planned for implementation after HOSTED-001; not delivered. This plan expands
PORTAL-001/002 in the [backlog](../FEATURE_BACKLOG.md). It does not add either portal
to the capacity-qualified Free-only Pilot 0. Use the [hosted foundation](../hosting/design/HOSTED_MVP_DESIGN.md),
[current module ownership](../ARCHITECTURE.md) and [payment design](PAY-001_DESIGN.md).

## Development and deployment

Tenant and Owner portals must run locally for development/testing, while their customer-facing production deployment is hosted-only. Admin has the same boundary; Operator supports both hosted and single-operator local production. See the [deployment matrix](../hosting/design/mvp/scope.md#development-and-production-deployment-boundary). Include isolated synthetic fixtures, local launch configuration and role/origin tests in each portal's detailed design before implementation. Development-only test adapters cannot authorize production access or real transfers. The production local application must not register tenant/owner APIs or expose these portals. This does not change paid-hosted entitlements or include portals in Pilot 0.

## Independent portal releases

Tenant and Owner have separate versioned artifacts and deployment assignments, independent
of Admin and per-workspace Operator runtime releases. Their detailed designs must include
standalone build/package/serve contracts, required API/auth/schema compatibility, canary
and rollback/status handling. Reuse existing UI packages at build time without requiring
all portals to ship the same version. Validate each portal against all admitted source
versions it may reach; new shared backend capability needs an explicit compatible source
upgrade, not another workspace writer. Asset-only rollback never restores business data.
Active forms/payment attempts retain original identities across asset refresh; a refresh
must not initiate another transfer. This remains future portal delivery, not Pilot 0.

## Shared experience and authority

All three portals use the same source-owned rent, assessed late fees, lease terms and
payment states. Operator controls publication, corrections and handling; tenants and
owners get explicitly scoped projections, never operator API access. Pending bank
processing is not received money; payout is distinct from payment. Failed/stale reads
show unavailable/as-of rather than zero, with independent section loading/errors.

| Experience | Operator | Tenant | Owner |
| --- | --- | --- | --- |
| Rent | All managed leases, balances, allocations and exceptions | Granted lease balance and eligible payment amounts | Authorized properties/leases, rent activity and relevant totals |
| Late fees | Configure/preview/review/assess/waive/correct through FIN-009 | Published assessed charge and calculation basis; no assessment power | Published assessed charge/basis in authorized property context; no assessment power |
| Lease terms | Own contractual changes and select published terms/documents | Own lease's published rent, dates, obligations and approved documents | Authorized property's published lease terms; exclude unnecessary tenant personal evidence |
| Payment | PAY-001 collections/reconciliation and PAY-002 authorized outgoing routes | PAY-001 own authorization, payment/autopay, status/history/receipts/help | PAY-002 own authorized outgoing routes, recipient setup/status and incoming-payment history |
| Report issue/concern | Triage/respond through Maintenance or Owner management | Submit and follow own lease/property issues | Submit and follow own property concerns |
| Reports | Current Finance sources and owner statement workflows | Own payment history/receipts | Explicit-period authorized reports/statements with source drill-down/download |

Reuse responsive light/dark components, keyboard navigation, clear selected workspace/
property/lease, revision conflicts and original-operation recovery. Multiple devices may
act as the same identity; unknown outcomes require status lookup, never a new payment.
Only operators buy EPM subscriptions. Tenant access uses both paid operator tiers;
owner access is provisionally included on those same tiers, subject to commercial
confirmation before launch. Free operators retain their manual business workflows.

Managed identity verifies issuer/subject; an operator-issued effective lease/owner
relationship grant authorizes access. Invite/revoke/rebind with revision and audit,
exclude former/future parties' data and revalidate on every request/download. A shared
email or guessed property ID is not a grant. General staff roles and public submission
links are not prerequisites. Tenant and owner sessions cannot inherit operator authority.

## PORTAL-001 — tenant slices

| Order | Delivery | Acceptance |
| --- | --- | --- |
| T01 | Operator participant invitation/grants/publication plus tenant enrollment/recovery, lease selection and shell | Exact host/issuer/grant; cross-lease/role denial; former tenant history narrowly bounded; revocation effective across devices. Reuse PAY-001 identity slice, not a second login system. |
| T02 | Rent, published lease terms and late-fee read composition; matching operator review/publication controls | Same Finance cents, revisions, due dates/property zone and assessed fee basis on both sides. Published fields/documents only; no internal notes, screening data or cotenant bank details. |
| T03 | Embed PAY-001 payment/history/help/autopay, adding assessed-fee allocation only after FIN-009 integration qualifies | Preview separates rent/fees, discloses order and consent, shows recipient/method/processing. No redirect-as-success or duplicate income. Preserve PAY-001 accounting/lifecycle/live-funds gates. |
| T04 | Report issue, safe evidence upload, receipt/status/follow-up and operator handling | Resolve property/lease/reporter from grant. Schema/size limits, idempotent submission and retained original receipt. Source-owned Maintenance issue/reporter history; attachment failure does not duplicate a committed issue. Tenant sees only published responses/status, never internal/provider private notes. |
| T05 | Full mobile/multi-device, revocation, downgrade, backup/restore and live qualification | Safe reads/history/help after collection ends; cancellation remains available; no historical grant revival. Issue submission after plan loss follows explicit current capability and never claims delivery when blocked. Show emergency contact guidance; submission is not monitored emergency dispatch. |

PORTAL-001 includes usable issue submission and tracking, not a general tenant chat or
unrestricted document library. It need not wait for INTAKE-001's later scoped-link channel.
PAY-001 remains the sole payment engine; T01/T03 accept its work rather than repeating it.

## PORTAL-002 — owner slices

| Order | Delivery | Acceptance |
| --- | --- | --- |
| O01 | Individual owner grants, operator publication controls, owner shell/property directory | Effective owner/property relationships, explicit historical access and revocation; multiple authorized properties selectable. Another owner's data denied, including exports and operation lookups. |
| O02 | Rent/assessed late fees/published lease terms and payment/history composition | Current source revisions/as-of and independent errors. Publish appropriate tenant details only; no tenant banking, screening evidence or operator internal notes. Separate rent, fees, expenses, received money and payout. |
| O03 | Concern submission/history/published responses and operator triage through OWNER-004 | Server-bound owner/property/reporter, safe optional evidence, duplicate-safe retry, source lifecycle and follow-up. Resolving concern does not change lease/money; no automatic provider assignment. |
| O04 | Scoped reports/statements/drill-down/download using FIN-003 and OWNER-001/002 | Exact authorized scope/period; distinguish whole-property activity from owner entitlement/share. Exclude other ownership interests and private records. Balance/disbursement numbers require source-owned statement contracts, not a portal calculation. |
| O05 | Owner payment actions via PAY-002 and operator reconciliation | Actual owner's authorization and verified recipient/purpose; operator authority cannot silently authorize owner debit. Only provider-qualified routes visible. Incoming receipt is not payout; no separate portal ledger. |
| O06 | End-to-end privacy, mobile/device, downgrade/recovery and operational acceptance | Stable operation identities, no stale grant/session restoration, tenant/private-note exclusions, exact report totals and source links; supported reads/export retained on plan loss under current grants. |

Owner payment means the owner can authorize their own qualified payments and inspect
receipts/payouts. It does not permit collecting another party's funds or directing an
operator's bank account. Unsupported PAY-002 routes cannot be marked implemented merely
because a manual transfer can be recorded. Reports are included in PORTAL-002; advanced
configurable dashboards remain RPT-005, avoiding a circular dependency.

## FIN-009 — shared late-fee prerequisite

Implement before accepting late-fee functionality in any portal:

1. Define a versioned source contract linked to the lease: operator-confirmed policy,
   applicability/effective dates, grace boundary, calculation basis, supported fixed or
   percentage formula, caps/frequency, rounding and property time zone. Require a stated
   contractual/rule basis and operator review; ship no invented default rate or universal
   jurisdiction eligibility. Unsupported combinations must fail validation.
2. Calculate a preview at an explicit as-of/revision, showing eligible unpaid rent,
   receipts/processing treatment, dates and each calculation step. A quote is not debt.
   Settle precise partial-payment, pending-bank, returned-payment and retroactive-change
   treatment in the FIN-009 design before coding; do not reuse a generic late flag.
3. Explicit operator confirmation assesses an immutable charge identity. Versioned
   waiver/correction/reversal preserves reason and audit. Enforce idempotency per lease,
   policy and assessment period/occurrence; retries cannot charge twice.
4. Publish assessed charges and calculations through scoped read contracts. Separate
   rent and fee obligations, allocations and report totals. Operator previews from a
   later rule version cannot silently rewrite existing assessments.
5. Extend Payments/Finance source-owned reservation, allocation, receipt and partial
   return/refund contracts to cover the supported charge types. Show allocation order
   before authorization. A rent-only mandate cannot silently authorize extra late fees;
   preserve consent/caps and obtain fresh consent where required.

These are implementation design gates, not permission to infer legal entitlement or
charge fees automatically. Resolve policy details in FIN-009 before its implementation;
HOSTED-001 H01 can start now without waiting for them.

## Cross-feature validation

| Area | Required proof |
| --- | --- |
| Happy paths | Same rent/fee/terms/payment facts on all authorized portals; tenant issue and owner concern reach operator with original reporter; report totals drill down exactly. |
| Invalid combinations/privacy | Forged host/role/lease/owner/operation/download; unpublished/private fields; unsupported fee policies; expired/revoked grants; unqualified payment route; no false zero on failed reads. |
| Idempotency/concurrency | Double submit/device, issue attachment retry, fee assessment retry/changed key payload, manual receipt versus fee/payment reservation, changed source revision and provider event duplicates. |
| Rollback | Assessment/publication/submission plus audit/result rollback together; external payment unknown outcome reconciles without a second transfer. |
| Persistence/schema | Current source-owned schema/constraints, grant scope, policy snapshots, unique assessment/payment identity, integer cents and retained histories. |
| Backup/restore | Business records/files recover consistently; authority/session not revived; payment reconciliation before reopening; publication scope independently checked. |
| Performance | Bounded scoped lists/reports, set-based reads without per-property/lease fan-out; responsive async sections and bounded polling. |
| Browser/operations | Mobile/keyboard/themes, multiple devices, quota errors preserve input, stale-preview refresh, maintenance notice/drain and end-of-subscription transitions. |
