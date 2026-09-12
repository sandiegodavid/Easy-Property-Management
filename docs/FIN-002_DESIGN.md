# FIN-002 — Recorded Property Expenses

## Purpose

`FIN-002` gives the local operator a truthful record of property spending that has already occurred: what was paid, when it was paid, which property it belongs to, who was paid, who paid it, how it was categorized, and which files support it. It does not create bills, predict obligations, or initiate payment.

The slice deliberately separates an operational cost from a financial fact. Maintenance may record estimates, quotes, and work-reported cost context. Finance alone owns confirmed actual spending. A later maintenance workflow may reference a FIN-002 expense ID, but it must not copy the expense amount as another source of actual spending.

## Scope

FIN-002 provides:

- Recorded expenses for exactly one property and, optionally, one space at that property.
- Finance-owned, operator-configurable expense categories.
- An optional provider reference plus a durable payee or merchant snapshot.
- The local operator or an eligible party as the recorded payer.
- Explicit expense and refund void-and-replace correction chains.
- Client-generated idempotency keys and operator-reviewed likely-duplicate warnings.
- FILE-001 evidence links created after the expense exists.
- Typed API contracts, atomic audit history, current-schema validation, and encrypted backup/export/restore coverage.

FIN-002 records actual spending only. Bills, due dates, scheduled or recurring expenses, and payment reminders belong to `FIN-005`. It does not initiate payments, store financial-account credentials, reconcile bank feeds, calculate tax treatment, allocate one expense across properties or spaces, aggregate portfolio profit, manage maintenance work, or produce owner statements. Those responsibilities belong to later FIN, MAINT, reporting, and owner-accounting items.

FIN-002 is US-only for the MVP. Currency is fixed to `USD`; dates are interpreted using the selected property's stored US IANA time zone. The React workflow is deferred to `UI-001`.

## Core decisions

### Expense means confirmed actual spending

An expense is created only after money has actually been paid. `paidOn` is the local calendar date on which spending occurred, not an invoice date, due date, planned payment date, or service period. An invoice may be supporting evidence, but its presence does not turn an unpaid bill into an expense.

Maintenance owns issues, work, quotes, estimates, and operational cost context. A quote or entered estimate is not included in financial totals. When actual spending is known, FIN-002 creates the authoritative expense. Future maintenance records may hold an optional expense ID for navigation and traceability, while Finance remains the only owner of the paid amount, refund history, category, and financial correction lifecycle.

### Money uses an exact decimal contract

Request and response amounts are canonical decimal strings with exactly two fractional digits, such as `"125.00"`. Floats, JSON numbers, exponent notation, signs, commas, whitespace, more or fewer fractional digits, zero, and negative values are rejected. The application parses with `Decimal`, converts once to integer cents, and persists only the exact minor-unit integer. It never stores or calculates money with binary floating point.

The largest accepted expense or refund is `99999999.99`. Currency is exactly the three ASCII uppercase letters `USD` in this US-only slice. Keeping `currencyCode` in the contract makes the monetary meaning explicit without claiming multicurrency support.

### Property is required; space is optional

Every expense targets exactly one property. It may also target one active space belonging to that property. FIN-002 does not split or allocate one expense among multiple properties or spaces. If an operator needs such a split, each property-level financial fact is recorded as a separate expense with its own idempotency key and evidence links.

Normal creation selects an active property and active space. An archived property or space may be selected only for a historical entry when the operator explicitly confirms that choice and supplies a 1–1,000 character reason. Existing expenses never block archival and remain queryable as history.

### Provider reference is optional; payee identity remains durable

An expense may reference one provider profile. When a provider is selected, the request omits the free-text payee label and the service snapshots that provider's current display name into `payee_name`. When no provider is selected, a trimmed 1–200 character payee or merchant label is required. The snapshot is retained even if the provider is later renamed or archived.

Normal provider selection excludes archived profiles. An archived provider may be selected for a historical expense only with explicit confirmation and a 1–1,000 character reason. Existing expense references never block provider archival, and an archived provider reference does not hide an expense from financial history.

### Payer records who funded the spending

`paidByKind` is either `local_operator` or `party`. `local_operator` requires a null `paidByPartyId`. `party` requires an existing shared party and may be used only when that party has an effective `client_owner` property-ownership relationship covering the expense property on `paidOn`. The payer is descriptive history; FIN-002 does not create reimbursement obligations, owner balances, or disbursements from it.

