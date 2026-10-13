# Issues, appointments, quotes and work journals

## Authority and issue reporting

Maintenance owns a physical issue's property/optional Space context, category, priority, status, reporter attribution and verified outcome. Issue categories are fixed domain vocabulary; Provider categories and Finance categories are independent. Reporter attribution selects owner/tenant/manager/staff and Party/local-operator identity, validated against source context and report time. Historical selection requires explicit confirmation/reason. Corrections are explicit audited commands rather than participant inference from a communication.

Reporter review offers a bounded 25-identity name search, active by default, with an explicit archived-identity toggle. Manager/staff use Local operator; tenant requires a Party; owner permits a Party or eligible self-owner Local operator. Changing to Local operator removes Party/historical fields. Archived selection requires confirmation and a bounded reason for a backdated relationship; it never restores a Party, ownership or lease. Ownership/occupancy/participant eligibility remains server-owned at the Property-local reported date, including end-exclusive boundaries. Invalid source relationships return the current typed `409 reporter_relationship` contract.

Reporter correction prefills only the existing attribution's command fields and retains the original report date. Stored display-name snapshots are visible in issue detail and list rows, alongside reporter role/subject/Party filters. List rows add no identity or relationship lookup. Linked communication creation explicitly prefills a Party reporter as a `reporter` participant from fresh issue detail; Local operator is never turned into a fake Party. Later attribution correction leaves the communication's immutable participant history unchanged. Sensitive identity and historical/correction context remain redacted from general activity.

## Workflow boundaries

Open/start/return-to-open preserve source-owned lifecycle and shared issue revision. Appointments have their own completion/cancellation facts; completing one never resolves the issue. Linked Tasks and reminders retain independent deadlines and state. Issue detail includes source context, child history and current revision.

Quotes preserve provider, scope, amount, received/valid dates, terms and optional paired earliest-start/estimated-finish dates. Withdrawal/replacement retains history. Comparison is bounded and does not mark a quote as spending. Assignment selects an explicit quote or uses confirmed direct assignment with a reason. Avoid-state overrides and reassignment require applicable confirmation/reasons; Provider taxonomy is advisory context. Ending an assignment does not infer physical completion.

Issue detail provides a separate bounded, server-ordered quote comparison with exact USD totals, scope/terms, validity and paired quoted dates, document counts, current Provider/Party state and current/historical assignment markers. No winner or total is inferred. Selecting an option prefills its exact quote/Provider identity for review; the server rechecks expiry, matching identities and eligibility. Quoted dates do not create appointments or represent actual work.

Quote replacement starts from its withdrawn predecessor, preserving Provider, scope and schedule context while requiring a new amount. Direct assignment requires confirmation/reason; avoided Providers additionally require override confirmation/reason. Current assignment offers explicit reassignment with end reason and confirmation; it atomically ends the predecessor and creates one replacement. Lost responses reconcile the original command rather than writing another assignment. Selection review links to source-owned Provider services/areas/history and displays preference/archive state without copying the Provider's sensitive preference reason.

Quote and assignment documents use Files' independent upload/archival commands. Contextual archival verifies owning issue/child membership and retains file bytes, IDs, reason and history. These documents are offer/engagement context, not completion evidence or proof of paid spending.

Operator estimates and work-reported costs are operational context. Confirmed actual spending belongs to a linked Finance Expense. Voiding a cost or archiving a link never rewrites the authoritative Expense. Appointment, cost, quote, assignment and link commands use the parent issue command/revision boundary and immutable receipts.

## Work evidence and completion

The work journal is append-only and keyed to a stable issue with optional assignment. Keep what was done, when, by whom and its outcome/evidence distinct from assignment documents. Journal entry does not silently complete an appointment, close an assignment or resolve an issue. Completion review must distinguish reported completion from verified physical outcome.

Issue-backed Provider history is derived from journal facts. Providers owns separately labeled manually entered past-work context. A later legal/HOA workflow may coordinate the same physical issue, but those case lifecycles cannot substitute for a verified repair.

The browser offers start, progress, blocked, completion and note entries, with optional same-issue current/ended assignment selection. Provider reports require an assignment. Completion records an outcome, summary, follow-up need and explicit operator-verification flag; a verified partial outcome is not a completed repair. Terminal issues permit confirmed historical entries without reopening. Journal commands contain no monetary fields and share the issue revision and immutable original-response receipts.

Issue journal and Maintenance-owned Provider history use 20-row cursor pages with a first-page reset, separate from the ten-entry issue-detail preview. Rows show source, actual UTC/local occurrence, recording time, assignment snapshot, quoted start/finish dates and recorded assignment-to-start duration. That duration is not Provider response time. Provider detail links back to the owning issue and never copies journal entries into manual Provider history.

