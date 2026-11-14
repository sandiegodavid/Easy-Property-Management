# Database schema catalog

This catalog is the entry point for business and hosted-store ownership, schema
conventions and per-store dictionaries. Main Admin and host inventory have implemented
structural baselines; hosted access and the two recovery resource sets remain
unavailable until their owning features deliver them. [HOSTED-001](../hosting/design/mvp/delivery-plan.md#implementation-slices)
owns delivery; [H01](../hosting/design/HOSTED_MVP_H01_DESIGN.md) owns the initial design.
All executable schema definitions must live under `application/database/`. Owning versioned resources there become executable authority when implemented; this Markdown file is the design/data dictionary, not a second executable schema.
Update this dictionary and those resources together; do not create another field
catalog in a feature design.

## Start here

This catalog and its linked documents together form the schema master. Each table has one owning definition below; shared conventions and lifecycle rules apply across stores. Splitting the documentation does not merge databases or change schema ownership.

Read **overview → the relevant store → lifecycle and validation**. For operator storage/access questions, use Admin registry, protected host inventory and Operator access together.

| Topic | Document |
| --- | --- |
| Store ownership, conventions and relationships | [overview.md](overview.md) |
| Admin registry, policies and release assignments | [admin-registry.md](admin-registry.md) |
| Admin identity, invitations and login handoffs | [admin-identity.md](admin-identity.md) |
| Admin operations, audit and protection observations | [admin-operations.md](admin-operations.md) |
| Admin recovery database | [admin-recovery.md](admin-recovery.md) |
| Protected host inventory | [host-inventory.md](host-inventory.md) |
| Operator access, sessions and usage control | [operator-access.md](operator-access.md) |
| Operator recovery database | [operator-recovery.md](operator-recovery.md) |
| Initialization, retention and schema validation | [lifecycle-and-validation.md](lifecycle-and-validation.md) |

## Related references

H03 D1–D16 were accepted November 13, 2026. Its unimplemented schema extensions are
part of this master: [central identity flow state](admin-identity.md#h03-flow-state),
[source authentication state](operator-access.md#h03-authentication-state), and
[protected authentication routing](host-inventory.md#h03-authentication-routing-extension).
Acceptance of the dictionary does not change the currently implemented baselines.

- [Hosted MVP design](../hosting/design/HOSTED_MVP_DESIGN.md).
- [H01 schema/contracts handoff](../hosting/design/HOSTED_MVP_H01_DESIGN.md).
- [Executable database resources](../../application/database/README.md).

Keep column definitions in the owning store document and executable resources together; do not duplicate them in this catalog or feature designs. Historical table/section lookups below lead to their current location. Dated qualification manifests retain the paths and hashes recorded at their original source commits; moving current documentation does not rewrite that evidence.

<details>
<summary>Direct section lookup (also preserves previous deep links)</summary>

- <a id="store-boundaries-and-current-implementation"></a>[Store boundaries and current implementation](overview.md#store-boundaries-and-current-implementation)

- <a id="required-schema-definition-location"></a>[Required schema definition location](overview.md#required-schema-definition-location)

- <a id="schema-conventions"></a>[Schema conventions](overview.md#schema-conventions)

- <a id="alembic_version--each-sqlite-store"></a>[`alembic_version` — each SQLite store](overview.md#alembic_version--each-sqlite-store)

- <a id="relationships"></a>[Relationships](overview.md#relationships)

- <a id="pilot-0-admin-database"></a>[Pilot 0 Admin database](admin-registry.md#pilot-0-admin-database)

- <a id="control_meta--h04-initialization"></a>[`control_meta` — H02 protected initialization](admin-registry.md#control_meta--h02-protected-initialization)

- <a id="storage_policies--h04-free-policy"></a>[`storage_policies` — H04 Free policy](admin-registry.md#storage_policies--h04-free-policy)

- <a id="qualified_releases--h02-release-qualification"></a>[`qualified_releases` — H02 release qualification](admin-registry.md#qualified_releases--h02-release-qualification)

- <a id="component_deployments--h02-shared-admin-h04-operator-assignments"></a>[`component_deployments` — H02 shared Admin; H04 Operator assignments](admin-registry.md#component_deployments--h02-shared-admin-h04-operator-assignments)

- <a id="operators--h03h04-assignment-and-desired-state"></a>[`operators` — H03/H04 assignment and desired state](admin-registry.md#operators--h03h04-assignment-and-desired-state)

- <a id="access-state-decision-and-external-enforcement"></a>[Access-state decision and external enforcement](admin-registry.md#access-state-decision-and-external-enforcement)

- <a id="invitations--h03"></a>[`invitations` — H03](admin-identity.md#invitations--h03)

- <a id="admin_principals--h03"></a>[`admin_principals` — H03](admin-identity.md#admin_principals--h03)

- <a id="admin_sessions--h03"></a>[`admin_sessions` — H03](admin-identity.md#admin_sessions--h03)

- <a id="login_handoffs--h03-central-login"></a>[`login_handoffs` — H03 central login](admin-identity.md#login_handoffs--h03-central-login)

- <a id="operations--h04-supported-manual-effects"></a>[`operations` — H04 supported manual effects](admin-operations.md#operations--h04-supported-manual-effects)

- <a id="operation_events--h04"></a>[`operation_events` — H04](admin-operations.md#operation_events--h04)

- <a id="admin_audit--h03h04"></a>[`admin_audit` — H03/H04](admin-operations.md#admin_audit--h03h04)

- <a id="workspace_recovery_status--h05"></a>[`workspace_recovery_status` — H05](admin-operations.md#workspace_recovery_status--h05)

- <a id="admin-recovery-database--h05"></a>[Admin recovery database — H05](admin-recovery.md#admin-recovery-database--h05)

- <a id="admin_recovery_meta--h05"></a>[`admin_recovery_meta` — H05](admin-recovery.md#admin_recovery_meta--h05)

- <a id="control_recovery_operations--h05"></a>[`control_recovery_operations` — H05](admin-recovery.md#control_recovery_operations--h05)

- <a id="control_recovery_points--h05"></a>[`control_recovery_points` — H05](admin-recovery.md#control_recovery_points--h05)

- <a id="control_restore_operations--h05"></a>[`control_restore_operations` — H05](admin-recovery.md#control_restore_operations--h05)

- <a id="control_backup_state--h05"></a>[`control_backup_state` — H05](admin-recovery.md#control_backup_state--h05)

- <a id="control_recovery_audit--h05"></a>[`control_recovery_audit` — H05](admin-recovery.md#control_recovery_audit--h05)

- <a id="pilot-0-protected-host-inventory--h02h04"></a>[Pilot 0 protected host inventory — H02/H04](host-inventory.md#pilot-0-protected-host-inventory--h02h04)

- <a id="host_identity"></a>[`host_identity`](host-inventory.md#host_identity)

- [`operator_principals`](host-inventory.md#operator_principals)

- <a id="resource_bindings"></a>[`resource_bindings`](host-inventory.md#resource_bindings)

- <a id="project_assignments--h02-if-project-quotas-qualify"></a>[`project_assignments` — H02 if project quotas qualify](host-inventory.md#project_assignments--h02-if-project-quotas-qualify)

- [`ingress_bindings`](host-inventory.md#ingress_bindings)

- <a id="host_receipts"></a>[`host_receipts`](host-inventory.md#host_receipts)

- <a id="pilot-0-per-operator-access-store"></a>[Pilot 0 per-operator access store](operator-access.md#pilot-0-per-operator-access-store)

- <a id="access_meta--h03h04"></a>[`access_meta` — H03/H04](operator-access.md#access_meta--h03h04)

- <a id="access_sessions--h03"></a>[`access_sessions` — H03](operator-access.md#access_sessions--h03)

- <a id="access_receipts--h03h04"></a>[`access_receipts` — H03/H04](operator-access.md#access_receipts--h03h04)

- <a id="access_audit--h03"></a>[`access_audit` — H03](operator-access.md#access_audit--h03)

- <a id="usage_state--h04"></a>[`usage_state` — H04](operator-access.md#usage_state--h04)

- <a id="usage_reservations--h04"></a>[`usage_reservations` — H04](operator-access.md#usage_reservations--h04)

- <a id="draft_leases--h03-reuse-existing-unfinished-form-fencing"></a>[`draft_leases` — H03 reuse existing unfinished-form fencing](operator-access.md#draft_leases--h03-reuse-existing-unfinished-form-fencing)

- <a id="per-operator-recovery-store--h05-normal-and-recovery-modes"></a>[Per-operator recovery store — H05, normal and recovery modes](operator-recovery.md#per-operator-recovery-store--h05-normal-and-recovery-modes)

- <a id="recovery_meta--h05"></a>[`recovery_meta` — H05](operator-recovery.md#recovery_meta--h05)

- <a id="recovery_operations--h05"></a>[`recovery_operations` — H05](operator-recovery.md#recovery_operations--h05)

- <a id="recovery_points--h05"></a>[`recovery_points` — H05](operator-recovery.md#recovery_points--h05)

- <a id="backup_state--h05"></a>[`backup_state` — H05](operator-recovery.md#backup_state--h05)

- <a id="restore_operations--h05"></a>[`restore_operations` — H05](operator-recovery.md#restore_operations--h05)

- <a id="recovery_audit--h05"></a>[`recovery_audit` — H05](operator-recovery.md#recovery_audit--h05)

- <a id="initialization-recovery-and-retention"></a>[Initialization, recovery and retention](lifecycle-and-validation.md#initialization-recovery-and-retention)

- <a id="later-slice-schema-additions--not-pilot-0-tables"></a>[Later-slice schema additions — not Pilot 0 tables](lifecycle-and-validation.md#later-slice-schema-additions--not-pilot-0-tables)

- <a id="schema-validation-matrix"></a>[Schema validation matrix](lifecycle-and-validation.md#schema-validation-matrix)

</details>
