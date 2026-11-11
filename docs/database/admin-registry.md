# Admin registry, policies and release assignments

[Database schema catalog](../DATABASE_SCHEMA.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

In this guide: [Pilot 0 Admin database](#pilot-0-admin-database) · [`control_meta` — H02 protected initialization](#control_meta--h02-protected-initialization) · [`storage_policies` — H04 Free policy](#storage_policies--h04-free-policy) · [`qualified_releases` — H02 release qualification](#qualified_releases--h02-release-qualification) · [`component_deployments` — H02 shared Admin; H04 Operator assignments](#component_deployments--h02-shared-admin-h04-operator-assignments) · [`operators` — H03/H04 assignment and desired state](#operators--h03h04-assignment-and-desired-state)

## Pilot 0 Admin database

H02 implements the complete Pilot 0 main-Admin structural baseline across this guide,
[identity](admin-identity.md) and [operations](admin-operations.md), keeping all local
FKs intact. Table phase labels describe owning behavior/population, not independent
partial database baselines. H02 initializes protected deployment metadata only;
H03/H04 own identity, policy/operator population and application actions. H05 owns
workspace protection reporting. No operator, session or fake qualified release is
created by schema initialization. See [accepted H02 decisions](../hosting/design/HOSTED_MVP_H02_DESIGN.md#resolved-design-decisions).

### `control_meta` — H02 protected initialization

<a id="control_meta--h04-initialization"></a>

Identifies the hosted deployment and its trusted public/login origins. Its registry
generation distinguishes current control authority from stale state after recovery.

One row (`id = 1`).

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `id` | `INTEGER` | No | — | Singleton row key. PK. |
| `deployment_id` | `ID` | No | — | Hosted deployment identity. UNIQUE. |
| `public_base_domain` | `TEXT` | No | — | Configured public domain for workspace subdomains. |
| `login_origin` | `TEXT` | No | — | Exact configured central login origin. |
| `registry_generation` | `REV` | No | — | Registry recovery/rebinding generation. |
| `created_at` | `TIME` | No | — | Creation time. |

Origin/domain match protected deployment configuration, not request
headers. Generation changes only through explicit recovery/rebinding. No secret values.

### `storage_policies` — H04 Free policy

Defines immutable, versioned plan rules for usable storage, backup cadence/retention
and warm-runtime behavior. Operators request a policy through `desired_policy_id`;
the source records the verified applied policy separately.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `policy_id` | `ID` | No | — | Immutable storage policy identity. PK. |
| `plan_code` | `TEXT` | No | — | Plan to which this policy applies. (Pilot 0 CHECK = `free`). |
| `policy_version` | `INTEGER` | No | — | Version of the plan policy. > 0. |
| `usable_bytes` | `BYTES` | No | — | Advertised logical workspace allowance in bytes. > 0. |
| `backup_interval_seconds` | `COUNT` | No | — | Scheduled backup interval in seconds; not a recovery SLA. > 0. |
| `retained_nightly_points` | `COUNT` | No | — | Number of nightly recovery points to retain. > 0. |
| `keep_warm` | `BOOLEAN` | No | — | Whether the policy keeps the runtime running. |
| `created_at` | `TIME` | No | — | Creation time. |

UNIQUE `(plan_code, policy_version)`. H04 inserts Free v1: 50,000,000 bytes,
86,400-second scheduling baseline, seven nightly points, keep_warm=1 for Pilot 0.
Actual protection health uses completed-point age; the interval is not an SLA.
No MB/MiB conversion ambiguity. No paid rows before H08; no arbitrary policy editor.

### `qualified_releases` — H02 release qualification

Catalogs exact release artifacts that have passed qualification, together with their
compatibility evidence. Deployment assignments select from this catalog; a published
image tag alone is not an approved release.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `release_id` | `ID` | No | — | Qualified release identity. PK. |
| `component` | `TEXT` | No | — | Portal component to which this record applies. (`admin`, `operator`, `tenant`, `owner`). |
| `artifact_kind` | `TEXT` | No | — | Release artifact format. (`oci_image`, `web_bundle`). |
| `artifact_digest` | `HASH` | No | — | Digest of exact immutable artifact bytes. |
| `artifact_ref` | `REF` | No | — | Registered immutable artifact location/reference. |
| `compatibility_manifest_ref` | `REF` | No | — | Reference to the pinned compatibility manifest. |
| `compatibility_manifest_sha256` | `HASH` | No | — | Digest of the compatibility manifest. |
| `business_schema_revision` | `REF` | Yes | — | Owned business schema revision, when applicable. |
| `access_schema_revision` | `REF` | Yes | — | Owned hosted-access schema revision, when applicable. |
| `admin_schema_revision` | `REF` | Yes | — | Owned main Admin schema revision, when applicable. |
| `admin_recovery_schema_revision` | `REF` | Yes | — | Owned separate Admin recovery schema revision, when applicable. |
| `inventory_schema_revision` | `REF` | Yes | — | Owned host inventory schema revision, when applicable. |
| `recovery_schema_revision` | `REF` | Yes | — | Owned per-operator recovery-store schema revision, when applicable. |
| `qualification_ref` | `REF` | No | — | Reference to release qualification evidence. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`qualified`, `withdrawn`). |
| `qualified_at` | `TIME` | No | — | Time release qualification was recorded. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

UNIQUE `(component, artifact_digest)` and `(release_id, component)`. The digest identifies
exact immutable bytes; OCI references also pin the registry manifest digest. Typed
compatibility manifest pins API contracts, required source/agent versions and supported
owned/read schema revisions. Null means the artifact does not own that store, never
“accept any schema.” Admin/Operator OCI images are separate Pilot 0 artifacts;
Tenant/Owner artifacts are registered only by their later portal backlog. Portal
web bundles own no schema revisions and never run schema upgrades.
Only verified release tooling inserts a qualified row. A tag alone is invalid.
Withdrawal blocks new admission, not blind destruction of existing runtimes. Record
exact compatible versions for Pilot 0; broader coexistence/rollout qualification is H10.

### `component_deployments` — H02 shared Admin; H04 Operator assignments

Tracks which qualified release each portal component should run and which release
has been verified as running. Operator assignments are per operator/workspace;
Admin and future Tenant/Owner assignments are deployment-wide. This supports
independent upgrades and distinguishes a requested release from a completed upgrade.
Release definitions live in `qualified_releases`; `operators` has no duplicate release
assignment.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `component_deployment_id` | `ID` | No | — | Scoped component deployment assignment identity. PK. |
| `deployment_id` | `ID` | No | — | Hosted deployment identity. FK control_meta.deployment_id. |
| `component` | `TEXT` | No | — | Portal component to which this record applies. (`admin`, `operator`, `tenant`, `owner`). |
| `scope_kind` | `TEXT` | No | — | Scope classification; see the table-specific allowed values. (`deployment`, `workspace`). |
| `operator_id` | `ID` | Yes | — | Operator identity; see table scope and relationship rules. |
| `workspace_id` | `ID` | Yes | — | Stable business workspace identity. |
| `desired_release_id` | `ID` | No | — | Qualified target release for this component assignment. |
| `observed_release_id` | `ID` | Yes | — | Last verified running release projection. |
| `operation_id` | `ID` | Yes | — | Original owning operation identity; see local FK or logical-reference rules. FK operations. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`pending`, `applying`, `applied`, `needs_attention`, `unknown`). |
| `observation_ref` | `REF` | Yes | — | Receipt/manifest reference proving the observed artifact and target generation. |
| `observed_at` | `TIME` | Yes | — | Time the state or usage was observed. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |


Constraints and indexes:

- CHECK Operator requires workspace scope and non-null operator/workspace IDs.
  Admin/Tenant/Owner require deployment scope with both IDs null.
- Composite FK `(operator_id, workspace_id)` references operators
  `(operator_id, workspace_id)`, preventing a mismatched workspace assignment.
- Partial UNIQUE `(deployment_id, component)` WHERE scope_kind=deployment;
  partial UNIQUE `(deployment_id, component, workspace_id)` WHERE scope_kind=workspace.
  These enforce one shared assignment per component and one Operator assignment per
  workspace without relying on nullable-key uniqueness.
- Composite FKs `(desired_release_id, component)` and `(observed_release_id, component)`
  reference qualified_releases `(release_id, component)`; cross-component assignments
  are invalid. Index `(state, component, component_deployment_id)` supports bounded
  status/rollout reads. CHECK applied requires desired_release_id=observed_release_id,
  non-null observation_ref and observed_at.

This is the only editable release-assignment authority for all four components.
H02 supplies this table's structure. Populate the shared Admin assignment only when
its artifact is genuinely qualified; unavailable candidate builds remain protected
build evidence, not qualified_releases rows or production assignments. H04 creates
each Operator assignment
atomically with its operator/operation/audit before provisioning can start. Within
that transaction insert identity and assignment with operation_id null, insert the
operation referencing the assignment, then link operation_id before commit; this
resolves the local FK cycle without disabling foreign-key enforcement. Reject
provision/enable if that exact assignment is missing or incompatible. Tenant/Owner
rows arrive only with their later qualified portal delivery; no placeholder releases.
Operator identity rows contain no desired release column.

H03–H05 component tests may use explicitly synthetic assignments/qualified-release
fixtures in isolated stores. They do not promote an incomplete production artifact;
repeat full installed-image/schema qualification after owning resources/assets arrive
and before H06 admission. H02's infrastructure acceptance cannot stand in for that gate.

Actual running images/resource identities remain authoritative in host inventory or
the owning component's deployment observation. observed_release_id is a verified
projection tied to its receipt/manifest and target generation through observation_ref,
not another manually editable actual state. A changed desired release increments
revision and returns pending; preserve the prior observation until new proof arrives.
Only a matching current operation/revision may mark applied; stale observations cannot
undo a newer assignment. Unknown effects remain unknown until reconciled.

A rollout changes only the targeted component_deployment_id; another Operator workspace
or compatible shared portal retains its own assignment. H10 adds scheduling/rollout
records. Admin self-upgrade status/recovery remains accessible through supported
restricted tooling if its UI stops. Retain assignments for retired operators as history;
release status never overrides account retirement or access disablement.

Access is through the Admin-owned application boundary: Admin requests assignments
and trusted deployment tooling records verified observations. Operator services and
browsers have no direct Admin database/table access. An authenticated private control
API supplies a workspace-scoped safe observation to the Operator backend, which exposes
only user-facing version/update/maintenance status and freshness through its own API.
See the [release projection contract](../hosting/design/mvp/releases.md#operator-visible-release-projection)
for asynchronous refresh, bounded caching and stale/unavailable behavior. This view
is informational; it cannot authorize release changes or clear enforcement gates.

Detailed operator scheduling design belongs to H10. Future preferences and scheduling
requests remain separate from this assignment table and reference its scope/revision
and operation identity through validated commands. Do not add scheduling columns now
or let an operator directly mutate assignments/verified observations. This preserves
the extension path while Pilot 0 uses a shared announced maintenance window.

### `operators` — H03/H04 assignment and desired state

Registers each operator’s identity, workspace/subdomain, requested access and storage
policy, and setup progress. Applied access/storage and running releases are tracked
by their owning stores or deployment assignments rather than inferred from this row.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operator_id` | `ID` | No | — | Operator identity; see table scope and relationship rules. PK. |
| `workspace_id` | `ID` | No | — | Stable business workspace identity. UNIQUE. |
| `display_name` | `TEXT` | No | — | Operator display name. |
| `invited_email` | `TEXT` | No | — | Intended operator sign-in email. |
| `email_key` | `TEXT` | No | — | Provider-qualified normalized email used for matching. UNIQUE. |
| `workspace_slug` | `TEXT` | No | — | Normalized public workspace subdomain slug. UNIQUE. |
| `issuer` | `REF` | No | — | Verified identity provider issuer. |
| `subject` | `TEXT` | Yes | — | Provider subject bound to the identity. |
| `desired_policy_id` | `ID` | No | — | Requested storage policy. FK storage_policies. |
| `desired_access` | `TEXT` | No | — | Requested account access state, not effective authority. (`enabled`, `disabled`, `retired`). |
| `setup_state` | `TEXT` | No | — | Provisioning and claim lifecycle state. (`pending`, `preparing`, `ready_for_claim`, `active`, `needs_attention`, `retired`). |
| `support_contact` | `TEXT` | No | — | Operator support contact. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |
| `created_at` | `TIME` | No | — | Creation time. |
| `updated_at` | `TIME` | No | — | Most recent update time. |
| `retired_at` | `TIME` | Yes | — | Time explicit retirement was recorded. |

UNIQUE `(operator_id, workspace_id)` for the assignment composite FK;
UNIQUE `(issuer, subject)` WHERE subject IS NOT NULL. Slug normalized lowercase,
reserved infrastructure slugs rejected; retain retired rows/slugs initially. `email_key`
is provider-qualified normalization, not Gmail dot/plus rewriting. Email equality
alone never links subjects. Default desired access is enabled but source access starts
DISABLED until readiness and claim; this is intent, not effective authority. No operator
expiry column. Only explicit Admin actions disable/retire an operator. Release selection
is owned solely by the workspace-scoped component_deployments row, not this table.
CHECK active setup requires a bound subject; retired setup requires retired_at and
desired_access=retired. CHECK updated_at >= created_at.
Indexes: `(setup_state, operator_id)`, `(desired_access, operator_id)`.
Rebinding subject/email needs a dedicated recent-auth Admin operation, new epoch,
revoked invitations/sessions and fresh verified claim; no generic PATCH of identity.

#### Access-state decision and external enforcement

Retain `operators.desired_access` as Admin intent and `access_meta.effective_access`
as locally applied source state. This separation supports local session checks without
an Admin DB lookup per request and makes pending/failed application explicit. It adds
reconciliation work; it is not a security barrier against a compromised Operator
process, which may have write access to its own access store or bypass its own checks.
Ordinary portal users have no direct database access or state-editing interface.

Admin disablement/retirement must also install a durable deny at the trusted gateway
outside the operator container. The container must not hold credentials or permissions
to change that deny, public routing or host lifecycle controls. Block direct-origin
access; deny existing as well as new request paths, terminating long-lived connections
or stopping/fencing the container where needed to make containment effective. A local
`effective_access = enabled` value must never override this external restriction.

Record the original operation, expected epoch/revision and verified external/source
results through owning `operations`/`operation_events`, protected host receipts where
applicable, and source `access_receipts`. These are separate stores and commits. Do
not treat desired state or a source receipt alone as proof of external enforcement.
Show disablement complete only after required external containment and source
disable/session-revocation are verified. If the source is unreachable but external
containment is confirmed, report containment with source reconciliation pending;
otherwise retain pending/unknown and escalate. Do not label partial success complete.

The external deny survives gateway/container restart and replacement. Missing or
unverifiable required routing/enablement authority fails closed. Only a fresh admitted
Admin enable operation, current readiness/identity checks and matching fences can
remove it; stale enable/provision receipts cannot reopen access. H02/H03 own the
protected gateway projection, verification and reconciliation contracts; H04 surfaces
safe progress. No public editor or second editable registry is introduced.