An effective entry offers a reasoned correction with its factual payload prefilled from the selected bounded page. The server rechecks source membership/effectiveness and rejects branching corrections. Originals remain visible as superseded context; no journal edit/delete is offered. Optional evidence is a separate Files command after entry creation; superseded entries cannot accept new evidence. Journal evidence can be archived from its owning page with link revision/confirmation/reason; normal pages hide archived links, while Files metadata and audit history retain the original association. Unavailable active evidence remains labeled unavailable. Lost journal responses reconcile the original receipt without another append.

## API and coordinated effects

`/api/maintenance-issues` owns issue/detail/list and child workflows; quote/assignment/appointment/cost/link routes validate owning issue context. `/api/maintenance-command-receipts/{id}` returns immutable original results. Work-journal reads are issue- or Provider-scoped and bounded. Source-owned Task/File/Finance ports and caller-owned transactions preserve atomic required effects and correlated audit history.

## Current implementation detail

Quoted earliest-start and estimated-finish dates exist in current `QuoteCreate` validation, persistence and browser comparisons. Older planning statements that the fields or comparison UI are absent are historical.

## Browser workflow boundary

Maintenance browser records expose issue reporter/context, appointments, operational costs, quotes/comparison, assignments, expense associations, journal, evidence and follow-up. Owning issue revisions/receipts govern child actions. Source Task, appointment and verified repair lifecycles remain distinct; loss of a response reconciles the original operation. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

Issue creation selects an active Property and optional matching Space from bounded source projections, with mandatory existing reporter attribution. Command review shows the Property IANA zone/local date, independent lifecycle rules and sensitive-data cues. Appointments retain their scheduled zone and reasoned rescheduling history; completing an appointment never resolves an issue. Follow-up Tasks remain separately managed and display their deadlines.

Operator-estimate/work-reported context is explicitly labeled non-financial, formatted in exact USD cents, never summed and never included in Finance totals. Voided context can be replaced from its retained predecessor. Paid spending is linked from a bounded same-Property Expense selection; archival removes only the association, not the Expense. Issue detail accepts the source projections' Expense void timestamp and Task deletion timestamp through typed response contracts rather than failing response validation.

Issue, appointment and cost evidence can be archived contextually with a required reason and File-link revision. File bytes, IDs and archive history remain retained and readable through metadata; normal lists hide archived associations and disable opening unavailable content. Attachment failure remains independent from saving a truthful issue/child record. Issue lists offer category/priority, Space, report/appointment intervals, evidence, linked Expense and active Task filters in addition to status/Property. Persistence still owns cursor selection and bounded set-based projections.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/maintenance/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/maintenance/application).
- [HTTP contracts](../../application/apps/server/app/modules/maintenance/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/maintenance/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `maintenance_issues`, `maintenance_command_receipts`, `maintenance_appointments`, `maintenance_cost_contexts`, `maintenance_issue_expense_links`, `maintenance_follow_up_operations`, `maintenance_quotes`, `maintenance_assignments`, `maintenance_work_journal_entries` | [sqlalchemy_models.py](../../application/apps/server/app/modules/maintenance/infrastructure/sqlalchemy_models.py) |

## Validation

DASH-001's source attention reader projects urgent/ordinary issues, explicit Task-supported waiting, scheduled appointment intervals and missed outcomes on a caller-owned snapshot. Exact counts and bounded child previews support the later Home composition while issue, appointment and Task lifecycle commands remain independent. See the [Slice 4 validation matrix](../active/DASH-001_CONTRACT_EXAMPLES.md#slice-4-maintenance-issue-and-appointment-facts) and [attention tests](../../application/apps/server/app/modules/maintenance/tests/test_attention_reader.py).

MAINT-001 acceptance completed on October 13, 2026; see the [completed matrix](../archive/designs/MAINT-001_DESIGN_COMPLETED_2026-10-13.md). Browser review and contextual archival are in [maintenance-context.tsx](../../application/apps/web/src/workflows/maintenance-context.tsx) and [maintenance-evidence.tsx](../../application/apps/web/src/workflows/maintenance-evidence.tsx). MAINT-004 reporter acceptance is separately recorded in its [completed matrix](../archive/designs/MAINT-004_DESIGN_COMPLETED_2026-10-13.md), with browser policy feedback in [reporter-context.tsx](../../application/apps/web/src/workflows/reporter-context.tsx). MAINT-002 quote/assignment acceptance is in its [completed matrix](../archive/designs/MAINT-002_DESIGN_COMPLETED_2026-10-13.md), with comparison/review in [quote-context.tsx](../../application/apps/web/src/workflows/quote-context.tsx). MAINT-003 journal acceptance is in its [completed matrix](../archive/designs/MAINT-003_DESIGN_COMPLETED_2026-10-13.md), with bounded timelines/review in [work-journal.tsx](../../application/apps/web/src/workflows/work-journal.tsx).

- [test_command_readiness.py](../../application/apps/server/app/modules/maintenance/tests/test_command_readiness.py).
- [test_models.py](../../application/apps/server/app/modules/maintenance/tests/test_models.py).
- [test_workflow.py](../../application/apps/server/app/modules/maintenance/tests/test_workflow.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
