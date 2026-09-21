# MAINT-001 — Repair Issues, Appointments, and Cost Context

## Purpose

`MAINT-001` establishes the maintenance aggregate for the local MVP. It lets the operator record a property or space issue, classify its urgency and lifecycle, schedule appointments, retain internal estimates and work-reported cost context, attach supporting files, create related follow-up tasks, and link confirmed spending without making Maintenance a second accounting system.

The boundary is deliberate:

- Maintenance owns the operational issue, its appointments, and non-financial cost context.
- Portfolio owns property and space identity, lifecycle, and time zone.
- Tasks owns follow-up lifecycle and reminders.
- Files owns file metadata, storage, and generic links.
- Finance owns confirmed expenses, refunds, correction history, and financial totals.

MAINT-001 is a backend/API slice. It does not implement React screens, provider quotes or assignment, reporter attribution, communication history, work journals, calendar synchronization, AI triage, or external intake.

## Scope

MAINT-001 provides:

- Property-level or space-level repair issues with a required category, priority, description, and explicit lifecycle.
- Property-local reported time and stable property/space references.
- Scheduled appointments with rescheduling, completion, and cancellation history.
- Operator-entered estimates and work-reported cost context that are explicitly not confirmed spending.
- Optional links from an issue to FIN-002 expenses; no financial amount is copied into maintenance storage.
- FILE-001 evidence for issues, appointments, and cost-context records through maintenance-owned link validation.
- Optional TASK-001 follow-ups linked to the issue.
- Typed APIs, atomic audit history, exact current-schema validation, bounded read projections, and encrypted backup/export/restore coverage.

MAINT-001 does not provide:

- Reporter identity or reporter role. `MAINT-004` owns owner, tenant, manager, and staff attribution.
- Provider quotes, quote comparison, provider selection, or assignment. `MAINT-002` owns those records.
- An append-only work journal or issue-backed provider outcome history. `MAINT-003` owns those facts; provider-facing views may compose a bounded Maintenance projection but never copy journal rows into Providers.
- Email, SMS, or calendar delivery/synchronization. `COM-002` and `COM-003` own connected delivery and calendars.
- Bills, payables, payment initiation, or recurring costs. Finance backlog items own those workflows.
- Automatic expense creation. The operator records confirmed spending through FIN-002 and then links the resulting expense.
- AI diagnosis, urgency decisions, duplicate detection, or provider recommendations. Later ISSUE-AI items create reviewed suggestions, not authoritative issue changes.
- React UI. `UI-001` owns the deferred MAINT-001 through MAINT-004 operator workflows.

## Core decisions

### The maintenance issue is the aggregate root

Appointments, cost-context records, expense links, evidence links, and maintenance-created follow-ups all relate to one stable maintenance issue ID. They do not independently change the issue lifecycle. The application service owns lifecycle policy and writes all same-operation maintenance rows and audit events in one immediate SQLite transaction.

An issue is never physically deleted through the product. Incorrect or duplicate issues are cancelled with a reason, preserving evidence and links for audit and future migration.

### Property is required and space is optional

Every issue belongs to exactly one property and may identify one space at that property. Normal creation requires an active property and, when supplied, an active space belonging to it. Existing issues remain readable and may be resolved or cancelled after the property or space is archived; archival does not rewrite history or cascade into maintenance.

The issue stores stable IDs rather than copied property or space records. Read projections use the existing transaction-aware `PortfolioContextReader`. Appointments retain the property's canonical IANA time zone as a schedule snapshot so a later address correction does not reinterpret an already recorded appointment.

### Category and priority are separate

`category` describes the kind of issue; `priority` describes how quickly the operator believes it needs attention. MAINT-001 uses a small fixed issue-category vocabulary:

- `plumbing`
- `electrical`
- `heating_cooling`
- `appliance`
- `structural`
- `safety_security`
- `pest`
- `exterior_grounds`
- `cleaning`
- `other`

`other` requires a bounded category detail. This taxonomy belongs to Maintenance and is not the same as provider service categories or Finance expense categories. `VEND-CAT-001` may later map provider categories to maintenance categories but must not silently reinterpret stored issue history.

Priority is `low`, `normal`, `high`, or `urgent`. `urgent` is an operator classification and a dashboard signal, not a claim that emergency services were contacted. The API never initiates contact or dispatch.

### Lifecycle is explicit and does not derive from child records

