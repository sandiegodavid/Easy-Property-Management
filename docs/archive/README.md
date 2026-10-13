# Historical design and delivery archive

Use [current module guides](../README.md#current-modules) to understand today's implementation and [active designs](../active/README.md) for remaining work.

## Design records

[designs](designs) contains two kinds of source records:

- Completed feature designs: LOCAL-002, AUDIT-001, FILE-001, TASK-001, PORT-001, PORT-002, PORT-003, LEASE-001 and TEN-001, based on the existing backlog status. The completed [TASK-001](designs/TASK-001_DESIGN_COMPLETED_2026-10-12.md), [PORT-003](designs/PORT-003_DESIGN_COMPLETED_2026-10-12.md) and [LEASE-001](designs/LEASE-001_DESIGN_COMPLETED_2026-10-12.md) acceptance records preserve October 12 validation evidence; current behavior is consolidated in the [Task](../modules/tasks.md), [Portfolio](../modules/portfolio.md) and [Lease](../modules/leases.md) guides.
- Superseded planning snapshots for partially delivered domains and UI-001. Their implemented content is consolidated into module/UI guides and their unfinished acceptance remains in active designs. Archiving these snapshots does not mark the features complete.

The complete original bodies remain available for decision rationale and contract traceability. Link paths are adjusted for relocation. Baseline observations, slice amendments and future-tense implementation plans are historical statements, not current capability claims.

INSP-001 is also complete: its [October 12 acceptance record](designs/INSP-001_DESIGN_COMPLETED_2026-10-12.md) preserves focused validation; the [Inspection guide](../modules/inspections.md) owns current behavior.

VEND-001's [October 12 acceptance record](designs/VEND-001_DESIGN_COMPLETED_2026-10-12.md) records completed profile/identity/service/area/manual-history/reference acceptance. Current behavior lives in the [Provider guide](../modules/providers.md); VEND-002 and VEND-CAT-001 have their own completed acceptance records below.

## Delivery and validation records

VEND-002's [completed acceptance record](designs/VEND-002_DESIGN_COMPLETED_2026-10-12.md) covers manual reputation pointers and contextual lifecycle history. Current behavior is in the [Provider guide](../modules/providers.md).

[implementation-plans](implementation-plans) contains the complete historical UI matrix, command-readiness plans and the prior architecture plan. [validation](validation) preserves dated feature test matrices. These records retain original evidence, counts and known gaps. No tests were rerun as part of documentation consolidation.

## Source mapping

FIN-001's [completed acceptance record](designs/FIN-001_DESIGN_COMPLETED_2026-10-12.md) covers rent schedule preview, receipt allocations/corrections and operational timeliness. Current behavior is in the [Finance guide](../modules/finance.md).

FIN-002's [October 13 acceptance record](designs/FIN-002_DESIGN_COMPLETED_2026-10-13.md) covers paid-expense context, duplicate review, evidence, category correction and refund/replacement workflows. Current behavior is consolidated in the [Finance guide](../modules/finance.md#actual-expenses-and-refunds); other Finance features retain separate gates.

FIN-008's [October 13 acceptance record](designs/FIN-008_DESIGN_COMPLETED_2026-10-13.md) covers deposit settlement review, interest calculations, payments/corrections and retained evidence history. Current behavior is in the [Finance guide](../modules/finance.md#security-deposits).

FIN-006's [October 13 acceptance record](designs/FIN-006_DESIGN_COMPLETED_2026-10-13.md) closes actual receipt-method selection, editable suggestions and safe masked references. Current behavior is in the [Finance guide](../modules/finance.md#rent-schedule-and-receipts).

FIN-007's [October 13 acceptance record](designs/FIN-007_DESIGN_COMPLETED_2026-10-13.md) closes prepaid-check queues, lifecycle review and original correlated receipt recovery. Current behavior is in the [Finance guide](../modules/finance.md#prepaid-checks).

COM-001's [October 13 acceptance record](designs/COM-001_DESIGN_COMPLETED_2026-10-13.md) closes manual conversation recording, participant/contact selection, correction history, timeline filters and original-result recovery. Current behavior is in the [Communications guide](../modules/communications.md).

MAINT-001's [October 13 acceptance record](designs/MAINT-001_DESIGN_COMPLETED_2026-10-13.md) closes issue, appointment, cost-context, Expense-association, follow-up and contextual evidence workflows. Current behavior is in the [Maintenance guide](../modules/maintenance.md); other Maintenance features retain separate gates.

MAINT-004's [October 13 acceptance record](designs/MAINT-004_DESIGN_COMPLETED_2026-10-13.md) closes contextual reporter selection, historical confirmation, reasoned correction, reporter filtering and independent linked Communications. Current behavior is in the [Maintenance guide](../modules/maintenance.md#authority-and-issue-reporting).

MAINT-002's [October 13 acceptance record](designs/MAINT-002_DESIGN_COMPLETED_2026-10-13.md) closes quote comparison, Provider selection/override, replacement/reassignment and retained engagement history. Current behavior is in the [Maintenance guide](../modules/maintenance.md#workflow-boundaries).

MAINT-003's [October 13 acceptance record](designs/MAINT-003_DESIGN_COMPLETED_2026-10-13.md) closes journal correction, reported/verified outcomes, evidence, bounded issue/Provider history and encrypted retained-history preservation. Current behavior is in the [Maintenance guide](../modules/maintenance.md#work-evidence-and-completion).

OWNER-003's [October 13 acceptance record](designs/OWNER-003_DESIGN_COMPLETED_2026-10-13.md) closes direct-rent claim/evidence review, explicit Finance adoption/creation, duplicate prevention, replacement history and encrypted lineage preservation. Current behavior is in the [Owner accounting guide](../modules/owner-accounting.md).

OWNER-004's [October 13 source acceptance](designs/OWNER-004_DESIGN_COMPLETED_2026-10-13.md) closes concern context, duplicate review, correction, independent lifecycle/Tasks/Communications and portable original results. Home presentation remains in DASH-001 by explicit scope agreement.

AI-GOV-001's [October 13 foundation acceptance](designs/AI-GOV-001_DESIGN_COMPLETED_2026-10-13.md) closes Settings, single-effect generation/review, original-result recovery and encrypted governance-history preservation. INGEST-002 retains approval-mode/domain-dismissal extensions; production AI registries remain empty.

INGEST-001's [October 13 acceptance](designs/INGEST-001_DESIGN_COMPLETED_2026-10-13.md) closes manual retention/import, exact audited evidence comparison, correction/attention/supersession recovery, independent Communications links and encrypted evidence-history preservation. Issue conversion and assistant transports remain separate active features.

VEND-CAT-001's [October 13 acceptance](designs/VEND-CAT-001_DESIGN_COMPLETED_2026-10-13.md) closes Settings catalog administration, effective classification/filtering, assignment lifecycle/recovery and encrypted history preservation. Legal engagements, AI recommendations and spreadsheet importing remain separate features.

FIN-003's [October 13 acceptance](designs/FIN-003_DESIGN_COMPLETED_2026-10-13.md) closes explicit-period portfolio/Property reporting, separate deposit activity/obligations, exact bounded drill-down and stale-view restart. Home presentation and future owner entitlement/reporting remain separately owned.

TASK-002's [October 13 acceptance](designs/TASK-002_DESIGN_COMPLETED_2026-10-13.md) closes waiting replacement, follow-up reschedule/date removal, independent deadline/reminder presentation, immutable recovery and portable history. Broader Home acceptance remains DASH-001-owned.

OPS-001's [October 13 acceptance](designs/OPS-001_DESIGN_COMPLETED_2026-10-13.md) closes bootstrap/preferences, bounded contextual directories/overviews, metadata search, coverage review and incomplete-form recovery. Home aggregation and future source registrations remain separately owned.

[Document inventory](../DOCUMENT_INVENTORY.md) identifies each original source, current authoritative guide, active work and archive location. No pending review findings are closed by this move.

## Completed core browser delivery

The [final UI-001 design](designs/UI-001_DESIGN_COMPLETED_2026-10-12.md) and [final delivery matrix](implementation-plans/UI-001_IMPLEMENTATION_MATRIX_COMPLETED_2026-10-12.md) preserve the completed October 12 record separately from earlier partial snapshots. Current behavior lives in [UI guides](../ui/operator-experience.md) and [modules](../README.md#current-modules); remaining Home and extension work lives in DASH-001/UI-002.
