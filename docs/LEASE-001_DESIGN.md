# LEASE-001 — Lease Records and Occupancy Integration

## Purpose

`LEASE-001` records the agreed lease for one rentable space: its parties, dates, initial financial terms, renewal options, and supporting documents. It makes a signed or executed lease the authoritative source for the lease-owned occupancy period created by `PORT-003`.

The feature serves both residential homes and office spaces for independent landlords and property managers. It records operational facts; it does not provide legal advice, calculate jurisdictional notice requirements, collect payments, or decide applicant eligibility.

## Delivery scope

LEASE-001 has two explicitly separate scopes:

| Scope | Contents | Delivery timing |
| --- | --- | --- |
| Backend and API | Current-schema records, business rules, typed local API, audit history, backup/restore validation, and lease-to-occupancy integration. | LEASE-001 implementation. |
| Operator UI | Lease list and detail screens, lease timeline, participant and term forms, document panel, renewal prompts, and guided execute/end workflows. | Delivered by `UI-001`, immediately before `DASH-001`. |

The backend/API scope may be verified independently, but LEASE-001 remains **In progress** until the operator UI is delivered.

## Scope and boundaries

LEASE-001 provides:

- One lease for one active rentable space, whether a residential whole home, office whole space, or office suite.
- Residential and commercial lease classification.
- Draft, execution, active/scheduled occupancy, end, termination, and void workflows.
- A reasoned early-termination request, review, proposal, acceptance, and completion workflow that does not mark a still-occupied space vacant.
- Effective-dated initial rent terms, currency, payment frequency, due-day convention, and agreed security deposit.
- Lease-owned participant roles using tenant-ready shared parties from `TEN-001`.
- Operator-entered renewal-option and notice-date records.
- Links to locally managed files from `FILE-001`.
- Lease milestones and stable references used by `INSP-001` for pre-move-in and post-move-out condition reports.
- Atomic, correlated audit events and lease-source occupancy transitions.

LEASE-001 does not provide:

- Rent receivables, receipts, balances, payment methods, late fees, owner disbursements, or accounting. These belong to `FIN-001` and later finance work.
- Rent increase calculations, jurisdictional legality checks, or statutory notice deadlines. `ADJ-001`, `ADJ-002`, and `JUR-001` own those workflows.
- Applications, screening, approval, negotiation, e-signature, listing, showing, or lead workflows.
- Automated document drafting or contract review; those are later document and AI backlog items.
- Multi-space leases, apartment units, CAM/operating-expense allocations, percentage rent, or complex commercial schedules. These are future extensions.
- Automatic availability changes. A lease may own occupancy, but `PORT-003` availability stays a separate explicit operational intention.
- Space-condition observations, walkthrough evidence, or deposit-settlement decisions. `INSP-001` owns condition reports, while `FIN-008` owns financial settlement.
- Legal conclusions about whether job relocation or another circumstance creates a right to terminate. The workflow records facts, lease-clause references, proposals, and operator decisions without providing legal advice.

## Core decisions

### Lease and tenant participation are separate

`TEN-001` owns the tenant-ready contact profile. `LEASE-001` owns the relationship between a lease and that profile's party ID, including lease role, dates, and lease-specific notes. This prevents copying contact data or treating a tenant profile as proof of occupancy.

### One lease owns one space

Every lease references exactly one `spaces.id`. The initial product intentionally models a residential home or each rentable office/suite as its own leaseable space. A future apartment or composite-commercial feature may introduce a lease-to-many-spaces association without changing the meaning of an existing lease.

### Execution is distinct from present occupancy

An executed lease can begin in the future. Its contract is already recorded, but its lease-source occupancy period is scheduled and does not change today's displayed occupancy until `occupancy_starts_on` arrives. API responses derive `occupancy_state` (`scheduled`, `current`, or `ended`) from effective dates rather than mutating a lease merely because a day has passed.

### Lease-owned status records cannot be silently edited manually

