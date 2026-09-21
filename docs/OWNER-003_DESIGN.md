# OWNER-003 — Owner-Reported Rent Receipt Intake and Verification

## Purpose

`OWNER-003` records a client owner's report that the owner received rent directly, preserves the report and its evidence, and requires operator verification before the report is connected to the application's financial record.

The report is provenance, not a second income entry. Verified money is represented exactly once by a linked `FIN-001` rent receipt and its allocations. Pending or rejected reports never affect rent balances, income totals, owner balances, or disbursements.

This design covers backend domain behavior, persistence, APIs, audit, file validation, and current-format workspace validation. It does not implement application code or a React screen.

## Current baseline and dependencies

The implemented repository already provides the boundaries OWNER-003 needs:

- `PORT-001` stores effective-dated `property_ownerships` for `client_owner` parties. `PortfolioContextReader.party_owned_property_on(...)` and `ownership_subject_kinds_on(...)` expose neutral historical ownership facts inside a caller-owned transaction.
- Shared `parties` provide stable owner identity. A party may be archived later without erasing its historical property ownership.
- `FIN-001` owns immutable rent receipts and allocations, likely-duplicate checks, receipt void-and-replace correction, and `received_by_party_id`. Its internal transaction-scoped receipt policy already supports another workflow creating a receipt without opening a nested transaction.
- `FIN-006` makes an immutable actual payment-method snapshot mandatory on every current `FIN-001` receipt. This is implemented even though it is absent from the OWNER-003 backlog dependency list.
- `FILE-001` owns file metadata, bytes, links, link archival, and storage availability. Owning modules register transaction-aware target/purpose validators.
- `AUDIT-001` supplies fail-closed, correlated append-only history.
- The architecture already names `owner-accounting` as the server module responsible for owner-reported receipts, balances, and disbursement history. No owner-accounting package or schema currently exists.

The current product remains greenfield and latest-format-only. There is one Alembic baseline, exact module schema validation, a product-table allowlist, retained-data validation, and encrypted backup/export/restore validation. No customer-workspace adoption framework exists.

## Scope

OWNER-003 provides:

- Manual operator entry of a rent-receipt report attributed to one client-owner party.
- Historical validation that the selected party was a client owner of the lease's property on the claimed receipt date.
- The owner's claimed receipt date, amount, actual payment-method details, report time, optional source note, and durable owner display-name snapshot.
- FILE-001 supporting evidence with an evidence requirement before verification.
- Pending-report correction before verification.
- Explicit operator verification or rejection.
- Atomic adoption of one compatible existing FIN-001 receipt or atomic creation of one new FIN-001 receipt and allocations.
- One-to-one report-to-receipt linkage, duplicate-income prevention, idempotency, audit history, correction lineage, bounded list/detail reads, exact schema/data validation, and encrypted backup/restore.

OWNER-003 does not provide:

- Owner login, direct submission, email/SMS ingestion, mailbox synchronization, or a portal. The local operator records the report. `INTAKE-001` and `PORTAL-002` own later direct-owner workflows.
- Payment initiation, bank reconciliation, credentials, account/routing numbers, raw check numbers, or unmasked financial data.
- Rent expectation generation, receipt accounting, allocation arithmetic, receipt correction, or income aggregation. Those remain Finance-owned.
- Ownership shares, legal entitlement, joint-account allocation, trust accounting, management fees, owner balances, statements, or disbursements. Later OWNER and FIN items own those calculations.
- Treating an attachment, owner statement, or matching amount as automatic verification. The operator makes the decision.
- A second owner-specific receipt table or copied FIN-001 allocation rows.

## Domain boundaries

### A report is source provenance, not income

An owner rent report records what a client owner said happened. Its amount does not contribute to received rent while the report is pending or rejected. Verification does not post an owner-accounting amount; it links the report to one active FIN-001 receipt, creating that receipt through Finance-owned transaction operations only when necessary.

