# INSP-001 — Move-In and Move-Out Condition Reports

## Purpose

`INSP-001` gives the operator a consistent, evidence-backed record of a rentable space's condition immediately before occupancy and after move-out. The two reports can be compared to identify changes, create follow-up repair work, and support—but never automatically decide—a later security-deposit settlement.

The inspection record belongs to a dedicated condition-report workflow. `LEASE-001` supplies the lease, space, participants, and timing context; `INSP-001` owns observations and evidence; a later finance workflow owns deposit receipts, deductions, approval, refund, and settlement.

## Delivery and dependency order

The implementation order is:

1. `LEASE-001` establishes the stable lease-to-space relationship and move-in/move-out dates.
2. `INSP-001` records pre-move-in and post-move-out condition evidence against that lease and space.
3. `FIN-008` uses inspection and repair evidence in an operator-reviewed security-deposit settlement.

An inspection may be designed and tested independently, but a lease-linked move-in or move-out report cannot be implemented before `LEASE-001`. `INSP-001` must not introduce a placeholder lease model.

Like other operator workflows, backend/API and UI delivery are separate. The operator UI is deferred to the phase beginning with `DASH-001`, and INSP-001 remains in progress until its guided walkthrough and comparison screens are usable.

## Scope

INSP-001 provides:

- A pre-move-in condition report linked to one lease and its one rentable space.
- A post-move-out condition report linked to the same lease and space.
- Reusable area/item checklists suitable for homes and offices without assuming apartment-building operations.
- Per-item condition, notes, observed date, and photos or documents managed by `FILE-001` in the local workspace or optional AWS S3 storage.
- Tenant presence and acknowledgment state without requiring a tenant portal or signature.
- A side-by-side comparison of pre- and post-condition observations.
- Operator classifications such as unchanged, normal wear, possible tenant-caused damage, maintenance needed, or not comparable.
- Links from an observation to a separately owned maintenance issue when follow-up work is required.
- Append-only audit history and portable backup/export behavior.

INSP-001 does not provide:

- A legal determination of damage, liability, normal wear, or a permissible deduction.
- Security-deposit receipt, accounting, deduction, refund, statutory statement, deadline, or payment. `FIN-008` owns settlement.
- Repair diagnosis, quote comparison, provider selection, or work cost. Maintenance modules own those records.
- Tenant e-signature, remote self-inspection, or portal submission.
- AI-generated damage decisions. Later AI may organize photos or draft comparisons, but the operator must review every classification.
- Apartment common-area inspections, bulk unit turnovers, or make-ready coordination.

## Core decisions

### Reports are lease-linked evidence, not lease fields

A condition report references both `lease_id` and `space_id`. The application verifies that the space is the one owned by the lease and preserves both identifiers for clear history and reporting. Reports are not embedded JSON inside a lease because they have their own lifecycle, evidence, acknowledgments, comparison, and audit trail.

### Pre and post reports remain independently truthful

The post-move-out report never overwrites the pre-move-in baseline. Comparisons are derived from separately retained observations. Correcting a finalized report requires an explicit addendum/correction with a reason; it does not silently rewrite what was recorded during the walkthrough.

### Evidence and financial decisions remain separate

An operator may mark a post-move-out observation as `possible_tenant_damage`, but that classification is only evidence. It does not create a receivable or reduce a refund. `FIN-008` must explicitly select supporting observations and costs, apply jurisdiction-aware human review, and record the final settlement decision.

### Inspections guide but do not block lease truth

The lease detail should prompt for a pre-move-in walkthrough before occupancy and a post-move-out walkthrough after confirmed move-out. Missing inspections produce visible attention states, but they do not prevent the operator from recording an actual move-in, move-out, termination, or emergency correction.

## Data model

All IDs are UUIDs. Timestamps are timezone-aware UTC text. Walkthrough dates are local calendar dates.

