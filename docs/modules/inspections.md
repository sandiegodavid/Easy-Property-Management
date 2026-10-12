# Condition inspections and comparisons

## Responsibility and lifecycle

Condition reports preserve pre-move-in and post-move-out evidence for one Lease and its Space. They contain checklist areas, observations, presence/acknowledgment facts and linked evidence. Reusable checklist templates have independent identity and revision.

Draft reports can be edited. Finalized evidence is corrected through a reasoned correction/addendum; the correction remains a draft until explicitly finalized. Prior reports stay retained, with supersession visible. A post report never overwrites the pre baseline. Comparison records preserve operator classifications such as normal wear or possible tenant damage; these do not determine liability or create deposit deductions.

## Command and evidence boundaries

Report create/correct/edit/checklist/acknowledgment/evidence/finalize/comparison commands share one Inspection revision per Lease, independent of Lease and Space revisions. Template commands have per-template revision. Each accepted new Inspection command, including a no-op, advances its scope once and retains an immutable original response. Replay precedes current scope/lifecycle validation.

File attachment publication, report association, revision, receipt and audit commit together through a caller-owned File batch. Failed transactions roll back operation-owned content. Receipt lookup never republishes bytes. A draft observation's association may be archived with confirmation and reason; finalized-report evidence remains protected by its owning policy. File association archival has its own link revision.

## API and integration

Lease-scoped `/api/leases/{id}/condition-reports` and condition report/template/observation/comparison routes supply the workflows. `/api/inspection-commands/{id}` and `/by-key/{key}` recover original results. The observation-to-report read verifies child membership.

Lease detail exposes inspection attention; missing evidence does not block recording actual move-in/out. [Finance](finance.md) explicitly selects finalized evidence for settlement decisions, and [Maintenance](maintenance.md) remains separately authoritative for repair work. Neither comparison nor acknowledgment changes those domains.

## Browser workflow boundary

Inspection browser workflows cover template/checklist drafts, observations, acknowledgment/finalization, correction/comparison and evidence history. Acknowledgment uses exactly the walkthrough-active participants. Child deletion recovers original receipts; evidence recovery requires matching-byte reselection. Findings do not automatically become deposit deductions. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/inspections/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/inspections/application).
- [HTTP contracts](../../application/apps/server/app/modules/inspections/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/inspections/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `inspection_command_operations` | [command_models.py](../../application/apps/server/app/modules/inspections/infrastructure/command_models.py) |
| `condition_reports`, `condition_areas`, `condition_observations`, `condition_report_acknowledgments`, `condition_comparisons`, `condition_checklist_templates`, `condition_checklist_template_items` | [sqlalchemy_models.py](../../application/apps/server/app/modules/inspections/infrastructure/sqlalchemy_models.py) |

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_command_readiness.py](../../application/apps/server/app/modules/inspections/tests/test_command_readiness.py).
- [test_contracts.py](../../application/apps/server/app/modules/inspections/tests/test_contracts.py).
- [test_workflow.py](../../application/apps/server/app/modules/inspections/tests/test_workflow.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