FIN-001 remains authoritative for:

- whether money is a receipt;
- the receipt amount, currency, date, recipient, actual-method snapshot, lifecycle, and replacement lineage;
- allocation to rent expectations; and
- received/outstanding rent totals.

OWNER-003 remains authoritative for:

- who reported the direct receipt and when;
- the unverified claim and its evidence;
- the verification/rejection decision; and
- whether a FIN-001 receipt has verified owner-report provenance.

Reports and receipts are not synchronized copies. A verified report response projects the linked receipt's current lifecycle and allocation summary. It never recalculates income independently.

### Only client-owner receipts use this workflow

The report selects one `client_owner` party and one lease. The selected party must have an effective ownership relationship to the lease's property on `received_on`. Current ownership or current party activity is not required for a truthful historical report; the report retains the owner display snapshot and surfaces current party/ownership state as context.

`local_operator` ownership has no Party ID and does not use OWNER-003. Rent received by the local operator is recorded directly through FIN-001. Mixed properties may use OWNER-003 only for the specifically selected client owner.

The relationship is operational evidence, not a determination of beneficial ownership, percentage share, or entitlement to the money.

### One report represents one actual receipt

One report records one actual payment received by one owner on one date. Its amount may be allocated across one or more eligible expectations for the selected lease, following FIN-001's existing 1–100 allocation rule, but it cannot combine separate payments, multiple leases, multiple recipients, or multiple currencies.

If a statement lists several payments, the operator records one report per payment. The MVP does not split a jointly received payment between owners or invent ownership percentages. That requires a later owner-accounting design.

### Claimed and verified payment facts remain distinguishable

The pending report stores the owner's claimed actual-method snapshot using FIN-006's safe vocabulary and bounds. This preserves what was reported before it is accepted as a financial fact. Verification requires the selected or newly created FIN-001 receipt to match the report's lease, received date, amount, USD currency, owner recipient, and method snapshot exactly.

The report never stores raw bank or check credentials. A method that is genuinely unknown cannot be changed to a fabricated value merely to pass FIN-006 validation; the report remains pending until the operator obtains the actual method or links an already verified compatible receipt.

### Verification adopts or creates exactly one receipt

Verification runs under one immediate SQLite transaction and one correlation ID.

The operator chooses exactly one mode:

1. **Use an existing receipt.** The selected receipt must be active, unlinked to another owner report, belong to the same lease, and exactly match the report's received date, amount, USD currency, owner recipient, and FIN-006 method snapshot. Its allocations must remain valid FIN-001 allocations.
2. **Create a receipt.** The request supplies a new FIN-001 receipt idempotency key and 1–100 expectation allocations totaling the report amount. Finance-owned transaction operations reapply all FIN-001 date, expectation, allocation, over-allocation, replacement, and concurrency rules and write the receipt/allocation audit events.

If an active likely matching FIN-001 receipt already exists, OWNER-003 must not use FIN-001's independent-payment override to create another receipt. It returns bounded candidate IDs and requires the operator to select a compatible receipt or correct/void the conflicting Finance record first. This is stricter than ordinary FIN-001 duplicate confirmation because OWNER-003's defining purpose is to avoid recording the same reported income twice.

Receipt creation and report verification commit or roll back together. File upload remains a prior separate FILE-001 operation because the report must exist before it can own links.

### Later receipt lifecycle does not rewrite report history

A verified report remains a truthful record of the prior verification even if its linked FIN-001 receipt is later voided. Reads then show `receiptLifecycleStatus = voided` and `financiallyEffective = false`; OWNER-003 does not silently reject, relink, or delete the report.

Correction uses explicit nonbranching report lineage. A replacement report may identify one terminal prior report through `replaces_report_id`, and one report may have at most one direct replacement. A replacement of a verified report can become verified only against the corresponding active FIN-001 replacement receipt; its predecessor receipt must be voided and the new receipt must name it through FIN-001's `replaces_receipt_id`. Rejected reports may be replaced without a receipt-lineage requirement.