Executing a lease creates a `PORT-003` occupancy period with `source_kind = lease` and `source_id = leases.id`. A normal manual occupancy route must reject edits, cancellation, or replacement that conflicts with an active or scheduled lease-owned period. Lease lifecycle actions own their corresponding source transitions.

## Data model

All IDs are UUIDs. Timestamps are UTC text. Dates are local calendar dates for the property and never inferred from a timestamp. Monetary values use integer minor units. Currency codes use exactly three ASCII uppercase letters (`A`–`Z`); this is deterministic ISO-style syntax validation, not a claim that the application maintains a live ISO 4217 registry.

### `leases`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID primary key. |
| `space_id` | Required foreign key to an active `spaces` record. |
| `lease_kind` | Required enum: `residential` or `commercial`. |
| `status` | Required enum: `draft`, `executed`, `ended`, `terminated`, or `void`. |
| `contract_starts_on`, `contract_ends_on` | Required start; optional end. If present, end is later than start. |
| `occupancy_starts_on` | Required effective date for the lease-owned occupancy period; it cannot precede the contract start. |
| `executed_on` | Required on transition to `executed`; otherwise null. |
| `actual_move_out_on` | Required when ended or terminated; null for draft, executed, and void. |
| `end_reason` | Required enum for ended/terminated: `contract_completed`, `early_termination`, `mutual_termination`, or `other`; null otherwise. |
| `notes` | Optional internal context, capped at 4,000 characters. |
| `created_at`, `updated_at` | Required UTC timestamps. |

For termination-case completion, the case governs the lease category: a `mutual` case produces `mutual_termination`, an `other` case produces `other`, and every other accepted case produces `early_termination`. The case's own reason remains the detailed stated reason. An `ended` lease always uses `contract_completed`; a `terminated` lease never does.

Lease records are lifecycle records, not soft-deleted data. `void` preserves an executed-but-never-effective agreement; it does not erase it.

An accepted early-termination agreement does not immediately change the lease from `executed` to `terminated`. The lease remains executed, and its lease-owned occupancy remains current, until actual move-out is confirmed. This keeps contractual planning separate from truthful occupancy.

### `lease_term_versions`

| Field | Rules and meaning |
| --- | --- |
| `id`, `lease_id` | Stable UUID and required lease reference. |
| `effective_on`, `ends_on` | Non-overlapping effective range within the lease contract. Initial terms begin on the contract start. |
| `base_rent_minor`, `currency_code` | Required positive amount and exactly three ASCII uppercase currency letters. A zero-rent agreement cannot produce FIN-001 expectations and is rejected rather than represented as recurring rent. |
| `payment_frequency` | Required enum: `monthly` or `weekly`. More complex commercial schedules are deferred. |
| `payment_due_day` | Optional day `1`–`31`; it is meaningful only for monthly terms. |
| `agreed_security_deposit_minor` | Required non-negative agreed deposit amount; this is not proof of receipt or a ledger balance. |
| `created_at` | Required UTC timestamp. |

Creating a lease requires one initial term version. Draft terms may be replaced before execution. After execution, LEASE-001 does not revise financial terms; a later amendment/rent-adjustment workflow owns subsequent versions.

Application commands and database constraints both enforce positive base rent and the ASCII currency syntax. Booleans, floats, numeric strings, zero, and negative base-rent inputs are invalid. Security deposits and optional termination fees remain non-negative because zero has a distinct valid meaning for those fields.

### `lease_participants`

| Field | Rules and meaning |
| --- | --- |
| `id`, `lease_id` | Stable UUID and required lease reference. |
| `tenant_party_id` | Required reference to an active `tenant_profiles.party_id`. |
| `participant_role` | `primary_tenant`, `co_tenant`, `guarantor`, or `business_signatory`. |
| `starts_on`, `ends_on` | Participant-effective range within the contract range. |
| `notes` | Optional lease-specific context, not a contact profile. |
| `created_at`, `updated_at` | Required UTC timestamps. |

A residential lease requires one active `primary_tenant` on execution. A commercial lease requires one active `business_signatory` on execution. A party cannot be an overlapping active participant twice on the same lease. Guarantors are participants, not occupants, and do not affect the space occupancy record.

