# FIN-001 — Rent Expectations and Recorded Receipts

## Purpose

`FIN-001` gives the local operator a truthful rent-collection record: what rent was expected for an executed lease, what was actually received, and which expected period each recorded receipt settles. It makes full, partial, late, and missed rent visible without initiating payments, attempting accounting reconciliation, or deciding legal delinquency consequences.

The slice deliberately separates contractual terms from financial facts. `LEASE-001` remains the source of lease lifecycle, effective-dated rent terms, and any agreed termination responsibility date. FIN-001 snapshots those terms into immutable expected-rent records and records operator-entered receipts against them.

## Scope

FIN-001 provides:

- Idempotent generation of recurring rent expectations from executed lease terms.
- Explicit operator confirmation of the recurrence anchor for one selected rent-term schedule.
- Immutable expected-rent snapshots with period, due date, amount, currency, and source lease-term ID.
- Recorded receipt and allocation workflows supporting one payment applied across one or more expectations of the same lease.
- Derived balances and clearly defined full, partial, late, and missed states.
- Receipt void-and-replace correction rather than destructive edits or deletes.
- Typed API contracts, atomic audit history, current-schema validation, and encrypted backup/export/restore coverage.

FIN-001 does not provide:

- Payment initiation, bank feeds, processor integrations, reconciliation, autopay, payment-method storage, check deposit workflows, or bank credentials. `FIN-006` and `FIN-007` own payment-method and prepaid-check workflows.
- Fees, concessions, credits, discretionary adjustments, write-offs, refunds, security-deposit receipt/settlement, owner-report intake/evidence/verification, expense tracking, owner balances, tax/accounting, or owner disbursements. Those belong to later FIN and OWNER items. FIN-001 may record an existing party as the confirmed recipient of rent, but `OWNER-003` later owns the report that an owner received it and must link that verified report to the FIN-001 receipt instead of creating duplicate income. FIN-001 performs only the deterministic first/final schedule-edge proration defined below; it does not accept an operator-entered prorated amount.
- A legal determination of delinquency, grace periods, notice requirements, eviction eligibility, collection activity, or tenant communication.
- File attachments or receipt-image capture. FILE-001 remains available to future owning workflows, but FIN-001’s durable fact is the recorded receipt and allocation, not an uploaded document.
- A React finance screen. This slice creates backend/API behavior and a typed contract; `UI-001` later delivers the FIN-001 operator workflow before `DASH-001`.

## Core decisions

### Lease terms are read through a port; Finance owns financial records

Finance depends on a transaction-aware lease read port supplied at composition. It reads the lease, the explicitly selected term version, space/property identity, the property's IANA time zone, actual move-out, and accepted termination responsibility boundary, but does not import lease or Portfolio SQLAlchemy models or alter their rows. Participants are not part of this projection because FIN-001 does not expose tenant identity. A separate transaction-aware party lookup validates an optional receipt recipient.

Conversely, LEASE-001 does not import Finance or create financial rows while executing, ending, or terminating a lease. The operator explicitly synchronizes expectations through FIN-001. This preserves the dependency direction and prevents a lease workflow from silently creating a financial obligation without review.

### Expectations are immutable snapshots, not live calculations

Every `rent_expectation` stores the precise lease-term ID, expected amount, currency, frequency, covered period, and due date used when it was generated. Later lease amendments or future rent-adjustment workflows never rewrite a previously generated record. They generate future expectations from their own effective term instead.

FIN-001 assumes that `base_rent_minor` is the complete amount due for each full recurring interval. It deterministically prorates only a first stub or final shortened period created by a term or responsibility boundary. It does not calculate concessions, fees, credits, or any discretionary adjustment. If the contractual amount cannot be represented by the deterministic rule, FIN-001 must not invent an amount; the operator leaves that period unsynchronized until a dedicated receivable-adjustment workflow exists.

### Schedule anchors, inclusive periods, and proration are explicit

Synchronization targets one explicit `leaseTermId`. Before FIN-001 generates that term's schedule, the operator confirms `scheduleAnchorOn`. For a monthly term, the UI initially suggests the first day of the calendar month following the term effective date for the normal day-1 schedule. If the term's configured `payment_due_day` differs, it suggests that configured day in the following month, clamped to that month's last calendar day. The API does not silently accept the suggestion: the confirmed monthly anchor must match the selected term's configured due day. The service derives the same configured due-day cadence backward and forward and uses the earliest occurrence on or after the effective date as the first regular due date. For a weekly term, the operator may intentionally choose any anchor on or after the term effective date; the service likewise extends that seven-day cadence backward and forward. Thus a later anchor chooses the cadence without leaving an unexplained coverage gap.