Pending reports may be patched instead of replaced. Verified and rejected reports are immutable except for the independently managed lifecycle of their FILE-001 links.

## Evidence

Evidence is uploaded and linked after the report exists. The FILE-001 entity type is `owner_rent_report`. Allowed purposes are:

- `owner_statement`;
- `payment_confirmation`;
- `deposit_confirmation`;
- `correspondence`; and
- `supporting_document`.

Each report may have at most twenty active links. Verification requires at least one active available file link. The operator must also supply `confirmed = true` and a bounded verification note identifying what was checked. Evidence never verifies a report automatically.

Archiving a link requires the normal FILE-001 confirmation and reason. The owner-accounting file validator must reject archival of the last active available evidence link while a report is verified. A replacement file can be linked before the incorrect link is archived. Rejected and pending reports may have all links archived while retaining link history.

File metadata and storage locators remain FILE-001-owned. Owner-accounting stores neither filenames nor hashes.

## Data model

All identifiers and operation idempotency keys are UUIDs. Amounts are positive integer cents from 1 through 9,999,999,999 and currency is exactly `USD`. Dates are ISO property-local dates. Timestamps are aware UTC text. Bounded text is trimmed and nonblank when required.

### `owner_rent_reports`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `lease_id` | Required stable lease reference. |
| `property_id`, `space_id` | Required immutable context snapshots resolved from the lease when the report is created. |
| `property_timezone_snapshot` | Required canonical IANA zone used for date validation and presentation. |
| `owner_party_id` | Required client-owner Party reference. |
| `owner_display_name_snapshot` | Required trimmed 1–240-character identity snapshot. |
| `received_on` | Required property-local date on which the owner says the money was received; cannot be in the future. |
| `amount_minor`, `currency_code` | Required positive integer amount and exact `USD`. |
| `payment_method_kind` | FIN-006 kind: `automatic_bank_payment`, `bank_transfer`, `check`, `cash`, `online_payment`, or `other`. |
| `payment_method_label`, `masked_reference`, `other_payment_method_note` | Same safe bounds and conditional rules as FIN-006. No raw credential or number. |
| `reported_at_utc` | Required aware instant when the owner reported the receipt; cannot be in the future or precede the claimed receipt's property-local day. |
| `source_note` | Optional sensitive context, maximum 4,000 characters. It is not a substitute for evidence. |
| `status` | `pending`, `verified`, or `rejected`. |
| `verified_receipt_id` | Null unless verified; then required and unique. |
| `reviewed_at`, `review_note` | Null while pending; both required for verified or rejected. `review_note` is the verification note or rejection reason. |
| `replaces_report_id` | Optional unique self-reference to a terminal prior report; never self-referential. |
| `created_at`, `updated_at` | Required UTC timestamps. A no-op does not advance `updated_at`. |

Database checks enforce bounded stored shapes, USD/amount rules, FIN-006 conditional fields, exhaustive status/nullability pairs, non-self replacement, and unique receipt/report and replacement edges. Application validation enforces lease/property context, property-local dates, historical owner eligibility, current replacement state, evidence, exact receipt compatibility, and nonbranching lineage.

### `owner_rent_report_operations`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `idempotency_key` | Required workspace-unique client UUID. |
| `action` | `create`, `patch`, `verify`, or `reject`. |
| `report_id` | Required result/target report ID. |
| `request_fingerprint` | Required canonical SHA-256 fingerprint of the semantic command. |
| `result_receipt_id` | Present only when verification returns a receipt. |
| `receipt_created` | Null for `create`, `patch`, and `reject`. For `verify`, immutable `0` means the report adopted the explicitly selected existing receipt; immutable `1` means verification created the receipt and its allocations under the operation correlation. |
| `correlation_id`, `created_at` | Required audit correlation and UTC timestamp. |

