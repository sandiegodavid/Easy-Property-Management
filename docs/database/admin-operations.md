# Admin operations, audit and protection observations

[Database schema catalog](../DATABASE_SCHEMA.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

In this guide: [`operations` — H04 supported manual effects](#operations--h04-supported-manual-effects) · [`operation_events` — H04](#operation_events--h04) · [`admin_audit` — H03/H04](#admin_audit--h03h04) · [`workspace_recovery_status` — H05](#workspace_recovery_status--h05)

### `operations` — H04 supported manual effects

Tracks one admitted Admin/infrastructure action from immutable intent through verified
outcome, including interrupted or unknown results. Its identity supports safe retry;
workspace and Admin backup/restore have separate owning operation tables.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operation_id` | `ID` | No | — | Original owning operation identity; see local FK or logical-reference rules. PK. |
| `operator_id` | `ID` | Yes | — | Operator identity; see table scope and relationship rules. FK operators. |
| `component_deployment_id` | `ID` | Yes | — | Scoped component deployment assignment identity. FK component_deployments. |
| `kind` | `TEXT` | No | — | Typed operation/effect kind; see allowed values below. (`provision`, `repair_runtime`, `disable`, `enable`, `rebind`, `retire`, `maintenance_release`). |
| `idempotency_key` | `TEXT` | No | — | Stable caller key identifying the original semantic request. |
| `request_hash` | `HASH` | No | — | Hash of the canonical consequential request parameters. |
| `request_json` | `TEXT` | No | — | Bounded canonical non-secret request for safe replay/reconciliation. |
| `actor_principal_id` | `ID` | Yes | — | Admin principal authorizing the operation, when applicable. FK admin_principals. |
| `system_actor` | `REF` | Yes | — | Registered system actor for an automated operation. |
| `expected_revision` | `REV` | Yes | — | Owning revision expected by the command. |
| `access_epoch` | `REV` | Yes | — | Access authority fence; stale operations must not override it. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`pending`, `running`, `needs_attention`, `unknown`, `succeeded`, `failed`). |
| `effect_reference` | `REF` | Yes | — | Reference to verified external/source effect evidence. |
| `result_json` | `TEXT` | Yes | — | Bounded typed original operation result; excludes secrets. |
| `error_code` | `TEXT` | Yes | — | Safe classified failure code. |
| `created_at` | `TIME` | No | — | Creation time. |
| `updated_at` | `TIME` | No | — | Most recent update time. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

UNIQUE `(kind, idempotency_key)` deployment-wide. Require exactly one non-null actor
among actor_principal_id and system_actor. These are main Admin/infrastructure operations;
backup/restore records do not belong here. Admin backup/restore uses the separate
Admin recovery DB; workspace backup/restore uses its own operator recovery DB.
Workspace recovery likewise requires no main Admin DB transaction or availability. Runtime repair instead uses kind=repair_runtime,
with current operator/workspace, resource binding, compatible release and expected fence
in its canonical request. It replaces only the runtime, preserves all business/auth/
recovery data and account identity, and cannot authorize a restore or initialize an
empty portfolio. Original operation/host receipts provide safe repair retry proof.
Schema-validated allowlisted request/result <=16 KiB each, no business content/secrets.
Persist the canonical non-secret intent alongside its hash so retry never reconstructs
old parameters from a subsequently changed assignment. For `provision`, the request
contains `initial_data` (`empty` by default, or `synthetic`), with the selected seed
bundle/version reference when synthetic. Include these in the semantic request hash.
The same request records `capacity_profile_ref` and a typed `admission_commitment`
covering reserved warm memory/CPU and physical workspace/control/scratch byte/inode
budgets. Admission checks active plus pending/unknown commitments in one control
transaction; no hard-coded five-operator limit or duplicate capacity ledger is added.
Five is an initial qualification target. Release commitments only after verified
cleanup/reconciliation; retained data allocations remain counted.
This is historical provisioning intent, not an operator mode or continuing entitlement.
After enablement all operators follow the same access, tier and business rules; never
branch runtime behavior on how their starting records were created. Replaying a completed
provisioning operation returns its result and cannot seed again or overwrite live data. Terminal
result immutable; unknown is not failed. Operator ID required for operator effects, including workspace-scoped releases;
validate it matches the referenced component assignment. Null operator is allowed for a deployment-scoped component release, not for
backup/restore operations owned by another store. A release operation
pins component_deployment_id, target release and expected assignment revision in its
canonical request; a scope mismatch is rejected by the owning transaction. Index `(operator_id, created_at, operation_id)`
and `(state, updated_at, operation_id)`. H04 manually invokes supported tools with this
identity; no job scheduler/lease/step journal required for optional synthetic seeding.

### `operation_events` — H04

Provides ordered, safe progress messages for an operation’s status view. It complements
the operation’s current state without storing raw process logs or a business-write journal.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operation_id` | `ID` | No | — | Original owning operation identity; see local FK or logical-reference rules. FK operations. |
| `sequence` | `INTEGER` | No | — | Monotonic event number within an operation. > 0. |
| `event_code` | `TEXT` | No | — | Safe typed progress/result event. |
| `safe_summary` | `TEXT` | No | — | Bounded operator-safe event description. |
| `recorded_at` | `TIME` | No | — | Time the record or event was persisted. |

PK `(operation_id, sequence)`.
Append-only coarse operator-safe progress/result, not raw subprocess logs. Events and
operation status commit together; cursor on PK. This is bounded lifecycle evidence,
not a per-business-write or synthetic-seed replay journal.

### `admin_audit` — H03/H04

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `audit_id` | `ID` | No | — | Immutable audit event identity. PK. |
| `actor_ref` | `REF` | No | — | Safe identity reference for the attributed actor. |
| `action` | `TEXT` | No | — | Audited action code. |
| `operator_id` | `ID` | Yes | — | Operator identity; see table scope and relationship rules. FK operators. |
| `operation_id` | `ID` | Yes | — | Original owning operation identity; see local FK or logical-reference rules. FK operations. |
| `recorded_at` | `TIME` | No | — | Time the record or event was persisted. |
| `safe_facts_json` | `TEXT` | No | — | Bounded allowlisted non-secret audit facts. (<=8 KiB). |

Append-only, allowlisted IDs/revisions/status only; no token/email/body dumps.
Indexes `(operator_id, recorded_at, audit_id)` and `(operation_id)`.
Owning mutation/result/audit commit together; audit failure rolls back its transaction.
Cross-store effects get independent source receipts, not fictitious central atomicity.

### `workspace_recovery_status` — H05

Gives Admin a compact, asynchronously reported view of each workspace’s protection
health. It is a monitoring projection, not the backup catalog or authority to start
or authorize a workspace restore.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operator_id` | `ID` | No | — | PK/FK operators; one latest summary per operator. |
| `workspace_id` | `ID` | No | — | Logical owning workspace; validate against registry assignment. |
| `source_epoch` | `REV` | No | — | Verified reporting source incarnation/fence. |
| `source_revision` | `REV` | No | — | Monotonic recovery-store observation revision within that epoch. |
| `latest_point_ref` | `REF` | Yes | — | Logical local/off-host recovery point reference, not an Admin FK. |
| `captured_at` | `TIME` | Yes | — | Actual capture time of the latest protected point. |
| `verified_at` | `TIME` | Yes | — | Actual completed off-host verification time. |
| `checked_at` | `TIME` | No | — | Time the owning source last evaluated protection. |
| `observed_at` | `TIME` | No | — | Time Admin received the observation. |
| `dirty_since` | `TIME` | Yes | — | Earliest known unprotected committed change. |
| `protection_state` | `TEXT` | No | — | CHECK healthy, unchanged, overdue, unavailable or unknown. |
| `active_operation_ref` | `REF` | Yes | — | Logical local recovery operation for support/status. |
| `revision` | `REV` | No | — | Admin projection revision. |

Visibility only: async source-authenticated reports, no recovery authorization or queue.
Accept reports only for the current registered workspace/source epoch and increasing
source_revision. A stopped/unreachable source leaves the last observation stale/unknown,
not zero or healthy. Do not rewrite capture time on heartbeat. Admin outages do not stop
workspace backup or restore; retry publishing the newest summary afterward. Index
`(protection_state, observed_at, operator_id)` supports bounded monitoring.

