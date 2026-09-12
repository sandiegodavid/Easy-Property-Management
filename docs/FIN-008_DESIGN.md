# FIN-008 — Security-Deposit Receipt and Settlement

## Purpose

`FIN-008` gives the local operator a truthful, reviewable record of security-deposit funds received for one lease, the evidence-backed deductions and credits used in settlement, the amount due back, and the refunds actually completed. It records the operator's decision; it does not make legal determinations or move money.

The slice keeps deposit liabilities separate from rent income and property expenses. A FIN-008 deposit receipt is never a FIN-001 rent receipt. A FIN-008 deduction is never a FIN-002 expense, even when it cites the same invoice or receipt. Inspection classifications remain evidence for human review and never create deductions automatically.

## Scope

FIN-008 provides:

- One security-deposit account per lease, with multiple immutable receipt records.
- An immutable snapshot of the selected lease term, agreed deposit amount, and currency when the account is established.
- Operator-reviewed draft, approved, completed, and voided settlement lifecycles.
- Positive deductions, positive credits, an exact refund-due calculation, and multiple partial refund records.
- Explicit references to rent expectations, expenses, inspection comparisons or observations, and FILE-001 evidence.
- An operator-recorded settlement deadline, legal or rule reference, and review notes.
- UUID idempotency, duplicate warnings, explicit historical-source confirmation, void-and-replace corrections, atomic audit history, and portable backup coverage.
- Typed list, detail, creation, approval, completion, and correction APIs.

FIN-008 does not calculate statutory deadlines, determine whether a deduction is legally permitted, initiate refunds, store payment methods, create tasks, recognize deposits as income, create expenses or receivables, or change leases and inspections. `JUR-001` may later provide sourced rule suggestions. `TASK-001` remains independent unless a later backlog item deliberately connects deposit deadlines to reminders. Payment execution belongs to later payment integrations, and portfolio aggregation belongs to `FIN-003`.

The MVP is US-only. Currency is exactly `USD`; dates and overdue state use the property's stored US IANA time zone. The React operator workflow and its simple interest calculator are deferred to `UI-001`.

## Core decisions

### A lease has one deposit account and many financial facts

Each lease has at most one security-deposit account. The account is created explicitly before the first receipt or settlement. Creation targets one explicit `leaseTermId` belonging to the lease and snapshots that term's agreed deposit amount and currency. Later lease amendments do not rewrite the account or its historical receipts and settlements; the UI shows any difference from the current lease term for operator review.

The account may contain multiple receipts and multiple refund payments. Individual receipt, refund, deduction, and credit amounts are positive. An account with no received funds does not require a settlement, but the operator may create and complete an explicitly confirmed zero-dollar closure to document that no funds were held or returned.

### Deposit money is not rent income

A security-deposit receipt represents funds held for a lease. It is a liability-side operational fact and never creates a FIN-001 receipt, allocation, expectation payment, or income entry. Likewise, a refund reduces held deposit funds and is not a FIN-002 expense refund.

`FIN-003` must consume FIN-008 through its own read port and present deposit liabilities, deductions, and refunds separately from rent income and operating expenses. It must not include a deposit receipt in income or a refund in property expense totals.

### Receipts preserve who paid and who received the funds

Each receipt records a property-local received date, amount, optional payer, and who received the funds. `receivedFromPartyId`, when present, may reference any saved shared party, including a parent paying for a student tenant; no tenant role is required. The payer's display name is snapshotted so history remains understandable after a rename or archival.

`receivedByKind` is `local_operator` or `party`. `local_operator` requires a null `receivedByPartyId`; `party` requires an existing shared party and snapshots its display name. FIN-008 records this history without assigning a lease role or ownership interest.

Normal party search excludes archived parties. An archived party may be selected for a historical entry only after explicit confirmation and a 1–1,000 character reason. Existing references never block party archival.

Receipts may be recorded while a lease is `draft`, `executed`, `ended`, `terminated`, or `void`. A receipt against an ended, terminated, or void lease requires explicit historical-entry confirmation and a reason. `receivedOn` may be any date from 1900-01-01 through the current property-local date; it is not constrained to occupancy dates because deposits may be received during signing or after a correction.

### Receipt retries are idempotent and likely duplicates are reviewed

Every receipt create request carries a client-generated UUID idempotency key. Repeating the same key with the same canonical payload returns the original record without another row or audit event. Reusing the key with different content returns `409`.