### `lease_renewal_options`

| Field | Rules and meaning |
| --- | --- |
| `id`, `lease_id` | Stable UUID and required lease reference. |
| `status` | `open`, `exercised`, `declined`, `expired`, or `withdrawn`. |
| `proposed_starts_on`, `proposed_ends_on` | Required proposed lease range; end is optional and must follow start when present. |
| `notice_due_on`, `response_due_on` | Optional operator-entered dates. They are not legal calculations. |
| `decided_on`, `notes` | Optional decision date and internal context. |
| `created_at`, `updated_at` | Required UTC timestamps. |

Exercising an option does not silently alter a lease. A later renewal/amendment workflow creates the resulting contractual record after the operator confirms it.

### `lease_termination_cases`

An early-termination case records the request and agreement process separately from the lease's final lifecycle transition.

| Field | Rules and meaning |
| --- | --- |
| `id`, `lease_id` | Stable UUID and required reference to one executed lease. |
| `status` | `requested`, `under_review`, `proposed`, `accepted`, `withdrawn`, `declined`, or `completed`. |
| `reason` | Tenant-stated reason: `job_relocation`, `military`, `habitability`, `mutual`, or `other`. This is recorded context, not a legal conclusion. |
| `notice_received_on` | Required local date on which the operator received the request or notice. |
| `requested_termination_on`, `expected_move_out_on` | Tenant-requested dates; either may be revised only through an audited proposal or correction. |
| `agreed_termination_on` | Required when the case is accepted or completed. |
| `accepted_on`, `completed_on` | Lifecycle dates consistent with case status. Completion requires confirmed lease termination and actual move-out. |
| `tenant_explanation` | Optional bounded factual explanation supplied by the tenant. |
| `contract_clause_reference` | Optional operator-entered lease section or clause reference. It is not a legal determination. |
| `operator_notes` | Optional bounded review context. |
| `created_at`, `updated_at` | Required UTC timestamps. |

Only one nonterminal termination case may exist for a lease. Opening or accepting a case does not change lease status, end the occupied period, or infer availability.

### `lease_termination_proposals`

| Field | Rules and meaning |
| --- | --- |
| `id`, `termination_case_id` | Stable UUID and required case reference. |
| `proposal_version` | Monotonically increasing version within the case. Prior proposals are retained. |
| `proposed_termination_on`, `expected_move_out_on` | Required proposed dates. |
| `rent_responsibility_ends_on` | Optional contractual input for the later finance workflow. |
| `termination_fee_minor`, `currency_code`, `fee_waived` | Optional proposed amount and waiver decision; these do not create a receivable or payment. |
| `replacement_tenant_condition`, `access_arrangement`, `other_terms` | Optional bounded plain-language terms. |
| `response_due_on` | Optional operator-entered deadline; no statutory deadline is inferred. |
| `status`, `decided_on` | `open`, `accepted`, `rejected`, `countered`, `withdrawn`, or `expired`, with a consistent decision date. |
| `created_at` | Required UTC timestamp. |

Proposal and counterproposal history is append-preserving. Accepting a proposal updates the termination case in the same transaction but does not post charges, waive balances, or close the lease.

### Documents

Documents remain `FILE-001` managed files. LEASE-001 adds typed `file_links` for the lease or termination case. Lease purposes include `executed_lease`, `addendum`, `renewal_offer`, and `supporting_document`; termination-case purposes include `termination_request`, `relocation_support`, `termination_proposal`, `signed_termination_agreement`, and `supporting_document`. Supporting material is optional and may contain sensitive employment information, so generalized activity never exposes its contents or filenames. Detaching a link preserves the underlying file and its audit history.

## Lifecycle and occupancy rules