If a term starts before its first regular occurrence, FIN-001 creates a prorated first stub beginning on the term's effective date and ending the day before that occurrence; that stub is due on the term's effective date. Regular monthly occurrences are generated independently from `payment_due_day` in each calendar month, so a February clamp never shifts March away from its configured day. Weekly occurrences stay on the seven-day cadence established by the operator-confirmed anchor.

Stored periods are inclusive. A regular period begins on its due date and ends the day before the next regular due date or on the final responsibility day, whichever comes first. `due_on` must be inside the stored period. A first or final shortened period is prorated by actual calendar days: `base_rent_minor * covered_days / days_in_the_complete_notional_recurring_period`. The result is rounded to the nearest minor unit using decimal half-up rounding. When two adjacent prorated pieces from the same source term divide one notional interval, the final chronological piece receives any one-minor-unit rounding remainder so the pieces reconcile to the full recurring amount.

LEASE-001 term `ends_on` and `actual_move_out_on` are exclusive boundaries: the corresponding last covered finance date is the preceding calendar date. An accepted `rent_responsibility_ends_on` and an operator `responsibilityEndsOnOverride` are inclusive last-responsibility dates. These conversions occur in the property's local time zone before schedule generation.

A stored period must contain at least two calendar dates; a one-day stub or final period is not valid and synchronization returns a controlled validation error instead of creating it. No period may cross a term or effective responsibility boundary. `throughOn` bounds the complete covered period: an occurrence is created only when its inclusive `period_ends_on` is on or before `throughOn`. The service also caps one synchronization request at 240 newly generated expectations. Generation is idempotent through a unique source-term/due-date key.

### Receipts and allocations represent received money exactly once

A `rent_receipt` records money the operator confirms was received. It has one lease, one received-on date, a positive currency amount, an optional `received_by_party_id`, optional bounded internal notes, one client-generated UUID idempotency key, and one or more allocations. A null `received_by_party_id` means the local operator received the money; a non-null value identifies an existing shared party that received it. `rent_receipt_allocations` distribute that receipt among open expectations of the same lease and currency.

The allocation total must equal the receipt amount exactly. An expectation cannot be allocated above its expected amount, and a receipt cannot span leases or currencies. Prepayment allocation to a future active expectation is allowed. This prevents ambiguous unapplied balances and double-counting. A correction voids the whole receipt—with a required reason—and then records a replacement receipt/allocation set whose `replaces_receipt_id` preserves explicit lineage. Receipts and allocations are never edited or deleted after recording.

The idempotency key is an opaque client-generated UUID, not a fingerprint derived from date, party, space, or amount because two legitimate receipts may share those values. Repeating a request with the same key and semantically identical payload returns the original receipt without new rows or audit events. Reusing the key with a different payload returns `409`.

### Payment status is derived, not manually claimed

Views expose both settlement and timeliness rather than collapsing unrelated facts into one mutable status:

| Field | Values and rule |
| --- | --- |
| `settlementStatus` | `unpaid`, `partial`, or `paid`, calculated from non-voided receipt allocations. |
| `timelinessStatus` | `upcoming` before `dueOn`; `due` on `dueOn`; `late` after `dueOn` while a balance remains; operator-reviewed `missed` after the covered period ends with no amount received; `paid_on_time` or `paid_late` once fully settled. |
| `receivedAmountMinor`, `outstandingAmountMinor` | Calculated from non-voided allocations. |

A partial expectation after its due date is `partial` and `late`; it is not relabeled missed. An unpaid expectation remains `late` after its period ends by default, which is the least restrictive automatic classification. Only the operator may mark it `missed`, after explicit confirmation and with a reason; the operator may later clear that review with another reason. Reviews are append-only. A missed review is effective only while the expectation remains active and has received no money; any receipt makes the historical review inactive, and a later receipt void does not reactivate it without a new review. A fully settled expectation is `paid_late` when its final required receipt was received after the due date. A voided expectation has lifecycle status `voided` and no settlement or timeliness status.