A new receipt is a likely duplicate when an active receipt for the same account has the same received date, amount, currency, and normalized payer identity. The API returns `409 possible_duplicate_deposit_receipt` with bounded candidate summaries unless `duplicateConfirmed` is true. The operator may cancel, open the existing receipt, or deliberately continue; the application never merges records automatically.

Receipts are immutable. Corrections use a confirmed void with a reason followed, when needed, by a new receipt whose unique `replacesReceiptId` points to the voided record. A receipt already captured by an approved or completed settlement cannot be voided until that settlement is voided. A later receipt may still be recorded because truthful cash history must not be suppressed; it appears as unsettled funds and requires a replacement settlement before those funds can be refunded.

### Settlement is an operator-approved snapshot

A settlement belongs to one account and moves through `draft`, `approved`, `completed`, or `voided`. At most one non-voided settlement may exist for an account. Draft deductions, credits, sources, notes, and deadline details are editable and auditable. Approval freezes the settlement and snapshots the exact active receipt IDs and total included in its calculation. Source records changing later never rewrite the approved settlement.

Settlement is normally available after an ended or terminated lease with an actual move-out date. A void lease with received deposit funds may also be settled. Creating a settlement earlier, or without an actual move-out where one is normally expected, requires explicit confirmation and a 1–1,000 character reason. These controls prompt review; they do not claim legal compliance.

Missing move-in or move-out inspection evidence produces a prominent warning but does not block settlement. The operator may settle from other retained evidence and remains responsible for the decision.

An approved settlement may be completed when its refund due is zero or when active refund payments equal the approved refund due exactly. If the refund due is zero, completion requires explicit confirmation. If receipts are added after approval, the detail response reports the unsettled difference and completion is blocked until the operator voids and replaces the settlement. A completed settlement with later receipts remains historical but leaves the account visibly unsettled until corrected.

Corrections after approval or completion always void the settlement with confirmation and a reason, then create a replacement draft with a unique `replacesSettlementId`. Nothing silently reopens or mutates an approved financial decision.

### Deadlines are recorded, not legally inferred

Every settlement records `settlementDueOn` as a property-local date. It is normally on or after actual move-out; an earlier date requires explicit confirmation and a reason. The operator may record a 1–500 character legal or rule reference and up to 4,000 characters of review notes.

The service derives `due`, `due_today`, or `overdue` from `settlementDueOn`, completion state, and the current property-local date. It does not infer a deadline from an address, calculate a statute, create a reminder, or present the recorded date as legal advice. A later jurisdiction module may suggest sourced rules, but the operator must still review and confirm the stored deadline.

### Deductions are independently entered and evidence-backed

Each deduction has a positive applied amount, category, concise description, and rationale. Categories are `unpaid_rent`, `damage`, `cleaning`, `missing_property`, `contractual_fee`, and `other`. These are factual organization labels, not findings that a deduction is lawful.

Draft deductions may exist without evidence. Approval requires every deduction to have at least one active source: a FILE-001 link, an exact finalized inspection comparison or observation, a FIN-001 rent expectation, or a FIN-002 expense. The operator selects every source explicitly. FIN-008 never turns an inspection classification into a deduction, and a superseded inspection does not rewrite a settlement.

Normal source selectors exclude archived, voided, or superseded values. A retained historical source may be selected only with explicit confirmation and a 1–1,000 character reason. Its current lifecycle is snapshotted and shown as a warning; the source remains stable evidence rather than being reactivated or copied.

For an unpaid-rent deduction, the operator enters the applied amount and may link one or more explicit FIN-001 expectations. Approval snapshots each expectation's then-current outstanding amount for context. The deduction amount is not inferred from that balance, and later allocations or corrections do not change it.

For damage, cleaning, or another cost, the operator may link zero or more FIN-002 expenses. The deduction amount remains independently entered. One expense may be cited by multiple settlements only after a duplicate-use warning and explicit confirmation; the application does not copy the expense, presume tenant responsibility, or alter expense totals.

Approved deductions may not exceed the approved receipt total plus approved credits. Only the amount applied from held funds belongs in FIN-008. Any excess claim or receivable is outside this slice.

### Credits include explicitly reviewed simple interest

Credits are positive settlement additions with kind `interest` or `other`, a description, and an operator-entered applied amount. An interest credit may store calculator inputs: principal, annual rate in integer basis points, inclusive start and exclusive end dates, day count, and calculated result.

The UI-001 calculator uses simple interest:

`principal × annual rate × days ÷ 365`

The service calculates with exact decimal arithmetic and rounds once to cents using half-up rounding. The stored day count must equal `endsOn - startsOn`; start must precede end; principal and annual rate must be positive and within the monetary and rate limits. If the applied credit differs from the calculated result, a 1–1,000 character override reason is required. The calculator is a convenience, not a statutory interest determination.

### Refunds record completed transfers without initiating them

A refund records one actual payment against an approved settlement: recipient party, durable recipient-name snapshot, paid date, positive amount, optional external reference, notes, and UUID idempotency key. FIN-008 is method-neutral and does not store bank details or initiate payment.

The normal recipient must be a lease participant or a party recorded as a deposit payer for the account. Any other saved party requires explicit override confirmation and a 1–1,000 character reason. Normal search excludes archived parties; historical selection of an archived recipient also requires confirmation and a reason.

Multiple partial refunds and multiple recipients are allowed. At creation time, active account refunds may never exceed the current approved refund due. Refunds are immutable and use confirmed void-and-replace correction chains.

Refund idempotency has the same semantics as receipt idempotency. A likely duplicate has the same account, paid date, amount, currency, and recipient; the API returns `409 possible_duplicate_deposit_refund` with bounded candidates unless the operator explicitly confirms an independent payment. It never merges refunds automatically.

Voiding or replacing a settlement does not void a truthful refund payment. Each refund retains the settlement that authorized it, while active refund totals belong to the account and carry into a replacement settlement. Approval of the replacement is rejected if its refund due would be less than the active amount already refunded. A refund is voided only when the refund record itself is incorrect.

### Evidence is attached through FILE-001

Files are uploaded and linked only after the owning FIN-008 record exists. Allowed purposes are:

| Entity | Allowed purposes |
| --- | --- |
| Receipt | `proof_of_deposit`, `payment_confirmation`, `supporting_document` |
| Deduction | `invoice`, `receipt`, `estimate`, `condition_evidence`, `supporting_document` |
| Refund | `proof_of_refund`, `payment_confirmation`, `supporting_document` |
| Settlement | `settlement_statement`, `correspondence`, `supporting_document` |

Each receipt, deduction, refund, or settlement may have at most twenty active file links. The production bootstrap registers Finance-owned, transaction-aware validators for these entity types and purposes. Link creation and archival use the caller's existing immediate transaction, recheck the entity and limit, and append audit history atomically. Archived links remain historical and do not count toward the active limit.

## Data model

All IDs and idempotency keys are UUIDs. API money values are canonical decimal strings with exactly two fractional digits; persisted money is integer cents. Amounts range from `0.00` through `99999999.99` for aggregates and account snapshots, while individual receipts, deductions, credits, and refunds range from `0.01` through `99999999.99`. Currency is exactly the three ASCII uppercase letters `USD`. Dates are ISO local dates and timestamps are timezone-aware UTC text.

The tables belong to the current greenfield Alembic baseline and exact schema validation. No compatibility schema, legacy fields, or data-adoption path is added.

### `security_deposit_accounts`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `lease_id` | Required unique lease reference. |
| `lease_term_id` | Required lease-term snapshot source belonging to `lease_id`. |
| `property_id`, `space_id` | Required durable lease-context references used for filtering and property-local time. |
| `agreed_amount_minor` | Required integer from 0 through 9,999,999,999 cents, snapshotted from the selected term. |
| `currency_code` | Required exact value `USD`, snapshotted from the selected term. |
| `created_at`, `updated_at` | Required UTC timestamps. No-op commands do not advance `updated_at`. |

### `security_deposit_receipts`

| Field | Rule |
| --- | --- |
| `id`, `account_id` | Stable UUID primary key and required account reference. |
| `idempotency_key` | Required client UUID, unique among deposit receipts. |
| `request_fingerprint` | Internal SHA-256 fingerprint of the canonical create request, including confirmations; never returned or audited. |
| `received_on` | Required property-local date from 1900-01-01 through today. |
| `amount_minor`, `currency_code` | Positive amount and exact account currency. |
| `received_from_party_id`, `received_from_name` | Optional party reference and required snapshot when a party is selected; both otherwise null. |
| `received_by_kind`, `received_by_party_id`, `received_by_name` | Required valid local-operator/null/null or party/ID/name combination. |
| `reference`, `notes` | Optional trimmed external reference up to 200 characters and internal notes up to 4,000. |
| `replaces_receipt_id` | Optional unique self-reference to the voided receipt replaced by this row. |
| `voided_at`, `void_reason` | Both null while active; both required after a confirmed void. |
| `created_at` | Required UTC timestamp. Receipts are otherwise immutable. |