| Action | Lease effect | Occupancy effect |
| --- | --- | --- |
| Create draft | Creates editable lease, initial terms, and participants. | None. |
| Execute | Records `executed_on`; freezes the LEASE-001 draft structure. | Creates a lease-source `occupied` period beginning `occupancy_starts_on`; it is current or scheduled by date. |
| End | Requires confirmed actual move-out. | Ends the lease-source occupied period and creates a lease-source `vacant` period from move-out date. |
| Request early termination | Opens a termination case while the lease remains executed. | None. The space remains occupied. |
| Accept termination agreement | Records the accepted proposal and agreed dates while the lease remains executed. | None. The space remains occupied until actual move-out. |
| Terminate | Requires an accepted termination case, confirmed actual move-out, and a termination reason. | Ends the lease-source occupied period and creates a lease-source `vacant` period from actual move-out. |
| Void | Allowed only before occupancy has begun. | Cancels the scheduled lease-source period; no vacant period is inferred. |

Execution is rejected unless all of these are true in one immediate transaction:

- The property and space are active, and the space is rentable.
- The required initial terms and participant role for the lease kind exist.
- Every participant has an active tenant profile.
- The new occupied period does not overlap another valid current or scheduled occupancy period for the space.
- The current/scheduled `PORT-003` timeline is compatible with lease source ownership. A manual period may be replaced only through the explicit execution transition. A lease-owned vacant period may also be closed or superseded when its owning lease is already ended or terminated; an occupied period owned by another active lease remains a conflict. Every replacement retains an audited prior/current timeline snapshot.

Ending, terminating, and voiding must reject a conflict if the lease's own source period is missing or has been superseded by an unsupported source. LEASE-001 never guesses an actual move-out date from the contract end date.

### Early termination for job relocation

1. Record the tenant's request, notice-received date, requested termination date, expected move-out date, explanation, and any voluntarily supplied supporting document.
2. Review the lease clause and operator-entered notice, fee, continuing-rent, replacement-tenant, and access considerations. The application presents these as review inputs and does not decide legal entitlement.
3. Record each proposal or counterproposal as a retained version, including proposed dates, financial inputs, response deadline, and conditions.
4. Accept, decline, withdraw, or continue negotiation. Acceptance records the agreement and exposes reminders for final payment review, marketing access, keys, and the post-move-out walkthrough; it does not mark the space vacant.
5. Optionally begin listing preparation and showing coordination through the owning marketing workflow, subject to the accepted access arrangement. Availability remains an explicit `PORT-003` operational intention.
6. On actual move-out, explicitly complete termination. In one transaction, set the lease to `terminated`, preserve lifecycle category `early_termination` plus stated reason `job_relocation`, close the lease-owned occupied period, create the vacant period, and complete the termination case.
7. Prompt for the `INSP-001` post-move-out report. Later finance workflows calculate outstanding rent or approved fees, and `FIN-008` separately handles deposit settlement.

Withdrawal or rejection leaves the executed lease and occupancy unchanged. If the parties agree to dates but the tenant does not move out as expected, the case remains accepted and visibly overdue; the system does not falsify actual move-out or vacancy.

An executed lease with a current or future occupancy period blocks archiving its space, property, and active/scheduled participant tenant profile. A future implementation may introduce a guided amendment workflow for participant changes; LEASE-001 limits ordinary participant and term edits to `draft` leases so it does not rewrite executed history.

The lease detail exposes condition-report attention states supplied by `INSP-001`: pre-move-in due before or on occupancy and post-move-out due after confirmed move-out. A missing report is a visible prompt, not a reason to prevent the operator from recording truthful execution, occupancy, termination, or move-out facts.

## API contract

