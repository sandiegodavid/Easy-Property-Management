# PAY-001 — Hosted tenant rent payments

Status: future payment-feature design, aligned November 10, 2026 with the [hosted MVP design](../hosting/design/HOSTED_MVP_DESIGN.md). Tenant access and rent payments follow that hosting task through the now-scheduled portal/payment backlog. This document does not qualify or deploy a rent-payment processor, tenant access or paid service, authorize live funds, or establish implementation completion. The backlog now schedules HOSTED-001 before PAY-001 and the expanded PORTAL-001/002 work.

## Purpose and scope

Close the payment gap identified in [market research](../../biz/EPM_MARKET_RESEARCH_2026-10-25.md#o2-payments-sold-on-payout-speed-and-transparency): make paying rent straightforward, expose fees and payout progress, and reconcile payment outcomes into the records operators already use. Payment completion and exception handling are part of delivery, not just checkout.

Local EPM remains free. Hosted EPM has Free and two paid operator subscriptions, provisionally 50 MB / 200 MB / 1 GB of usable workspace storage at $0 / $10 / $20 USD monthly. The hosted design owns this provisional catalog, publication gates, automated subscription billing, identity, storage and recovery policies. Storage counts business database usage plus retained managed files; there is no fixed property/space entitlement or separate attachment allowance. Imports, when delivered, are included on every tier. Tenant access/payments are intended future benefits on both paid tiers, not delivered benefits of the initial hosting task. Tenants do not buy subscriptions.

Stripe Checkout/Billing/Customer Portal handles operator subscriptions in the hosted design. That choice does not select or qualify the rent-payment processor. Subscription charges, tenant rent transfers and recipient-paid processing fees have separate identities, authority and accounting. A subscription checkout return is neither proof of effective paid capability nor evidence that tenant rent was paid.

PAY-001 includes tenant authentication/authorization, operator payment setup, enforcement of the effective collection capability, payment-specific transactional notifications, help, bank payment initiation, autopay, reconciliation and all related UI. Reuse the qualified hosted foundation rather than rebuilding operator login, subscription billing, storage-tier UI or container lifecycle inside Payments. The existing operator-only demo is insufficient. Initial SAAS-001/SEC-001 delivery is consolidated into HOSTED-001; SEC-002 retains later advanced roles. None is marked implemented by this design. PORTAL-001 composes this payment area with published lease terms, assessed late-fee views and tenant issue reporting. General messaging and unrestricted document libraries remain later extensions. PAY-001 does not depend on PORTAL-001 or FIN-004 bank feeds, avoiding a cycle. See the [portal implementation plan](PORTALS_IMPLEMENTATION_PLAN.md).

HOSTED-001 is now a hard hosting prerequisite. FIN-009 is a prerequisite specifically for assessed late-fee collection, not the rent-only engine or hosted Pilot 0. Before enabling tenant access, qualify lease-scoped identity/grants, the central-login handoff and exact operator-origin routing for tenant actors as well as operators. A verified managed identity or paid operator subscription alone never grants tenant access.

Hard dependencies: HOSTED-001, LOCAL-001/002, AUDIT-001, TEN-001, LEASE-001, FIN-001/002/006 and OWNER-003. FIN-002 owns actual processor-fee spending through an explicit source-owned handoff. Dependencies and implementation slices must be complete before live collection. This design does not authorize live charges, invitations, host changes or processor purchases.

Out of first release: cards, deposits, utilities, arbitrary prepayments/credit wallets, guarantor/unrelated third-party payer accounts, general tenant messaging or maintenance, tenant-initiated refunds, automated rent-payment retries and local payment initiation. Operator subscription billing is owned by the hosted foundation, outside PAY-001. PAY-002 continues to own other payment directions. FIN-009 owns late-fee calculation/assessment; extend the rent-only contracts below for assessed fees before PORTAL-001 acceptance. A separate reviewed Finance/Payments contract must specify fee allocation, reporting, partial return/refund and mandate consent. Existing rent-only previews or mandates cannot silently include fees.

## Accepted experience and operating rules

| Decision | Agreed behavior |
| --- | --- |
| Q1–Q6: offering | Focused rent-payment area; future hosted-only benefit on either paid operator tier; no tenant subscription. Free local and Free hosted operator offerings remain. Owner or operator receives rent directly through the qualified rent processor. One-time payments followed by autopay in the same intended PAY-001 release. No initial EPM transaction markup; rent processor fees and operator subscription charges remain distinct. |
| Q7–Q8: methods/fees | US bank payments first. Processor-hosted bank entry and authorization. Recipient absorbs standard processing fees; no tenant surcharge in the first release. |
| Q9–Q10: amounts/participants | Partial payments allowed by default, configurable per lease; full payable balance preselected. Only issued future rent is eligible after older rent. Individual primary/co-tenant access; explicit individual authorization for business signatories. No shared credentials, guarantor or unrelated payer access. |
| Q11–Q13: access/autopay/notices | Operator invites an existing participant; shared managed Google/email-link authentication and explicit tenant lease grants. Fixed monthly amount/date, capped at eligible rent remaining, tenant-authorized. Transactional email only, with delivery status. |
| Q14–Q15: lifecycle | Confirmed subscription capability, including existing-paid renewal grace, followed by safe wind-down when collection capability ends; historical receipts and authorization cancellation remain accessible. Lease end stops autopay; renewal and changed recipient require fresh authorization. |
| Q16–Q18: exceptions | No automatic retry. Unknown outcome requires status reconciliation. Processing and overdue dates shown separately; no automatic late fees/legal timeliness decision. Processor-console refunds initially; Finance reconciles the separate financial consequence. |
| Q19–Q20: shell/limits | Rent, Payment history, Account; explicit lease selection. Reuse hosted unified storage allowances: Free 50 MB, Paid 1 200 MB, Paid 2 1 GB. At quota preserve reads/export, billing repair, backups and supported cleanup; payment reconciliation needs bounded reserved capacity, not an unrestricted write exemption. |
| Q21–Q24: publication/allocation | Explicit per-lease activation and opening-balance review. Rent-only baseline, with separately identified FIN-009 assessed fees after integration qualifies. Oldest eligible rent first; immutable preview and recheck before initiation. Processing reservations prevent duplicate collection; excess funds become explicit exceptions. |
| Q25–Q27: help/rollout/outage | Structured payment-help queue and tenant-visible responses. One qualified processor, sandbox then approved live pilot. Stale/unavailable balance disables new initiation; existing activity reconciles before reopening. |
| Q28–Q32: confirmation/security/recovery | Payment receipt and payout are separate. Access removal explicitly addresses mandates. Restore requires reconciliation. Minimal private notifications. Platform-owned verified effective subscription capability; restore cannot reinstate old grants. Both paid tiers retain the intended payment capability when switching between them. |

## Current implementation and required boundaries

[Architecture](../ARCHITECTURE.md), [Finance](../modules/finance.md), [Tenants](../modules/tenants.md), [owner accounting](../modules/owner-accounting.md) and [operator UI](../ui/operator-experience.md) describe shipped behavior. The former active UI-001 design is consolidated into the UI guides.

- `application/apps/server/app/modules/hosted_access/application/configuration.py` and `application/service.py` bind one operator email to broad workspace access. `app/platform/actor_context.py` currently supplies an operator actor. A tenant must never be admitted as that operator or gain existing operator routes by hiding navigation.
- Tenant profiles are business identities, not login identities. Lease participation supplies party, role and effective dates. Verify access through explicit grants; matching a contact email alone is not authorization.
- Finance records received money. Its `domain/models.py` receipt command requires exact fully allocated cents. `application/commands.py` owns revision/idempotency and audit atomicity. It has no safe generic unallocated-credit receipt to reuse.
- The receipt UI in `application/apps/web/src/workflows/money-command.tsx` is manual recording, not collection. Preserve it for free operators and external payments.
- OWNER-003 verifies owner claims against Finance receipts. A processor-confirmed owner payment must create/adopt one receipt with provider provenance, not a second income path through an additional owner claim.
- No production checkout, payment event consumer or tenant payment actor is currently implemented. Provider confirmation, fee booking, return/refund corrections and restore fencing need source-owned extensions; they cannot be achieved by adding a tenant page alone.

## Tenant workflows

### Invitation and account

The operator opens Lease → Tenant payments, reviews participants and invites selected individuals. The invitation contains the property/unit, inviting manager and secure enrollment link, never payment or bank credentials. A single-use expiring invitation is bound to workspace, participant, intended email and grant revision. Email verification must finish before grant activation; guessing a lease ID or reusing an invitation cannot grant access.

Reuse the hosted managed identity provider (Google Identity Platform/Firebase Google sign-in and email-link login), fixed central authentication domain and exact callback. Bind the single-use browser handoff to the registered operator origin; establish a Secure, HttpOnly, host-only tenant session with its own actor/grant scope, never a broad operator session or parent-domain cookie. Qualify tenant session validity and recovery before launch rather than assuming operator remembered-login policy grants tenant authority. Apply rate limits, bounded invitation/handoff attempts and non-enumerating errors; managed issuer/subject, not mutable email, is the durable identity. Revoke invitations and sessions explicitly. Email changes require authenticated recovery/reverification and explicit rebinding, never automatic reassignment of another person's history. Business signatories receive individual grants linked to their authorized organization/lease role.

Returning tenants select a lease if more than one is available. Each workspace remains isolated; the first release need not aggregate unrelated operators into one balance. Every page states property/unit and recipient context. Account offers email/account recovery, current sessions/sign-out-all and links to managing payment authorizations. Bank method edits go through hosted processor screens.

### Rent and checkout

Rent is the landing page. Its main card shows rent balance, due date, processing amount, available-to-pay amount, last successful refresh and Pay rent. Autopay is a separate card with amount, date, recipient, next scheduled attempt and Manage autopay. Recent activity and Get payment help sit below it. Use the existing warm neutral/teal visual language, light/dark tokens and accessible status labels in a simpler tenant shell; no operator sidebar.

The server computes posted rent outstanding, processing reservations and payable amount separately. Do not subtract a settled payment both as a receipt allocation and as a reservation. A positive processing amount is not received rent. Failed reads show unavailable, not zero. A zero payable amount caused by processing says “Payment processing,” not “All paid.”

Pay rent opens an amount/period review, oldest eligible rent first. Default to full payable rent; when partial payment is disabled, require the full eligible payable amount. Future rent requires explicit selection and older eligible rent must be covered first. Display rent allocation, gross amount, zero tenant processing fee, recipient and payment method before continuing to processor-hosted authorization. Never use browser-supplied balances, recipient IDs or redirect results as authority.

On return from the processor, show “Checking payment” until the server verifies its state. Closing a tab, navigating Back or losing the response never produces a second attempt automatically. Provide Check payment status for an unresolved attempt. History and receipts remain reachable across devices.

Receipt detail shows rent amount/allocations, payer's own safe method label, payment reference, submission/confirmation dates and corrections. Other cotenants see shared balance and aggregate applied payment activity without bank information, payer identity or private failure details. Historical access is bounded to the person's granted lease/participation scope; no subsequent tenant data is exposed.

### Autopay

The tenant selects a fixed monthly maximum, local calendar date and own processor method. Show recipient, amount, schedule, cancellation route and consequences of insufficient scheduled rent. At each occurrence prepare the lesser of the authorized amount and eligible payable rent, after excluding live reservations. Skip zero amounts. If partial payments are disabled and the authorized maximum cannot cover the full eligible payable amount, skip the debit and notify the tenant/operator rather than charging a forbidden partial amount or exceeding consent. Changing that policy previews its effect on existing mandates. Monthly dates clamp to month end; schedule display uses the property zone. Provider lead times, bank holidays and required notices must be qualified before enabling the chosen dates; do not promise a same-day payout or legal timeliness.

First release autopay covers already-issued rent due by the scheduled date, oldest first; it does not silently pay future periods. Weekly/irregular leases can use one-time payments; monthly autopay is offered only where its preview makes the resulting coverage clear. Notify the tenant of a remaining balance when their authorized amount will not cover rent. An increased lease rent does not raise the mandate automatically.

Manual payment and autopay share the same lease reservation boundary. The UI warns about approaching or processing autopay. Cancellation is a durable request with pending/confirmed/failed status; do not say canceled until the processor's relevant authorization/schedule is disabled or EPM's qualified scheduling authority is fenced. In-flight payments may not be cancelable.

Processor-managed scheduling is preferred only if it supports an authoritative EPM balance check/cap for each occurrence. If it cannot, autopay is blocked pending a revised, explicitly reviewed orchestration design. An independent fixed debit running regardless of EPM balance does not satisfy this design. During an EPM outage, already-submitted payments may finish, but no new scheduled occurrence may debit without the qualified authoritative balance/cap check. A processor must skip or hold an occurrence whose check is unavailable; it cannot treat timeout as permission. Qualification must also settle how loss of effective collection capability, access suspension, restore and overdue reconciliation stop future debits. Tenant access removal must not disable the operator account; operator account suspension must fence collection across the workspace.

### Help and former tenants

Get payment help creates a lease/payment-linked case: incorrect balance, failed payment, duplicate, missing confirmation or other payment question. Show case ID, status and operator responses. The operator can respond or resolve; the tenant can reply/reopen a payment case. Keep internal notes separate from tenant-visible responses. No general messaging inbox or attachments are required initially; provider-specific issues link to qualified support instructions without exposing secrets.

Former tenants retain their own receipts and explicitly published historical outstanding rent. Publication grants must not grow with future occupancy or renewed leases automatically. After collection capability ends, tenant access is limited to history, relevant unresolved payment help and mandate cancellation; new collection is disabled. Retain only independently verified, explicitly scoped grants, including after an operator workspace returns to Free.

## Operator and administrator workflows

Money → Payments provides Processing, Needs attention and History views, filters by property/lease/recipient and links to Finance source records. A status count must not hide failed reads. Needs attention includes returned/failed payments, unmatched events, excess funds, pending cancellation, delivery failures and unresolved help. Each item names the next action and current owner.

Lease → Tenant payments is a guided setup:

1. Verify hosted production readiness, delivered/qualified payment-feature availability and effective paid collection capability. A desired plan or successful checkout redirect is insufficient; tenant lease grants remain a separate check.
2. Onboard the owner or operator recipient through the processor. Show verification/payout readiness; raw bank information stays with the processor. One verified recipient arrangement per lease; do not infer it from later ownership edits.
3. Review generated rent expectations, existing manual receipts and opening balance; resolve owner claims or duplicate candidates before publishing.
4. Select eligible participants and review exactly what they will see. Configure partial payments.
5. Confirm Enable tenant payments, then send invitations. Pending/failed delivery remains visible and retryable.

Once enabled, ordinary rent generated through the existing confirmed schedule becomes published under the approved arrangement. Financial corrections require an explicit before/after tenant-visible preview. Publication never generates rent independently of Finance. Revisions fence previews; an existing authorization does not permit changing its recipient or increasing its amount.

Payment detail shows gross rent, fee, net proceeds, payment status, payout status/estimate, event freshness and linked receipts/corrections. Do not conflate a batched payout with one rent payment. Initial refunds use the processor console and are observed by EPM. The operator separately resolves any change to rent obligation; refunding money does not erase a charge.

Settings reuses the hosted plan, unified usage/freshness, change/cancel controls and durable operation status. Payment setup/detail links to it and explains payment eligibility and any end-of-service checklist; it does not create a second billing or quota editor. The platform reconciles Stripe subscription facts into verified effective capabilities through owning ports. PAY-001 checks those capabilities without opening the Admin database or treating a plan badge as authority. Routine paid access does not use Admin-assigned pilot dates. Exceptional complimentary grants remain explicit, audited, time-bounded and capacity-qualified under the hosted design. No tenant gains billing or Admin rights.

At storage limits retain reads/export, billing repair, backups and supported cleanup, with input-preserving growth denials. Reserve bounded capacity for provider events, accounting consequences, audit and recovery so already-submitted money can still be reconciled, including after downgrade. Reject new unadmitted growth/initiation safely before capacity is exhausted; no unlimited reconciliation exemption. If required accounting capacity is unavailable, preserve the durable provider outcome, alert the operator/Admin and reconcile through the original identity. Infrastructure admission and physical reserves remain separate from the advertised allowance.

### Changes and wind-down

| Trigger | Required behavior |
| --- | --- |
| Paid collection capability ending | Cancellation or paid-to-Free downgrade takes effect at paid-period end; failed renewal retains the existing paid capability during the seven-day grace, then Free restrictions. Show the effective boundary and advance notices; stop future scheduling beyond it, request provider-schedule cancellation, verify outcome and expose failures. Continue in-flight reconciliation, returns/refunds, historical access and own-mandate cancellation. Do not infer operator disablement or workspace deletion. |
| Switching between paid tiers | Retain payment capability and grants; apply the hosted storage/recovery change without canceling valid mandates solely because the paid plan changed. First-time paid activation still requires verified payment and applied capability; failed first checkout earns no grace benefits. |
| Lease ending | Stop future autopay at the effective lease boundary; retain receipts and authorized historical arrears. Renewal needs a new grant/arrangement and fresh mandate; do not inherit automatically. |
| Recipient change | Pause initiation, onboard/verify replacement, show pending payments to original recipient, notify and obtain fresh tenant authorization. No rerouting in-flight money. |
| Remove access | Preview affected grants and mandates; explicitly cancel/pause relevant future collection. Security suspension immediately fences new actions and EPM scheduling. Track any outstanding provider cancellation; access revocation itself must not wait for provider availability. |
| Failed/returned payment | Confirm provider state, release reservation or apply source-owned correction once, show restored rent balance and notify privately. No automatic retry. |
| Provider/account restriction | Disable affected new collections, retain observed state, expose operator action and continue status reconciliation where permitted. |

## Backend design

### Ownership and proposed records

Add a `payments` module with domain/application/infrastructure/api layers, source-owned Finance/Lease/Party ports and a processor adapter. Add a hosted tenant-access boundary and tenant-specific read compositions; do not repurpose the broad operator actor. Platform primitives supply audit/errors/transactions, not payment policy.

| Record group | Required facts and authority |
| --- | --- |
| Hosted identity and grants | Reuse managed issuer/subject and platform assignment; add verified tenant contact binding, workspace/party/lease grant, effective scope, invitation hash/expiry and tenant session/revocation generation. Protected hosted control state outside portable business backups; tenant capabilities distinct from operator capabilities. Live tenant authority must be independently reconciled after recovery. |
| Effective collection capability | Platform-owned read contract: workspace, verified effective plan/capabilities, feature availability, paid-through/grace boundary, state/revision and source operation references. Stripe owns subscription/payment facts; control jobs apply and verify effective source authority. Payments does not own a parallel subscription registry. Restoring business data cannot resurrect paid capability, account activation or sessions. |
| Recipient and lease arrangement | Processor/account/environment reference, recipient party or operator identity, verification state, lease, publication revision, partial-payment policy, enabled/paused state and frozen recipient history. Credentials separate from workspace. |
| Publication | Expectation identity/revision and tenant-facing visibility, opening-balance confirmation, arrangement revision and grants. Reads compose Finance facts rather than copying a mutable balance. |
| Attempt and reservation | Workspace/lease/payer identity, amount/currency, frozen allocations, recipient, ledger/arrangement revision, idempotency key, processor object, reservation state, command result and timestamps. |
| Mandate and occurrence | Payer, consent reference/version/time, method token reference, recipient, fixed maximum, date/property zone, active/end/cancel state; unique mandate+scheduled occurrence identity and resulting attempt. No raw bank credentials. |
| Provider inbox and reconciliation | Verified provider account/environment/event ID, payload digest and minimal validated facts, processing state, cursor/freshness, corrections and retry diagnostics. Conflicting duplicate payloads quarantined. |
| Financial mapping | Unique payment-to-receipt lineage, allocation/adoption proof, fee expense link, return/refund correction links, gross/fee/net and payout references. |
| Help and notifications | Scoped case and append-only replies, internal/public visibility, status; outbox event/template/recipient/dedupe key, delivery attempts/results. No source financial authority. |

Retain operation records and financial mappings in portable business data; keep usable authentication, secrets and execution authority outside it. Exported processor references are inert until explicit reauthorization/reconciliation. Use the latest greenfield schema and retained validation; no migration compatibility project is introduced.

### API boundary

Proposed contract families, generated through existing OpenAPI tooling:

| Boundary | Operations |
| --- | --- |
| Tenant access | Accept invitation, session/current grants, sign-out/all devices, recovery through managed authentication. Server resolves authorized workspace; client parameters never choose authority. |
| `/api/tenant/leases/{leaseId}/rent` | Scoped balance/publication, as-of and ledger revision, processing reservations, recipient and available actions. |
| `/api/tenant/leases/{leaseId}/payment-previews` | Validate amount/period selection; issue expiring preview bound to payer, grants, ledger and arrangement. No charge. |
| `/api/tenant/leases/{leaseId}/payments` | Confirm preview with idempotency key; create durable intent, reserve amount and return attempt/hosted authorization status. |
| `/api/tenant/payments/{id}` | Own attempt status, safe receipt and original operation lookup. Other-party detail is denied even within the lease. |
| Tenant autopay/help | Preview/authorize/cancel own mandate; create/read/reply to scoped help cases. All consequential mutations revision/key protected. |
| Operator payment routes | Arrangement activation/publication, invitations/revocation, recipient setup, exceptions/help, reconciliation status. Existing operator record routes stay forbidden to tenants. |
| Provider events | Dedicated signature-verified raw-body endpoint, bounded size and replay checks, isolated from browser session/CSRF handling; account/environment mapping establishes workspace. |
| Hosted account/billing integration | Reuse platform subscription and operation-status ports, source account fences and narrowly authorized complimentary-grant operations. Operator Settings owns self-service checkout/change/cancel; Admin owns operational intervention/capacity gates. Tenant grants never confer these privileges. |

Use shared API problem mappings, including 413 for oversized content, 409 for stale/semantic conflicts, 401 for missing authentication and consistent non-disclosing denial for unauthorized objects. Enforce authorization on every detail, list, receipt/download, operation lookup and mutation; deny tenant access to operator search, files, exports, drafts and debug endpoints. Payment-required responses expose safe capability state, not a substitute for object authorization. Historical reads, own-mandate cancellation and unresolved payment help remain permitted by their narrowly scoped grants after collection capability ends; they do not depend on a current collection entitlement.

### Atomic initiation and external calls

1. Under the workspace's existing single-writer transaction, verify actor/grant, effective collection capability, current binding/epoch, published lease scope, recipient readiness and processor freshness. Replay a matching prior command before creating any new intent. Reject changed semantics under the same key.
2. Revalidate preview revisions and amount. Reserve eligible rent and persist immutable intent, audit and outbox dispatch atomically. Do not call external APIs while holding the SQLite writer.
3. A durable worker claims the intent and calls the processor with the stable provider idempotency key and frozen recipient/amount. Lost responses trigger provider lookup; never create a new intent to guess whether the first succeeded.
4. The signed event inbox and authenticated provider queries resolve the attempt. A browser redirect cannot establish payment success. Release a reservation only after definitive failure/cancellation/expiry is verified; local checkout timeout alone is insufficient.
5. Manual Finance receipt writes and corrections use a shared source-owned lease coordination port so reservations and incoming receipts cannot pass independent balance checks. Preserve the ability to record actual external money; conflicts become operator reconciliation, not fictitious allocations or suppressed receipts.

Two simultaneous tenants, tabs, devices or workers must compete through the same lease-level invariant. An outbox operation and its reservation roll back together. A remote payment cannot roll back with a local transaction: persist and retry reconciliation using the original identity until its consequence is recorded or explicitly quarantined.

### Accounting, returns and excess funds

Qualify the exact provider event that permits creating a received-rent record. Distinguish authorization, processing, confirmed receipt and recipient payout. A payout delay is not another unpaid rent amount. Returns after confirmation require correction history, not deleting a payment or pretending confirmation never occurred.

Finance owns an atomic apply-provider-outcome operation with semantic idempotency, receipt/allocations, audit and Payments mapping in one caller transaction. Preserve existing direct-owner receipt provenance. Matching an existing manual receipt requires exact evidence/explicit review; fuzzy date/amount matching cannot automatically adopt it.

Gross rent is allocated income; withheld processor fees are separate confirmed spending through FIN-002, and net payout is a separate projection. Provider fee refunds/adjustments follow expense correction rules. A processor dispute or deducted payout alone is not enough to invent an expense/refund classification; unsupported adjustments remain visible reconciliation exceptions until mapped to a qualified source-owned contract. Do not reduce rent income by the fee or record a payout as additional income. FIN-004 bank-line matching later links to these same records.

Add a Finance-owned unapplied processor-funds exception for confirmed money that cannot safely fit existing expectations after a race/correction. It is not a tenant spendable wallet: show gross confirmed funds, allocated rent and unresolved amount separately, with exactly one provider source identity. Do not drop confirmed money or fabricate future charges to satisfy the existing fully-allocated receipt command. Operator resolution may allocate to legitimate published rent with explicit review or reconcile an actual provider refund; conservation of cents and immutable history are required.

Refunds and returns need typed source-owned partial/full correction contracts. A bank return reverses the corresponding received-money effect once and restores applicable outstanding rent. A refund records money sent back; changing the underlying rent obligation requires a separate confirmed source correction. Provider status alone cannot void an unrelated charge. These contracts and summary/report treatment are required Finance extensions in Slice 5, not capabilities claimed for existing receipt APIs.

### Workers, freshness and restart

Use a supervised durable worker with SQLite-backed inbox/outbox/occurrence records and short transactions through existing workspace lock coordination. Do not run a second uncoordinated writer process. A hosting-compatible worker lifecycle is required: either the owning application process runs it or a qualified service coordinates the same writer authority. Schedule state must survive server restarts; in-memory timers alone are insufficient. Integrate with the hosted lifecycle: paid runtimes stay warm initially, but required reconciliation/cancellation work must remain scheduled when a workspace returns to Free and may sleep. Do not suspend admitted work or let UI polling keep a Free runtime awake indefinitely; use the qualified platform scheduling/wake boundary for due work.

Webhooks provide prompt updates; periodic provider reconciliation supplies missed/out-of-order event recovery. Deduplicate by account+environment+provider identity and re-read canonical object state when event ordering is uncertain. Use bounded backoff and observable lag; do not retry a debit as if it were a read. Disable new initiation when relevant status freshness cannot satisfy the configured qualified threshold. Expose timestamps and next action rather than a false all-clear.

### Recovery and security

Business backups include consistent payment records, mappings, exception balances and outbox state. Hosted auth/session generations, credentials and execution authority are not restored from them. Use the hosted encrypted off-host recovery catalog and Admin-confirmed separate-destination restore/switchover; preserve the pre-restore state. Restore starts all affected collection in Reconciliation required, obtains a new host execution fence and prevents the former runtime from dispatching. Independently reconcile current account/subscription authority and revoke affected app sessions before reopening; neither an old paid grant nor an old enabled flag is restored from an archive. Reauthorize recipient accounts, reconcile events since the restored snapshot and verify mandate state before explicit reopening. Stable provider keys survive restore so an older outbox cannot generate a second debit.

Hosted per-operator releases follow qualified image/schema pins, a suggested low-activity window, all-device drain and a verified pre-upgrade recovery point. Automatic restoration of pre-upgrade data is permitted only before any post-reopen operator writes; otherwise use a forward fix or reviewed recovery that preserves accepted writes. Any allowed rollback or workspace move follows the same collection fence. If the chosen processor cannot establish authoritative history or cancellation state, keep collection disabled and surface manual recovery. Historical receipts remain readable where identity is independently verified. Never automatically resume an old canceled mandate from backup.

Payment method entry stays hosted by the processor; EPM stores only allowed opaque references and safe display labels. Keep payment pages and secrets out of analytics/session replay, browser persistent storage and logs. Validate hosted redirect destinations, CSRF/Origin, secure sessions and webhook signatures separately. Scope audit actors to tenant/operator/system provider processing with immutable attribution.

## Notifications and usability acceptance

Send invitation, upcoming autopay, submitted/confirmed/failed/returned/canceled payment, authorization and recipient-change notices. Prefer processor notices where adequate; one event/channel has one configured sender. EPM supplies missing lifecycle/help notices. Durable outbox identities prevent duplicate sends after restart. Delivery failure does not change payment outcome.

Messages contain minimal property context and the recipient's own payment amount where appropriate, secure links and safe support guidance. Exclude bank details, cotenant identity and private failure explanations. Upcoming-payment notice lead time and cancellation cutoffs must be validated with the processor; users see the actual supported schedule before consenting.

All tenant pages work at narrow mobile widths, keyboard-only, 200% text scaling and both themes. Use labeled controls, focus restoration, error summaries and accessible status announcements. Slow sections retain independent loading/error states. Disable repeated submit while an intent is unresolved, but preserve a usable status check and help route. UI labels distinguish rent owed, processing, payable now, confirmed payment, payout estimate and refund; never show a generic success banner for all of them.

## Ordered implementation slices

| Order | Cohesive delivery | Acceptance gate |
| --- | --- | --- |
| 1 | Rent processor and hosted integration qualification | Reuse the selected hosted identity/subscription/recovery services; qualify tenant access and payment-specific delivery. Identify one rent processor and obtain evidence for recipient onboarding, direct settlement, all fees, notices, capped autopay, cancellation, event history and restore. Document exact API/event mapping and limits. Unsupported cap/safety behavior blocks dependent build, not silently weakened scope. |
| 2 | Tenant identity and hosted capability integration | Separate actor/grants/routes, managed enrollment/recovery and exact-origin handoff; consume verified subscription capability and quota ports. Link existing plan/usage UI and preserve Free operator continuity. Prove cross-workspace/role denial; no parallel billing registry or pilot-date editor. |
| 3 | Lease payment setup and publication | Recipient setup, opening balance review, participant invitations, partial policy, activation/correction UI and tenant Rent read model with safe shared history. |
| 4 | One-time hosted payment | Preview, authorization, reservation/outbox, original-attempt recovery and mobile checkout/status/history; sandbox only until accounting gate. |
| 5 | Financial outcomes and exception workflow | Provider inbox/polling, source-owned receipt/fee/return/refund mapping, unapplied-funds exception, operator queues, tenant receipts, gross/net/payout displays and reporting consistency. |
| 6 | Help and transactional delivery | Scoped cases/replies, operator triage, sender ownership, notification outbox/delivery failures and tenant help/history. |
| 7 | Autopay | Qualified capped occurrence scheduling, consent, manual overlap, notices, cancel/pause and lease/recipient changes. One-time payments do not alone complete PAY-001. |
| 8 | Lifecycle, backup and recovery acceptance | Paid-to-Free transition/grace, paid-to-paid continuity, over-quota reconciliation, access removal/security suspension, lease end, outage/restart/sleep, platform restore/upgrade fences and persistent cancellation failures. |
| 9 | Hosted live pilot and release | Explicit approval for live funds; small bounded set of leases, real enrollment/collection/payout/return-support evidence, observed fees/latency, operator runbook and support ownership. Full usable tenant/operator workflows are completion criteria. |

These are PAY-001 delivery slices after the required hosted foundation qualifies; they are not part of the initial hosting delivery. Each slice includes its required backend, UI and focused tests. No separate UI backlog postpones the usable workflow. Do not enable real collection at Slice 4; financial and lifecycle acceptance are launch gates.

## Validation matrix

| Area | Required evidence |
| --- | --- |
| Happy paths | Owner/operator recipient; one-time full/partial; issued future rent; two roommates; fixed capped autopay; skipped zero; fee/net/payout and receipt drill-down. |
| Invalid combinations | Local/Free/unavailable or revoked collection capability initiation; unconfirmed first-time subscription checkout; unverified recipient; unpublished rent; deposits/cards; disallowed partial; invalid dates/amounts; guarantor access; changed recipient/preview. |
| Isolation/privacy | Cross-workspace/lease/payment/operation-ID requests denied; tenant operator endpoints forbidden; shared balance excludes private method/payer/failure data; archived/former/new tenant boundaries; email reassignment. |
| Idempotency/concurrency | Double click/device; manual receipt vs autopay; two tenants; duplicate/changed/out-of-order events; timeout after provider acceptance; same key changed payload; duplicate occurrence; webhook/poll race. |
| Rollback | Crash before/after intent commit, provider call and event application; no orphan reservation, duplicate debit, receipt without mapping or fee double count. |
| Accounting | Fees distinct from income; payout batches; owner claim adoption; partial/full returns/refunds; excess funds; allocation correction; exact conservation and audit lineage across reports. |
| Persistence | Current-schema checks, unique source identities, consent/recipient snapshots, operation replay, retained exception history, terminal-state evidence and invalid JSON rejection. |
| Backup/restore | Restored outbox cannot resubmit; canceled mandates stay canceled; old runtime fenced; current subscription/account/grants reconciled without restoring old sessions; reauth/reconciliation required; missing provider history blocks reopening. Verify payment consistency at each tier's qualified recovery points. |
| Lifecycle | Cancellation/paid-to-Free transition and seven-day renewal grace during processing; paid-to-paid change retains collection; failed first checkout grants nothing; over-quota reconciliation; cancellation failure; lease end/renewal; recipient change; session/access revocation; history/cancel/help after capability ends; required work survives Free sleep. |
| Notifications/help | Duplicate delivery prevention, provider/EPM sender overlap, email failures, private vs shared visibility, help reopen and support handoff. |
| Performance | Bounded 50-row cursor lists; set-based lease/balance/payment reads; compare query counts for 1 vs 50 rows to prove no per-row queries; short writer locks, no provider network call under transaction; responsive loading during worker backlog. |
| Browser/accessibility | Phone/desktop, keyboard/zoom/theme, refresh/back/multiple tabs, expired session and hosted redirects, unknown payment status, slow/offline reads without false zero/success. |
| Operational pilot | Sandbox/live separation, quotas/headroom, webhook validation, monitored reconciliation lag, recovery drill, documented support ownership and approved real-data/funds admission. |

## Late-fee integration for portal acceptance

Before PORTAL-001 is accepted, add FIN-009 assessed-charge identities to previews, reservations, allocations, receipt/fee breakdowns, reports and source-owned return/refund corrections. Preserve the rent-only baseline until these contracts qualify. Calculation previews are not assessed debt; recipient processing fees are not lease late fees. Show allocation order and required consent explicitly, and test fee waiver/payment races and source revisions. This extension does not allow arbitrary charges or automatic legal eligibility decisions.

## Remaining qualification gates, not assumed decisions

The accepted product scope is settled. Before implementation beyond the relevant gates, record provider-specific facts: merchant/recipient eligibility and fund-flow responsibilities; availability of balance-capped scheduling; mandate notices and date/cancellation cutoffs; actual fees, return/dispute handling and payout estimates; authoritative confirmation events; historical reconciliation reach; tenant qualification of the selected hosted identity provider, payment-email delivery and session policy; reserved reconciliation capacity and operational support. Review applicable processor terms and payment obligations with qualified advice where needed. No speed or fee claim becomes a product promise before qualification.

The hosted design owns provisional plan prices/allowances, automated operator billing and capacity qualification. PAY-001 does not reopen those decisions or imply that choosing Stripe for subscriptions proves rent-collection suitability. Paid subscription launch must stand on delivered storage/recovery benefits; advertise tenant payments only after the payment-specific live-funds gates pass. No fixed space limit or unlimited Free hosting capacity is implied.
