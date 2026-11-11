# Protected host inventory

[Database schema catalog](../DATABASE_SCHEMA.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

In this guide: [Pilot 0 protected host inventory — H02/H04](#pilot-0-protected-host-inventory--h02h04) · [`host_identity`](#host_identity) · [`resource_bindings`](#resource_bindings) · [`project_assignments` — H02 if project quotas qualify](#project_assignments--h02-if-project-quotas-qualify) · [`host_receipts`](#host_receipts)

## Pilot 0 protected host inventory — H02/H04

### `host_identity`

Binds the privileged inventory to one registered host, filesystem and agent contract.
It helps prevent a command or recovered inventory from being applied to the wrong host.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `id` | `INTEGER` | No | — | Singleton row key. PK CHECK=1. |
| `host_id` | `ID` | No | — | Protected host identity. UNIQUE. |
| `deployment_id` | `ID` | No | — | Hosted deployment identity. |
| `filesystem_identity` | `REF` | No | — | Verified filesystem identity. |
| `agent_contract_version` | `REF` | No | — | Version of the restricted host-agent protocol. |
| `created_at` | `TIME` | No | — | Creation time. |

Protected root ownership pins actual host/filesystem identity. No caller-selected paths.

### `resource_bindings`

Maps an operator/workspace to its registered private resources, container/image and
physical storage ceilings. The agent resolves admitted IDs through these bindings
instead of accepting paths or container targets from a browser.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `binding_id` | `ID` | No | — | Registered resource binding identity. PK. |
| `operator_id` | `ID` | No | — | Operator identity; see table scope and relationship rules. |
| `workspace_id` | `ID` | No | — | Stable business workspace identity. |
| `resource_generation` | `REV` | No | — | Generation distinguishing resource incarnations. |
| `role` | `TEXT` | No | — | Binding role in active/staging/retained lifecycle. (`active`, `restore_staging`, `retained`). |
| `workspace_relative_ref` | `REF` | No | — | Workspace location relative to protected roots. UNIQUE. |
| `access_relative_ref` | `REF` | No | — | Hosted-access/control location relative to protected roots. UNIQUE. |
| `scratch_relative_ref` | `REF` | No | — | Bounded temporary-processing location relative to protected roots. UNIQUE. |
| `container_ref` | `REF` | Yes | — | Registered container identity. UNIQUE. |
| `image_digest` | `TEXT` | No | — | Pinned immutable running image digest. |
| `workspace_byte_ceiling` | `BYTES` | No | — | Physical workspace byte ceiling, separate from usable allowance. > 0. |
| `workspace_inode_ceiling` | `COUNT` | No | — | Physical workspace inode ceiling. > 0. |
| `control_byte_ceiling` | `BYTES` | No | — | Reserved control-tree byte ceiling. > 0. |
| `control_inode_ceiling` | `COUNT` | No | — | Reserved control-tree inode ceiling. > 0. |
| `scratch_byte_ceiling` | `BYTES` | No | — | Temporary-tree byte ceiling. > 0. |
| `scratch_inode_ceiling` | `COUNT` | No | — | Temporary-tree inode ceiling. > 0. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`allocated`, `prepared`, `running`, `stopped`, `needs_attention`, `retired`). |
| `provision_operation_id` | `ID` | No | — | Original provisioning operation; logical Admin-store reference. |
| `last_verified_at` | `TIME` | Yes | — | Time actual resource identity/limits were verified. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

Partial UNIQUE `(operator_id)` WHERE role=active AND state!=retired; UNIQUE
`(workspace_id, resource_generation)`. Filesystem project IDs, when used, live in `project_assignments` below. Relative refs
resolve only below protected roots with symlink/ownership/mount verification. Workspace,
control and scratch each have explicit bounded ceilings, never an implicit unlimited
side directory. Exact mechanism and
physical ceiling sizes remain H02 proof results, not arbitrary H01 constants.

### `project_assignments` — H02 if project quotas qualify

Assigns distinct filesystem project IDs to the protected resource trees used for
quota enforcement. This keeps workspace, control and scratch accounting tied to
registered resources rather than caller-selected project IDs.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `project_id` | `INTEGER` | No | — | Exclusive positive filesystem project allocation ID. PK CHECK > 0. |
| `binding_id` | `ID` | No | — | Registered resource binding identity. FK resource_bindings. |
| `tree_kind` | `TEXT` | No | — | Tree protected by the project assignment. (`workspace`, `control`, `scratch`). |
| `filesystem_identity` | `REF` | No | — | Verified filesystem identity. |
| `assigned_at` | `TIME` | No | — | Time the resource allocation was recorded. |

UNIQUE `(binding_id, tree_kind)`.
The primary key prevents project reuse across every tree and binding on this host.
Retain allocation after a binding retires until ownership-verified cleanup explicitly
releases it. If another qualified quota mechanism is chosen, document its equivalent
unique resource allocation in this master before implementing H02, rather than adding
a second competing allocation ledger.

### `host_receipts`

Records evidence of an original privileged host effect so a retry can inspect what
already happened instead of allocating or applying it again. It is host-side evidence,
separate from the Admin operation’s requested state.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operation_id` | `ID` | No | — | Original owning operation identity; see local FK or logical-reference rules. PK. |
| `request_hash` | `HASH` | No | — | Hash of the canonical consequential request parameters. |
| `binding_id` | `ID` | Yes | — | Registered resource binding identity. FK resource_bindings. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `kind` | `TEXT` | No | — | Typed operation/effect kind; see allowed values below. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`pending`, `unknown`, `applied`, `rejected`). |
| `observed_json` | `TEXT` | Yes | — | Bounded typed effect observations, excluding raw shell output. (typed <=16 KiB). |
| `recorded_at` | `TIME` | No | — | Time the record or event was persisted. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

Matching operation replays observed identity; changed semantics conflict. Inspect actual
effects after restart/unknown; never reallocate merely because the receipt is incomplete.
CHECK kind IN (`prepare_resources`, `initialize_container`, `repair_runtime`, `start_container`,
`stop_container`, `apply_limits`, `stage_restore`, `switch_binding`, `retire_resources`).
The repair_runtime effect replaces only a stopped/fenced container from a registered
compatible image, retaining data/control identities; it cannot call business initialization
or silently switch to another workspace. Read-only inspect needs no receipt. No generic path/command string is admitted.