### Expense categories belong to Finance

Expense categories are independent from provider service categories. Provider categories answer what work a provider performs; expense categories classify actual spending. FIN-002 seeds editable categories with stable IDs: Repairs and maintenance, Utilities, Insurance, Property taxes, Supplies, Professional services, Management fees, and Other.

Category names are unique after trim, Unicode normalization, and case folding. Archived categories are excluded from normal selection but remain on historical expenses. They may be restored unless their normalized name has since been reused. An active category is required for normal creation; historical use of an archived category requires explicit confirmation and a reason.

### Financial facts are immutable and corrections are explicit

After creation, the expense's property, space, paid date, amount, currency, provider, payee snapshot, payer, description, reference, and idempotency key do not change. The operator may reclassify only its category and may update internal notes; each change is audited, and category changes require a 1–1,000 character reason.

Every other correction uses void-and-replace. Voiding requires `confirmed: true` and a reason, retains the complete original record, and removes it from active totals. A replacement is a new expense with a new idempotency key and a unique `replacesExpenseId` pointing to the voided expense. One record may have at most one direct replacement; repeated corrections form a forward chain.

### Refunds and reversals are separate financial facts

A refund records money returned against one expense. It has its own date, positive amount, idempotency key, optional notes, and void-and-replace lifecycle. Active refunds for one expense may not exceed that expense amount. A refund must use the expense currency and cannot be added to a voided expense. An expense with active refunds cannot be voided until those refunds are voided, preventing an orphaned active reversal.

FIN-002 exposes the active refunded amount and net amount for each expense. Broader aggregation belongs to `FIN-003`; FIN-002 does not infer credits, chargebacks, reimbursements, or owner balances from a refund.

### Retries are idempotent; duplicates require operator review

Every expense and refund request carries an opaque client-generated UUID idempotency key, unique within its record type. Repeating the same key and semantically identical payload returns the original result without new rows or audit events. Reusing a key with different content returns `409`.

Separate from retry safety, a new expense is a likely duplicate when an active record has the same property, paid date, amount, currency, and normalized provider/payee identity. The API returns `409 possible_duplicate_expense` with bounded candidate summaries unless the request carries `duplicateConfirmed: true`. The UI shows the candidates and lets the operator cancel, open an existing record, or deliberately continue. The application never merges automatically. A confirmed duplicate remains an independent expense and records that confirmation in audit history.

### Evidence is linked after the expense exists

An expense can exist without evidence. The operator first records the expense, then uploads and links zero to twenty supporting files through FILE-001. This intentionally creates two transactions: an upload failure does not roll back truthful spending, and the UI must preserve the saved expense while offering a clear retry.

Allowed expense-link purposes are `receipt`, `invoice`, `proof_of_payment`, and `supporting_document`. In this context, `receipt` means documentary FILE-001 evidence, not a FIN-001 `rent_receipt`. The production bootstrap registers the Finance-owned expense link validator; it confirms that the expense exists, that the purpose is allowed, and that no more than twenty active evidence links result. Finance stores no filename, hash, path, media type, or storage locator.

FILE-001 links are append-only historical records. An incorrect link is archived through the generic file-link lifecycle after explicit confirmation and a 1–1,000 character reason; it is never deleted. Archived links are hidden by default but remain visible in expense history and audit. Evidence may be added to an active or voided retained expense because it documents the historical financial fact.

## Data model

All IDs and idempotency keys are UUIDs. API monetary values are fixed-scale decimal strings; persisted monetary values are integer minor units. Dates are ISO local dates. Timestamps are timezone-aware UTC text. The tables are part of the current greenfield Alembic baseline and exact schema validation; no compatibility schema or data adoption path is added.

### `expense_categories`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `display_name`, `normalized_name` | Required 1–100 character label and application-computed unique normalized identity. |
| `description` | Optional trimmed operator guidance, maximum 1,000 characters. |
| `display_order` | Required integer from 0 through 10,000. |
| `archived_at` | Null while active; UTC timestamp after archival. |
| `created_at`, `updated_at` | Required UTC timestamps. No-op updates do not advance `updated_at`. |