Issue status is one of:

- `open` — accepted as an official issue but work has not started.
- `in_progress` — operational work is underway.
- `resolved` — the operator confirms the issue is resolved.
- `cancelled` — the issue was entered in error, duplicated, or intentionally abandoned.

Allowed transitions are:

- `open` → `in_progress`, `resolved`, or `cancelled`
- `in_progress` → `open`, `resolved`, or `cancelled`
- `resolved` or `cancelled` → `open` through an explicit reopen action

Resolution requires a bounded resolution summary. Cancellation requires a reason. Reopen requires a reason and clears the terminal timestamp while retaining prior transitions in audit history. Resolving an issue is rejected while it has a scheduled future appointment; the operator must complete or cancel that appointment first.

Appointments, tasks, estimates, files, and expense links do not automatically start or resolve an issue. This avoids hidden transitions across module boundaries.

### Appointments are maintenance records, not calendar events

An appointment records a scheduled start and end, the property's time-zone snapshot, a purpose, optional access/instruction notes, and lifecycle `scheduled`, `completed`, or `cancelled`.

- Start and end are aware instants stored in UTC; end must be after start.
- New appointments require an `open` or `in_progress` issue and an active property/space context.
- A scheduled appointment may be rescheduled with a reason; the audit event preserves the prior schedule.
- Completion records a completion timestamp and optional outcome note.
- Cancellation requires a reason.
- Completed and cancelled appointments are immutable.
- Overlapping appointments are allowed because MAINT-001 has no staff/provider resource-assignment model.

MAINT-001 does not mirror every appointment into a task. Mirrored mutable schedules would create two sources of truth and require cross-module synchronization on every reschedule and cancellation. The operator may create a separate issue follow-up task when action tracking is useful. `COM-003` may later synchronize maintenance appointments with an external calendar without changing appointment ownership.

### Estimates and work-reported amounts are context, never actual spending

`maintenance_cost_contexts` records one of:

- `operator_estimate` — an internal rough estimate entered by the operator.
- `work_reported` — an amount reported in connection with work, not yet established as paid spending.

Each record is a labeled, dated amount with a source note. It is displayed as context and is never included in income/expense totals, owner balances, or confirmed repair-cost reporting. The UI and API must label it “estimate” or “work-reported amount,” never simply “cost paid” or “expense.” Multiple records may coexist and are not summed by default because they may represent alternatives, revisions, or overlapping scopes.

Amounts use FIN-002's exact USD convention: API decimal strings with exactly two fractional digits and persisted integer cents. A context record is immutable. An incorrect record is voided with confirmation and a reason; an optional `replaces_cost_context_id` creates a one-to-one correction chain. Provider quotes introduced by MAINT-002 are separate quote records and must not be stored as MAINT-001 estimates.

### Finance remains the sole authority for actual spending

An issue may link to zero or more existing FIN-002 expenses. The maintenance link stores only stable IDs and link lifecycle metadata; it does not copy amount, payee, category, refund, or void state. Detail projections obtain current expense summaries through a consumer-neutral, transaction-aware Finance context reader.

New links require:

- an existing, non-voided expense;
- the same property as the issue; and
- when the issue has a space, an expense whose space is either that space or null at the property level.

A later expense void or refund does not delete the maintenance link. The view shows its current Finance lifecycle and net amount. An incorrect link is archived with confirmation and a reason.

For the MVP, one FIN-002 expense may be actively linked to at most one maintenance issue. An issue may link many expenses. This prevents ambiguous double counting in repair reporting without adding an allocation model. If one expense must be allocated across multiple issues, that requires a separate design before implementation.

### Follow-up tasks are independent action records

MAINT-001 may atomically create a TASK-001 task related to `maintenance_issue`. The task uses the issue summary as its durable related label and may have its own title, notes, priority, due instant, time zone, and reminders through TASK-001.

Task status never changes issue status, and resolving or cancelling an issue does not silently complete or cancel linked tasks. Detail and list views surface active linked tasks so the operator can resolve them deliberately. This retains one owner for each lifecycle and avoids bidirectional synchronization.

### Create retries are idempotent without a generic workflow framework

Every issue, appointment, cost-context, expense-link, and follow-up create request carries a client-generated UUID `idempotencyKey`. For same-module creates, the created record stores the key and a canonical request fingerprint. Repeating a key at the same endpoint with the same semantic payload returns the original resource identity and its current representation without new rows, timestamps, or audit events; reuse with a different payload returns typed `409`.