All date-relative states use the current date in the property's stored IANA time zone. The application injects the clock/time-zone boundary so tests and future runtime environments do not depend on the server process's ambient time zone. FIN-001 uses no grace period and makes no legal assertion from these labels.

### Termination responsibilities are bounded

For an executed lease, expectations may be generated only through the effective term boundary, requested horizon, and any already accepted termination responsibility boundary. Acceptance applies immediately even though LEASE-001 keeps the lease `executed` until actual move-out. For an ended or terminated lease, the default responsibility boundary is the accepted proposal's `rent_responsibility_ends_on` when present; otherwise it is actual move-out. This permits an accepted responsibility date to end before or continue after physical move-out without deriving an obligation from prose.

The operator may supply `responsibilityEndsOnOverride` only with explicit confirmation and a required 1–1,000 character reason. The selected boundary and override reason are snapshotted on each newly generated expectation and audited. An override never rewrites existing expectations: shortening a boundary requires the operator to void affected unallocated expectations, while extending it may generate additional eligible periods. FIN-001 does not derive fees or continuing-rent obligations from notices or contract clauses.

## Data model

All IDs are UUIDs. Monetary values are integer minor units and are never floating point. Dates are ISO local dates. Timestamps are timezone-aware UTC text. Records remain in the current greenfield Alembic baseline and participate in exact schema validation, backup, export, and restore.

### `rent_expectations`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `lease_id` | Required foreign key to an executed, ended, or terminated `leases.id`. |
| `lease_term_id` | Required foreign key to `lease_term_versions.id`; immutable source snapshot. |
| `period_starts_on`, `period_ends_on` | Required covered local-date range; end is after start. |
| `due_on` | Required local due date within the covered period. |
| `expected_amount_minor` | Required positive integer snapshot of base rent. |
| `currency_code` | Required snapshot using exactly three ASCII uppercase letters. |
| `payment_frequency` | Required `monthly` or `weekly` snapshot. |
| `schedule_anchor_on` | Required operator-confirmed monthly or weekly recurrence anchor used to derive the source schedule. Every expectation for one term carries the same value. |
| `is_prorated`, `proration_numerator_days`, `proration_denominator_days` | Explain deterministic first/final proration. `is_prorated = false` requires both day counts null; a prorated row requires positive counts with numerator less than denominator. |
| `responsibility_boundary_on`, `responsibility_override_reason` | Optional effective responsibility boundary snapshot and optional operator-override reason used during generation. An open executed lease may have no finite responsibility boundary beyond its selected term and requested horizon. |
| `voided_at`, `void_reason` | Both null for active rows; both required for a voided expectation. Void requires an operator reason and is never a deletion. |
| `created_at` | Required UTC creation timestamp. |

The database enforces positive amounts, `period_ends_on > period_starts_on`, inclusive `due_on` containment, a unique `(lease_term_id, due_on)` source schedule, and indexes lease/date/status reads. It also requires valid currency/frequency, consistent proration metadata, and a consistent void pair. A voided expectation remains in history, reserves its source schedule key, and cannot receive new allocations. Expectation source and schedule fields are immutable; void metadata is the only mutable lifecycle state.

### `rent_expectation_timeliness_reviews`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `expectation_id` | Required foreign key to `rent_expectations.id`. |
| `decision` | Required `mark_missed` or `clear_missed`. |
| `reason` | Required trimmed operator reason, 1–1,000 characters. |
| `created_at` | Required UTC timestamp. |

Reviews are append-only and ordered by creation timestamp and ID. A `mark_missed` decision is allowed only after the inclusive period end while the active expectation has received nothing. `clear_missed` requires an effective missed decision. The latest applicable decision determines whether `timelinessStatus` is `missed`; receipt activity never deletes review history.

### `rent_receipts`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `lease_id` | Required foreign key to `leases.id`. |
| `idempotency_key` | Required client-generated UUID with a workspace-wide unique constraint. |
| `received_on` | Required local date, not later than the operator’s current local date. |
| `amount_minor` | Required positive integer. |
| `currency_code` | Required code using exactly three ASCII uppercase letters. |
| `received_by_party_id` | Optional foreign key to an existing shared party; null means the local operator. |
| `replaces_receipt_id` | Optional unique self-reference to the voided receipt this receipt replaces. |
| `notes` | Optional trimmed internal receipt context, maximum 4,000 characters. |
| `voided_at`, `void_reason` | Both null for an active receipt; both required after a confirmed void. |
| `created_at` | Required UTC creation timestamp. |