### `expenses`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `idempotency_key` | Required client-generated UUID, unique among expenses. |
| `request_fingerprint` | Required internal SHA-256 fingerprint of the canonical create request, including duplicate and historical-entry confirmations. It makes retry comparison Finance-owned; it is immutable and never returned or shown in audit snapshots. |
| `property_id` | Required Portfolio property reference. |
| `space_id` | Optional space reference; when present it belongs to `property_id`. |
| `category_id` | Required Finance expense-category reference. |
| `provider_party_id` | Optional Providers role-party reference. |
| `payee_name` | Required 1–200 character snapshot, whether derived from a provider or entered directly. |
| `paid_by_kind`, `paid_by_party_id` | Required `local_operator`/null or `party`/required-party pair. |
| `paid_on` | Required property-local date, from 1900-01-01 through the current property-local date. |
| `amount_minor` | Required integer from 1 through 9,999,999,999 cents. |
| `currency_code` | Required exact value `USD`. |
| `description` | Required trimmed spending description, 1–500 characters. |
| `reference` | Optional external invoice, confirmation, check, or transaction reference, maximum 200 characters. It is descriptive only and need not be unique. |
| `notes` | Optional trimmed internal context, maximum 4,000 characters. |
| `replaces_expense_id` | Optional unique self-reference to the voided expense this row replaces. |
| `voided_at`, `void_reason` | Both null while active; both required after a confirmed void. Reason is 1–1,000 characters. |
| `created_at`, `updated_at` | Required UTC timestamps. Only allowed classification/notes changes and lifecycle transitions update `updated_at`; no-op requests do not. |

The database enforces non-null positive amounts, exact currency, payer-pair validity, bounded stored text, void-field pairing, unique idempotency and replacement references, and non-self replacement. Application validation enforces cross-module identity/lifecycle rules and replacement compatibility. Indexes cover property/date, space/date, category/date, provider/date, payer/date, lifecycle/date, and likely-duplicate lookup.

### `expense_refunds`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `expense_id` | Required expense reference. |
| `idempotency_key` | Required client-generated UUID, unique among expense refunds. |
| `received_on` | Required property-local date from the expense date through the current property-local date. |
| `amount_minor` | Required integer from 1 through 9,999,999,999 cents. |
| `currency_code` | Required exact value `USD` and equal to the expense currency. |
| `notes` | Optional trimmed internal context, maximum 4,000 characters. |
| `replaces_refund_id` | Optional unique self-reference to a voided refund for the same expense. |
| `voided_at`, `void_reason` | Consistent null pair while active and required timestamp/reason pair after void. |
| `created_at` | Required UTC timestamp. |

Refund rows are otherwise immutable. Database constraints mirror expense positivity, currency, lifecycle, idempotency, and replacement rules. The application transaction enforces cumulative refund limits and replacement compatibility after acquiring the writer lock.

### FILE-001 `file_links` lifecycle extension

`file_links` adds nullable `archived_at` and `archive_reason`; both are null for an active link and both are required for an archived link. `archive_reason` is trimmed and limited to 1–1,000 characters. A new partial unique index on `(file_id, entity_type, entity_id, purpose)` applies to active links only, allowing a corrected active association while retaining the archived mistake. Physical deletion remains out of scope.

## Workflows and invariants

### Record an expense

`POST /api/expenses` runs in one immediate transaction. It validates the property, optional space, category, optional provider, payer, local date, decimal amount, replacement target, idempotency, and duplicate policy before inserting the expense and correlated audit event. A replacement must point to a voided expense, and the new row may intentionally correct every immutable business field.

For archived property, space, provider, or category selection, `historicalEntryConfirmed` must be true and `historicalEntryReason` must be present. One confirmation/reason pair covers all archived references used by that request and is preserved in the audit snapshot; normal creation does not accept the pair.

### Reclassify or annotate an expense

`PATCH /api/expenses/{expenseId}` accepts only `categoryId`, `notes`, and an optional category-change reason. At least one effective change is required. A category change uses the same active/historical category rules as creation and requires its reason. No-op updates return the unchanged view without changing timestamps or appending audit events.

### Void and replace an expense

`POST /api/expenses/{expenseId}/void` requires confirmation and reason. It rejects an already voided expense and an expense with an active refund. The original stays addressable and its evidence stays linked. A corrected expense is then recorded through the normal create endpoint with `replacesExpenseId` and a new idempotency key.

### Record, void, or replace a refund

`POST /api/expenses/{expenseId}/refunds` records one refund after rechecking the active expense and active-refund total in the writer transaction. `POST /api/expense-refunds/{refundId}/void` requires confirmation and reason. A correction uses the normal refund-create endpoint with `replacesRefundId` and a new idempotency key.

### Query behavior