Follow-up creation coordinates a Maintenance record, a TASK-001 task, and correlated audit events. A small Maintenance-owned follow-up-operation record therefore stores the key, request fingerprint, issue ID, resulting task ID, and correlation ID so an uncertain retry can return the same task identity and its current representation. This record is not a general workflow engine. Non-create lifecycle commands use current-state validation and do not gain operation records merely for symmetry.

### Evidence uses FILE-001 without duplicating file metadata

Files are linked only after their target maintenance record exists. MAINT-001 registers a maintenance-owned FILE-001 validator for:

| Entity type | Allowed purposes | Active-link limit |
| --- | --- | --- |
| `maintenance_issue` | `issue_photo`, `inspection_report`, `supporting_document` | 50 |
| `maintenance_appointment` | `appointment_document`, `access_document` | 10 |
| `maintenance_cost_context` | `estimate_document`, `work_report_document`, `supporting_document` | 10 |

The validator confirms target existence, allowed purpose, and active-link limit inside FILE-001's transaction. Maintenance stores no filename, hash, media type, path, storage state, or provider locator. Incorrect links are archived through FILE-001 and remain in history.

## Data model

All IDs are UUIDs. UTC timestamps are timezone-aware ISO text. Monetary context is integer USD minor units. The schema is added to the current greenfield baseline, module-owned exact schema validation, workspace/archive validation, and backup/restore verification.

### `maintenance_issues`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `property_id` | Required Portfolio property reference. |
| `space_id` | Optional Portfolio space reference belonging to `property_id`. |
| `summary` | Required trimmed operator-facing text, 1–240 characters. |
| `description` | Required sensitive narrative, 1–10,000 characters. |
| `category` | Required maintenance category code. |
| `category_detail` | Required 1–200 characters exactly when category is `other`; null otherwise. |
| `priority` | `low`, `normal`, `high`, or `urgent`; default `normal`. |
| `status` | `open`, `in_progress`, `resolved`, or `cancelled`. |
| `reported_at_utc` | Required aware occurrence instant normalized to UTC. |
| `reported_timezone` | Required property IANA time-zone snapshot. |
| `resolution_summary`, `resolved_at` | Both required exactly when status is `resolved`. |
| `cancellation_reason`, `cancelled_at` | Both required exactly when status is `cancelled`. |
| `idempotency_key`, `request_fingerprint` | Required create-retry identity and canonical payload fingerprint; key unique for issue creation. |
| `created_at`, `updated_at` | Required UTC timestamps. No-op requests do not change `updated_at`. |

Indexes support `(status, priority, reported_at_utc)`, `(property_id, status, reported_at_utc)`, `(space_id, status, reported_at_utc)`, and `(category, status)`. Database checks enforce vocabulary and paired terminal fields; application validation enforces property/space ownership, lifecycle, time zone, and cross-row appointment rules.

Reporter fields are intentionally absent from the MAINT-001 schema. MAINT-004 adds typed attribution without rewriting existing issue identity or narrative.

### `maintenance_appointments`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `issue_id` | Required maintenance issue reference. |
| `starts_at_utc`, `ends_at_utc` | Required aware instants; end is after start. |
| `scheduled_timezone` | Required property IANA time-zone snapshot. |
| `purpose` | Required 1–500 character description. |
| `instructions` | Optional sensitive access or preparation notes, maximum 4,000 characters. |
| `status` | `scheduled`, `completed`, or `cancelled`. |
| `completed_at`, `outcome_note` | Completion timestamp required when completed; outcome note optional. |
| `cancelled_at`, `cancellation_reason` | Both required when cancelled. |
| `idempotency_key`, `request_fingerprint` | Required create-retry identity and canonical payload fingerprint; key unique for appointment creation. |
| `created_at`, `updated_at` | Required UTC timestamps. |

Indexes support `(issue_id, starts_at_utc)` and `(status, starts_at_utc)`. No provider or staff ID appears in MAINT-001 appointments.

