# Issues, appointments, quotes and work journals

## Authority and issue reporting

Maintenance owns a physical issue's property/optional Space context, category, priority, status, reporter attribution and verified outcome. Issue categories are fixed domain vocabulary; Provider categories and Finance categories are independent. Reporter attribution selects owner/tenant/manager/staff and Party/local-operator identity, validated against source context and report time. Historical selection requires explicit confirmation/reason. Corrections are explicit audited commands rather than participant inference from a communication.

## Workflow boundaries

Open/start/return-to-open preserve source-owned lifecycle and shared issue revision. Appointments have their own completion/cancellation facts; completing one never resolves the issue. Linked Tasks and reminders retain independent deadlines and state. Issue detail includes source context, child history and current revision.

Quotes preserve provider, scope, amount, received/valid dates, terms and optional paired earliest-start/estimated-finish dates. Withdrawal/replacement retains history. Comparison is bounded and does not mark a quote as spending. Assignment selects an explicit quote or uses confirmed direct assignment with a reason. Avoid-state overrides and reassignment require applicable confirmation/reasons; Provider taxonomy is advisory context. Ending an assignment does not infer physical completion.

Operator estimates and work-reported costs are operational context. Confirmed actual spending belongs to a linked Finance Expense. Voiding a cost or archiving a link never rewrites the authoritative Expense. Appointment, cost, quote, assignment and link commands use the parent issue command/revision boundary and immutable receipts.

## Work evidence and completion

The work journal is append-only and keyed to a stable issue with optional assignment. Keep what was done, when, by whom and its outcome/evidence distinct from assignment documents. Journal entry does not silently complete an appointment, close an assignment or resolve an issue. Completion review must distinguish reported completion from verified physical outcome.

Issue-backed Provider history is derived from journal facts. Providers owns separately labeled manually entered past-work context. A later legal/HOA workflow may coordinate the same physical issue, but those case lifecycles cannot substitute for a verified repair.

## API and coordinated effects

`/api/maintenance-issues` owns issue/detail/list and child workflows; quote/assignment/appointment/cost/link routes validate owning issue context. `/api/maintenance-command-receipts/{id}` returns immutable original results. Work-journal reads are issue- or Provider-scoped and bounded. Source-owned Task/File/Finance ports and caller-owned transactions preserve atomic required effects and correlated audit history.

## Current implementation detail

Quoted earliest-start and estimated-finish dates exist in current `QuoteCreate` validation, persistence and comparisons. Browser workflow acceptance is tracked separately; older planning statements that the fields are absent are historical.

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

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_command_readiness.py](../../application/apps/server/app/modules/maintenance/tests/test_command_readiness.py).
- [test_models.py](../../application/apps/server/app/modules/maintenance/tests/test_models.py).
- [test_workflow.py](../../application/apps/server/app/modules/maintenance/tests/test_workflow.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Browser acceptance is tracked separately in [active UI delivery](../active/UI-001_IMPLEMENTATION_MATRIX.md).