### `condition_reports`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID primary key. |
| `lease_id`, `space_id` | Required references; the space must be the lease's space. |
| `report_kind` | `pre_move_in` or `post_move_out`. |
| `status` | `draft`, `finalized`, or `superseded`. |
| `walkthrough_on` | Required local date. Pre-move-in normally occurs on or before occupancy; post-move-out normally occurs on or after actual move-out. Exceptions require a note rather than falsifying dates. |
| `conducted_by` | Required plain-language local-operator attribution. |
| `tenant_presence` | `present`, `not_present`, `declined`, or `not_recorded`. |
| `tenant_acknowledgment` | `acknowledged`, `disputed`, `declined`, `not_requested`, or `pending`. This is not an e-signature. |
| `acknowledged_on` | Optional date consistent with acknowledgment state. |
| `supersedes_report_id` | Optional reference to the finalized report corrected by this report; required for a correction and never used to mutate the original evidence. |
| `general_notes` | Optional bounded report-level context. |
| `finalized_at`, `created_at`, `updated_at` | UTC lifecycle timestamps. |

At most one current finalized report of each kind exists per lease. Drafts may be replaced before finalization; finalized reports are corrected through a linked correction rather than destructive editing.

### `condition_areas`

| Field | Rules and meaning |
| --- | --- |
| `id`, `condition_report_id` | Stable UUID and required report reference. |
| `display_name` | Required label such as `Kitchen`, `Suite entrance`, or `Conference room`. |
| `sort_order` | Required non-negative display order. |
| `notes` | Optional area-level context. |

Area labels are operator-editable so the same model works for residential and office spaces.

### `condition_observations`

| Field | Rules and meaning |
| --- | --- |
| `id`, `condition_area_id` | Stable UUID and required area reference. |
| `item_name` | Required label such as `Flooring`, `Walls`, `Range`, or `HVAC thermostat`. |
| `condition_state` | `good`, `fair`, `poor`, `damaged`, `missing`, `not_tested`, or `not_applicable`. |
| `cleanliness_state` | Optional `clean`, `needs_cleaning`, or `not_assessed`. |
| `notes` | Optional bounded factual observation. |
| `sort_order` | Required non-negative display order. |

Evidence files use `FILE-001` links with `entity_type = condition_observation` and a purpose such as `condition_photo` or `supporting_document`. File capture retains its own creation metadata; the report does not claim a photo was taken on a different date.

### Evidence association and storage

Evidence association is storage-neutral:

```text
condition_observation -> file_link -> file_record -> current content location
                                                          |-- local workspace
                                                          `-- AWS S3