All routes require a ready workspace. Request models forbid unknown fields; application commands independently validate the same rules. Responses use explicit Pydantic models and stable identifiers.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/leases` | Create a draft lease with initial term and participants atomically. |
| `GET` | `/api/leases` | List leases by property, space, tenant, lifecycle state, `contractStartFrom`/`contractStartTo`, and `renewalDueOnOrBefore` across open notice or response deadlines. |
| `GET` | `/api/leases/{leaseId}` | Return lease detail, effective terms, participants, renewal options, document links, and derived occupancy state. |
| `PATCH` | `/api/leases/{leaseId}` | Update allowed draft identity/date/note fields only. |
| `PUT` | `/api/leases/{leaseId}/initial-term` | Replace the one draft initial term. |
| `POST` | `/api/leases/{leaseId}/participants` | Add a draft participant. |
| `PATCH` | `/api/leases/{leaseId}/participants/{participantId}` | Edit a draft participant. |
| `DELETE` | `/api/leases/{leaseId}/participants/{participantId}` | Remove a draft participant. |
| `POST` | `/api/leases/{leaseId}/execute` | Explicitly execute the contract and create the lease-source occupancy period. |
| `POST` | `/api/leases/{leaseId}/end` | Confirm move-out and end the lease. |
| `POST` | `/api/leases/{leaseId}/terminate` | Confirm early termination and move-out. |
| `POST` | `/api/leases/{leaseId}/void` | Void a not-yet-effective executed lease with confirmation. |
| `POST` | `/api/leases/{leaseId}/renewal-options` | Record an operator-entered renewal option. |
| `PATCH` | `/api/leases/{leaseId}/renewal-options/{optionId}` | Update or decide a renewal option. |
| `POST` | `/api/leases/{leaseId}/termination-cases` | Record an early-termination request without changing occupancy. |
| `GET` | `/api/leases/{leaseId}/termination-cases` | Return request, review, proposal, decision, and completion history. |
| `PATCH` | `/api/termination-cases/{caseId}` | Update allowed review facts or make a controlled case-status transition. |
| `POST` | `/api/termination-cases/{caseId}/proposals` | Append a proposal or counterproposal version. |
| `POST` | `/api/termination-cases/{caseId}/accept` | Accept one open proposal with explicit confirmation. |
| `POST` | `/api/termination-cases/{caseId}/complete` | Confirm actual move-out and atomically complete the case and lease termination. |

File upload and link operations remain the generic `FILE-001` API; the lease detail response exposes linked file metadata. Errors distinguish malformed data (`422`), missing resources (`404`), invalid lifecycle/data rules (`400`), and source, overlap, archive, or concurrent-transition conflicts (`409`).

## Audit, privacy, backup, and export

Every mutation persists data rows and required audit events in one immediate transaction. A business action that changes a lease, term, participants, and occupancy timeline uses one generated correlation ID.

Audit entity types include `lease`, `lease_term`, `lease_participant`, `lease_renewal_option`, `lease_termination_case`, and `lease_termination_proposal`; an execution/end/termination action also records the corresponding `space_occupancy_period` change. Snapshots include stable IDs, statuses, dates, amounts, currency, roles, and source ownership needed to explain the action. They exclude contact-method values, document bytes, file content, sensitive employment-document metadata, and secrets. A proposal acceptance and final termination each use one correlation ID across every related record.

The current exact schema validator, encrypted backup/export inventory, restore validation, and audit presentation registry must include all LEASE-001 tables and policies. Backup/restore regression tests must prove that lease terms, participant links, lifecycle records, document links, occupancy-source records, and their audit history round-trip together.

## Required integration changes to the existing foundation

The first LEASE-001 implementation slice must include these existing-module integrations. They are part of LEASE-001 acceptance, not optional cleanup or separate prerequisite backlog items.

1. **Add one lease transaction boundary.** Create a lease-specific unit of work that loads and writes leases, terms, participants, lease-owned occupancy periods, and audit events in one immediate transaction. Validate tenant-profile availability through TEN-001's transaction-aware application port within that transaction; do not load or write tenant persistence types directly. The application service must not implement execution, ending, termination, or voiding by calling tenant and portfolio services sequentially after either service has committed.
2. **Add the tenant lease-participation archive guard.** Supply TEN-001's application-level lease-participation guard so an active tenant profile cannot be archived while it has current or future participation on an `executed` lease. A participant on an editable draft does not block tenant archival; execution revalidates every participant profile. The check and archive mutation use the same transaction, and TEN-001 does not import lease persistence types.
3. **Add lease-owned occupancy operations.** Lease execution and lifecycle closure must create, end, cancel, or replace `PORT-003` periods using `source_kind = lease` and `source_id = lease_id`. Existing manual occupancy operations continue to reject edits to those source-owned periods; the lease workflow is the only normal owner of their lifecycle.
4. **Extend all current-format boundaries.** Add the lease tables to the greenfield Alembic baseline and extend module-owned exact schema validation, the application-table allowlist, encrypted backup/export and restore validation, and the audit presentation-policy registry for every lease entity and event type.
5. **Add lease-aware archive regression coverage.** Verify that active and scheduled executed leases prevent space and property archival through their occupancy records, and that current or future participants on executed leases prevent tenant-profile archival while draft participants do not. Also verify that execution revalidates archived profiles and that ending, terminating, or voiding a lease releases only the appropriate guard without weakening unrelated occupancy or participant history.
6. **Harden FIN-001 source terms.** Require positive integer base rent and exactly three ASCII uppercase currency letters in the HTTP model, direct application command, SQLAlchemy constraints, greenfield baseline, and exact-schema validator. Regression tests must reject booleans, floats, numeric strings, zero/negative rent, lowercase codes, non-ASCII letters, digits, and punctuation.

Because the product remains greenfield and latest-format-only, introducing the lease schema requires recreating the configured development workspace from the updated current baseline; no legacy adoption or upgrade path is added.

## Implementation outline

1. Add lease models and the current schema definitions directly to the greenfield Alembic baseline, plus module-owned exact schema validation.
2. Add lease domain commands and a transaction-oriented unit-of-work port; compose the SQLite implementation only at the application bootstrap.
3. Implement draft creation and editing, then lifecycle transitions together with `PORT-003` source-owned occupancy writes.
4. Implement participants, initial terms, renewal options, early-termination cases and versioned proposals, file links, typed query/detail responses, and archive guards.
5. Register audit presentation policies and extend current-schema, encrypted backup/export, and restore validation.
6. Expose stable lease milestones and links for the separately owned `INSP-001` condition-report workflow.
7. Add the deferred React operator workflow without changing the backend contract.

## Acceptance criteria

LEASE-001 is complete when:

1. An operator can record residential or commercial draft leases for one active rentable space with initial terms and the required participant role.
2. Executing, ending, terminating, and voiding a lease create only valid lease-owned occupancy timeline changes and never infer availability; requesting or accepting an early termination does not end truthful occupancy.
3. Current and future lease occupancy is conflict-checked against valid space history, and manual routes cannot overwrite lease-owned records.
4. Lease participants reuse active tenant profiles without duplicating shared identity or contact data, and active/scheduled relationships enforce archive guards.
5. Terms, deposits, dates, renewal options, document links, and lifecycle state are audit-backed and survive encrypted backup/export/restore.
6. The API has explicit request/response contracts and controlled `400`, `404`, `409`, and `422` behavior.
7. The UI provides the deferred operator workflows before the backlog item is marked done.
8. An operator can record and negotiate a job-relocation termination request, retain proposal history, accept an agreement without premature vacancy, and complete it only with confirmed actual move-out.
9. Every term exposed to FIN-001 has positive integer base rent and deterministic three-ASCII-uppercase-letter currency syntax enforced at both application and database boundaries.

## Dependencies and follow-on work

LEASE-001 uses `FILE-001` for document links, `PORT-002` for rentable spaces, `PORT-003`'s backend occupancy source model, and `TEN-001` for participant-ready profiles. `AUDIT-001` is required for the ledger behavior described here. LEASE-001 deliberately precedes `INSP-001`: it supplies the lease/space relationship and the dates that place pre-move-in and post-move-out reports in context.

It is a direct prerequisite for condition inspections (`INSP-001`), rent expectations and payments (`FIN-001`), payment-method tracking (`FIN-006`), rent-review and adjustment workflows (`ADJ-001` and `ADJ-002`), jurisdictional notice rules (`JUR-001`), document intelligence (`DOC-001` and `DOC-AI-002`), e-signature (`SIGN-001`), commercial extensions (`OFFICE-001`), data import (`DATA-001`), and tenant portal access (`PORTAL-001`). `FIN-008` follows both the lease and inspection records and owns any security-deposit refund or deduction decision.