### `maintenance_cost_contexts`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `issue_id` | Required maintenance issue reference. |
| `context_kind` | `operator_estimate` or `work_reported`. |
| `label` | Required 1–200 character explanation. |
| `amount_minor` | Required positive integer from 1 through 9,999,999,999 cents. |
| `currency_code` | Required exact value `USD`. |
| `observed_on` | Required property-local ISO date. |
| `source_note` | Optional sensitive context, maximum 4,000 characters. |
| `replaces_cost_context_id` | Optional unique self-reference to a voided context for the same issue and kind. |
| `voided_at`, `void_reason` | Both null while active and both required after a confirmed void. |
| `idempotency_key`, `request_fingerprint` | Required create-retry identity and canonical payload fingerprint; key unique for cost-context creation. |
| `created_at` | Required UTC timestamp. |

Indexes support `(issue_id, context_kind, observed_on)` and active issue context. Database constraints enforce positivity, USD, lifecycle pairing, unique replacement, and non-self replacement.

### `maintenance_issue_expense_links`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `issue_id` | Required maintenance issue reference. |
| `expense_id` | Required FIN-002 expense reference. |
| `idempotency_key`, `request_fingerprint` | Required create-retry identity and canonical payload fingerprint; key unique for expense-link creation. |
| `created_at` | Required UTC timestamp. |
| `archived_at`, `archive_reason` | Null while active; both required after archival. |

A partial unique index allows only one active link for an expense and prevents duplicate active issue/expense pairs. Archived mistakes remain auditable and permit a corrected active link.

### `maintenance_follow_up_operations`

| Field | Rule |
| --- | --- |
| `idempotency_key` | Client UUID primary key for this follow-up operation. |
| `request_fingerprint` | Required canonical semantic-request fingerprint. |
| `issue_id` | Required maintenance issue reference. |
| `task_id` | Required resulting TASK-001 task reference. |
| `correlation_id` | Required audit correlation UUID. |
| `created_at` | Required UTC timestamp. |

This table exists only because follow-up creation coordinates a cross-module result that must be recoverable after an uncertain response. It must not become a generic operation or orchestration abstraction.

### No dedicated maintenance-task link table

TASK-001 already owns the generic `related_entity_type`, `related_entity_id`, and durable label. Maintenance follow-ups use `related_entity_type = 'maintenance_issue'`; duplicating the relationship would introduce two sources of truth.

## Workflows and invariants

### Record an issue

`POST /api/maintenance-issues` validates the active property/space context, property time zone, category, priority, reported instant, summary, description, and create idempotency in one immediate transaction. It inserts the issue and correlated audit event. Creating an official issue is an operator action; future ingestion and AI drafts remain separate until operator approval.

### Edit issue details

`PATCH /api/maintenance-issues/{issueId}` may change summary, description, category/detail, and priority while the issue is open or in progress. Property and space are immutable after creation; correcting them requires cancellation and a new issue so evidence and financial links cannot silently move between properties. An empty or semantically unchanged patch is a no-op.

### Start, resolve, cancel, and reopen

Dedicated lifecycle endpoints enforce the status graph. Resolution and cancellation require explicit confirmation and their respective narrative. Reopen requires confirmation and a reason. Every transition writes one issue audit event; no child records or cross-module records transition implicitly.

### Schedule or reschedule an appointment

`POST /api/maintenance-issues/{issueId}/appointments` creates a scheduled appointment after resolving the current property time zone. `PATCH /api/maintenance-appointments/{appointmentId}` changes only a scheduled appointment's times, purpose, or instructions and requires a reschedule reason when either time changes. Completion and cancellation use dedicated confirmed endpoints.

### Record or correct cost context

`POST /api/maintenance-issues/{issueId}/cost-contexts` records an operator estimate or work-reported amount. `POST /api/maintenance-cost-contexts/{contextId}/void` retains an incorrect record with a reason. A replacement uses the normal create endpoint with `replacesCostContextId` and must match the issue and context kind.

### Link or archive an expense relationship

`POST /api/maintenance-issues/{issueId}/expense-links` validates the issue and FIN-002 expense in the same transaction, then inserts the relationship and audit event. `POST /api/maintenance-expense-links/{linkId}/archive` requires confirmation and a reason. Finance records are never created, mutated, or voided through these endpoints.

### Create a follow-up

`POST /api/maintenance-issues/{issueId}/follow-ups` validates the issue, creates one TASK-001 task in the same transaction through generic task transaction operations, and records correlated issue/task audit events. Subsequent task lifecycle and reminders use TASK-001 endpoints.

### Add or archive evidence