`void_reason` is trimmed and limited to 1–1,000 characters. A replacement must reference a voided receipt from the same lease and currency, and one receipt may have at most one direct replacement. A replacement may use a corrected date, amount, recipient, notes, and allocation set. If that replacement is later voided, another receipt may replace it, forming an explicit forward correction chain without editing history.

The database enforces `amount_minor > 0`, exactly three ASCII uppercase currency letters, workspace-wide idempotency-key uniqueness, replacement-reference uniqueness, and the null/non-null pairing of `voided_at` and `void_reason`. Application validation additionally enforces UUID syntax, receipt dates, recipient existence, replacement lifecycle/lease/currency compatibility, bounded text, and idempotent payload equivalence.

### `rent_receipt_allocations`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `receipt_id` | Required foreign key to `rent_receipts.id`. |
| `expectation_id` | Required foreign key to `rent_expectations.id`. |
| `amount_minor` | Required positive integer amount allocated to that expectation. |
| `created_at` | Required UTC creation timestamp. |

The database enforces positive allocation amounts and one allocation per receipt/expectation pair. The application transaction enforces receipt/expectation lease and currency equality, active lifecycle, exact total allocation, no more than 100 allocations in one receipt, and no over-allocation across concurrently recorded receipts. “Non-voided allocations” means allocations whose parent receipt is not voided. Allocations under a voided receipt remain historical, contribute nothing to balances, and do not block expectation voiding.

## Workflows and invariants

### Synchronize recurring expectations

`POST /api/leases/{leaseId}/rent-expectations/synchronize` takes an explicit `leaseTermId`, typed `throughOn`, and—where that source term has no prior expectation—an operator-confirmed `scheduleAnchorOn`. It may also take a confirmed responsibility-boundary override and reason. It reads the lease and selected term in the transaction, verifies their relationship and eligible lifecycle, applies the term/responsibility boundaries, and creates only missing occurrences whose complete covered period ends by the requested date.

Repeated requests with the same inputs create no duplicate rows or no-op audit events. A term with an amount/frequency that cannot be faithfully scheduled under these rules returns a controlled validation error rather than guessing a proration or obligation.

### Record or void a receipt

`POST /api/rent-receipts` records a new receipt plus all of its allocations in one immediate transaction and one correlation ID. SQLite's `BEGIN IMMEDIATE` transaction is the concurrency boundary; the service reloads every expectation and current non-voided allocation total after acquiring it before calculating balances. If any allocation is invalid, no receipt, allocation, or audit event persists.

`POST /api/rent-receipts/{receiptId}/void` requires `confirmed: true` and a bounded nonblank `voidReason`. It retains the receipt and allocations, marks the receipt voided, recalculates all affected views, and appends a before/after audit event. The operator records a replacement separately with `replacesReceiptId`; FIN-001 never silently changes a historical amount.

### Void an erroneous expectation

An expectation may be voided only while it has no non-voided allocations. This requires explicit confirmation and a trimmed 1–1,000 character reason. Its source schedule key remains reserved, and FIN-001 supports no expectation replacement workflow. A generated expectation cannot be edited or regenerated in place; a future adjustment workflow owns any replacement receivable.

### Review a missed expectation

`POST /api/rent-expectations/{expectationId}/timeliness-reviews` appends a confirmed `mark_missed` or `clear_missed` decision and required reason. This is an operator-reviewed operational label, not a legal delinquency conclusion. It never changes the expected amount, allocations, or lease.

### Query behavior

Expectation list and detail queries support typed filters: lease ID, property ID via the lease/space projection, `dueOn` range, settlement status, timeliness status, and `includeVoided`. Results are ordered by `dueOn`, then expectation ID and use cursor pagination with a default page size of 100 and maximum of 500. They include the expectation fields, lifecycle status, lease/property/space IDs, aggregate received/outstanding values, effective missed-review summary, and allocation summaries containing allocation ID, receipt ID, received date, allocated amount, and receipt lifecycle state.

