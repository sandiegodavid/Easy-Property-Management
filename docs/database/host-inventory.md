# Protected host inventory

[Database schema catalog](README.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

In this guide: [Host identity](#host_identity) · [Operator principals](#operator_principals) · [Resource bindings](#resource_bindings) · [Project assignments](#project_assignments--h02-if-project-quotas-qualify) · [Ingress authority](#ingress_bindings) · [Effect receipts](#host_receipts)

## Pilot 0 protected host inventory — H02/H04

H02.2 delivers the [six-table current baseline](../../application/database/host-inventory-migrations/README.md)
and separate protected metadata binding. H02.3 adds the
[private command/reservation boundary](../hosting/qualification/reports/HOSTED_MVP_H02_3_HANDOFF.md).
Native verification and Docker/gateway effects remain later slices; schema creation
itself creates no operator resources.

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

### `operator_principals`

Owns the host UID/GID assigned to each operator so filesystem isolation survives
container replacement. These are process/filesystem identities, not extra OS instances,
human login accounts or product roles. Structural constraints are implemented in H02.2; H02.3 reserves mappings in the
private inventory transaction using an explicit collision-probe dependency. Physical
resource creation and native qualification remain H02.5/H02.8.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operator_id` | `ID` | No | — | PK; logical Admin operator reference, verified through admitted authority. |
| `workspace_id` | `ID` | No | — | UNIQUE owning workspace reference. |
| `host_uid` | `INTEGER` | No | — | UNIQUE allocated non-root host UID; > 0 and < 4294967295. |
| `host_gid` | `INTEGER` | No | — | UNIQUE allocated non-root host GID; > 0 and < 4294967295. |
| `assigned_at` | `TIME` | No | — | Time the mapping was reserved. |
| `retired_at` | `TIME` | Yes | — | Explicit retirement time; does not release filesystem ownership. |
| `cleanup_verified_at` | `TIME` | Yes | — | Verified cleanup time, only after retirement and all owned resources are removed. |
| `revision` | `REV` | No | — | Owning optimistic concurrency revision. |

UNIQUE `(operator_id, workspace_id)` supports local binding FKs. Allocate from the
protected configured range after checking reserved system/container identities; no
UUID hashing or operator-selected UID. CHECK retired_at >= assigned_at when present;
cleanup requires retired_at and cleanup_verified_at >= retired_at. Retain the mapping
while any active, failed, unknown or retained allocation belongs to it. Pilot 0 does
not automatically recycle identities; any later reuse requires explicit verified cleanup.

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
`(workspace_id, resource_generation)` and UNIQUE
`(binding_id, operator_id, workspace_id, resource_generation)` for ingress binding FKs.
Composite FK `(operator_id, workspace_id)` references operator_principals in this
inventory, not the Admin DB. Filesystem project IDs, when used, live in `project_assignments` below. Relative refs
resolve only below protected roots with symlink/ownership/mount verification. Workspace,
control and scratch each have explicit bounded ceilings, never an implicit unlimited
side directory. Exact mechanism and
physical ceiling sizes remain H02 proof results, not arbitrary H01 constants.

H02 creates active bindings and retains their identity through runtime replacement;
it does not execute business restore stage/switch. The restore_staging/retained role
vocabulary describes the future H05 lifecycle, not an implemented capability. H05 must
resolve staging target identity and these path uniqueness constraints before enabling
those effects; access/recovery authority must remain outside restored business data.

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

### `ingress_bindings`

Owns durable external access denial and its highest accepted access fence independently
of the Operator process. Gateway configuration is a generated projection of this table,
not a second editable registry. Accepted H02 D4/D5; H03 supplies live identity/source
proof and H04 integrates Admin commands. H02.2 implements structural constraints;
H02.3 reserves desired fences and verifies typed effect results; actual gateway
execution/containment remains H02.6.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operator_id` | `ID` | No | — | PK; one current ingress authority per operator. |
| `workspace_id` | `ID` | No | — | UNIQUE registered workspace identity. |
| `binding_id` | `ID` | No | — | Current registered resource binding. |
| `resource_generation` | `REV` | No | — | Current resource incarnation paired with that binding. |
| `public_origin` | `TEXT` | No | — | UNIQUE exact admitted HTTPS origin; <=253 characters, validated flat hostname, no port/path/query/user info. |
| `access_epoch` | `REV` | No | — | Highest accepted access fence; never reduced by replay or replacement. |
| `desired_state` | `TEXT` | No | — | CHECK held, eligible or blocked; new bindings initialize held explicitly. |
| `operation_id` | `ID` | No | — | FK host_receipts; original child effect requesting this projection. |
| `verified_state` | `TEXT` | No | — | Last observed held/eligible/blocked, or unknown. |
| `verified_revision` | `REV` | Yes | — | Desired row revision actually verified at the gateway. |
| `verification_ref` | `REF` | Yes | — | Protected gateway/containment evidence; not raw configuration or credentials. |
| `verified_at` | `TIME` | Yes | — | Actual completed observation time. |
| `updated_at` | `TIME` | No | — | Most recent desired-state update time. |
| `revision` | `REV` | No | — | Expected-revision fence for changing this authority. |

Composite FK `(binding_id, operator_id, workspace_id, resource_generation)` references
resource_bindings in this store. Index `(desired_state, operator_id)` supports bounded
reconciliation. Verification fields are all null with verified_state=unknown, or all
present for a known observation; verified_revision <= revision. A new desired revision
may retain prior observed evidence but is pending until the exact revision/state is
verified. No stale successful observation can mark a newer command applied.

Reserve binding, pending host receipt and initial held ingress authority in a short
owning transaction before external access is possible. Persist a new deny/fence before
gateway effects; authenticate exact Admin intent through owning ports, never source
local fields. All later host effects check this current fence, including fresh requests
with unseen keys. A matching historical retry can return its original receipt but
cannot rerun an obsolete effect. Removing a deny requires current admitted enable,
source/identity readiness proof and verified resource generation. No H02 customer
enablement before those H03/H04 capabilities exist.

On gateway restart, derive a protected projection from current inventory and verify it
before reopening. Missing authority stays closed; a valid last-known projection may
continue during an Admin outage. Successful config loading alone does not prove old
connections are contained; stop/fence the container where necessary. Report verified
external containment separately from pending source revocation. This table tracks
external enforcement, not local sessions or a browser-editable account setting.

### `host_receipts`

Records evidence of an original privileged host effect so a retry can inspect what
already happened instead of allocating or applying it again. It is host-side evidence,
separate from the Admin operation’s requested state.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operation_id` | `ID` | No | — | PK; original deterministic child host-effect identity, not the shared Admin parent ID. |
| `parent_operation_id` | `ID` | No | — | Logical original Admin/control operation reference; no cross-store FK. |
| `idempotency_key` | `TEXT` | No | — | Stable child-effect key, <=120 characters; shared contract character rules. |
| `request_hash` | `HASH` | No | — | Hash of the canonical consequential request parameters. |
| `request_json` | `TEXT` | No | — | Immutable typed canonical intent <=16 KiB, including parent/scope/effect slot, resource generation and consequential parameters; no secrets or arbitrary paths. |
| `binding_id` | `ID` | Yes | — | Registered resource binding identity. FK resource_bindings. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `kind` | `TEXT` | No | — | Typed operation/effect kind; see allowed values below. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`pending`, `unknown`, `applied`, `rejected`, `superseded`). |
| `observed_json` | `TEXT` | Yes | — | Bounded typed effect observations, excluding raw shell output. (typed <=16 KiB). |
| `recorded_at` | `TIME` | No | — | Time the record or event was persisted. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

UNIQUE `(kind, idempotency_key)` within this host's deployment. Indexes
`(parent_operation_id, operation_id)` and `(state, recorded_at, operation_id)` support
bounded effect lookup/reconciliation. Derive child IDs/keys from the immutable parent,
kind, registered target/generation and declared effect slot; one parent can have several
effects. Include that identity context in the semantic hash. Retried matching keys
return the original child identity even if a different proposed ID was supplied;
changed scope/parent/hash conflicts. Keep immutable intent so restart never reconstructs
old parameters from changed assignments. Every H02 mutating operator-resource effect,
including initial preparation, has a registered binding reserved before dispatch.

Matching operation replays observed identity; changed semantics conflict. Inspect actual
effects after restart/unknown; never reallocate merely because the receipt is incomplete.
CHECK kind IN (`prepare_resources`, `initialize_container`, `repair_runtime`, `start_container`,
`stop_container`, `apply_limits`, `apply_ingress_policy`, `stage_restore`, `switch_binding`, `retire_resources`).
H02 adds narrow apply/inspect ingress contracts. Stage/switch restore remains unavailable
without effects until H05 delivers its target/authorization design and implementation.
Current highest access authority is in ingress_bindings, not inferred by scanning old
receipts. Reserve pending receipts before host effects and verify afterward in another
short transaction; failure between them stays unknown, not falsely atomic rollback.
The repair_runtime effect replaces only a stopped/fenced container from a registered
compatible image, retaining data/control identities; it cannot call business initialization
or silently switch to another workspace. Read-only inspect needs no receipt. No generic path/command string is admitted.


### Verified containment and current supervision

An authenticated, successfully verified `stop_container` atomically records its
receipt and terminates older pending/unknown `start_container` receipts for the same
binding, generation and owning scope as `superseded`. The original intent/hash and
unknown observation remain unchanged; `observed_json` adds the verified stop child
ID (`superseded_by_operation_id`), `containment_evidence_ref` and `superseded_at`.
This proves current containment, not whether the historical start ever ran. The
superseded state is terminal/immutable and cannot be replayed. A newly admitted
start or repair may proceed at the current revision/fence once uncertainty is cleared.
Stops do not resolve uncertain creation, limits or ingress effects without those
owners' evidence. No cross-store atomicity or unauthenticated recovery path is implied.

The immutable stop-only projection retains its first command solely for target
identity and emergency containment. Under the inventory singleton, supervision
resolves the current binding/container to an actual applied start receipt at the
current access epoch and preceding binding revision. It does not manufacture a new
command by copying a newer epoch onto old intent. Missing/stale authority remains
fail-closed; independent physical/profile/external-deny checks still apply. Lookup
loads only the matching command in one SQL query, not the target's entire history.
