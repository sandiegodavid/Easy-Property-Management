# FIN-009 — Late fees

Status: **Complete — Slices 1–6 implemented and validated (November 27, 2026)** (aligned with [FEATURE_BACKLOG.md](../FEATURE_BACKLOG.md#now--hosted-mvp-then-tenant-and-owner-portals), [PORTALS_IMPLEMENTATION_PLAN.md](PORTALS_IMPLEMENTATION_PLAN.md#fin-009--shared-late-fee-prerequisite), [PAY-001_DESIGN.md](PAY-001_DESIGN.md#late-fee-integration-for-portal-acceptance), [Finance module guide](../modules/finance.md), [Operator experience](../ui/operator-experience.md), and [Frontend architecture](../ui/frontend-architecture.md)).

Hard dependencies: `AUDIT-001`, `LEASE-001`, `FIN-001`, `FIN-006` (all `✅ Done`).
Downstream consumers: `PORTAL-001` (Tenant portal), `PORTAL-002` (Owner portal), and `PAY-001` (Hosted tenant payments late-fee integration).

---

## 1. Purpose, boundaries, and non-goals

`FIN-009` delivers source-owned, operator-confirmed lease late-fee policies, deterministic property-zone calculation previews, explicit operator assessment/waiver/correction workflows, separate late-fee receipt and reporting accounting, shared read contracts for operator/tenant/owner views, and typed integration contracts for `PAY-001` collection.

### Core invariants

1. **No invented defaults and no legal inference:** A lease has no late-fee policy until the operator explicitly configures and confirms one citing its contractual basis (e.g., lease section or addendum). EPM ships no default late-fee rates, infers no statutory caps or holiday grace extensions, and never claims legal eligibility.
2. **A preview is not debt:** Calculation previews are read-only, deterministic quotes bound to an explicit property-local `asOfDate`, captured UTC `asOf`, and `rentLedgerRevision`. Previews create no charges, liabilities, or audit entries.
3. **Policy-confirmed automatic assessment with lease-level and per-occurrence waivers (no automatic debit):** Once an operator explicitly configures and confirms a lease late-fee policy, write-authorized catch-up (`POST /api/late-fees/sync`, scoped to `leaseId`, `propertyId`, or `rentExpectationId`, plus workspace startup) automatically assesses eligible overdue rent periods past the property-local grace boundary (including bounded daily accrual up to policy caps/max days) and commits them atomically through the lease `rent_ledger` command ledger (`auto_assess_late_fees`, advancing `rentLedgerRevision` on effective writes). Read endpoints (`GET`) remain strictly read-only. Operators can waive late fees either **at the lease level** (`late_fee_lease_waivers`, pausing future auto-assessments with a recorded reason and optional all-or-nothing bulk waiver of currently unpaid fees that rejects on processing-payment reservations; revoking resumes only future periods/days while permanently excluding the waived interval) or **per occurrence** (partial or full waiver, stopping further daily accrual for that period). Auto-assessment skips periods with processing payments, voided unreplaced assessments, existing waivers, or delinquency created by a voided/returned timely rent receipt (`D9`). Overdue rent never triggers automatic tenant debit.
4. **Immutable historical authority:** Policy versions and assessed charges are immutable once committed. Later policy versions never rewrite prior assessments; each assessment freezes its policy version ID and complete step-by-step calculation snapshot.
5. **Strict financial separation:** Rent, assessed late fees, and security deposits remain distinct across obligations, allocations, receipts, reporting (`FIN-003`), and payment previews. Recipient-paid payment-processing fees (`FIN-002` / `PAY-001`) are never late fees.
6. **Single source of truth across portals:** Operator, `PORTAL-001`, and `PORTAL-002` consume the same Finance-owned assessed charge and calculation-breakdown read contracts. Portals have zero assessment, waiver, or policy-editing power.

### Explicit non-goals

- External cron-driven billing or silent automatic tenant debits (auto-assessment runs lazily on workspace open and Finance reads only under an explicitly confirmed lease policy, and never debits a tenant).
- Jurisdiction/state statutory late-fee rulebooks, legal-holiday calendars, or compliance certification.
- Interest compounding on unpaid late fees, NSF/returned-check fee schedules, and arbitrary miscellaneous lease charges (tracked separately in [`FIN-010`](../FEATURE_BACKLOG.md#now--hosted-mvp-then-tenant-and-owner-portals), requiring its own design).
- Live payment processor execution (owned by `PAY-001`; `FIN-009` defines the Finance-side contracts `PAY-001` will consume).
- Multi-currency support (USD integer cents only, matching `FIN-001`/`FIN-002`/`FIN-008`).

---

## 2. Accepted design decisions (November 26, 2026)

| ID | Decision | Rationale |
| --- | --- | --- |
| **D1** | **Shared Lease `rent_ledger` revision scope:** Late-fee policy versions, assessments, waivers, void/replace corrections, and late-fee receipts share `finance_command_revisions` (`scope_kind = 'rent_ledger'`, `scope_id = lease_id`) and `finance_command_operations`. | Rent receipts, prepaid checks, late-fee assessments, waivers, and future `PAY-001` reservations mutate overlapping lease-level financial invariants. One lease-scoped optimistic concurrency boundary prevents race conditions without introducing cross-aggregate locking. |
| **D2** | **Immutable effective-dated policy versions:** Policies are stored in `late_fee_policy_versions` with `[effective_on, ends_on)` property-local date windows (exclusive `ends_on`, matching `lease_term_versions`). Active windows on the same lease cannot overlap. | Preserves exact historical terms for past rent periods and matches `LEASE-001` effective-dating conventions. |
| **D3** | **Closed, bounded formula catalog:** Support four deterministic formulas: `fixed_flat`, `percentage_once`, `daily_flat`, and `fixed_plus_daily_flat`, paired with explicit `calculation_basis` (`unpaid_rent_at_grace_end`, `current_unpaid_rent`, `scheduled_rent`) and `rounding_mode` (`half_up`, `floor`). | Covers real residential and commercial US lease clauses without arbitrary expression scripting, hidden defaults, or ambiguous rounding. |
| **D4** | **Mandatory accrual bound on daily formulas:** `daily_flat` and `fixed_plus_daily_flat` require at least one of `per_period_cap_minor` or `max_accrual_days` (`1..365`). | Prevents unbounded runaway fee calculations while preserving operator flexibility. |
| **D5** | **Grace boundary uses property-local calendar days:** Grace covers `due_on` through `grace_ends_on = due_on + grace_period_days` inclusive. First eligible fee date is `first_eligible_on = grace_ends_on + 1 day` in the Property's canonical US IANA time zone. | Matches `PRODUCT_BRIEF.md` property-zone date rules and avoids browser-local midnight drift or inferred legal-holiday rules. |
| **D6** | **Explicit occurrence identity and daily non-overlap:** One-time formulas permit at most one active (non-voided) assessment per `rent_expectation_id` (`occurrence_number = 1`). Daily formulas allow incremental assessments (`occurrence_number = 1, 2, ...`) covering strictly disjoint, advancing date ranges `[accrual_starts_on, accrual_ends_on]`, bounded cumulatively by `per_period_cap_minor` and `max_accrual_days`. | Guarantees idempotency per `(rent_expectation_id, occurrence_number)` and prevents charging any delinquent calendar day twice. |
| **D7** | **Exact server-calculated assessment + explicit partial/full waivers:** Assessment commits the exact server-calculated `calculated_amount_minor` verified by `preview_fingerprint`. Courtesy reductions use explicit append-only `late_fee_waivers` (full or partial, with required reason); errors use void-and-replace. | Keeps the published calculation breakdown 100% faithful to the lease policy while giving operators clear, auditable relief and correction paths. |
| **D8** | **Separate `late_fee_receipts` and `late_fee_receipt_allocations`:** Late-fee payments are recorded in dedicated tables mirroring `FIN-001`/`FIN-006` receipt contracts, rather than mixing fee dollars into `rent_receipts.amount_minor`. Combined rent + late-fee payments create both receipts atomically in one transaction linked by a shared `payment_batch_id`. | Guarantees zero contamination of `FIN-001` rent receipts, `FIN-003` Rent received, `FIN-007` prepaid checks, and `OWNER-003` owner-reported rent verification while supporting real-world single-check combined payments. |
| **D9** | **No silent mutations on retroactive changes:** Returned/voided rent receipts never auto-assess fees; backdated/later rent receipts never auto-void assessed fees (instead surfacing `sourceDriftWarning`). Voiding a `rent_expectation` with active late-fee assessments is blocked (`409`) until those assessments are explicitly waived or voided. | Preserves operator authority, financial auditability, and referential integrity across corrections. |
| **D10** | **Explicit `PAY-001` allocation order and opt-in autopay consent:** Combined tenant payments allocate **oldest eligible unpaid rent first, then oldest eligible unpaid assessed late fees**, disclosed line-by-line before authorization. Rent-only autopay mandates (`rent_only`) never debit assessed late fees; including fees requires explicit opt-in (`rent_and_assessed_late_fees`) still bounded by the tenant's fixed monthly cap. | Prevents silent fee collection under rent-only consent and aligns with `PAY-001_DESIGN.md` and `PORTALS_IMPLEMENTATION_PLAN.md`. |
| **D11** | **Scoped shared read port (`LateFeeReadPort`):** Finance exposes one consumer-neutral read contract with projection scopes (`operator`, `tenant`, `owner`). Tenant and owner projections return assessed charges only, excluding unassessed previews, internal operator notes, and cotenant private payment details. | Ensures identical cents, dates, and math across all portals without leaking operator internals or private party data. |
| **D12** | **Separate `FIN-003` reporting line item:** `MoneySummaryService` adds `lateFeesReceivedMinor` (and count/drill-down) alongside `rentReceivedMinor`, preserving `rentLessNetExpensesMinor` unchanged and keeping rent, late fees, expenses, and deposits distinct. | Satisfies strict financial category separation and existing `FIN-003` contract stability. |
| **D13** | **`fixed_plus_daily_flat` day-1 convention:** Applies `flat_amount_minor` on `first_eligible_on` and `daily_amount_minor` for each subsequent delinquent day (`max(0, eligible_days - 1)`); no separate day-1 overlap toggle. | Matches standard residential/commercial lease wording and keeps day counts unambiguous in step-by-step calculation breakdowns. |
| **D14** | **Future-date preview horizon vs strict assessment date:** Read-only previews accept `asOfDate` up to `current_property_local_date + 31 days` (badged `future_projection: true`), while assessment strictly requires `asOfDate <= current_property_local_date`. | Supports operator planning without ever permitting speculative future-dated debt creation. |
| **D15** | **Combined manual receipt UI placement:** Extend the existing **Record rent receipt** workflow with an optional **"Include assessed late fees"** section alongside standalone **Record late-fee payment**, rather than adding a separate top-level screen. | Matches operator workflow for single-check combined payments while preserving clean navigation and strict rent/fee separation. |

---

## 3. Domain model and calculation rules

### 3.1 Policy version contract (`late_fee_policy_versions`)

A lease policy version belongs to one non-void `lease_id` and records:

- **Identity & lineage:** `id` (UUID), `lease_id` (FK `leases.id`), `version_number` (positive int, sequential per lease), `supersedes_policy_version_id` (nullable FK self, unique when set).
- **Effective window:** `effective_on` (property-local `YYYY-MM-DD`), `ends_on` (nullable exclusive `YYYY-MM-DD`, `ends_on > effective_on`).
- **Contractual basis & confirmation:**
  - `lease_term_id` (optional FK `lease_term_versions.id` belonging to the same lease),
  - `rule_basis` (required trimmed 1–500 chars; e.g., `"Lease Section 5(b), signed 2026-01-15"`),
  - `operator_confirmed_at` (required UTC timestamp), `operator_confirmed_by_actor` (immutable actor snapshot),
  - `notes` (optional trimmed 1–1,000 chars; operator-internal only, excluded from tenant/owner portals).
- **Rules & bounds:**
  - `grace_period_days`: integer `0..60`.
  - `calculation_basis`: `'unpaid_rent_at_grace_end' | 'current_unpaid_rent' | 'scheduled_rent'`.
  - `formula_kind`: `'fixed_flat' | 'percentage_once' | 'daily_flat' | 'fixed_plus_daily_flat'`.
  - `flat_amount_minor`: positive int `1..9_999_999_999` (required for `fixed_flat` and `fixed_plus_daily_flat`; `NULL` otherwise).
  - `percentage_bps`: integer `1..10_000` (0.01% to 100.00%; required for `percentage_once`; `NULL` otherwise).
  - `daily_amount_minor`: positive int `1..9_999_999_999` (required for `daily_flat` and `fixed_plus_daily_flat`; `NULL` otherwise).
  - `max_accrual_days`: optional int `1..365` (allowed only for `daily_flat` and `fixed_plus_daily_flat`).
  - `per_period_cap_minor`: optional positive int `1..9_999_999_999`. For `daily_flat` and `fixed_plus_daily_flat`, at least one of `per_period_cap_minor` or `max_accrual_days` MUST be set.
  - `per_period_min_minor`: optional positive int `1..9_999_999_999`; if `per_period_cap_minor` is also set, `per_period_min_minor <= per_period_cap_minor`.
  - `minimum_unpaid_threshold_minor`: integer `>= 0` (default `0`). If eligible unpaid rent is `< minimum_unpaid_threshold_minor` (or `<= 0`), calculated fee is `0`.
  - `rounding_mode`: `'half_up' | 'floor'` (required; no implicit default).
  - `applies_to_prorated_periods`: boolean (`0 | 1`, required; no implicit default).
- **Lifecycle:** `status` in `('active', 'superseded', 'voided')`, plus `voided_at` / `void_reason` when `voided`.
  - **Void guard:** A policy version referenced by any non-voided `late_fee_assessments` row cannot be voided (`409`). To change rules going forward, the operator creates a new effective-dated version (superseding the prior version by setting its `ends_on` to the new version's `effective_on` atomically).

### 3.2 Deterministic calculation engine (preview & assessment verification)

Given `(lease_id, rent_expectation_id, as_of_date)` inside a single consistent read/write transaction:

1. **Resolve Property time zone & dates:**
   - Read the Property's canonical US IANA time zone via Portfolio port.
   - Previews accept an explicit ISO calendar `as_of_date` up to `current_property_local_date + 31 days` (badged `future_projection: true` when `as_of_date > current_property_local_date`, per **D14**); assessments strictly require `as_of_date <= current_property_local_date`.
2. **Validate expectation & policy applicability:**
   - Expectation must belong to `lease_id` and be active (`voided_at IS NULL`).
   - Find the active policy version where `effective_on <= expectation.due_on AND (ends_on IS NULL OR expectation.due_on < ends_on)`. If none exists, return `eligibilityStatus = "no_applicable_policy"`.
   - If `expectation.is_prorated == True` and `policy.applies_to_prorated_periods == False`, return `eligibilityStatus = "excluded_prorated_period"`.
3. **Compute grace boundary:**
   - `grace_ends_on = expectation.due_on + timedelta(days=policy.grace_period_days)`
   - `first_eligible_on = grace_ends_on + timedelta(days=1)`
   - If `as_of_date < first_eligible_on`, return `eligibilityStatus = "within_grace_period"` with `calculatedAmountMinor = 0`.
4. **Compute rent receipt facts (active non-voided `rent_receipts` only):**
   - `paid_through_grace_minor`: sum of active `rent_receipt_allocations.amount_minor` for `expectation_id` where `rent_receipts.voided_at IS NULL AND rent_receipts.received_on <= grace_ends_on`.
   - `paid_after_grace_through_as_of_minor`: sum where `rent_receipts.voided_at IS NULL AND grace_ends_on < rent_receipts.received_on <= as_of_date`.
   - `unpaid_at_grace_end_minor = max(0, expected_amount_minor - paid_through_grace_minor)`.
   - `unpaid_as_of_date_minor = max(0, expected_amount_minor - paid_through_grace_minor - paid_after_grace_through_as_of_minor)`.
5. **Determine eligibility & calculation basis amount:**
   - Check delinquency gate:
     - For `unpaid_rent_at_grace_end`: gate amount is `unpaid_at_grace_end_minor`.
     - For `current_unpaid_rent`: gate amount is `unpaid_as_of_date_minor`.
     - For `scheduled_rent`: gate amount is `unpaid_at_grace_end_minor` (positive unpaid rent remaining past the grace boundary) and `basis_amount_minor = expected_amount_minor`.
   - If `gate_amount_minor == 0`: return `eligibilityStatus = "paid_in_full"` with `calculatedAmountMinor = 0`.
   - If `gate_amount_minor < policy.minimum_unpaid_threshold_minor`: return `eligibilityStatus = "below_minimum_threshold"` with `calculatedAmountMinor = 0`.
   - Set `basis_amount_minor`:
     - `unpaid_rent_at_grace_end` → `unpaid_at_grace_end_minor`
     - `current_unpaid_rent` → `unpaid_as_of_date_minor`
     - `scheduled_rent` → `expected_amount_minor`
6. **Check existing non-voided assessments on this expectation:**
   - Load all active (`voided_at IS NULL`) `late_fee_assessments` for `expectation_id`, ordered by `occurrence_number`.
   - `previously_assessed_minor = sum(a.assessed_amount_minor for a in active_assessments)` (note: waived amounts still count toward `per_period_cap_minor`? Yes — `assessed_amount_minor` tracks assessed charges against the period cap so waiving a fee doesn't unexpectedly re-trigger another charge for the same period!).
   - **One-time formulas (`fixed_flat`, `percentage_once`):**
     - If any active assessment exists, return `eligibilityStatus = "already_assessed"` with `calculatedAmountMinor = 0`.
     - Otherwise `occurrence_number = 1`, `accrual_starts_on = first_eligible_on`, `accrual_ends_on = first_eligible_on`.
   - **Daily formulas (`daily_flat`, `fixed_plus_daily_flat`):**
     - Determine `accrual_starts_on`:
       - If no active assessment exists: `accrual_starts_on = first_eligible_on`, `occurrence_number = 1`.
       - If prior active assessments exist: `accrual_starts_on = max(a.accrual_ends_on) + 1 day`, `occurrence_number = max(a.occurrence_number) + 1`.
     - If `accrual_starts_on > as_of_date`, return `eligibilityStatus = "already_assessed_through_date"` with `calculatedAmountMinor = 0`.
     - Compute `raw_days = (as_of_date - accrual_starts_on).days + 1` (inclusive).
     - Enforce `max_accrual_days` cumulatively across prior occurrences (`prior_days_assessed = sum(a.accrual_days)`):
       - `eligible_days = min(raw_days, max(0, max_accrual_days - prior_days_assessed))` if `max_accrual_days` is set, else `raw_days`.
     - If `eligible_days == 0`, return `eligibilityStatus = "max_accrual_days_reached"` with `calculatedAmountMinor = 0`.
     - `accrual_ends_on = accrual_starts_on + timedelta(days=eligible_days - 1)`.
7. **Exact integer arithmetic (zero floating point):**
   - `fixed_flat`: `raw_minor = policy.flat_amount_minor`.
   - `percentage_once`:
     - Exact rational: `numerator = basis_amount_minor * policy.percentage_bps`, `denominator = 10_000`.
     - If `rounding_mode == 'half_up'`: `raw_minor = (numerator + 5_000) // 10_000`.
     - If `rounding_mode == 'floor'`: `raw_minor = numerator // 10_000`.
   - `daily_flat`: `raw_minor = policy.daily_amount_minor * eligible_days`.
   - `fixed_plus_daily_flat`:
     - If `occurrence_number == 1`: `initial_minor = policy.flat_amount_minor`, `daily_days = max(0, eligible_days - 1)`, `raw_minor = initial_minor + policy.daily_amount_minor * daily_days`.
     - If `occurrence_number > 1`: `raw_minor = policy.daily_amount_minor * eligible_days`.
8. **Apply floor (`per_period_min_minor`) and cap (`per_period_cap_minor`):**
   - Apply minimum (only on `occurrence_number == 1` when `raw_minor > 0`): `after_min = max(raw_minor, policy.per_period_min_minor)` if set else `raw_minor`.
   - Apply cumulative per-period cap:
     - If `policy.per_period_cap_minor` is set: `remaining_cap = max(0, policy.per_period_cap_minor - previously_assessed_minor)`; `final_minor = min(after_min, remaining_cap)`.
     - If `final_minor == 0` because cap was already reached, return `eligibilityStatus = "period_cap_reached"`.
9. **Surface non-blocking payment warnings (never counted as paid):**
   - Query active `scheduled` `FIN-007` prepaid checks for `expectation_id` → `scheduledPrepaidChecks` (count, total minor, check dates).
   - Query `PendingPaymentReader` port (implemented as empty no-op until `PAY-001` delivers live reservations) → `processingPayments` (count, total minor, earliest submitted date).
   - If `processingPayments.count > 0`, preview sets `requiresProcessingAcknowledgment = true`.
10. **Emit step-by-step calculation breakdown & `previewFingerprint`:**
    - Ordered array of structured `calculationSteps` (step code, plain-language label, exact inputs, exact intermediate minor value, formula expression) so UI and portals render the exact same math without recomputing in JavaScript.
    - `previewFingerprint` = lowercase SHA-256 of canonical JSON of `{leaseId, rentExpectationId, policyVersionId, asOfDate, occurrenceNumber, accrualStartsOn, accrualEndsOn, rentLedgerRevision, calculatedAmountMinor, calculationSnapshot}`.

### 3.3 Edge-case treatment summary

| Scenario | Deterministic FIN-009 behavior |
| --- | --- |
| **Partial payment before grace end** | Reduces `unpaid_at_grace_end_minor` and `unpaid_as_of_date_minor`. Shown explicitly in preview breakdown. |
| **Partial or full payment after grace end** | Shown separately as `paidAfterGraceThroughAsOfMinor`. `unpaid_rent_at_grace_end` still sees the grace-end delinquency; `current_unpaid_rent` uses the remaining unpaid balance as of `as_of_date`. |
| **Scheduled prepaid check (`FIN-007`)** | Not received income; does not reduce unpaid rent. Preview surfaces a visible warning with check date and amount before assessment. |
| **Processing bank payment (`PAY-001`)** | Not received income; does not reduce unpaid rent. Preview surfaces processing amount/date and requires explicit operator acknowledgment (`acknowledgeProcessingPayments: true` + reason) to assess while processing. |
| **Returned / voided rent payment** | Restores unpaid rent on the expectation. Never auto-creates a late fee; becomes eligible on the next operator preview. |
| **Backdated / post-assessment rent receipt** | Never silently deletes or alters an assessed fee. Read models compute `sourceDriftWarning: true` comparing frozen `calculation_snapshot` paid totals against current active allocations, prompting operator review (keep, waive, or void-and-replace). |
| **Policy version superseded** | Never alters existing assessments. New policy applies only to expectations whose `due_on` falls in its effective window. |
| **Voiding a rent expectation** | Blocked (`409`, `expectation_has_active_late_fees`) while any non-voided late-fee assessment exists for that expectation. |
| **Voiding an assessed late fee** | Blocked (`409`, `late_fee_has_active_receipts`) while active `late_fee_receipt_allocations` or live `PAY-001` reservations reference it. |

---

## 4. Persistence and schema design (greenfield SQLite)

All tables belong to the **Operator business SQLite** store, defined exclusively in `application/database/sqlite-migrations/versions/0001_initial_schema.py` and reflected in `application/apps/server/app/modules/finance/infrastructure/sqlalchemy_models.py` (greenfield latest schema; no legacy migration compatibility).

### 4.1 Tables

1. **`late_fee_policy_versions`**
   - Columns: `id` (PK UUID), `lease_id` (FK `leases.id`), `lease_term_id` (nullable FK `lease_term_versions.id`), `version_number` (INT >= 1), `effective_on` (ISO date), `ends_on` (nullable ISO date), `rule_basis` (TEXT 1..500), `grace_period_days` (INT 0..60), `calculation_basis` (`'unpaid_rent_at_grace_end' | 'current_unpaid_rent' | 'scheduled_rent'`), `formula_kind` (`'fixed_flat' | 'percentage_once' | 'daily_flat' | 'fixed_plus_daily_flat'`), `flat_amount_minor` (nullable INT > 0), `percentage_bps` (nullable INT 1..10000), `daily_amount_minor` (nullable INT > 0), `max_accrual_days` (nullable INT 1..365), `per_period_cap_minor` (nullable INT > 0), `per_period_min_minor` (nullable INT > 0), `minimum_unpaid_threshold_minor` (INT >= 0), `rounding_mode` (`'half_up' | 'floor'`), `applies_to_prorated_periods` (INT 0|1), `status` (`'active' | 'superseded' | 'voided'`), `supersedes_policy_version_id` (nullable FK self, UNIQUE), `notes` (nullable TEXT 1..1000), `operator_confirmed_at` (TEXT UTC), `operator_confirmed_by_actor` (TEXT), `voided_at` (nullable TEXT UTC), `void_reason` (nullable TEXT 1..1000), `created_at` (TEXT UTC).
   - Constraints & indexes:
     - `UNIQUE (lease_id, version_number)`
     - Check constraints enforcing formula-specific required/null columns, `per_period_min_minor <= per_period_cap_minor`, daily bound (`per_period_cap_minor IS NOT NULL OR max_accrual_days IS NOT NULL`), `ends_on IS NULL OR ends_on > effective_on`, and `voided` paired fields.
     - `INDEX late_fee_policies_lease_effective (lease_id, status, effective_on, ends_on)`.

2. **`late_fee_assessments`**
   - Columns: `id` (PK UUID), `lease_id` (FK `leases.id`), `rent_expectation_id` (FK `rent_expectations.id`), `policy_version_id` (FK `late_fee_policy_versions.id`), `occurrence_number` (INT >= 1), `as_of_date` (ISO date), `accrual_starts_on` (ISO date), `accrual_ends_on` (ISO date), `accrual_days` (INT >= 1), `assessed_amount_minor` (INT > 0), `currency_code` (`'USD'`), `time_zone` (TEXT, frozen Property IANA zone), `rule_basis_snapshot` (TEXT 1..500), `calculation_snapshot_json` (TEXT, schema-validated bounded JSON <= 16 KiB containing inputs, dates, paid/unpaid figures, and step-by-step math), `calculation_snapshot_hash` (64-char hex SHA-256), `processing_acknowledged` (INT 0|1), `processing_acknowledgment_reason` (nullable TEXT 1..1000), `internal_notes` (nullable TEXT 1..1000), `replaces_assessment_id` (nullable FK self, UNIQUE), `voided_at` (nullable TEXT UTC), `void_reason` (nullable TEXT 1..1000), `assessed_at` (TEXT UTC), `assessed_by_actor` (TEXT).
   - Constraints & indexes:
     - Partial unique index `late_fee_assessments_one_active_occurrence ON (rent_expectation_id, occurrence_number) WHERE voided_at IS NULL`.
     - `INDEX late_fee_assessments_lease_date (lease_id, voided_at, as_of_date, id)`.
     - `INDEX late_fee_assessments_expectation (rent_expectation_id, voided_at, occurrence_number)`.
     - Immutability trigger: `BEFORE UPDATE` permits modifying ONLY `voided_at` and `void_reason` (once, from `NULL` to non-`NULL`); `BEFORE DELETE` aborts.

3. **`late_fee_waivers`** (append-only)
   - Columns: `id` (PK UUID), `assessment_id` (FK `late_fee_assessments.id`), `lease_id` (FK `leases.id`), `waived_amount_minor` (INT > 0), `currency_code` (`'USD'`), `reason` (TEXT 1..1000; visible to tenant/owner), `internal_notes` (nullable TEXT 1..1000; operator-only), `waived_on` (property-local ISO date), `waived_at` (TEXT UTC), `waived_by_actor` (TEXT).
   - Constraints & indexes:
     - `INDEX late_fee_waivers_assessment (assessment_id, waived_at, id)`.
     - Append-only triggers (`BEFORE UPDATE` / `BEFORE DELETE` abort).

4. **`late_fee_receipts`**
   - Mirrors `rent_receipts` (`id`, `lease_id`, `idempotency_key` UNIQUE, `payment_batch_id` nullable UUID, `received_on`, `amount_minor` > 0, `currency_code = 'USD'`, `FIN-006` actual payment method fields `payment_method_kind`, `payment_method_label`, `masked_reference`, `other_payment_method_note`, `received_by_party_id`, `replaces_receipt_id` UNIQUE, `notes`, `voided_at`, `void_reason`, `created_at`).
   - Indexes: `late_fee_receipts_lease_received (lease_id, received_on)`, `late_fee_receipts_lifecycle_received (voided_at, received_on, lease_id, id)`.

5. **`late_fee_receipt_allocations`**
   - Columns: `id` (PK UUID), `receipt_id` (FK `late_fee_receipts.id`), `assessment_id` (FK `late_fee_assessments.id`), `amount_minor` (INT > 0), `created_at` (TEXT UTC).
   - Constraints & indexes:
     - `UNIQUE (receipt_id, assessment_id)`
     - `INDEX late_fee_receipt_allocations_assessment (assessment_id)`.

6. **Existing table alignment:**
   - `rent_receipts` adds optional nullable `payment_batch_id` (UUID) solely to correlate combined manual or `PAY-001` rent + late-fee payments recorded atomically in one transaction.
   - `finance_command_revisions` and `finance_command_operations` require **zero new scope kinds** (all `FIN-009` writes use `scope_kind = 'rent_ledger'`, `scope_id = lease_id`).

---

## 5. API contracts and shared application ports

### 5.1 Operator HTTP API (FastAPI / generated OpenAPI contracts)

Operator-initiated mutations require client-supplied `expectedRevision` (Lease `rent_ledger` revision) and `idempotencyKey` (UUID), write immutable results to `finance_command_operations`, and support recovery via existing `GET /api/finance/operations/by-key/{key}`. Write-authorized automatic catch-up (`POST /api/late-fees/sync`, plus workspace startup) derives each targeted lease's current `rent_ledger` revision and deterministic UUIDv5 command identity on the server, committing effective auto-assessments (`auto_assess_late_fees`) atomically with correlated audit events while leaving `rentLedgerRevision` unchanged on no-op retries. All `GET` routes remain strictly read-only.

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/leases/{leaseId}/late-fee-policies` | `GET` | List policy versions for a lease (active first, then historical/voided) with `rentLedgerRevision`. |
| `/api/leases/{leaseId}/late-fee-policies` | `POST` | Create and confirm a new effective-dated policy version (optionally superseding an existing active version atomically). |
| `/api/leases/{leaseId}/late-fee-policies/{policyVersionId}/void` | `POST` | Void an unused policy version (`confirmed: true`, `reason`). |
| `/api/leases/{leaseId}/late-fee-waiver` | `GET` | Read current active lease-level waiver and revocation history with `rentLedgerRevision`. |
| `/api/leases/{leaseId}/late-fee-waiver` | `POST` | Create an active lease-level waiver pausing automatic assessment (`reason`, `confirmed: true`, optional all-or-nothing `waiveOpenAssessments: true` which rejects on processing reservations). |
| `/api/leases/{leaseId}/late-fee-waiver/revoke` | `POST` | Revoke the active lease-level waiver (`reason`, `confirmed: true`), resuming automatic assessment only for future periods/days while permanently excluding the waived interval. |
| `/api/late-fees/sync` | `POST` | Write-authorized idempotent automatic assessment catch-up, optionally scoped to `leaseId`, `propertyId`, or `rentExpectationId`. Admitted under hosted write authorization (`records.write` + CSRF). |
| `/api/leases/{leaseId}/late-fees/preview` | `POST` | Read-only deterministic preview for one `rentExpectationId` or all eligible open expectations on the lease at an explicit `asOfDate`. Returns step-by-step math, payment warnings, and `previewFingerprint`. |
| `/api/leases/{leaseId}/late-fee-assessments` | `POST` | Explicitly assess one verified preview (`previewFingerprint`, `operatorConfirmed: true`, optional `acknowledgeProcessingPayments` + reason). |
| `/api/leases/{leaseId}/late-fee-assessments` | `GET` | Strictly read-only bounded cursor list of assessed late fees for a lease (filterable by settlement/voided status). |
| `/api/late-fee-assessments` | `GET` | Strictly read-only portfolio-wide bounded cursor queue (default 50 / max 100) for Money → Late fees and Rent due, filterable by Property, Lease, `rentExpectationId`, settlement status, and voided visibility. |
| `/api/late-fee-assessments/{assessmentId}` | `GET` | Full assessment detail: frozen breakdown, waivers, fee allocations, `sourceDriftWarning`, replacement lineage, and `rentLedgerRevision`. |
| `/api/late-fee-assessments/{assessmentId}/waive` | `POST` | Append a full or partial waiver (`waivedAmountMinor`, `waivedOn`, `reason`, `confirmed: true`). |
| `/api/late-fee-assessments/{assessmentId}/void` | `POST` | Void an unpaid assessment (`reason`, `confirmed: true`; blocked if active receipts or reservations exist). |
| `/api/leases/{leaseId}/late-fee-receipts` | `POST` | Record a manual standalone late-fee receipt (with `FIN-006` actual method and explicit assessment allocations). |
| `/api/leases/{leaseId}/combined-receipts` | `POST` | Atomically record a single manual payment split across `rentAllocations` and `lateFeeAllocations` (creates one `rent_receipt` + one `late_fee_receipt` sharing `payment_batch_id`). |
| `/api/late-fee-receipts/{receiptId}/void` | `POST` | Void a late-fee receipt (`reason`, `confirmed: true`). |

Error mapping follows [api-contracts.md](../platform/api-contracts.md): `422` invalid formula/dates/bounds, `413` oversized text/notes, `404` missing lease/expectation/assessment, `409` stale revision, preview fingerprint mismatch, overlapping policy dates, already assessed, expectation/assessment protected by active children, or idempotency-key payload conflict.

### 5.2 Shared read contract for portals (`LateFeeReadPort`)

Finance exposes a transaction-aware application port consumed by Operator views, `PORTAL-001`, and `PORTAL-002`:

- `list_assessed_late_fees_for_lease(session, *, lease_id, scope: Literal["operator", "tenant", "owner"], as_of, include_voided=False, cursor=None, limit=50)`
- `get_assessed_late_fee(session, *, assessment_id, scope: Literal["operator", "tenant", "owner"], as_of)`

Projection rules by scope:
- **`operator`**: Full record including `internalNotes`, `processingAcknowledgmentReason`, `sourceDriftWarning`, voided/replacement history, and payer details.
- **`tenant`**: Active assessed charges only (`voided_at IS NULL`, plus previously-paid voided adjustments if needed for receipt history). Includes `assessedAmountMinor`, `waivedAmountMinor`, `paidAmountMinor`, `remainingBalanceMinor`, `ruleBasisSnapshot`, frozen `calculationSteps`, `timeZone`, `asOfDate`, public waiver `reason`s, and aggregate applied fee payments (masking cotenant private payment references). **Excludes** unassessed previews, `internalNotes`, and operator-only warnings.
- **`owner`**: Active assessed charges in authorized property scope. Includes full frozen `calculationSteps`, `ruleBasisSnapshot`, waivers, collected fee totals, and remaining balances. **Excludes** `internalNotes` and tenant private banking/method details.

### 5.3 `PAY-001` integration contracts (Finance-owned ports)

Before `PAY-001` or `PORTAL-001` collects late fees, Finance defines and tests these source-owned contracts:

1. **`PendingPaymentReader` (port into Finance):** Supplies active processing reservation totals per `rent_expectation_id` and per `late_fee_assessment_id` on the caller's transaction. Defaults to an empty no-op adapter until `PAY-001` is wired.
2. **Typed charge-allocation contract:**
   ```text
   ChargeAllocationTarget =
     | { chargeKind: "rent_expectation", targetId: UUID, amountMinor: int }
     | { chargeKind: "late_fee_assessment", targetId: UUID, amountMinor: int }
   ```
   - Allocation order helper in Finance: **oldest eligible unpaid `rent_expectation` (by `due_on`, `id`) first, then oldest eligible unpaid `late_fee_assessment` (by `as_of_date`, `assessed_at`, `id`)**.
   - Preview returns separate `rentTotalMinor`, `lateFeeTotalMinor`, `grossTotalMinor`, `allocationOrderExplanation`, and `rentLedgerRevision`.
3. **Reservation & race fencing:** `PAY-001` reservations and Finance manual writes (waivers, voids, manual fee receipts) coordinate through the same Lease `rent_ledger` revision and live reservation check, preventing a waiver or manual receipt from colliding silently with an in-flight bank payment.
4. **Atomic `apply_provider_payment_outcome` extension:** Accepts typed rent + fee allocation lines in one caller transaction; creates `rent_receipt` and/or `late_fee_receipt` linked by `payment_batch_id` and provider `payment_attempt_id`. If a targeted late fee was waived/voided before settlement (reducing remaining balance below the reserved amount), routes the excess cents to Finance's `unapplied_processor_funds` exception rather than failing or fabricating debt.
5. **Typed return & partial-refund correction contract:**
   - Bank return reverses the linked `rent_receipt` and/or `late_fee_receipt` atomically, restoring exact unpaid balances without auto-assessing any new fee.
   - Partial refund requires explicit `rentRefundMinor` and `lateFeeRefundMinor` attribution; refunding money never automatically waives the assessed fee.
6. **Autopay mandate scope contract:**
   - `mandateScope: "rent_only" | "rent_and_assessed_late_fees"`.
   - `rent_only` excludes all `late_fee_assessments` from scheduled occurrence calculation.
   - `rent_and_assessed_late_fees` includes eligible unpaid assessed late fees *after* eligible rent, strictly capped by the tenant's fixed monthly maximum (`max_amount_minor`), and requires explicit fresh tenant consent.

---

## 6. Operator UI and experience design

Follows [operator-experience.md](../ui/operator-experience.md) and [frontend-architecture.md](../ui/frontend-architecture.md). No new top-level sidebar destination is added.

### 6.1 Entry points and navigation

1. **Lease Detail → Late fees section:**
   - **Policy panel:** Shows current effective policy version (or explicit **"No late-fee policy configured"** empty state with **Configure late-fee policy** action), contractual `rule_basis`, dates, formula summary, and **Policy history** disclosure.
   - **Calculation preview & review panel:** Property-local `asOfDate` picker (defaults to property-local today), **Preview eligible late fees** button, and expandable rows for each eligible/ineligible open rent period. Each row shows the exact server-computed step-by-step math, payment breakdown, scheduled-check/processing warnings, and a prominent **"Preview only — not an assessed charge"** notice. Inside the expanded panel sits **Assess late fee**, which opens a confirmation dialog naming lease, period, amount, and policy version.
   - **Assessed late fees list:** Expandable summary bars (`Click anywhere on an item’s summary bar to expand or collapse its details.`) showing status badge + text (`Unpaid`, `Partially paid`, `Paid`, `Waived`, `Voided`), assessed/waived/paid/remaining amounts, frozen calculation breakdown, `sourceDriftWarning` banner when applicable, and History link.
2. **Money → Late fees view:**
   - Portfolio-wide bounded queue (default 50 / max 100) with Property, Lease, settlement status, and voided-history filters (auto-applying filters per `operator-experience.md`).
   - Actionable links to Lease Detail, Record fee payment, Waive, and Void & replace.
3. **Money → Record payment (standalone & combined):**
   - Existing **Record rent receipt** workflow gains an optional **"Include assessed late fees"** section when the lease has unpaid assessed late fees, clearly separating Rent subtotal, Late fee subtotal, and Total received (reusing `FIN-006` actual payment method & safe masked reference validation).
   - Standalone **Record late-fee payment** is also available directly from an expanded assessed late fee.
4. **Money → Reporting (`FIN-003`):**
   - Displays `Late fees received` as a distinct metric row with exact USD formatting and source drill-down to `late_fee_receipts`, separate from `Rent received` and `Security deposits`.

### 6.2 Forms, recovery, and accessibility

- All consequential mutations (Create policy, Void policy, Assess late fee, Waive late fee, Void assessment, Record late-fee/combined receipt) register with `OPS-001` recoverable forms: UUID idempotency key persisted before dispatch, `editing → submitting → committed | rejected | outcome_unknown`, and reconciliation via `GET /api/finance/operations/by-key/{key}` on lost response.
- Any input edit or stale `rentLedgerRevision` immediately invalidates an active calculation preview and requires a fresh server preview before **Assess late fee** is enabled.
- Failed reads show **Unavailable** / **Out of date** with retry — never `$0.00` or "No fees due".
- **WCAG 2.2 AA:** Semantic tables/disclosures, keyboard-only navigation, focus restoration on dialog close and local collapse, visible required/optional labels, error summaries linked to controls, Light/Dark CSS tokens, and responsive reflow at 390px, 900px, and 1440px (plus 200% zoom).

---

## 7. Query-budget and performance constraints

All reads execute under one deferred SQLite snapshot and one captured UTC `asOf`:

| Operation | Query ceiling | Structural guarantee |
| --- | --- | --- |
| Lease late-fee preview (up to 24 open periods) | ≤ 8 `SELECT`s | Set-based load of lease/property zone, active policies, expectations, preaggregated rent allocations, active prior assessments, scheduled checks, and pending reservations. Zero per-expectation queries. |
| Lease assessed late-fees list (50 rows) | ≤ 6 `SELECT`s | Preaggregated waivers and fee receipt allocations joined by `assessment_id`. Identical query count for 1 vs 50 rows. |
| Portfolio Money → Late fees queue (50 rows, cursor-paginated) | ≤ 6 `SELECT`s | Set-based filtered count + page hydration with 15-minute bound cursor (`asOf`, normalized filters, sort tie-breaker). |
| `FIN-003` Reporting with late fees | +1 `SELECT` over existing budget | Preaggregated `late_fee_receipts` grouped by property/period; no multiplicative join with `rent_receipts` or `expenses`. |

---

## 8. Ordered implementation slices

| Slice | Cohesive delivery | Acceptance gate |
| --- | --- | --- |
| **1** | **Schema & policy versioning:** Greenfield DDL (`0001_initial_schema.py`), SQLAlchemy models, immutable triggers, domain validators, policy create/supersede/void commands on `rent_ledger` revision, and API routes. | Policy validation, non-overlap, immutability, void-guard, idempotency, and schema/fingerprint checks pass. |
| **2** | **Deterministic preview engine:** Property-zone date math, partial/after-grace receipt math, 4 formula kinds, caps/min/rounding, `FIN-007` prepaid-check & `PendingPaymentReader` warnings, step-by-step breakdown, `previewFingerprint`, and `POST .../late-fees/preview`. | Exact integer-cent proofs across all formulas, DST/timezone boundaries, partial/returned payments, and ≤ 8 SELECT query-budget test. |
| **3** | **Assessment, waiver & correction lifecycle:** Explicit `assess`, append-only partial/full `waive`, `void` / `void-and-replace`, `sourceDriftWarning`, expectation-void protection, audit events, and command recovery. | Preview-fingerprint/revision fencing, unique occurrence enforcement, exact conservation, rollback atomicity, and audit/replay proofs. |
| **4** | **Late-fee receipts & `FIN-003` reporting:** Standalone `late_fee_receipts`, atomic combined rent+fee receipt command (`payment_batch_id`), receipt void/replace, and separate `lateFeesReceivedMinor` reporting + drill-down. | Zero contamination of `rent_receipts` / `FIN-003` rent totals, `FIN-006` masked-reference enforcement, and exact reporting drill-down. |
| **5** | **Shared portal read port & `PAY-001` contracts:** `LateFeeReadPort` (`operator`/`tenant`/`owner` projections), `PendingPaymentReader` reservation integration, typed charge-allocation ordering, `apply_provider_payment_outcome` fee support, return/refund attribution, and autopay mandate-scope guards. | Cross-scope privacy/redaction tests (no previews/internal notes to tenants/owners), waiver-vs-reservation race tests, and `rent_only` mandate fence tests. |
| **6** | **Operator UI & end-to-end acceptance:** Generated OpenAPI contracts, Lease policy/preview/assessment UI, Money → Late fees queue, standalone/combined fee payment, waive/void flows, Reporting row, OPS recovery, and browser/a11y/restart/restore proofs. | `npm run lint`, `format:check`, `typecheck`, `ruff`, focused Playwright browser tests (390/900/1440px, Light/Dark, keyboard), and `LOCAL-002` backup/restore proof. |

---

## 9. Validation matrix

| Area | Required test proof |
| --- | --- |
| **Happy paths** | Create/supersede effective-dated policies (all 4 formulas, `half_up`/`floor`, caps/min); preview & explicit assess in property zone; write-authorized `POST /api/late-fees/sync` automatic catch-up (scoped by `leaseId`/`propertyId`/`rentExpectationId`, cursor-paged past 500+ older candidates, advancing `rentLedgerRevision` via `auto_assess_late_fees` command ledger); partial & full per-occurrence waiver; lease-level waiver & revoke (permanently excluding pre-waiver/during-waiver one-time periods and waived daily intervals); standalone & combined rent+fee receipt; void-and-replace assessment & receipt; `FIN-003` separate `Late fees received` reporting & drill-down; identical assessed breakdown across `operator`/`tenant`/`owner` read projections. |
| **Automatic write boundary & hosted auth** | `GET /api/leases/{leaseId}/late-fee-assessments` and `GET /api/late-fee-assessments` perform zero writes (assessments and audit unchanged); hosted `POST /api/late-fees/sync` succeeds for admitted writers (`records.write` + CSRF) and rejects read-only callers (`403`); bulk lease-level waiver (`waiveOpenAssessments: true`) rejects atomically (`409`) when any open fee has a processing reservation; `D9` guard skips auto-assessment when a voided/returned receipt had prevented eligibility under either `unpaid_rent_at_grace_end` or `current_unpaid_rent`. |
| **Invalid combinations** | Missing `rule_basis` or unconfirmed policy; overlapping policy effective dates; invalid formula/field pairings; daily formula without cap or `max_accrual_days`; `per_period_min_minor > per_period_cap_minor`; future `asOfDate` assessment; assessment within grace period; prorated period excluded by policy; voiding policy/expectation/assessment with active dependent children; waiving more than unpaid remaining balance; stale `previewFingerprint` or `expectedRevision`; `rent_only` autopay mandate attempting to include late fees. |
| **Idempotency & retry** | Exact `idempotencyKey` replay on policy create, assess, waive, void, and fee receipt returns identical original response without duplicate charge/audit; changed payload under same key returns `409`; concurrent double-assess on same `(expectation, occurrence)` commits once and conflicts the second; lost response recovers via `/api/finance/operations/by-key/{key}`. |
| **Transaction rollback** | Fault injected during assessment insert, audit write, combined rent+fee receipt split, or `PAY-001` outcome application leaves zero partial charges, receipts, allocations, or revision increments. |
| **Persistence & schema** | `0001_initial_schema.py` matches SQLAlchemy metadata and workspace schema fingerprint; SQLite CHECK constraints, partial unique indexes, and immutability triggers reject direct tampering (`UPDATE`/`DELETE` on waivers/assessments); invalid `calculation_snapshot_json` rejected. |
| **Backup & restore** | `LOCAL-002` encrypted backup/restore preserves policy versions, frozen assessment snapshots, waivers, fee receipts, `payment_batch_id` links, command receipts, and audit history with stable UUIDs; runtime continuations invalidate cleanly. |
| **Query budget / N+1** | Automated SQL statement counter verifies preview ≤ 8 `SELECT`s and list/queue ≤ 6 `SELECT`s with identical query counts for 1 vs 50 rows; `FIN-003` reporting adds ≤ 1 `SELECT`. |
| **Browser & accessibility** | Packaged Playwright tests for policy setup, preview invalidation on edit, assessment confirmation, waive/void dialogs, combined receipt entry, `sourceDriftWarning` visibility, failed-read unavailable state (no false zero), Light/Dark themes, keyboard focus restoration, and 390px/900px/1440px reflow. |

---

## 10. Implementation status and checkpoint

All design decisions (`D1–D15`) and implementation slices (`1–6`) are complete. Consolidated delivery summary and validation results: [FIN-009_CHECKPOINT.md](FIN-009_CHECKPOINT.md).

| Slice | Status |
| --- | --- |
| Slice 1 — Schema & policy versioning | ✅ Done |
| Slice 2 — Deterministic preview engine | ✅ Done |
| Slice 3 — Assessment, waiver & correction lifecycle | ✅ Done |
| Slice 4 — Late-fee receipts & `FIN-003` reporting | ✅ Done |
| Slice 5 — Shared portal read port & `PAY-001` contracts | ✅ Done |
| Slice 6 — Operator UI & end-to-end acceptance | ✅ Done |