### `security_deposit_settlements`

| Field | Rule |
| --- | --- |
| `id`, `account_id` | Stable UUID primary key and required account reference. |
| `status` | Required `draft`, `approved`, `completed`, or `voided`; at most one non-voided settlement per account. |
| `settlement_due_on` | Required property-local date. |
| `legal_rule_reference`, `review_notes` | Optional trimmed text up to 500 and 4,000 characters. |
| `eligibility_override_reason`, `deadline_override_reason` | Optional 1–1,000 character reasons, required by the exceptional paths described above. |
| `receipt_total_minor`, `credit_total_minor`, `deduction_total_minor`, `refund_due_minor` | Null in a draft; immutable nonnegative approval snapshots satisfying `refund_due = receipt_total + credit_total - deduction_total`. |
| `replaces_settlement_id` | Optional unique self-reference to the voided settlement replaced by this row. |
| `approved_at`, `completed_at` | Set exactly when those transitions occur and retained after a later void. |
| `voided_at`, `void_reason` | Both null before void; both required after a confirmed void. |
| `created_at`, `updated_at` | Required UTC timestamps. Draft edits and lifecycle transitions update `updated_at`; no-op commands do not. |

`security_deposit_settlement_receipts` stores the exact active receipt IDs included at approval, with a unique `(settlement_id, receipt_id)` pair. Its rows and the approval totals are immutable.

### `security_deposit_deductions`

| Field | Rule |
| --- | --- |
| `id`, `settlement_id` | Stable UUID primary key and required settlement reference. |
| `category` | Required closed category value defined above. |
| `amount_minor` | Required positive integer amount. |
| `description`, `rationale` | Required trimmed text, 1–500 and 1–2,000 characters. |
| `created_at`, `updated_at` | Required UTC timestamps; editable only while the settlement is draft. |

`security_deposit_deduction_sources` stores unique typed references with `source_kind` of `inspection_comparison`, `inspection_observation`, `rent_expectation`, or `expense`. It retains a durable source summary; rent-expectation sources also snapshot the outstanding amount at approval. Source status changes are displayed as warnings and never rewrite the deduction.

### `security_deposit_credits`

| Field | Rule |
| --- | --- |
| `id`, `settlement_id` | Stable UUID primary key and required settlement reference. |
| `kind` | Required `interest` or `other`. |
| `amount_minor` | Required positive applied credit. |
| `description` | Required trimmed text, 1–500 characters. |
| `calculator_principal_minor`, `annual_rate_basis_points`, `starts_on`, `ends_on`, `day_count`, `calculated_amount_minor` | All null or all present for an interest calculation. Rate is 1–100,000 basis points; period is positive and at most 36,600 days. |
| `override_reason` | Required when the applied amount differs from the calculated amount; otherwise null. |
| `created_at`, `updated_at` | Required UTC timestamps; editable only while the settlement is draft. |

### `security_deposit_refunds`

| Field | Rule |
| --- | --- |
| `id`, `account_id` | Stable UUID primary key and required account reference. |
| `authorized_by_settlement_id` | Required reference to the settlement that was approved when this payment was recorded; retained if that settlement is later voided. |
| `idempotency_key`, `request_fingerprint` | Required unique client UUID and internal canonical request fingerprint. |
| `recipient_party_id`, `recipient_name` | Required party reference and durable 1–200 character display-name snapshot. |
| `paid_on` | Required property-local date from 1900-01-01 through today. |
| `amount_minor`, `currency_code` | Positive amount and exact account currency. |
| `reference`, `notes` | Optional trimmed external reference up to 200 characters and notes up to 4,000. |
| `recipient_override_reason` | Required for a recipient who is neither a lease participant nor an account payer. |
| `replaces_refund_id` | Optional unique self-reference to the voided refund replaced by this row. |
| `voided_at`, `void_reason` | Both null while active; both required after a confirmed void. |
| `created_at` | Required UTC timestamp. Refunds are otherwise immutable. |

Database CHECK constraints enforce money bounds, valid paired fields, status timestamps, date ordering, exact `USD`, received-by consistency, calculator completeness, and void lifecycle consistency. Unique and partial indexes enforce lease-account uniqueness, idempotency, correction lineage, source uniqueness, and one non-voided settlement per account. Aggregate and cross-module rules remain transaction-scoped application invariants because SQLite CHECK constraints cannot safely enforce them across rows or modules.