Evidence uses existing FILE-001 APIs after the target exists. Upload/link failure does not roll back a truthful issue, appointment, or cost-context record. The UI must preserve the saved target and offer retry. FILE-001 owns content retrieval and link archival.

## Read behavior and performance

`GET /api/maintenance-issues` uses cursor pagination, default 100 and maximum 500. Filters include property, space, category, priority, status, reported-date range, appointment window, evidence presence, linked-expense presence, and active-task status. Default ordering is urgent/high priority first, then reported time descending and ID descending.

List projections show issue identity, property/space summaries, current appointment summary, active follow-up count, evidence count, and linked-expense count. They do not load full narratives, file metadata, cost-context history, task history, or financial correction chains.

`GET /api/maintenance-issues/{issueId}` returns the issue, appointments, cost-context history, active and archived file-link summaries, linked expense summaries, and related task summaries.

All page projections must be set-based and bounded independently of page size:

- Portfolio contexts use `contexts_for_property_spaces`.
- Task summaries use a consumer-neutral batch reader keyed by `maintenance_issue` IDs.
- File summaries use `links_for_entities` or bounded count projections.
- Finance expense summaries use a consumer-neutral batch reader.
- Appointments, cost contexts, and expense links load with one query per child type for the whole page, not one query per issue.

No provider reader is needed until MAINT-002. The implementation must document query budgets in tests before adding another abstraction or accepting an N+1 trade-off.

## Cross-module application contracts

The maintenance application service owns its workflow policy. Infrastructure receives small transaction-aware, consumer-neutral dependencies composed at bootstrap:

- `PortfolioContextReader` for property/space identity, lifecycle, display context, and time zone.
- `TaskTransactionOperations` for atomic task insertion, plus a task batch context reader for list/detail projection.
- `FileLinkReader` for evidence projection and filtering.
- A Finance-owned expense context reader exposing only raw expense facts required to validate and display links, with single and batch methods.
- `AuditRecorder` for same-transaction events.

Maintenance must not import Portfolio, Task, File, or Finance SQLAlchemy models or concrete repositories. Those modules must not contain `maintenance_operations.py` adapters or maintenance-specific projections. Consumer-specific mapping stays in Maintenance, following the SRP guidance in `ARCHITECTURE.md`.

The currently implemented Portfolio and File readers already provide most required operations. TASK-001 lacks a neutral batch reader for tasks by related entity, and FIN-002 lacks a neutral single/batch expense context reader. Those are small source-owned extensions required before MAINT-001 implementation; they must preserve caller-owned transactions and bounded query counts.

## API contract