Expense list queries support property ID, space ID, category ID, provider party ID, payer kind/party ID, paid-on range, evidence presence, and `includeVoided`. Normal reference pickers exclude archived values, but historical expense lists do not disappear when related records are archived. Results are ordered by `paidOn` descending, then expense ID, with cursor pagination defaulting to 100 and capped at 500.

Detail includes the expense snapshot, category/provider/property/space summaries, active and archived evidence summaries, refund history, active refunded amount, net amount, lifecycle, and correction chain. It does not return portfolio aggregate totals; `FIN-003` owns aggregation and source-record drill-down across finance records.

## Operator workflow delivered by UI-001

UI-001 adds **Money > Expenses** with filters matching the API and plain-language columns Date paid, Property, Space, Category, Paid to, Paid by, Amount, Refunded, Net, Evidence, and Status. Voided records are hidden by default but can be included. Every amount opens its expense, refund, evidence, and correction source records.

**Record expense** requires property, category, paid date, decimal amount, payee/provider choice, payer, and description. Space, reference, and notes are optional. Provider search excludes archived providers and displays a separate merchant-label path. Selecting a property limits spaces and shows its local time zone. The client creates and retains the UUID idempotency key across retries.

When the API identifies likely duplicates, the screen shows bounded candidates and offers **Open existing**, **Go back**, or **Record separately**. It never merges automatically. After the expense is saved, the workflow moves to **Add evidence**. Upload errors leave the expense visibly saved and provide retry/skip actions.

Detail supports category/notes updates, evidence-link archival, refund recording, and explicit void-and-replace flows. Void/replacement screens preserve the old record and show lineage. Historical selection of an archived property, space, provider, or category is visually exceptional and requires confirmation plus a reason.

## API contract

All routes require a ready workspace. Mutations require the writer lock. Request models use `extra="forbid"`, `StrictBool` confirmations, typed UUIDs and ISO dates, and the strict fixed-scale decimal-string amount. Application commands repeat validation for direct callers. Responses use explicit Pydantic models.

| Method | Path | Intent |
| --- | --- | --- |
| `GET` | `/api/expense-categories` | List active categories, optionally including archived history. |
| `POST` | `/api/expense-categories` | Create a category. |
| `PATCH` | `/api/expense-categories/{categoryId}` | Update a category's label, description, or display order. |
| `POST` | `/api/expense-categories/{categoryId}/archive` | Archive a category after confirmation. |
| `POST` | `/api/expense-categories/{categoryId}/restore` | Restore a category after confirmation. |
| `POST` | `/api/expenses` | Record an expense or an explicit replacement. |
| `GET` | `/api/expenses` | List expenses with typed filters and cursor pagination. |
| `GET` | `/api/expenses/{expenseId}` | Return one expense with refunds, evidence, and correction history. |
| `PATCH` | `/api/expenses/{expenseId}` | Change category and/or internal notes only. |
| `POST` | `/api/expenses/{expenseId}/void` | Void an expense after explicit confirmation and reason. |
| `POST` | `/api/expenses/{expenseId}/refunds` | Record a refund or replacement refund. |
| `POST` | `/api/expense-refunds/{refundId}/void` | Void a refund after explicit confirmation and reason. |
| `POST` | `/api/file-links/{fileLinkId}/archive` | Archive an incorrect evidence association after owning-domain validation and confirmation. |

Create-expense requests contain `idempotencyKey`, `propertyId`, optional `spaceId`, `categoryId`, optional `providerPartyId`, `paidByKind`, optional `paidByPartyId`, `paidOn`, `amount`, `currencyCode`, `description`, optional `reference`, optional `notes`, optional `replacesExpenseId`, `duplicateConfirmed`, and the optional historical-entry confirmation/reason pair. `payeeName` is required exactly when `providerPartyId` is absent and is otherwise forbidden because the service derives the provider-name snapshot. Refund requests contain `idempotencyKey`, `receivedOn`, `amount`, `currencyCode`, optional `notes`, and optional `replacesRefundId`.

Malformed input returns `422`; missing records return `404`; invalid business data returns `400`; likely duplicates, idempotency mismatches, lifecycle conflicts, cumulative over-refunds, stale state, and concurrent writes return `409`.

## Module and transaction boundaries

FIN-002 adds a separate `ExpenseService` inside the existing `finance` module. It reuses Finance's unit-of-work abstractions and audit port but does not expand the FIN-001 `FinanceService` into an unrelated coordinator. Expense repositories and read models remain separate from rent-expectation, receipt, and allocation repositories.

