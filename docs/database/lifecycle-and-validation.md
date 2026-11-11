# Initialization, retention and schema validation

[Database schema catalog](../DATABASE_SCHEMA.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

In this guide: [Initialization, recovery and retention](#initialization-recovery-and-retention) · [Later-slice schema additions — not Pilot 0 tables](#later-slice-schema-additions--not-pilot-0-tables) · [Schema validation matrix](#schema-validation-matrix)

## Initialization, recovery and retention

1. Install owning schema resources. Private file creation is exclusive and rejects
   existing mismatched/nonempty stores, unsafe paths and wrong permissions. Never let
   ordinary startup silently create a new empty registry or workspace after loss.
2. H02 installs one complete main-Admin structural baseline, including identity,
   operations and observation tables needed for its local FK closure, and initializes
   protected deployment metadata. H03 owns protected Admin identity bootstrap; H04
   owns Free policy and operator/application population. Candidate builds do not seed
   qualified releases or assignments: insert genuinely qualified Admin/Operator
   releases and the shared Admin assignment only after the owning artifact gates pass.
   Synthetic test fixtures are not production qualification. Separately initialize
   Admin recovery schema/meta from protected deployment/recovery-authority bindings,
   with null checkpoint and no active operation. Initialize agent inventory from verified
   host/filesystem identity.
   No example operators, paid policy rows, sessions or credentials are seeded.
3. Add operator transaction inserts the operator identity, workspace-scoped Operator
   component_deployments assignment, one operation and audit. Agent allocates
   registered resources with access disabled; source initializes business, access and private recovery
   schemas, Free policy binding and counters. Optional synthetic seed is a supported
   wrapper around `application/demo/seed.py`, not a new seed journal. Verify source
   readiness/routing/isolation and a first recoverable point before invitation.
4. Identity claim and effective enablement use operation/epoch receipts; central
   `active` setup observation follows source proof. A later disable increments epoch
   and wins over delayed activation. Unknown effects require inspection/reconciliation.
5. The internal operator scheduler captures/verifies workspace backups and commits its
   local recovery catalog/checkpoint/audit. It asynchronously reports a safe summary to
   Admin; reporting failure never invalidates or stops the completed backup. The Admin service
   backs up main Admin/inventory/config state through its separate Admin recovery store;
   restricted platform tooling supports recovery when the service cannot start. Off-host manifests and protected
   bootstrap/key custody remain recoverable without either local DB or the Admin portal.
6. Normal self-service restore runs in the same operator service; minimal recovery
   mode starts auth/recovery routes without business schema/DB bootstrap. No offline
   workspace restore/decrypt command. Repair failed runtime/identity before fresh
   authentication; reconstruct missing catalog only inside authenticated recovery mode
   by verified own-workspace manifests. Never restore old sessions or jobs.

Audit/operation/receipt/retired assignment records are retained through Pilot 0; monitor
size in separate control reserves. Expired sessions/handoffs/invitations can be purged
after 24-hour diagnostic retention, but keep non-secret claim/audit lineage. Admission
must stop if reserves cannot hold required evidence; do not delete unresolved receipts
or grow unlimited event logs. H07 designs compaction/retention before scaling. Backup
point expiry follows seven-night policy without deleting chain objects still referenced
by another retained manifest. Recovery metadata references outlive their object expiry
until verified cleanup is recorded.

## Later-slice schema additions — not Pilot 0 tables

| Slice | Required extension design |
| --- | --- |
| H07 | Durable job claims/leases, effect steps, delivery outbox, host placement/reservations; keep original H04 operation identities and receipts. |
| H08 | Qualify internal backup execution against paid protection objectives before selling them; versioned paid policies, effective allocation/metering changes, safe overage ceilings and recovery thinning/reference retention. Free runtime warm policy changes only with H11 acceptance. |
| H09 | Billing event inbox, provider subscription references, desired/effective capability projection, scheduled changes/grace and compensation. No provider/card secrets or parallel financial truth. |
| H10 | Per-component API/schema compatibility paths and independent rollout/upgrade operations; per-operator preferred time zone/window and bounded batches. Never couple all portal versions to one release row. |
| H11 | Desired/observed sleep/runtime state and deduplicated wake operations; bounded ephemeral activity preferred over durable per-request history. |
| PORTAL/FIN/PAY | Separate role grants and source-owned late-fee/payment records. Extend this master when designed; never add them speculatively to H01. |

## Schema validation matrix

| Area | Required proof by the owning implementation slice |
| --- | --- |
| Happy paths | Fresh private stores, one Free operator, verified claim, multiple devices, first/nightly recovery and supported restore. |
| Invalid combinations | Duplicate slug/subject/project ID; null policy; wrong workspace/epoch; source enabled without readiness; unknown enum; malformed JSON/result; wrong schema/permissions. |
| Retry/idempotency | Original operation replay; changed hash conflict; duplicate claim/handoff; unknown host/access result; reserve/source-success/crash reconciliation. |
| Rollback | Failure between record/audit/receipt writes leaves none committed; cross-store failure stays safely pending/unknown, not falsely atomic. |
| Persistence | Exact current columns/types/constraints/indexes, FK checks, revision/state transitions, initial population, latest greenfield baseline and restart behavior. |
| Host authority | Unique operator UID/GID mapping retained across resource replacement; ingress scope/binding-generation FKs, monotonic current fences and safe unknown observations; deterministic parent/child effect identity, duplicate-key reconciliation and immutable request preservation. |
| Backup/restore | Operator-selected/authorized own-workspace restore, no Admin approval; qualified strong-step-up and exact-action proof; no offline/Admin impersonation path; cross-workspace/tenant/owner denial, authorization expiry and duplicate/conflicting jobs; DB/files and separate main Admin and Admin recovery stores recover consistently without losing active restore evidence; current recovery principal is verified without trusting damaged/restored Admin rows; corrupt/missing/key failure; stale jobs/sessions/grants never revived; prior destination retained; internal authenticated business-DB-independent recovery mode, interrupted switch, runtime/auth failure stays closed; stolen session, forged Admin, replay/path/key/object attacks rejected; Admin outage does not block workspace backup/restore. |
| Admin recovery separation | Main Admin corruption/replacement leaves catalog/checkpoint/operation/audit readable; reject main-DB FKs and recovered-session authority; independently authenticate current recovery principal; main-only/recovery-only/host loss, interrupted switch, duplicate restore and local audit rollback; no automatic job replay. |
| Query budget | Indexed session lookup and expiry cleanup, bounded Admin list/status projection without per-row source calls, bounded events/catalog pages and indexed reservation sum. |

Before deployment keep one latest greenfield schema per store, with no legacy migration
project. Once real Pilot 0 records exist, future slices must upgrade admitted versions
safely; recreating stores is not an acceptable way to avoid preserving customer records.