Receipt list and detail queries support lease ID, received-on range, received-by party ID, replacement-chain ID, and `includeVoided`. Results are ordered by `receivedOn`, then receipt ID and use the same 100/500 cursor limits. They include the receipt fields and allocations with expectation ID, due date, covered period, and allocated amount. No endpoint returns a portfolio money total; `FIN-003` owns income/expense aggregation.

## Operator workflow delivered by UI-001

UI-001 adds a **Money** workflow with **Rent expectations** and **Recorded receipts** views. The expectation list uses the plain-language columns Expected, Money received, Still due, Due date, Covered period, and Needs attention while retaining the precise settlement/timeliness labels in detail and accessible help text. Filters mirror the API, and every amount drills into its receipt allocations rather than presenting an unexplained total.

From an executed lease, **Synchronize rent expectations** requires the operator to select one term. It displays the property time zone, term amount/frequency, suggested recurrence anchor, effective term/responsibility boundary, and a complete preview of every full or prorated period before confirmation. Prorated rows show their covered-day fraction and rounded amount. A responsibility override is visually exceptional and requires its own confirmation and reason.

**Record receipt** generates the UUID idempotency key in the client, defaults `receivedByPartyId` to null (local operator), permits selection of an existing shared party, and allocates 1–100 amounts against still-open expectations from one lease/currency. The screen continuously shows receipt total, allocated total, and remaining balance and cannot submit until they are equal. **Void and replace** first confirms the void reason and then opens a prefilled new receipt with explicit replacement lineage and a new idempotency key; it never edits the old record.

An unpaid ended period remains **Late** unless the operator chooses **Mark missed**, confirms, and records a reason. Detail shows the review history and provides **Clear missed classification** with a new reason. The UI never describes these operational labels as a legal conclusion, never initiates collection, and does not expose a portfolio money aggregate before FIN-003.

## API contract