Operation records are append-only and are the retry authority. Same key and same semantic request returns the original current representation without repeating file checks, receipt creation, allocations, or audit events. Same key with a changed request returns typed `409`.

## Application and infrastructure boundaries

The new `owner-accounting` module owns report commands, policy, persistence, HTTP response shaping, file-target validation, and audit presentation. It does not import Portfolio, Parties, Finance, Files, Leasing, or Audit SQLAlchemy models.

Its transaction composes small source-owned application contracts at bootstrap:

- a lease/Finance context reader that resolves lease, property, space, and time-zone facts needed for a report;
- the existing neutral Portfolio historical ownership reader;
- a Party identity reader for the durable display snapshot and current state;
- a File link reader for bounded evidence presence/count/detail;
- Finance-owned neutral receipt context and transaction operations that can validate/select or create a receipt in the caller's existing connection while applying FIN-001 policy; and
- `AuditRecorder` for same-transaction report and Finance events.

The Finance extension must be consumer-neutral. Do not add `owner_report_operations.py`, owner-specific response objects, or OWNER eligibility policy to Finance. Reuse/refactor the existing transaction-scoped receipt policy rather than duplicating receipt rules or invoking `FinanceService` inside another unit of work.

No nested transaction, cross-service HTTP call, or post-commit repair process is acceptable for verification. Query paths must be bounded and set-based. List reads use one owner-report page query plus bounded batch projections for receipt lifecycle, Party current state, and file counts; detail may add file metadata and allocation summaries. No owner, file, receipt, or expectation N+1 queries are allowed.

## Workflows

### Record and edit a pending report

Creation validates the lease context, claimed dates and money, owner identity, and historical client-owner relationship in one immediate transaction. It records the immutable context snapshots and one audit event. Evidence upload happens afterward and may be retried without losing the report.

Only a pending report may be patched. Editable claim fields are revalidated together, including owner eligibility and payment-method rules. A patch is audited with before/after snapshots. Empty patches are no-ops. Changing the report target does not silently move FILE-001 links; the operator must review existing evidence before verification.

### Verify

Verification reloads the report, active evidence, ownership history, and Finance candidates after acquiring the writer transaction. It requires explicit confirmation and a verification note. It then adopts a compatible receipt or creates one through Finance, stores the unique link, sets the report to verified, and writes all report/receipt/allocation audit events under one correlation ID.

The stored owner party must be the FIN-001 `received_by_party_id`. A null recipient or another Party is incompatible even if all other values match.

### Reject

Rejection requires explicit confirmation and a 1–1,000-character reason. It changes a pending report to rejected and writes an audit event. It creates, voids, and links no FIN-001 receipt. Repeating a semantic retry is idempotent; a verified or already rejected report otherwise returns a lifecycle conflict.

### Correct historical records

Pending input errors are patched. A terminal report is corrected by recording an explicit replacement report. A verified financial error is corrected through FIN-001 void-and-replace plus the report replacement rule; neither module deletes or rewrites its source history. An evidence-only mistake is corrected by linking the right file and archiving the wrong FILE-001 link with a reason.

## API contract