## Workflows

### Establish the account and record funds

1. Select one lease and one explicit applicable lease term.
2. Create the account after reviewing the snapshotted agreed amount and currency.
3. Record each actual receipt with a new UUID idempotency key.
4. Review any likely-duplicate or historical-context warning; never merge automatically.
5. Upload and link optional evidence after the receipt exists.

Underpayment does not block recording. When active receipt total exceeds the snapshotted agreed amount, creation requires `overageConfirmed: true` and a reason. Account detail shows agreed amount, active received amount, variance, approved settlement snapshot, active refunds, and any unsettled post-approval receipts.

### Prepare and approve settlement

1. Create the only non-voided draft with an operator-entered deadline and any legal reference or notes.
2. Explicitly select inspection, rent-expectation, expense, and file evidence.
3. Enter deductions and credits independently; use the optional UI interest calculator only as an aid.
4. Review receipt total, credits, deductions, and calculated refund due.
5. Approve with `confirmed: true`.

Approval runs in one `BEGIN IMMEDIATE` transaction. It rechecks lease and move-out eligibility, active receipt set and totals, every source identity and status, deduction evidence, duplicate expense use, arithmetic, amount bounds, and FILE-001 link state. It then freezes source snapshots, advances status, and appends audit events atomically.

### Record refunds and complete settlement

1. After approval, record each actual partial refund with a new UUID idempotency key.
2. Review recipient eligibility, historical-source warnings, duplicate warnings, and the remaining amount.
3. Link optional proof after each refund exists.
4. Complete when active refunds equal refund due, or explicitly confirm a zero-refund completion.

Refund writes use an immediate transaction and recheck the current approved settlement, its snapshot, and the account's active-refund total. Completion repeats those checks and also refuses completion while post-approval receipts remain unsettled.

### Correct history

Receipt and refund corrections use void-and-replace. A settlement correction voids the settlement and creates a replacement draft linked to it; active truthful refunds carry forward at account level and retain the old settlement as their authorization source. Replacement approval cannot calculate a refund due below the active amount already paid. The service validates correction chains, rejects cycles or branching, and retains every row, file link, source snapshot, and audit event.

## API contract

The REST API uses camelCase JSON, UUID identifiers, ISO dates, UTC timestamps, and exact two-decimal money strings. Representative routes are:

- `GET /api/security-deposits` — paginated account summaries filtered by property, space, lease, settlement state, deadline state, or unresolved balance.
- `POST /api/leases/{leaseId}/security-deposit` and `GET /api/leases/{leaseId}/security-deposit` — establish or read the lease account.
- `POST /api/security-deposits/{accountId}/receipts` and `POST /api/security-deposit-receipts/{receiptId}/void` — record and correct receipts.
- `POST /api/security-deposits/{accountId}/settlements` and `PATCH /api/security-deposit-settlements/{settlementId}` — create or edit the only draft.
- `POST`, `PATCH`, and `DELETE` draft-only deduction and credit subresources — maintain proposed settlement lines and typed sources without deleting approved history.
- `POST /api/security-deposit-settlements/{settlementId}/approve`, `/complete`, and `/void` — execute explicit lifecycle transitions.
- `POST /api/security-deposit-settlements/{settlementId}/refunds` and `POST /api/security-deposit-refunds/{refundId}/void` — record and correct actual refunds.
- `GET /api/security-deposit-settlements/{settlementId}` — return source snapshots, evidence summaries, correction lineage, approved arithmetic, refund progress, warnings, and contextual history.

Lists default to 100 items and accept a maximum page size of 500. Filters exclude voided financial rows and archived selectable source records by default, with explicit history flags for retained records. Detail responses expose both backward and forward correction links.

Validation errors return `422`; missing records return `404`; stale lifecycle, changed idempotency payloads, duplicate-review requirements, concurrent aggregate conflicts, and invalid correction order return typed `409` errors. Retrying a successful idempotent command returns the original response without changing timestamps or audit history.

## Module and transaction boundaries

FIN-008 is implemented by a separate `DepositService` inside the Finance module. It does not enlarge FIN-001's `FinanceService` or FIN-002's `ExpenseService` and does not import another module's ORM models or repositories.

Bootstrap composes transaction-aware application protocols for:

- Lease account context, explicit term snapshots, lifecycle, participants, actual move-out, property/space, and stored property time zone.
- Finalized inspection comparison and observation summaries.
- FIN-001 expectation identity and outstanding-balance snapshots.
- FIN-002 expense identity and duplicate settlement-use checks.
- Shared-party identity, status, and durable display labels.
- FILE-001 entity validation and active-link counts.

Every command opens one Finance unit of work using `BEGIN IMMEDIATE`, and every port reads through that same session. Aggregate totals, one-current-settlement rules, source eligibility, correction lineage, file-link limits, mutation, and audit append are rechecked in that transaction. Ports contain no commits and callers never open nested write transactions.

## Audit, privacy, backup, and restore

AUDIT-001 records account creation; receipt creation, void, and replacement; draft settlement edits; deduction, source, and credit changes; approval, completion, void, and replacement; refund creation, void, and replacement; duplicate confirmations; historical-source confirmations; and exceptional override decisions.

Global activity identifies the action and safe context but redacts amounts, payer and recipient names, descriptions, rationales, references, notes, deadline-rule text, and override reasons. Contextual entity history may show the complete authorized snapshot. Internal request fingerprints are never shown in either view.

The current schema, exact validation, encrypted portable backups, export manifest, restore staging, and managed-file validation include every FIN-008 table and referenced active or archived FILE-001 link. Restore rejects missing rows, broken lineages, invalid checks, orphaned sources, inconsistent approval arithmetic, excess refunds, and unsupported schema versions before publication.

## UI-001 operator workflow

UI-001 delivers a lease-context security-deposit workspace that:

- Shows agreed amount, receipts, payer history, held balance, variance, settlement status, deadline state, refund progress, and correction chains.
- Searches and selects any existing party as payer; normal search excludes archived parties and warns before historical selection.
- Warns on likely duplicate receipts and refunds and never merges automatically.
- Builds a draft from explicit source selections while keeping inspection classifications, rent balances, expense amounts, and deduction decisions visually distinct.
- Allows missing evidence in a draft but explains the source required before approval.
- Provides the simple-interest calculator, displays every input and rounding result, and requires a reason for an override.
- Requires clear confirmation for approval, exceptional eligibility/deadline choices, overages, zero-dollar closure, zero-refund completion, voids, and out-of-role recipients.
- Records multiple partial refunds without implying that the application moved money.
- Preserves a saved record when a later evidence upload fails and offers a retry.

## Acceptance criteria

FIN-008 backend/API scope is complete when:

1. One current-format account per lease snapshots one explicit lease term and supports multiple immutable receipts.
2. Receipt and refund retries are idempotent, likely duplicates require review, and corrections form retained void-and-replace chains.
3. Deposits never create rent income; deductions never create or copy expenses; inspection classifications never create deductions.
4. Every approved deduction has an allowed active source, and source snapshots remain stable after later changes.
5. Approval freezes exact receipt membership and satisfies `refund due = receipts + credits - deductions` with exact cents.
6. Interest calculations use the documented inputs, day convention, and half-up rounding, with reasons for applied overrides.
7. Refund totals cannot exceed the approved refund due, and completion requires exact payment or explicit zero-refund confirmation.
8. Deadlines use property-local dates and operator-entered rule context without statutory inference or legal-compliance claims.
9. Party selection, archived sources, overages, exceptional settlement timing, and recipient overrides enforce the documented confirmations.
10. Every aggregate mutation and file-link guard is transaction-scoped, concurrent-safe, and atomically audited.
11. Global activity redacts sensitive financial context while contextual history and encrypted backup/restore preserve complete records.
12. Tests cover happy paths, zero-dollar closure, partial and multiple receipts/refunds, duplicate and idempotency cases, stale sources, post-approval receipts, correction chains, archive/history selection, rounding edges, FILE-001 limits, concurrency, audit redaction, and restore rejection.

The overall backlog item remains incomplete until UI-001 delivers and verifies the operator workflow above.

## Dependencies

Hard prerequisites are `AUDIT-001`, `FILE-001`, `LEASE-001`, `FIN-001`, `FIN-002`, and `INSP-001`. FIN-008 also consumes the shared party and transaction/guard protocols established by TEN-001/VEND-001 through those current architecture boundaries. `FIN-003` depends on FIN-008 so its totals can distinguish held deposits and settlement activity. `UI-001` depends on FIN-008 for the deferred operator workflow.