All endpoints require a ready workspace. Mutations require the writer lock. Request models reject unknown fields and use typed UUIDs, strict booleans, aware timestamps, ISO dates, and exact decimal strings. Every create endpoint in the table requires a UUID `idempotencyKey`; same-payload retries return the original resource identity and current representation, while changed-payload reuse returns `409`. Application commands repeat essential validation for direct callers.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/maintenance-issues` | Record an official issue. |
| `GET` | `/api/maintenance-issues` | Return a filtered cursor page. |
| `GET` | `/api/maintenance-issues/{issueId}` | Return complete issue detail and projections. |
| `PATCH` | `/api/maintenance-issues/{issueId}` | Edit active issue details. |
| `POST` | `/api/maintenance-issues/{issueId}/start` | Move an open issue to in progress. |
| `POST` | `/api/maintenance-issues/{issueId}/resolve` | Resolve with confirmation and summary. |
| `POST` | `/api/maintenance-issues/{issueId}/cancel` | Cancel with confirmation and reason. |
| `POST` | `/api/maintenance-issues/{issueId}/reopen` | Reopen with confirmation and reason. |
| `POST` | `/api/maintenance-issues/{issueId}/appointments` | Schedule an appointment. |
| `PATCH` | `/api/maintenance-appointments/{appointmentId}` | Reschedule or edit a scheduled appointment. |
| `POST` | `/api/maintenance-appointments/{appointmentId}/complete` | Complete an appointment. |
| `POST` | `/api/maintenance-appointments/{appointmentId}/cancel` | Cancel an appointment. |
| `POST` | `/api/maintenance-issues/{issueId}/cost-contexts` | Record an estimate or work-reported amount. |
| `POST` | `/api/maintenance-cost-contexts/{contextId}/void` | Void incorrect cost context. |
| `POST` | `/api/maintenance-issues/{issueId}/expense-links` | Link an existing FIN-002 expense. |
| `POST` | `/api/maintenance-expense-links/{linkId}/archive` | Archive an incorrect expense link. |
| `POST` | `/api/maintenance-issues/{issueId}/follow-ups` | Create a related TASK-001 follow-up. |

Malformed requests return `422`; missing targets return `404`; business validation returns `400`; lifecycle, duplicate-link, replacement, stale-state, and concurrent conflicts return typed `409` errors with stable machine-readable codes.

## Audit, privacy, and portability

Every maintenance mutation and coordinated task creation writes domain rows and `AUDIT-001` events in the same immediate transaction and correlation ID. Entity types are:

- `maintenance_issue`
- `maintenance_appointment`
- `maintenance_cost_context`
- `maintenance_expense_link`
- `task` for a coordinated follow-up

General activity redacts issue descriptions, appointment instructions/outcomes, cost source notes, resolution/cancellation narratives, access details, and task notes. It may show bounded issue summary, category, priority, status, property context, appointment time, and non-sensitive lifecycle labels. Contextual issue history may reveal full operator-authorized detail.

Audit snapshots contain stored domain facts, not copied file metadata or derived Finance balances. Idempotency keys and request fingerprints are never exposed or included in audit snapshots.

Maintenance rows, links, related generic file links, task relations, audit events, and stable cross-module IDs participate in exact current-schema validation and encrypted backup/export/restore. Archive validation rejects missing issue parents, invalid child lifecycle pairs, cross-property space/expense links, duplicate active expense links, invalid task relation shapes, and broken correction lineage.

## Implementation outline

1. Add maintenance domain values, typed commands, lifecycle and idempotency rules, audit policy, application ports/service, SQLAlchemy models, exact schema/data validation, and typed routes.
2. Add the current greenfield maintenance tables, constraints, indexes, expected-table registration, archive validation, and backup/restore coverage.
3. Extend Tasks with a consumer-neutral batch context reader and Finance with a consumer-neutral expense context reader; compose both at bootstrap without adding maintenance-specific code to source modules.
4. Register maintenance FILE-001 link validation and audit policies before enabling writes.
5. Add tests for validation, lifecycle, idempotent retries and conflicts, transaction rollback, audit correlation/redaction, files, tasks, expense links, local time, query budgets, exact schema/data rejection, and encrypted backup/restore.
6. Deliver the MAINT-001 through MAINT-004 operator workflows through `UI-001`.

## Backend acceptance criteria

MAINT-001 backend/API scope is complete when:

1. An operator can record an issue for an active property and optional matching space, with required category, priority, reported time, summary, and description.
2. Issue start, resolution, cancellation, and reopen transitions enforce their invariants and retain append-only audit history.
3. Appointments use the property time zone, retain reschedule/completion/cancellation history, and block issue resolution while still scheduled.
4. Estimates and work-reported amounts remain clearly non-financial and cannot affect Finance totals.
5. Confirmed spending is represented only by validated links to existing FIN-002 expenses; Maintenance stores no copied actual amount.
6. Issue, appointment, and cost-context evidence uses FILE-001 validation and archival without duplicating file metadata.
7. Maintenance-created TASK-001 follow-ups are atomic with their creation audit and remain lifecycle-independent from the issue.
8. List/detail projections use bounded set-based queries and expose no N+1 behavior as page size or linked-record count grows.
9. All retained maintenance records, links, task relations, evidence, audit events, and correction lineage survive encrypted backup/restore with stable IDs.
10. Typed APIs reject unknown or malformed fields and return controlled `404`, `400`, `409`, and `422` outcomes.
11. Retrying any create command with the same key and semantic payload returns the same resource identity and current representation without duplicate domain rows, tasks, or audit events; changed-payload key reuse returns `409`.

Overall MAINT-001 must not be marked as a finished operator workflow until `UI-001` delivers the maintenance interface and MAINT-004 delivers reporter attribution.

## Contradictions and design decisions

The following contradictions or ambiguities were found during design review. The decisions below are now authoritative for MAINT-001 implementation.

### 1. Backlog dependencies omitted Audit and Finance

The original MAINT-001 row depended only on FILE-001, TASK-001, and PORT-002. That contradicted `ARCHITECTURE.md`, which treats issue history as auditable, and the backlog sentence that confirmed actual spending is a FIN-002 expense. The backlog row now includes completed `AUDIT-001` and `FIN-002` dependencies.

### 2. Reporter attribution is mandatory in the Product Brief but deferred to MAINT-004

`PRODUCT_BRIEF.md` says every rental or property issue records a reporter and reporter role. `FEATURE_BACKLOG.md` assigns that responsibility to MAINT-004, after MAINT-001. Decision: retain MAINT-004 ownership. MAINT-001 may ship as a backend foundation with reporter attribution temporarily absent, but the repair workflow is not complete until MAINT-004 is delivered.

There is no implemented canonical manager/staff identity source in the current local baseline. That identity representation remains a MAINT-004 design decision rather than a MAINT-001 blocker. MAINT-004 must not represent those roles as unvalidated free-text IDs or assume that the audit actor is the reporter.

### 3. Issue category is required by the Product Brief but absent from the backlog row

The Product Brief requires every issue to have a category, and later AI work expects structured category input. The backlog gives MAINT-001 no category decision and `VEND-CAT-001` owns provider categories, not issue categories. Decision: use the fixed Maintenance-owned taxonomy defined in this design. Do not reuse provider or expense categories by implication.

### 4. Maintenance has no assigned React workflow

`UI-001` occurs after MAINT-001 through MAINT-004, but its original scope and dependency list omitted maintenance. `DASH-001` then depended on both UI-001 and MAINT-001 and promised repair visibility. A backend-only MAINT-001 cannot satisfy the roadmap's repair-to-completion workflow.

Decision: expand UI-001 to include MAINT-001 through MAINT-004 while it remains the deferred MVP operator-interface slice. The backlog scope and dependencies are updated accordingly.

### 5. “Work-reported cost context” is undefined

The phrase could mean a provider quote, an internal estimate, a claimed completed-work amount, or confirmed spending. Those meanings have different owners. Decision: treat it as a labeled informational amount that is never summed or treated as paid; MAINT-002 owns quotes and FIN-002 owns actual spending.

### 6. Expense-to-issue cardinality and allocation are unspecified

The current backlog does not say whether one expense can fund several issues. Allowing unrestricted many-to-many links creates double-counting risk in repair reports, while proportional allocation introduces accounting scope. Decision: permit at most one active issue link per expense for the MVP. A future shared-expense requirement needs an explicit allocation and reporting design before implementation.

### 7. Appointment/task synchronization is unspecified

TASK-001 identifies maintenance appointments and follow-ups as consumers, but neither backlog item defines whether every appointment must create and synchronize a task. Decision: this design explicitly keeps appointments authoritative in Maintenance and tasks as optional, lifecycle-independent follow-ups. No appointment automatically creates or synchronizes a task. Any future automatic mirroring requires a separate design covering rescheduling, cancellation, reminders, restore validation, and conflicts.

### 8. Mutation retry and idempotency behavior is unspecified

The backlog does not say how a client safely retries issue, appointment, cost-context, expense-link, or coordinated follow-up creation after an uncertain response. Decision: require client-generated idempotency keys for every create operation. Persist the key and request fingerprint on same-module created records; use a Maintenance-owned operation record only for coordinated follow-up creation whose TASK-001 result must be replayed. Do not add a generic workflow framework.

## Dependencies and follow-on work

MAINT-001 requires completed `AUDIT-001`, `FILE-001`, `TASK-001`, `PORT-002`, and `FIN-002`.

Follow-on ownership remains:

- `MAINT-004` — reporter identity, role, and related communication context.
- `MAINT-002` — quotes, comparison, provider selection, and assignment.
- `MAINT-003` — append-only work journal and completed-work history.
- `DASH-001` — urgent/open repair summaries and drill-down.
- `RPT-001` — repair reporting using maintenance records and deduplicated Finance expenses.
- `INGEST-001`, `ISSUE-AI-001`, `ISSUE-AI-002`, and `INGEST-002` — source intake, reviewed extraction, matching, duplicate review, and operator-approved issue creation.
- `ISSUE-AI-003` and `ISSUE-AI-004` — advisory diagnosis and provider suggestions.
- `COM-003` — external calendar synchronization.

`MAINT-001` introduces no provider dependency. Provider profiles enter only through MAINT-002, preserving the backlog sequence and avoiding premature assignment semantics.