All routes require a ready workspace. Mutations require the writer lock. Request models use `extra="forbid"`, `StrictBool` confirmations, integer minor-unit amounts, and typed ISO dates. Application commands repeat validation for direct callers. All responses use explicit Pydantic models.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/leases/{leaseId}/rent-expectations/synchronize` | Generate missing recurring expectation snapshots for one explicit term through a requested horizon. |
| `GET` | `/api/rent-expectations` | List expectation views with financial and lifecycle filters. |
| `GET` | `/api/rent-expectations/{expectationId}` | Return one expectation, its balances, and receipt allocations. |
| `POST` | `/api/rent-expectations/{expectationId}/void` | Void an unallocated erroneous expectation after explicit confirmation. |
| `POST` | `/api/rent-expectations/{expectationId}/timeliness-reviews` | Mark an unpaid ended period missed, or clear that review, after confirmation and a reason. |
| `POST` | `/api/rent-receipts` | Record one receipt and its complete allocation set atomically. |
| `GET` | `/api/rent-receipts` | List receipts with typed filters. |
| `GET` | `/api/rent-receipts/{receiptId}` | Return one receipt and its allocations. |
| `POST` | `/api/rent-receipts/{receiptId}/void` | Void a recorded receipt after explicit confirmation and reason. |

Synchronization requests contain `leaseTermId`, `throughOn`, optional `scheduleAnchorOn`, and an optional confirmed responsibility override/date/reason tuple. Receipt requests contain `idempotencyKey`, `leaseId`, `receivedOn`, `amountMinor`, `currencyCode`, optional `receivedByPartyId`, optional `replacesReceiptId`, optional `notes`, and 1–100 `{expectationId, amountMinor}` allocations. Void and timeliness-review requests use `StrictBool` confirmation and bounded reasons. Monetary request fields use strict integers so booleans, floats, numeric strings, zero, and negative values are rejected.

Expectation responses expose IDs, schedule dates, expected/received/outstanding minor units, currency, frequency, proration evidence, responsibility-boundary evidence, lifecycle timestamps, settlement/timeliness status, effective missed review, and the bounded allocation summary defined above. Receipt responses expose receipt, recipient, idempotency, correction-lineage, lifecycle, and allocation fields. The API returns canonical UUID and ISO-date strings and never substitutes display labels for stable references.

Malformed request data returns `422`; missing leases, terms, parties, expectations, or receipts return `404`; invalid business data returns `400`; stale state, mismatched idempotency payloads, duplicate scheduling, over-allocation, lifecycle, and concurrent-write conflicts return `409`.

## Audit, privacy, and portability

Each write persists its rows and `AUDIT-001` changes in one immediate transaction and one correlation ID. Entity types are `rent_expectation`, `rent_expectation_timeliness_review`, `rent_receipt`, and `rent_receipt_allocation`. Synchronization records only newly created expectations; receipt creation records the receipt and every allocation; void workflows record the complete prior/current state; each missed/clear decision records its appended review.

General activity presentation exposes concise lifecycle and due/received dates. Expectation activity redacts expected amounts and responsibility override reasons. Receipt activity redacts amount, notes, idempotency key, `receivedByPartyId`, and correction references. Allocation activity replaces the entire before/after snapshot with a redacted marker because its identifiers and amount together disclose sensitive payment application. Timeliness-review activity exposes the decision and date but redacts its reason. Contextual finance history can reveal the complete local records to the operator. Policies must be registered before the service can write events, preserving fail-closed audit behavior.

FIN-001 data and audit history are retained in the encrypted workspace backup/export/restore package. It stores no payment credentials, account numbers, processor tokens, checks, or attachment contents, so no secret-store or remote-content adapter is introduced.

## Implementation outline

1. Add FIN-001 SQLAlchemy models, constraints, indexes, module-owned exact schema validation, and baseline/product/archive validation updates for the greenfield current schema.
2. Define immutable domain values and validated commands for schedule synchronization, proration, expectations, receipts, allocations, missed reviews, and void operations; reject floats, non-positive amounts, non-ASCII currency syntax, future receipt dates, and unchecked direct construction.
3. Define finance unit-of-work and transaction protocols plus transaction-aware lease, property-time-zone, and party read operations. Compose concrete adapters in bootstrap; keep finance application code independent of lease, Portfolio, Parties, and SQLAlchemy infrastructure.
4. Implement balance/status projections using bounded queries and transaction-time allocation rechecks, then expose typed FastAPI routes and ready/writer-lock/error handling.
5. Register finance audit policies and add regression coverage for recurring date generation, inclusive ranges, stub/final proration and half-up rounding, leap/month-end behavior, idempotence, property-local dates, partial/full/late/operator-reviewed-missed views, allocations, void/replacement lineage, responsibility overrides, concurrency, schema rejection, and encrypted backup/export/restore.

## Acceptance criteria

FIN-001 is complete when:

1. An operator can synchronize accurate, nonduplicated recurring expectation snapshots for one selected term of an eligible executed lease using a confirmed recurrence anchor, deterministic edge proration, responsibility boundary, and bounded horizon.
2. Each expectation clearly shows expected, received, outstanding, settlement, and timeliness state without asserting legal delinquency or applying a hidden grace period.
3. A receipt can be allocated across one lease’s eligible expectations atomically; totals, currency, lifecycle, and over-allocation rules are enforced under concurrency.
4. Receipt corrections are explicit void-and-replace chains; expectation corrections are void-only until a future adjustment workflow. Both retain correlated audit history and use no physical deletion.
5. Payment methods, check/deposit status, fees, discretionary/operator-entered prorations, deposits, expense accounting, bank integration, and automatic collection remain absent from this slice.
6. Typed HTTP and application contracts provide controlled `400`, `404`, `409`, and `422` outcomes.
7. Exact schema validation and encrypted backup/export/restore preserve all FIN-001 data and audit history.

## Dependencies and follow-on work

FIN-001 requires completed `AUDIT-001`, `LEASE-001`, `LOCAL-001`, and `LOCAL-002`. It reads PORT-002 space/property context through LEASE-001’s existing relationship, so it does not add a direct Portfolio persistence dependency.

`UI-001` delivers the expectation synchronization/review, receipt allocation, void/replacement, filters, and source-record drill-down workflows. `FIN-006` adds expected and actual payment methods; `FIN-007` adds prepaid checks and deposit reminders; `FIN-008` owns deposits and settlement; `FIN-002` owns expenses; `FIN-003` aggregates financial records; `ADJ-001` proposes adjustments and `ADJ-002` owns the resulting effective-dated rent amendment; `COM-001` owns payment follow-up communication; and `DASH-001` surfaces overdue-rent action cards. None may reinterpret FIN-001 status labels as legal conclusions or initiate collection automatically.