```

An observation never stores a filesystem path, S3 bucket, object key, or URL. Each association is a `file_links` row with:

- `entity_type = condition_observation`;
- `entity_id = condition_observations.id`;
- `purpose = condition_photo` or `supporting_document`;
- the linked `file_id` owned by `FILE-001`.

One observation may have multiple evidence links. A file may be reused through another explicit link when appropriate, without duplicating its bytes. Replacing, correcting, or removing an observation does not silently delete the underlying file; normal FILE-001 reference and retention rules apply.

`FILE-001` selects and validates the local or S3 content-store adapter. S3 locations persist stable object identifiers, never presigned URLs, and retain application-owned hashes and sizes independently of provider metadata. Finalized inspection evidence cannot be silently replaced: new evidence is attached through an audited correction while the original link and file identity remain in history.

### `condition_comparisons`

| Field | Rules and meaning |
| --- | --- |
| `id` | Stable UUID. |
| `pre_observation_id`, `post_observation_id` | References to observations for the same lease and space; either may be null only when an item exists on one report alone. |
| `comparison_state` | `unchanged`, `improved`, `normal_wear`, `possible_tenant_damage`, `maintenance_needed`, or `not_comparable`. |
| `operator_notes` | Required for possible damage and not-comparable decisions. |
| `maintenance_issue_id` | Optional reference to a maintenance issue created through the owning module. |
| `created_at`, `updated_at` | UTC timestamps. |

Comparisons are explicit operator-reviewed records rather than conclusions inferred from condition labels alone.

## Workflow

### Pre-move-in

1. The executed lease exposes a due-soon walkthrough prompt based on `occupancy_starts_on`.
2. The operator creates a pre-move-in draft using a default or copied checklist.
3. The operator records each item's condition and attaches photos where useful.
4. The operator records whether the tenant was present and whether the report was acknowledged or disputed.
5. Finalization validates required observations and freezes the baseline.

### Post-move-out

1. A lease end or termination with confirmed `actual_move_out_on` exposes the post-move-out walkthrough action.
2. The operator records current condition without modifying the pre-move-in report.
3. The application presents comparable items side by side and requires operator classifications.
4. Maintenance-needed observations may create or link to issues; the inspection retains the reference but does not own repair work.
5. The finalized comparison becomes eligible evidence for `FIN-008` deposit settlement.

The operator may complete the post report before the lease lifecycle is formally closed only as a draft. Finalizing it requires a confirmed move-out date, preventing condition evidence from silently asserting that occupancy ended.

## API contract

All requests forbid unknown fields, use typed response models, and repeat critical validation in application commands.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/leases/{leaseId}/condition-reports` | Create a pre- or post-move report draft. |
| `GET` | `/api/leases/{leaseId}/condition-reports` | List reports and attention states for a lease. |
| `GET` | `/api/condition-reports/{reportId}` | Return report areas, observations, evidence links, and acknowledgment state. |
| `PATCH` | `/api/condition-reports/{reportId}` | Update an unfinalized report. |
| `PUT` | `/api/condition-reports/{reportId}/areas` | Replace the ordered draft checklist atomically. |
| `POST` | `/api/condition-reports/{reportId}/finalize` | Finalize with explicit confirmation. |
| `POST` | `/api/condition-reports/{reportId}/corrections` | Create a reasoned correction without rewriting the finalized source. |
| `GET` | `/api/leases/{leaseId}/condition-comparison` | Return aligned pre/post observations and comparison state. |
| `PUT` | `/api/leases/{leaseId}/condition-comparison` | Save reviewed comparison classifications atomically. |

Errors distinguish malformed requests (`422`), missing records (`404`), invalid workflow rules (`400`), and finalized/source/concurrency conflicts (`409`).

## Audit, privacy, and portability

Creating, editing, finalizing, correcting, acknowledging, and comparing reports produces domain-owned audit events. One business operation shares one correlation ID across report, area, observation, file-link, comparison, and any explicitly requested maintenance-link changes.

General activity shows concise condition metadata and classifications, not image bytes, storage credentials, object keys, temporary URLs, or tenant contact details. Evidence bytes may reside in the local managed-file store or an enabled S3 content store, while the observation relationship remains a portable FILE-001 link. Backup and export retrieve and hash-verify referenced S3 evidence and embed it in the encrypted archive so restore is not dependent on the original cloud account. Exact-schema validation and future SaaS migration include reports, comparisons, logical file records, links, storage metadata, and audit history together.

## Acceptance criteria

INSP-001 is complete when:

1. The operator can finalize one pre-move-in and one post-move-out condition report for a lease and space while preserving both independently.
2. Reports support residential and office checklists, observations, photos/documents, tenant presence, and acknowledgment state. Evidence uses the same links with the default local adapter or, when configured, the optional S3 adapter.
3. Post-move-out observations can be compared with the pre-move-in baseline and classified only through an explicit operator decision.
4. Inspection evidence may link to maintenance issues and later deposit settlement without creating either record implicitly.
5. Finalized history cannot be silently rewritten; corrections, file links, and comparisons are atomic and audited.
6. The workflow prompts at appropriate lease milestones but never blocks recording truthful occupancy or lease lifecycle facts.
7. Typed APIs, current-schema validation, and encrypted backup/export/restore preserve the complete inspection record.
8. The guided operator UI is delivered before the backlog item is marked done.

## Dependencies and follow-on work

INSP-001 requires `AUDIT-001`, `FILE-001`, and `LEASE-001`. It integrates with `MAINT-001` when available but does not require maintenance merely to record condition.

`FIN-008` depends on INSP-001 for condition evidence and owns the security-deposit settlement decision. Later e-signature or portal features may add tenant-signed or tenant-submitted reports without changing the local operator-owned evidence model.
