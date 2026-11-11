# Operator access, sessions and usage control

[Database schema catalog](README.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

In this guide: [Pilot 0 per-operator access store](#pilot-0-per-operator-access-store) · [`access_meta` — H03/H04](#access_meta--h03h04) · [`access_sessions` — H03](#access_sessions--h03) · [`access_receipts` — H03/H04](#access_receipts--h03h04) · [`access_audit` — H03](#access_audit--h03) · [`usage_state` — H04](#usage_state--h04) · [`usage_reservations` — H04](#usage_reservations--h04) · [`draft_leases` — H03 reuse existing unfinished-form fencing](#draft_leases--h03-reuse-existing-unfinished-form-fencing)

## Pilot 0 per-operator access store

### `access_meta` — H03/H04

Internal source authority only. Never expose this row or its storage representation
through Operator, Admin, Tenant or Owner portals, public APIs, downloadable reports
or portable business exports. No user-facing editor may modify it directly. Owning
services enforce and change it through validated application commands; authenticated
private control ports return only allowlisted observations/receipts. Portals receive
purpose-built safe projections such as access availability, maintenance status and
storage allowance, without internal fences, generations, binding IDs or identity-proof
metadata. Such projections report status; they never become access authority.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `id` | `INTEGER` | No | — | Singleton row key. PK CHECK=1. |
| `deployment_id` | `ID` | No | — | Hosted deployment identity. |
| `operator_id` | `ID` | No | — | Operator identity; see table scope and relationship rules. UNIQUE. |
| `workspace_id` | `ID` | No | — | Stable business workspace identity. UNIQUE. |
| `binding_id` | `ID` | No | — | Registered resource binding identity. |
| `resource_generation` | `REV` | No | — | Generation distinguishing resource incarnations. |
| `issuer` | `REF` | No | — | Verified identity provider issuer. |
| `subject` | `TEXT` | Yes | — | Provider subject bound to the identity. |
| `email_key` | `TEXT` | No | — | Provider-qualified normalized email used for matching. |
| `effective_access` | `TEXT` | No | — | Verified source access state, independent of central desired state. (`disabled`, `enabled`). |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `session_generation` | `REV` | No | — | Generation used to invalidate prior sessions. |
| `not_before` | `TIME` | No | — | Authentication validity boundary rejecting older proof. |
| `effective_policy_id` | `ID` | No | — | Verified applied policy; logical Admin-store reference. |
| `usable_bytes` | `BYTES` | No | — | Advertised logical workspace allowance in bytes. > 0. |
| `policy_revision` | `REV` | No | — | Applied policy revision. |
| `maintenance_operation_id` | `ID` | Yes | — | Operation owning the current maintenance gate, if any. |
| `restore_generation` | `REV` | No | — | Generation advanced for restored source authority. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

Initialize disabled, subject null, fixed Free policy/allowance, no session, epoch pinned
to the admitted registry assignment. Enable only with current readiness/off-host point,
verified claim and exact resource identity; compare source fence in the same transaction.
Subject rebinding invalidates generations. CHECK enabled requires subject and an admitted binding; freshness/readiness proofs
are service invariants checked under the source fence, not expressible as cross-store
SQL CHECKs. No account-expiry field or wall-clock auto-disable.
Policy references are logical; source checks command proof, never opens the Admin DB.

`effective_policy_id`, `usable_bytes` and `policy_revision` are internal applied state,
not caller-editable entitlement fields. Change them only through the owning authenticated
`apply_policy` command with admitted policy/version, original operation identity,
current fences and verified application evidence. Browser requests cannot select an
arbitrary policy or allowance; a subscription request alone does not authorize application.
Reject stale/replayed conflicting changes and reconcile policy observations against
current Admin intent and protected host receipts rather than trusting a reported tier.

Independently enforce physical byte/inode ceilings through the privileged host boundary.
The Operator process must have no ability to modify project assignments, ceilings or
protected policy configuration. Editing local policy fields must not increase those
ceilings or authorize a paid benefit. Host changes resolve registered resources and
admitted control-plane authority, never a local field as their sole authorization.
Physical ceilings include qualified headroom and may exceed logical allowance; they
limit damage but do not prove exact logical subscription enforcement after a runtime
compromise. Unexpected policy/limit divergence requires an alert, investigation and
external containment when compromise is suspected, without deleting retained data.
H02/H04 must prove local-field tampering cannot increase host limits; later paid slices
must also prove it cannot grant externally controlled paid capabilities.

### `access_sessions` — H03

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `session_hash` | `HASH` | No | — | Hash of the session secret; no raw cookie is stored. PK. |
| `csrf_hash` | `HASH` | No | — | Hash of the CSRF secret. |
| `actor_subject` | `TEXT` | No | — | Verified identity subject owning the session. |
| `handoff_id` | `ID` | No | — | Central-login handoff identity. UNIQUE. |
| `generation` | `REV` | No | — | Session generation bound at issuance. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `issued_at` | `TIME` | No | — | Session issuance time. |
| `expires_at` | `TIME` | No | — | Expiry of this temporary capability/session/lease, not of the operator account. |
| `managed_valid_until` | `TIME` | No | — | Independent validity limit of managed authentication proof. |
| `last_seen_at` | `TIME` | No | — | Throttled last-observed session activity. |
| `revoked_at` | `TIME` | Yes | — | Explicit session revocation time. |

Indexes `(generation, revoked_at, expires_at)` and `(expires_at)`.
30-day maximum EPM remembered session; managed proof must remain independently valid
through supported refresh, never beyond its own validity. Hash-only cookie, do not
archive usable sessions. Bound each operator to 32 live sessions initially, with visible
old-device revocation; throttled last-seen updates avoid a DB write on every read.
No tenant/owner role enum yet: their grant/session extension belongs to portal tasks.

### `access_receipts` — H03/H04

Records the original result of an access or policy command together with its source
fence. It supports retry and Admin reconciliation without treating central intent
as proof that the Operator service applied the change.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operation_id` | `ID` | No | — | Original owning operation identity; see local FK or logical-reference rules. PK. |
| `request_hash` | `HASH` | No | — | Hash of the canonical consequential request parameters. |
| `kind` | `TEXT` | No | — | Typed operation/effect kind; see allowed values below. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `source_revision` | `REV` | No | — | Owning source revision recorded in the receipt. |
| `result_json` | `TEXT` | No | — | Bounded typed original operation result; excludes secrets. (typed <=16 KiB). |
| `recorded_at` | `TIME` | No | — | Time the record or event was persisted. |

CHECK kind IN (`initialize_binding`, `enable`, `disable`, `revoke_sessions`,
`rebind`, `claim`, `maintenance_fence`, `restore_binding`, `apply_policy`).
Persist result/audit and owning access mutation atomically; use the receipt for retry
without returning a raw session token. Expired authority cannot be extended by replay.

### `access_audit` — H03

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `audit_id` | `ID` | No | — | Immutable audit event identity. PK. |
| `operation_id` | `ID` | Yes | — | Original owning operation identity; see local FK or logical-reference rules. |
| `action` | `TEXT` | No | — | Audited action code. |
| `actor_ref` | `REF` | No | — | Safe identity reference for the attributed actor. |
| `recorded_at` | `TIME` | No | — | Time the record or event was persisted. |
| `safe_facts_json` | `TEXT` | No | — | Bounded allowlisted non-secret audit facts. (<=8 KiB). |

indexes `(operation_id)` and `(recorded_at, audit_id)`.
No business source data in access audit; control backup may retain this audit separately.

### `usage_state` — H04

Stores the latest source-bound measurement of committed business database and retained
file usage. Admission combines this measurement with outstanding reservations; a stale
or missing measurement cannot be treated as an empty workspace.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `id` | `INTEGER` | No | — | Singleton row key. PK CHECK=1. |
| `business_revision` | `REF` | No | — | Captured/observed business source revision. |
| `committed_db_bytes` | `BYTES` | No | — | Committed non-freelist business database bytes, including indexes. |
| `retained_file_bytes` | `BYTES` | No | — | Retained managed blob bytes counted once per content identity. |
| `observed_at` | `TIME` | No | — | Time the state or usage was observed. |
| `measurement_version` | `REF` | No | — | Version of the logical storage measurement definition. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

Total is derived, not another mutable column.
Count committed non-freelist business pages times page size, including indexes; count
retained managed blob bytes once per immutable content identity. Do not count the same
state again as WAL, backup or scratch. Missing/stale measurement is unknown, not zero.
H04 must reconcile this definition against exact source/store snapshots and physical
headroom; if proof fails, block growth rather than silently redefine the allowance.

### `usage_reservations` — H04

Reserves space before a potentially growing operation so concurrent requests cannot
spend the same remaining allowance. The reservation is settled against the owning
source result, including reconciliation after a crash or lost response.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `reservation_id` | `ID` | No | — | Durable storage admission reservation identity. PK. |
| `operation_id` | `ID` | No | — | Original owning operation identity; see local FK or logical-reference rules. UNIQUE. |
| `request_hash` | `HASH` | No | — | Hash of the canonical consequential request parameters. |
| `reserved_bytes` | `BYTES` | No | — | Bytes reserved before the source operation. > 0. |
| `purpose` | `TEXT` | No | — | Typed reason for the storage reservation. |
| `source_epoch` | `REV` | No | — | Source authority epoch at reservation admission. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`held`, `committed`, `released`, `unknown`). |
| `created_at` | `TIME` | No | — | Creation time. |
| `updated_at` | `TIME` | No | — | Most recent update time. |
| `result_revision` | `REF` | Yes | — | Confirmed business result revision used to reconcile the reservation. |

Index `(state, created_at, reservation_id)`. Reservation admission is serialized against
usage+held/unknown reservations; unknown effects retain their allocation until source
reconciliation, not time-based release alone. Because stores cannot commit atomically,
reserve first, perform the source-owned command, reconcile its immutable result and
measurement, then settle reservation. Crashes may overreserve temporarily, never admit
extra growth on an assumed rollback. Operational headroom is bounded separately.

### `draft_leases` — H03 reuse existing unfinished-form fencing

Tracks temporary edit ownership of unfinished forms across sessions/devices; “lease”
here means an editing lock, not a rental contract. It stores ownership/fences, not
the form contents, and supports controlled takeover without silent conflicting edits.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `record_id` | `ID` | No | — | Unfinished-form record whose edit ownership is fenced. PK. |
| `session_hash` | `HASH` | No | — | Hash of the session secret; no raw cookie is stored. |
| `lease_token_hash` | `HASH` | No | — | Hash of the edit-ownership lease secret. UNIQUE. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `expires_at` | `TIME` | No | — | Expiry of this temporary capability/session/lease, not of the operator account. |
| `renewed_at` | `TIME` | No | — | Most recent edit-lease renewal time. |

Index `(expires_at)`. Logical session reference: no cascading deletion that silently
releases an unresolved business attempt. Check session/grant/epoch and current form
ownership through owning ports; explicit takeover preserves existing conflict semantics.
No raw unfinished form body in this access store.

