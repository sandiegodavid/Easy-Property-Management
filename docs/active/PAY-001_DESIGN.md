# PAY-001 — Hosted tenant rent payments

Accepted product decisions: October 27, 2026. Status: design; no payment processor, tenant access, or premium service is qualified or deployed by this document.

## Purpose and scope

Close the payment gap identified in [market research](../../biz/EPM_MARKET_RESEARCH_2026-10-25.md#o2-payments-sold-on-payout-speed-and-transparency): make paying rent straightforward, expose fees and payout progress, and reconcile payment outcomes into the records operators already use. Payment completion and exception handling are part of delivery, not just checkout.

Local EPM and the hosted operator workspace remain free. The initial free hosted allowance is one operator, five rentable spaces and 250 MB of attachments per workspace. Tenant-facing functionality is hosted-only and premium, purchased by the operator; tenants do not buy subscriptions. Premium pricing/capacity remains a commercial decision. A private administrator assigns dated entitlements for the pilot; automated subscription billing is deferred. Physical host admission, recovery capacity and workspace quotas still apply independently of product allowances.

PAY-001 includes tenant authentication/authorization, operator setup, premium enforcement, transactional notifications, payment help, bank payment initiation, autopay, reconciliation and all related UI. These bounded hosted capabilities are prerequisites implemented within its ordered slices; the existing operator-only demo is insufficient. Broader SAAS-001/SEC-001/SEC-002 capabilities remain separate and are not marked complete. PORTAL-001 later extends this payment area with general documents, communications and maintenance; PAY-001 does not depend on that extension or FIN-004 bank feeds.

Hard source dependencies: LOCAL-001/002, AUDIT-001, TEN-001, LEASE-001, FIN-001/002/006 and OWNER-003. FIN-002 owns actual processor-fee spending through an explicit source-owned handoff. Dependencies and implementation slices must be complete before live collection. This design does not authorize live charges, invitations, host changes or processor purchases.

Out of first release: cards, deposits, utilities, late fees, arbitrary prepayments/credit wallets, guarantor/unrelated third-party payer accounts, general tenant messaging or maintenance, tenant-initiated refunds, automated retries, automated subscription billing and local payment initiation. PAY-002 continues to own other payment directions.

## Accepted experience and operating rules

| Decision | Agreed behavior |
| --- | --- |
| Q1–Q6: offering | Focused rent-payment area; hosted-only premium; operator subscription; free local and bounded free hosted operator functionality. Owner or operator receives funds directly through the processor. One-time payments followed by autopay in the same intended release. No EPM transaction markup initially; processor fees remain distinct. |
| Q7–Q8: methods/fees | US bank payments first. Processor-hosted bank entry and authorization. Recipient absorbs standard processing fees; no tenant surcharge in the first release. |
| Q9–Q10: amounts/participants | Partial payments allowed by default, configurable per lease; full payable balance preselected. Only issued future rent is eligible after older rent. Individual primary/co-tenant access; explicit individual authorization for business signatories. No shared credentials, guarantor or unrelated payer access. |
| Q11–Q13: access/autopay/notices | Operator invites an existing participant; managed email-code authentication and explicit lease grants. Fixed monthly amount/date, capped at eligible rent remaining, tenant-authorized. Transactional email only, with delivery status. |
| Q14–Q15: lifecycle | Paid-through service followed by safe wind-down; historical receipts and authorization cancellation remain accessible. Lease end stops autopay; renewal and changed recipient require fresh authorization. |
| Q16–Q18: exceptions | No automatic retry. Unknown outcome requires status reconciliation. Processing and overdue dates shown separately; no automatic late fees/legal timeliness decision. Processor-console refunds initially; Finance reconciles the separate financial consequence. |
| Q19–Q20: shell/limits | Rent, Payment history, Account; explicit lease selection. Free hosted allowance: one operator, five spaces, 250 MB attachments. Limits block additions, not reads, export or corrections. |
| Q21–Q24: publication/allocation | Explicit per-lease activation and opening-balance review. Rent-only balance. Oldest eligible rent first; immutable preview and recheck before initiation. Processing reservations prevent duplicate collection; excess funds become explicit exceptions. |
| Q25–Q27: help/rollout/outage | Structured payment-help queue and tenant-visible responses. One qualified processor, sandbox then approved live pilot. Stale/unavailable balance disables new initiation; existing activity reconciles before reopening. |
| Q28–Q32: confirmation/security/recovery | Payment receipt and payout are separate. Access removal explicitly addresses mandates. Restore requires reconciliation. Minimal private notifications. Admin-assigned pilot premium dates; automated EPM billing later. |

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

Use managed authentication with email codes. Apply rate limits, bounded code attempts and non-enumerating errors; provider subject, not mutable email, is the durable identity. Revoke invitations and sessions explicitly. Email changes require authenticated recovery/reverification and explicit rebinding, never automatic reassignment of another person's history. Business signatories receive individual grants linked to their authorized organization/lease role.

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

Processor-managed scheduling is preferred only if it supports an authoritative EPM balance check/cap for each occurrence. If it cannot, autopay is blocked pending a revised, explicitly reviewed orchestration design. An independent fixed debit running regardless of EPM balance does not satisfy this design. During an EPM outage, already-submitted payments may finish, but no new scheduled occurrence may debit without the qualified authoritative balance/cap check. A processor must skip or hold an occurrence whose check is unavailable; it cannot treat timeout as permission. Qualification must also settle how premium expiry, access suspension, restore and overdue reconciliation stop future debits.

### Help and former tenants

Get payment help creates a lease/payment-linked case: incorrect balance, failed payment, duplicate, missing confirmation or other payment question. Show case ID, status and operator responses. The operator can respond or resolve; the tenant can reply/reopen a payment case. Keep internal notes separate from tenant-visible responses. No general messaging inbox or attachments are required initially; provider-specific issues link to qualified support instructions without exposing secrets.

Former tenants retain their own receipts and explicitly published historical outstanding rent. Publication grants must not grow with future occupancy or renewed leases automatically. Post-premium access is limited to history, relevant unresolved payment help and mandate cancellation; new collection is disabled.

## Operator and administrator workflows

Money → Payments provides Processing, Needs attention and History views, filters by property/lease/recipient and links to Finance source records. A status count must not hide failed reads. Needs attention includes returned/failed payments, unmatched events, excess funds, pending cancellation, delivery failures and unresolved help. Each item names the next action and current owner.

Lease → Tenant payments is a guided setup:

1. Verify hosted production readiness and active premium entitlement.
2. Onboard the owner or operator recipient through the processor. Show verification/payout readiness; raw bank information stays with the processor. One verified recipient arrangement per lease; do not infer it from later ownership edits.
3. Review generated rent expectations, existing manual receipts and opening balance; resolve owner claims or duplicate candidates before publishing.
4. Select eligible participants and review exactly what they will see. Configure partial payments.
5. Confirm Enable tenant payments, then send invitations. Pending/failed delivery remains visible and retryable.

Once enabled, ordinary rent generated through the existing confirmed schedule becomes published under the approved arrangement. Financial corrections require an explicit before/after tenant-visible preview. Publication never generates rent independently of Finance. Revisions fence previews; an existing authorization does not permit changing its recipient or increasing its amount.

Payment detail shows gross rent, fee, net proceeds, payment status, payout status/estimate, event freshness and linked receipts/corrections. Do not conflate a batched payout with one rent payment. Initial refunds use the processor console and are observed by EPM. The operator separately resolves any change to rent obligation; refunding money does not erase a charge.

A private administrator assigns premium start/end dates, reason and actor with revision and idempotency protection. The operator sees plan status, limits and the end-of-service checklist. No tenant gains administrative access. Free hosted limits count provisioned spaces, including archived spaces until an explicit verified retention policy permits removal; attachment usage is measured in bytes across retained versions. This product allowance must not replace infrastructure disk admission or impose an unsafe hard stop on reconciliation writes. Preserve capacity for audit/events/recovery; reject new uploads before exhausting disk.

### Changes and wind-down

| Trigger | Required behavior |
| --- | --- |
| Premium ending | Advance notices and paid-through date; stop scheduling future collections beyond it, request cancellation of standing provider schedules, verify outcome and expose failures. Continue in-flight reconciliation, returns/refunds and historical access. |
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
| Hosted identity and grants | Managed issuer/subject, verified contact binding, workspace/party/lease grant, effective scope, invitation hash/expiry, session/revocation generation. Hosted control state outside portable business backups; tenant capabilities distinct from operator capabilities. |
| Entitlement | Workspace, plan, starts/ends, state/revision, assigning administrator, audit/operation result. Host control plane authoritative; restore cannot resurrect premium. |
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
| Private administration | Assign/revoke dated entitlement; inspect capacity and lifecycle gates. No browser tenant or ordinary operator privilege. |

Use shared API problem mappings, including 413 for oversized content, 409 for stale/semantic conflicts, 401 for missing authentication and consistent non-disclosing denial for unauthorized objects. Enforce authorization on every detail, list, receipt/download, operation lookup and mutation; deny tenant access to operator search, files, exports, drafts and debug endpoints. Payment-required responses expose safe capability state, not a substitute for object authorization. Historical reads, own-mandate cancellation and unresolved payment help remain permitted by their narrowly scoped grants after premium expiry; they do not depend on a current collection entitlement.

### Atomic initiation and external calls

1. Under the workspace's existing single-writer transaction, verify actor/grant, entitlement, current binding/epoch, published lease scope, recipient readiness and processor freshness. Replay a matching prior command before creating any new intent. Reject changed semantics under the same key.
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

Use a supervised durable worker with SQLite-backed inbox/outbox/occurrence records and short transactions through existing workspace lock coordination. Do not run a second uncoordinated writer process. A hosting-compatible worker lifecycle is required: either the owning application process runs it or a qualified service coordinates the same writer authority. Schedule state must survive server restarts; in-memory timers alone are insufficient.

Webhooks provide prompt updates; periodic provider reconciliation supplies missed/out-of-order event recovery. Deduplicate by account+environment+provider identity and re-read canonical object state when event ordering is uncertain. Use bounded backoff and observable lag; do not retry a debit as if it were a read. Disable new initiation when relevant status freshness cannot satisfy the configured qualified threshold. Expose timestamps and next action rather than a false all-clear.

### Recovery and security

Business backups include consistent payment records, mappings, exception balances and outbox state. Hosted auth/session generations, credentials and execution authority are not restored from them. Restore starts all affected collection in Reconciliation required, obtains a new host execution fence and prevents the former runtime from dispatching. Reauthorize recipient accounts, reconcile events since the restored snapshot and verify mandate state before explicit reopening. Stable provider keys survive restore so an older outbox cannot generate a second debit.

Rollback to an earlier release or moving a workspace follows the same fence. If the chosen processor cannot establish authoritative history or cancellation state, keep collection disabled and surface manual recovery. Historical receipts remain readable where identity is independently verified. Never automatically resume an old canceled mandate from backup.

Payment method entry stays hosted by the processor; EPM stores only allowed opaque references and safe display labels. Keep payment pages and secrets out of analytics/session replay, browser persistent storage and logs. Validate hosted redirect destinations, CSRF/Origin, secure sessions and webhook signatures separately. Scope audit actors to tenant/operator/system provider processing with immutable attribution.

## Notifications and usability acceptance

Send invitation, upcoming autopay, submitted/confirmed/failed/returned/canceled payment, authorization and recipient-change notices. Prefer processor notices where adequate; one event/channel has one configured sender. EPM supplies missing lifecycle/help notices. Durable outbox identities prevent duplicate sends after restart. Delivery failure does not change payment outcome.

Messages contain minimal property context and the recipient's own payment amount where appropriate, secure links and safe support guidance. Exclude bank details, cotenant identity and private failure explanations. Upcoming-payment notice lead time and cancellation cutoffs must be validated with the processor; users see the actual supported schedule before consenting.

All tenant pages work at narrow mobile widths, keyboard-only, 200% text scaling and both themes. Use labeled controls, focus restoration, error summaries and accessible status announcements. Slow sections retain independent loading/error states. Disable repeated submit while an intent is unresolved, but preserve a usable status check and help route. UI labels distinguish rent owed, processing, payable now, confirmed payment, payout estimate and refund; never show a generic success banner for all of them.

## Ordered implementation slices

| Order | Cohesive delivery | Acceptance gate |
| --- | --- | --- |
| 1 | Processor and real-data hosting qualification design | Identify one processor and authentication/email services; evidence for recipient onboarding, direct settlement, all fees, notices, capped autopay, cancellation, event history and restore. Document exact API/event mapping and limits. Unsupported cap/safety behavior blocks dependent build, not silently weakened scope. |
| 2 | Hosted tenant identity, entitlement and free limits | Separate actor/grants/routes, managed enrollment/recovery, private dated premium assignment, capacity/usage UI, free operator continuity. Prove cross-workspace/role denial. |
| 3 | Lease payment setup and publication | Recipient setup, opening balance review, participant invitations, partial policy, activation/correction UI and tenant Rent read model with safe shared history. |
| 4 | One-time hosted payment | Preview, authorization, reservation/outbox, original-attempt recovery and mobile checkout/status/history; sandbox only until accounting gate. |
| 5 | Financial outcomes and exception workflow | Provider inbox/polling, source-owned receipt/fee/return/refund mapping, unapplied-funds exception, operator queues, tenant receipts, gross/net/payout displays and reporting consistency. |
| 6 | Help and transactional delivery | Scoped cases/replies, operator triage, sender ownership, notification outbox/delivery failures and tenant help/history. |
| 7 | Autopay | Qualified capped occurrence scheduling, consent, manual overlap, notices, cancel/pause and lease/recipient changes. One-time payments do not alone complete PAY-001. |
| 8 | Lifecycle, backup and recovery acceptance | Premium end, access removal/security suspension, lease end, outage/restart, restore/old-runtime fences and persistent cancellation failures. |
| 9 | Hosted live pilot and release | Explicit approval for live funds; small bounded set of leases, real enrollment/collection/payout/return-support evidence, observed fees/latency, operator runbook and support ownership. Full usable tenant/operator workflows are completion criteria. |

Each slice includes its required backend, UI and focused tests. No separate UI backlog postpones the usable workflow. Do not enable real collection at Slice 4; financial and lifecycle acceptance are launch gates.

## Validation matrix

| Area | Required evidence |
| --- | --- |
| Happy paths | Owner/operator recipient; one-time full/partial; issued future rent; two roommates; fixed capped autopay; skipped zero; fee/net/payout and receipt drill-down. |
| Invalid combinations | Local/free/expired premium initiation; unverified recipient; unpublished rent; deposits/cards; disallowed partial; invalid dates/amounts; guarantor access; changed recipient/preview. |
| Isolation/privacy | Cross-workspace/lease/payment/operation-ID requests denied; tenant operator endpoints forbidden; shared balance excludes private method/payer/failure data; archived/former/new tenant boundaries; email reassignment. |
| Idempotency/concurrency | Double click/device; manual receipt vs autopay; two tenants; duplicate/changed/out-of-order events; timeout after provider acceptance; same key changed payload; duplicate occurrence; webhook/poll race. |
| Rollback | Crash before/after intent commit, provider call and event application; no orphan reservation, duplicate debit, receipt without mapping or fee double count. |
| Accounting | Fees distinct from income; payout batches; owner claim adoption; partial/full returns/refunds; excess funds; allocation correction; exact conservation and audit lineage across reports. |
| Persistence | Current-schema checks, unique source identities, consent/recipient snapshots, operation replay, retained exception history, terminal-state evidence and invalid JSON rejection. |
| Backup/restore | Restored outbox cannot resubmit; canceled mandates stay canceled; old runtime fenced; reauth/reconciliation required; missing provider history blocks reopening. |
| Lifecycle | Subscription expiry during processing; cancellation failure; lease end/renewal; recipient change; session/access revocation; read-only history/cancel/help after premium ends. |
| Notifications/help | Duplicate delivery prevention, provider/EPM sender overlap, email failures, private vs shared visibility, help reopen and support handoff. |
| Performance | Bounded 50-row cursor lists; set-based lease/balance/payment reads; compare query counts for 1 vs 50 rows to prove no per-row queries; short writer locks, no provider network call under transaction; responsive loading during worker backlog. |
| Browser/accessibility | Phone/desktop, keyboard/zoom/theme, refresh/back/multiple tabs, expired session and hosted redirects, unknown payment status, slow/offline reads without false zero/success. |
| Operational pilot | Sandbox/live separation, quotas/headroom, webhook validation, monitored reconciliation lag, recovery drill, documented support ownership and approved real-data/funds admission. |

## Remaining qualification gates, not assumed decisions

The accepted product scope is settled. Before implementation beyond the relevant gates, record provider-specific facts: merchant/recipient eligibility and fund-flow responsibilities; availability of balance-capped scheduling; mandate notices and date/cancellation cutoffs; actual fees, return/dispute handling and payout estimates; authoritative confirmation events; historical reconciliation reach; authentication/email provider selection; hosting capacity and operational support. Review applicable processor terms and payment obligations with qualified advice where needed. No speed or fee claim becomes a product promise before qualification.

Final premium prices/capacity and automated subscription billing remain outside this pilot design. Free hosted availability still needs cost/capacity monitoring; the five-space allowance is a product limit, not a claim that the current VM can host unlimited free workspaces.