Cross-module checks use transaction-aware application protocols composed at bootstrap:

- `PortfolioExpenseOperations` supplies property/space identity, lifecycle, relationship, and stored property time zone.
- `ProviderExpenseOperations` supplies provider role, lifecycle, and display-name projection without exposing provider persistence.
- Party/ownership operations validate a party payer's effective client-owner relationship.
- The Finance expense-link validator supplies FILE-001 entity/purpose/count authorization without FILE-001 importing Finance models.

Every protocol call uses the caller's existing immediate transaction. Finance application code does not import Portfolio, Providers, Parties, Files, or their SQLAlchemy models. Other modules may retain stable expense IDs but do not mutate Finance rows.

## Audit, privacy, and portability

Every mutation persists business rows and `AUDIT-001` changes atomically under one correlation ID. Entity types are `expense_category`, `expense`, `expense_refund`, and the existing `file_link`. Category changes, historical-reference confirmations, duplicate confirmations, lifecycle transitions, and replacement lineage are explicit in contextual history. No-op/idempotent replays create no audit event.

General activity may show the action, property, paid/refund date, and lifecycle, but redacts amount, payee, provider and payer IDs, description, reference, notes, idempotency keys, reasons, and replacement references. Contextual Finance history may reveal the complete local record to the operator. Audit presentation policies are registered before any expense workflow is available, preserving fail-closed behavior.

Expense, category, refund, evidence-link metadata, and audit history participate in LOCAL-002 encrypted backup/export/restore. FILE-001 remains responsible for materializing and hash-validating linked content. FIN-002 stores no bank credentials, account numbers, payment tokens, or file bytes.

## Implementation outline

1. Add category, expense, refund, and file-link lifecycle columns/constraints/indexes to the single current greenfield baseline and to exact module/archive schema validation.
2. Add strict amount/text/date/idempotency/lifecycle domain values and commands, keeping decimal parsing separate from exact minor-unit persistence.
3. Add the dedicated `ExpenseService`, repositories, unit-of-work operations, transaction-aware Portfolio/Provider/Party protocols, and the production Finance file-link validator.
4. Register fail-closed audit policies, expose typed FastAPI routes, and preserve the ready-workspace/writer-lock/error boundaries.
5. Add regression coverage for validation, archived references, property/space/provider/payer boundaries, category lifecycle, idempotency, duplicate confirmation, refunds, concurrency, void/replacement chains, file-link correction/count limits, redaction, exact schema validation, and encrypted backup/export/restore.

## Acceptance criteria

FIN-002 is complete when:

1. The operator can record one exact, positive, already-paid USD expense for one property and optional child space, with a Finance category, durable payee, payer, description, date, and idempotent retry behavior.
2. Provider-backed and free-text payees, archived historical references, and party-funded expenses obey the documented cross-module guards without direct persistence coupling.
3. Likely duplicates are shown for operator review and are never merged automatically.
4. Expense and refund corrections preserve explicit void/replacement lineage; active refunds cannot exceed or outlive their active expense.
5. Zero to twenty FILE-001 evidence links can be added after creation, and an incorrect association can be archived with retained history rather than deleted.
6. FIN-002 contains no bills, due dates, recurrence, reminders, payment initiation, multi-property allocations, maintenance workflow state, or portfolio aggregate reporting.
7. Typed API/application contracts, fail-closed audit presentation, exact schema validation, and encrypted backup/export/restore preserve the complete record.
8. UI-001 delivers the documented expense creation, duplicate review, evidence, filtering, refund, and correction workflows before FIN-002 is marked complete.

## Dependencies and follow-on work

FIN-002 requires completed `AUDIT-001`, `FILE-001`, `PORT-002`, and `VEND-001`. It also relies on the shared Parties and owner-management relationship capabilities already established through `TEN-001`, `PORT-001`, and VEND-001, without adding redundant hard dependencies to the backlog row.

`UI-001` delivers the operator expense workflow. `FIN-003` aggregates active expense net amounts with income and provides source-record drill-down. `FIN-005` owns bills, due dates, recurrence, and reminders. `MAINT-001` and later maintenance slices may reference expense IDs but do not own actual spending. `FIN-008` may reference expenses as approved deposit-settlement evidence without changing them. Later reconciliation, tax, owner-balance, and disbursement features consume FIN-002 records through application/read-model boundaries rather than rewriting them.