All endpoints require a ready workspace; mutations require the writer lock. Requests forbid unknown fields, use typed UUIDs, strict booleans, strict positive integer cents, aware timestamps, and exact enums. Application commands repeat essential validation.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/owner-rent-reports` | Record one pending owner report, optionally replacing a terminal report. |
| `GET` | `/api/owner-rent-reports` | Return a bounded cursor page filtered by owner, property, space, lease, receipt date range, status, evidence presence, and linked-receipt lifecycle. |
| `GET` | `/api/owner-rent-reports/{reportId}` | Return the report, evidence summaries, current owner state, verification, replacement context, and linked receipt/allocation summary. |
| `PATCH` | `/api/owner-rent-reports/{reportId}` | Change only a pending report. |
| `POST` | `/api/owner-rent-reports/{reportId}/verify` | Explicitly verify and atomically adopt or create the FIN-001 receipt. |
| `POST` | `/api/owner-rent-reports/{reportId}/reject` | Explicitly reject a pending report without creating income. |

The create response may be returned before evidence exists and clearly shows `pending`. Verification accepts a tagged existing-receipt or create-receipt choice; it must not infer which candidate the operator intended. Receipt creation includes a separate FIN-001 idempotency key and the allocation set, while claimed payment-method facts come from the report.

Malformed requests return `422`; missing report, lease, owner, receipt, or expectation returns `404`; invalid dates, unsafe method data, or missing evidence returns `400`; stale lifecycle, ownership mismatch, incompatible receipt, possible duplicate, changed idempotency payload, over-allocation, replacement, and concurrency conflicts return typed `409` with stable codes and bounded candidate identifiers where applicable.

## Read semantics and downstream accounting

List and detail responses expose both report status and linked receipt state. `financiallyEffective` is true only when the report is verified and its exact linked receipt is currently active. This is a convenience projection, not a separately stored balance.

FIN-003 continues to aggregate income from active FIN-001 receipts only; it does not sum owner reports. Later OWNER-002 may use a verified, financially effective report to identify rent already held directly by a client owner when calculating operator-held funds and proposed disbursements. OWNER-001 may show the report and evidence as provenance while sourcing money totals from Finance.

A FIN-001 receipt with `received_by_party_id` but without a verified OWNER-003 link is not silently classified as verified owner-reported rent. It remains a Finance receipt that may need owner-report review.

## Audit, privacy, schema, and portability

Audit entity types are `owner_rent_report` and `owner_rent_report_operation`. Create, patch, verify, reject, and report replacement changes are fail-closed on audit. Verification-created `rent_receipt` and `rent_receipt_allocation` events use the same correlation ID as the report verification event.

General activity may show report lifecycle, property context, claimed receipt date, evidence count, and whether a Finance receipt was linked. It must redact amount, owner/lease/receipt/expectation identifiers, method label/reference, source note, review note, idempotency keys, file identifiers, and allocation detail. Contextual owner-accounting history may display permitted details to the local operator. File content remains protected by FILE-001 retrieval rules and encrypted archives.

The current greenfield baseline, SQLAlchemy models, owner-accounting exact schema/data validator, product-table allowlist, audit-policy registry, FILE-001 target registration, archive validator, and encrypted backup/export/restore coverage must include reports, operations, file links, receipt links, correction lineage, and correlated audit evidence. Retained-data validation rejects invalid lifecycle pairs, missing/mismatched receipts, duplicate links, broken report or receipt replacement chains, missing terminal audits, and verified reports that never had valid evidence/verification history.

Restore validates stored historical consistency. It does not re-evaluate whether a Party is still active or still owns the property today. No compatibility tables, nullable adoption state, dual reads/writes, or inferred legacy owner reports are added.

## Implementation outline

1. Implement the authoritative decisions below without reopening receipt ownership, evidence, correction, UI, or migration scope implicitly during schema work.
2. Add the `owner-accounting` module, report/operation domain values, persistence, application ports, service, typed routes, audit policies, exact schema/data validation, and tests.
3. Add the smallest neutral Finance receipt-context/transaction-operations extension, reusing FIN-001's existing transaction-scoped receipt policy and current connection.
4. Compose existing Portfolio, Party, File, Finance, and Audit boundaries at bootstrap; add an owner-accounting FILE-001 validator for `owner_rent_report`.
5. Extend the current greenfield baseline, product allowlist, archive validation, backup/restore validation, and audit registry without compatibility paths.
6. Add query-budget tests and regression coverage for owner/date eligibility, method snapshots, evidence, adoption/creation, duplicate prevention, allocation concurrency, idempotency, rejection, correction lineage, receipt void/replacement, file archival guards, privacy, tampered schema/data, and backup/restore.
7. Deliver the operator workflow through `UI-001`; do not add React work before that item.

## Backend acceptance criteria

OWNER-003 backend/API scope is complete when:

1. The operator can record one client-owner's direct-rent report with who reported it, when, how funds were received, exact USD amount/date, lease/property context, and evidence.
2. Pending and rejected reports never affect income, expectations, balances, statements, or disbursements.
3. Verification requires evidence and an explicit human decision and atomically links exactly one compatible active FIN-001 receipt.
4. Verification can adopt an existing receipt or create one through Finance without bypassing receipt/allocation, payment-method, idempotency, duplicate, or concurrency rules.
5. The same reported money cannot create duplicate income or be linked to two owner reports.
6. Historical client-owner eligibility and identity snapshots preserve truthful past reports without inventing ownership percentages or legal entitlement.
7. Pending corrections, terminal replacement lineage, FIN-001 void/replacement history, and FILE-001 link archival retain full history without destructive edits.
8. List/detail reads are bounded and set-based, and downstream consumers derive money only from active FIN-001 receipts.
9. General audit presentation redacts financial and identity-sensitive data while contextual history retains authorized provenance.
10. Exact schema/data validation and encrypted backup/restore preserve reports, operations, evidence, receipt/allocation links, replacement chains, and correlated audits.

The overall feature remains incomplete until its operator workflow is delivered through the agreed UI backlog scope.

## Contradictions and decisions required before implementation

The following contradictions or missing decisions were found by comparing the backlog, architecture, product brief, dependent designs, and current implementation. The decisions below are now authoritative for OWNER-003 implementation.

### 1. OWNER-003 omits FIN-006 even though every receipt now requires it

The OWNER-003 backlog lists FIN-001 but not FIN-006. The current FIN-001 command and schema require an immutable actual payment-method snapshot, and the product brief explicitly says an owner report records how the owner received the funds.

Decision: add completed `FIN-006` as a direct dependency. Store the claimed safe method on the report and require the linked FIN-001 snapshot to match. Do not add `unknown`, credentials, or raw payment numbers implicitly.

### 2. “Link the verified report to its FIN-001 receipt” does not say who creates the receipt

Requiring the operator to leave OWNER-003, create a receipt separately, and return to link it creates a partial workflow and a duplicate-income race. Letting owner-accounting insert Finance rows directly breaks module ownership.

Decision: verification must explicitly select a compatible existing receipt or atomically create one through a small Finance-owned transaction operation using the same SQLite transaction and correlation ID.

### 3. Ordinary FIN-001 duplicate override conflicts with OWNER-003's stated purpose

FIN-001 permits a confirmed independent receipt when amount/date/lease/recipient match. OWNER-003 specifically exists to prevent an owner report from duplicating already recorded income.

Decision: OWNER-003 must never expose the independent-duplicate override. Return matching candidates and require adoption or prior Finance correction.

### 4. Evidence requirements and archival behavior are unspecified

The backlog says “attach supporting evidence” but does not say whether evidence is mandatory for verification, which purposes are allowed, or whether the last file can later be archived.

Decision: allow report creation without evidence for retryability; require at least one active available link plus explicit confirmation/note at verification; cap active links at twenty; and prevent archival of the last active evidence for a verified report.

### 5. Owner eligibility date and later archival are unspecified

Current Portfolio relationships are effective-dated. Requiring current ownership would prevent late entry of a truthful past receipt, while accepting any Party would misattribute funds.

Decision: require that the selected Party was a `client_owner` of the lease property on `received_on`. Preserve the display snapshot, allow later party/ownership archival, and surface current state as context rather than rewriting history.

### 6. Local-operator and mixed-property behavior is ambiguous

PORT-001 represents the local operator without a Party ID, but FIN-001 uses a null recipient for local-operator receipt. Mixed properties can contain both local-operator and client-owner relationships.

Decision: OWNER-003 applies only to a specifically selected client-owner Party. Record local-operator receipts directly in FIN-001 and do not synthesize an owner Party or infer a recipient from mixed ownership.

### 7. One report may be confused with an owner statement total

The backlog does not say whether one report can aggregate payments, leases, or owners. FIN-001 receipts each have one lease, date, amount, recipient, and allocation set.

Decision: one report equals one actual receipt for one lease and one owner. Record statement line items separately. Defer joint-receipt splits and ownership-share allocation until a concrete owner-accounting design exists.

### 8. Correction semantics across owner-accounting and Finance are missing

A linked FIN-001 receipt can be voided and replaced, but the backlog does not say whether the owner report changes, relinks, or disappears. Silent relinking would destroy provenance.

Decision: keep terminal reports immutable; show a voided linked receipt as financially ineffective; use nonbranching report replacement lineage; and require a replacement verified report to link the corresponding FIN-001 replacement receipt. Pending reports remain patchable.

### 9. Downstream balance semantics are not stated

OWNER-002 depends on OWNER-003, but the backlog does not explain how a verified direct receipt affects later disbursement calculations. Summing the report and receipt would double income; ignoring custody would overstate funds held by the operator.

Decision: FIN-001 remains the only income source. A verified active report classifies the linked receipt as funds already received by that client owner for future owner-balance/disbursement calculations; OWNER-003 itself calculates no balance.

### 10. Direct owner submission is out of scope but not explicit in the item

The future `INTAKE-001` and `PORTAL-002` items own direct submissions and authentication. The MVP product brief says the local operator records or approves owner-provided facts.

Decision: OWNER-003 is manual local operator intake only. Add no login, external actor, inbox, delivery, or portal concepts.

### 11. UI-001 omits OWNER-003

Architecture defers all React work to UI-001, but UI-001's outcome and dependencies enumerate other completed backend workflows and omit OWNER-003. No later pre-dashboard UI item provides the owner-report review workflow.

Decision: add OWNER-003 to UI-001's outcome and dependencies and deliver pending intake, evidence, duplicate resolution, verification/rejection, and linked-receipt drill-down there. Keep OWNER-003 backend status in progress until that UI exists.

### 12. DASH-001 promises “owner actions” without an OWNER dependency

Pending owner reports requiring evidence or verification are natural owner actions, yet DASH-001 depends on UI-001 and Finance/Maintenance/Lead items only.

Decision: the initial owner-actions card includes pending owner-report evidence and verification review. Add OWNER-003 as a direct DASH-001 dependency.

### 13. Schema adoption is not stated

The repository uses one current greenfield baseline and no customer workspace migration framework.

Decision: update the baseline and rebuild development workspaces/fixtures. No customer workspace migration is required. Do not add compatibility columns, inferred reports, dual-read/write paths, or a migration solely for repository-local data.

## Dependencies and follow-on work

OWNER-003 directly requires completed `AUDIT-001`, `FILE-001`, `PORT-001`, `FIN-001`, and `FIN-006`. It consumes lease, Party, and property facts through implemented source-owned application boundaries rather than taking persistence ownership.

Follow-on ownership remains:

- `UI-001` — operator intake, evidence, verification/rejection, duplicate resolution, correction, and receipt drill-down.
- `DASH-001` — pending owner-report evidence and verification action cards.
- `FIN-003` — portfolio/property financial aggregation from Finance facts only.
- `OWNER-002` — owner-held/operator-held balance and manual disbursement calculations using verified provenance.
- `OWNER-001` — owner statements with source-record drill-down.
- `OWNER-005` — management-fee agreements and calculations.
- `INTAKE-001` — authenticated or externally sourced direct owner/tenant report intake without redefining OWNER-003 verification.
- `PORTAL-002` — authenticated owner access.
