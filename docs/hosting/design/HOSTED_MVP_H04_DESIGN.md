# HOSTED-001 Slice H04 Design & Implementation Plan — Admin-lite and Free Usage

- **Backlog item**: `HOSTED-001` — Slice **H04** (`Admin-lite and Free usage`) in [delivery-plan.md](mvp/delivery-plan.md)
- **Status**: Approved for implementation (**D1–D10 decided on 2026-11-22**)
- **Baseline checkout**: `hosted_mvp` at `332e7eef` (`H03 complete`, including `63fd487a address H03 review comments`)
- **Greenfield scope**: Keep only the latest format and schema; no migration compatibility work.

---

## 1. Purpose, Scope, and Slice Boundaries

H04 delivers the **Admin-lite operator management workflow**, **Free-tier (`50,000,000`-byte) logical and physical storage admission**, **hosted Operator portal composition**, **Operator Settings (Free pilot)**, and **per-tier Free physical storage sizing qualification** on native Linux/Docker/GCP.

### 1.1 In Scope for H04
- **Admin-lite control plane & UI** (`admin.<domain>`):
  - Add, list, and inspect operators with set-based directory reads (no per-operator DB fan-out).
  - Default empty workspace or optional synthetic sample portfolio (`initial_data: empty | synthetic` with pinned `seed_bundle`).
  - Pinned Free v1 storage policy (`usable_bytes = 50,000,000`, `backup_interval_seconds = 86,400`, `retained_nightly_points = 7`, `keep_warm = 1`).
  - Serialized capacity-profile / commitment admission checks inside the Admin control transaction counting `active`, `pending`, `retained`, `unknown`, and `cleanup_pending` commitments (no hard-coded 5-operator cap).
  - Atomic creation of `operators`, workspace-scoped `component_deployments`, `capacity_commitments`, `operations`, `operation_events`, and `admin_audit`.
  - Supported manual provisioning completion and idempotent retry via Host Agent `AdmissionPort`.
  - Explicit invitation issuance, delivery, and reissue when an operator reaches `ready_for_claim`.
- **Hosted Operator composition & Free usage** (`<slug>.<domain>`):
  - Reuse the existing Operator frontend (`application/apps/web`) and business APIs (`BUSINESS_ROOTS`); do not build a second Operator portal.
  - Compose frontend and business APIs with provisioned workspace storage, current source authority, and qualified Free storage admission (`access_meta.effective_policy_id` / `usable_bytes` / `policy_revision` via `initialize_binding` and `apply_policy`, `usage_state`, and `usage_reservations`).
  - Hosted **Operator Settings** showing **Free pilot**, logical usage/allowance/remaining space/freshness, honest backup protection state (`unavailable` until H05), administrator support contact, and announced maintenance notices, while hiding unavailable paid upgrades, billing, individual scheduling, and idle-wake controls.
  - Preserve local single-operator mode unchanged.
- **Per-tier physical storage sizing qualification (Free `50,000,000` bytes)**:
  - Qualify `workspace`, `control`, and `scratch` physical byte and inode ceilings on native Linux/Docker/GCP using measured allocated-byte and inode high-water marks across database-heavy, retained-file-heavy, and many-small-file/history shapes, justified nonzero byte and inode margins, and independent physical byte exhaustion and inode exhaustion / rollback / UI tests.
- **Deployed handoff boundary with H05**:
  - Wire real Operator provisioning, assignment readiness, invitation claim, and managed business-session inputs.
  - Prove with **two disposable deployed assignments** that missing readiness or missing H05 verified recovery-point protection holds each workspace closed (`desired_state = 'held'`, HTTP `503` on business paths).
  - Verify ordinary portfolio, money, maintenance, file upload, unfinished-form, and two-device workflows through the hosted composition in integration/Playwright tests without substituting fixtures for missing H05 protection in a real deployment.

### 1.2 Explicitly Out of Scope for H04
- **H05**: Backup/restore execution, verified recovery-point catalog, Operator self-service restore UI, backup/restore physical sizing reservations, and opening positive deployed business ingress (`desired_state = 'eligible'`).
- **H06**: Pilot 0 live go-live operations, single maintenance-window release execution, disable/rebind/retire full operator-lifecycle UI beyond H04 containment verification.
- **H07 / H08**: Paid plans, billing, upgrades, idle-wake / cold-start scaling, or individual maintenance scheduling.

---

## 2. Current-Code Assessment (HEAD `332e7eef`)

### 2.1 Reusable Foundations Already Present
- **Admin & Source Contracts (H01)**:
  - `application/apps/server/app/modules/hosted_admin/application/pilot_contracts.py`: `AdminCommand`, `CreateAssignment`, `Provision`, `ReissueInvitation`, `RefreshSource`, `AdminResult`, `AdminObservation`, `AdminPort`, `AdmissionCommitment`, `ResourceCeiling`.
  - `application/apps/server/app/modules/hosted_admin/application/ui_contracts.py`: `AdminList`, `AdminAdd`, `AddDraft`, `AdminDetail`, `OperatorSummary`, `Readiness` (5 independent gates: `isolation`, `schema`, `routing`, `protection`, `binding`).
  - `application/apps/server/app/modules/hosted_access/application/ui_contracts.py`: `Settings` (`delivery_owner = "H04"`), `FreeUsage`, `Protection`, `MaintenanceNotice`, `Section`, `Actions`.
  - `application/apps/server/app/modules/hosted_access/application/source_contracts.py`: `AdmittedFreePolicy`, `InitializeDisabled`, `ApplyPolicy`, `ReserveUsage`, `ReconcileUsage`, `SourceCommand`.
  - `application/apps/server/app/modules/host_agent/application/capacity.py`: pure capacity planner (`Resources`, `Commitment`, `OperatorBudget`, `CandidateCapacityProfile`, `CapacitySnapshot`, `plan_reservation`).
  - `application/apps/server/app/modules/host_agent/application/dispatch.py` & `effect_contracts.py`: `EffectIdentity`, `HostEffect`, `ResourcePlan`, `AdmittedEffect`, `AdmissionPort`.
- **Database Baselines**:
  - `application/database/admin-migrations/versions/admin_0001_initial.py`: `control_meta`, `storage_policies`, `qualified_releases`, `component_deployments`, `operators`, `invitations`, `operations`, `operation_events`, `admin_audit`, `workspace_recovery_status`, plus H03 identity tables and immutability triggers.
  - `application/database/hosted-access-migrations/versions/access_0001_initial.py`: `access_meta`, `access_sessions`, `access_receipts`, `access_audit`, `usage_state`, `usage_reservations`, `draft_leases`, `source_login_attempts`, `source_recent_challenges`.
- **Runtime & Identity Plumbing (H02 / H03)**:
  - `application/apps/server/app/modules/hosted_access/api/admin_identity.py`: Admin Google + TOTP session middleware, CSRF, origin checks, and asset delivery.
  - `application/apps/server/app/modules/hosted_access/infrastructure/central_invitations.py`: `CentralInvitations.issue()` and `claim_from_source()`.
  - `application/apps/server/app/modules/hosted_access/infrastructure/source_lifecycle.py`: `SourceLifecycle` (`claim`, `enable`, `disable`, `rebind`, `revoke`).
  - `application/apps/server/app/modules/hosted_access/infrastructure/operator_identity_runtime.py`, `operator_entry.py`, and `api/managed_business.py`: `DestinationHTTP`, `ManagedBusiness`, `ManagedDraftLeases`.
  - `application/demo/seed.py`: resumable API-driven synthetic portfolio seeder with `dataset.json`.

### 2.2 Concrete Gaps to Close in H04
1. **No Admin-lite control-plane implementation** (`AdminPort` adapter, Free v1 policy bootstrap, capacity ledger persistence, or Admin-lite HTTP endpoints).
2. **No Admin-lite UI** (`application/apps/web/src/admin/main.tsx` currently only renders sign-in/sign-out).
3. **No Host Agent `AdmissionPort` or manual `provision` / retry runner** (`service_runtime.py` currently uses `no_allocations()`).
4. **Source lifecycle & logical storage accounting missing**: `initialize_binding` and `apply_policy` are not yet in `SourceLifecycle`, `usage_state` and `usage_reservations` are unused, and `ManagedBusiness` still wires the retired 250 MiB loop-volume `HostedStorageBudget`.
5. **No Operator hosted Settings API or UI**: `/api/hosted/settings` does not exist; `shell.tsx` has no Free-pilot Settings panel and still contains `"this demo"` placeholder copy.
6. **No qualified Free physical storage sizing**: only trial/placeholder constants exist; no native Linux/Docker/GCP workload high-water mark or byte/inode exhaustion proofs exist yet.

---

## 3. Resolved Contradictions & Design Decisions (D1–D10)

All ten items below are **decided** as of 2026-11-22.

### D1 — `operations.kind` CHECK constraint vs `AdminPort` / `ui_contracts.py` actions — **Decided**
- **Conflict**: `admin_0001_initial.py:406-418` constrains `operations.kind` to `provision | repair_runtime | disable | enable | rebind | retire | maintenance_release` and enforces `ck_operator_effect` (`kind='maintenance_release' OR operator_id IS NOT NULL`). Meanwhile `pilot_contracts.py:160-174` and `ui_contracts.py:177` expect operation outcomes for `create_assignment`, `reissue_invitation`, and `refresh_source` (specifically `AdminDetail.refresh_operation: OperationOutcome[AdminResult] | None`).
- **Decision**: In greenfield `admin_0001_initial.py`, expand `operations.kind` to add `reissue_invitation` and `refresh_source`. `CreateAssignment` atomically creates the `operators` row + `component_deployments` row + initial `operations` row of `kind='provision'` (`state='pending'`).

### D2 — Missing set-based projection table for `AdminList` / `AdminDetail` source observations — **Decided**
- **Conflict**: `ui_contracts.py:34-68` requires `OperatorSummary` to display `access: Section[Access]` (`effective_enabled`) and `usage: Section[FreeUsage]` (`used_bytes`) using `read_strategy="registry_projection_set_based"` (never opening per-operator SQLite files or calling containers during list/detail reads). `admin_0001_initial.py` has `workspace_recovery_status` for protection, but no table or columns for cached source access or usage observations.
- **Decision**: Add a greenfield `operator_source_observations` table to `admin_0001_initial.py` (`operator_id` PK, `workspace_id`, `access_epoch`, `effective_enabled`, `usage_bytes`, `usable_bytes`, `source_revision`, `observed_at`, `checked_at`, `freshness_state`, `revision`), updated exclusively by `refresh_source` and source-lifecycle receipts.

### D3 — Missing capacity ledger & snapshot persistence in Admin DB — **Decided**
- **Conflict**: `host_agent/application/capacity.py:3-4` delegates persistence and serialized reservation commits to H04, and `delivery-plan.md` requires serialized capacity-profile/commitment checks in the control transaction. `admin_0001_initial.py` currently has no capacity tables.
- **Decision**: Add greenfield `capacity_profiles`, `capacity_snapshots`, and `capacity_commitments` tables to `admin_0001_initial.py`. Persist a `pending` commitment atomically inside `CreateAssignment`'s `BEGIN IMMEDIATE` transaction after running `plan_reservation()`. Refresh `capacity_snapshots` via a protected Host Agent read-only inspection command before admission when stale.

### D4 — Invitation delivery transport vs Identity Platform email-link quota — **Decided**
- **Conflict**: H04 requires *"explicit invitation delivery/reissue when ready"*, and `CentralInvitations.issue()` creates `state='pending_delivery'` and returns `(invitation_id, SecretStr(token))`. There is no transactional email provider in the repo; Firebase/Identity Platform email sends are reserved for sign-in links (initially bounded at a 9-send/day app ceiling in H03; **Google subsequently confirmed a 100 emails/day quota on 2026-11-23**).
- **Decision**: For Pilot 0, Admin-lite UI displays the one-time invitation claim URL on explicit Issue/Reissue for out-of-band delivery by the Admin, with an explicit "Mark delivered" confirmation transitioning `invitations.state` from `pending_delivery` to `sent` (zero new email provider, secrets, or egress).

### D5 — Legacy 250 MiB loop-volume `HostedStorageBudget` vs H04 Free logical + ext4 `prjquota` admission — **Decided**
- **Conflict**: `managed_business.py:25,41,212` currently wires the legacy `HostedStorageBudget` (`storage_budget.py`), which enforces a hard-coded 250 MiB loop-mounted ext4 image (`WORKSPACE_BYTES = 250 MiB`) and volatile in-memory `_reserved` counters. H04 requires Free `50,000,000`-byte logical admission backed by `usage_state` / `usage_reservations` in `access.sqlite` plus ext4 project-quota physical checks.
- **Decision**: Replace the legacy loop-volume `HostedStorageBudget` in `ManagedBusiness` with the H04 two-layer storage admission adapter (durable logical admission in `access.sqlite` + read-only physical `prjquota` headroom check), and retire the 250 MiB loop-volume code from hosted runtime paths.

### D6 — Exact logical storage accounting formula (`committed_db_bytes` and `retained_file_bytes`) — **Decided**
- **Gap**: `plans-and-budgets.md` defines logical usage as `committed_db_bytes + retained_file_bytes` (excluding WAL/SHM/temp/backups/system overhead), but does not pin the exact SQLite and deduplication queries.
- **Decision**:
  - `committed_db_bytes = (PRAGMA page_count - PRAGMA freelist_count) * PRAGMA page_size` (live committed SQLite pages, so deleting records reclaims logical allowance even before `VACUUM`, while ext4 `prjquota` still bounds physical allocated pages).
  - `retained_file_bytes = SUM(size_bytes)` across **distinct `content_sha256`** blobs referenced by `file_content_locations` where `storage_provider = 'local'` and `storage_state = 'available'` (matching `FilesystemContentStore`'s content-addressed deduplication).

### D7 — Manual provisioning trigger & Host Agent `AdmissionPort` boundary — **Decided**
- **Gap**: `host_agent/application/dispatch.py:154-160` leaves `AdmissionPort` to H04, while `service_runtime.py:48-50` is read-only and the shared Admin container runs unprivileged without Docker/root access.
- **Decision**: Admin-lite creates/retries the immutable `provision` operation (`state='pending'`). A root-owned Host Agent CLI (`epm-host-agent provision --operation-id <id>`) authenticates the operation via the private Unix relay (`AdmissionPort`), executes idempotent Host Agent effects, seeds if `synthetic`, initializes `access_meta`/policy, registers held auth routes, and posts the verified receipt back to Admin.

### D8 — `SharedIdentityManifest` strict allowlist & H04/H05 `eligible` gateway boundary — **Decided**
- **Conflict**: `host_agent/application/auth_routes.py:37-42,91-99` hard-codes `ADMIN_IDENTITY_ROUTES` to 4 auth routes (`GET /auth/start`, `POST /auth/complete`, `GET /api/admin/session`, `POST /auth/logout`) and rejects any other routes. `gateway.py:46-47` rejects `desired_state == 'eligible'`.
- **Decision**:
  1. Version/expand `SharedIdentityManifest` (`admin_routes`) to admit the exact H04 Admin-lite API routes (keeping Admin-lite as a single-page app served from `/` + pinned `/assets/*`).
  2. Keep `Gateway` rejecting `desired_state == 'eligible'` in real deployments until H05 supplies the verified recovery-point gate. In H04, prove on GCP with two disposable assignments that missing readiness/H05 protection holds each workspace closed, and verify full hosted business + Settings + two-device workflows via integration/Playwright tests against `DestinationHTTP` + `ManagedBusiness`.

### D9 — H03.12 P1 prerequisite defects — **Resolved**
- **Status**: Resolved in commit `63fd487a` (`address H03 review comments`) and `332e7eef` (`H03 complete`), as documented in [HOSTED_MVP_H03_54be42cd_REVIEW_RESPONSE.txt](../../pending_code_review_comments/HOSTED_MVP_H03_54be42cd_REVIEW_RESPONSE.txt) (items 2, 6, and 24 — along with all other 23 findings). No separate `H04.0` prerequisite slice is needed.

### D10 — Synthetic seed bundle pin & Settings copy — **Decided**
- **Gap**: `pilot_contracts.py:65-72` requires `seed_bundle` whenever `initial_data == 'synthetic'`, and `shell.tsx:535-538` still displays `"for this demo"`.
- **Decision**: Pin `seed_bundle` as `synthetic-demo-v1:<sha256(dataset.json)>`, run `demo/seed.py` offline before `ready_for_claim`, include seeded bytes in initial `usage_state`, and update hosted Settings/AI copy from `"this demo"` to `"the Free pilot"` with zero paid-upgrade controls.

---

## 4. Detailed Architecture & Component Design

### 4.1 Admin Control Plane & Persistence (`hosted_admin`)

#### Greenfield Schema Additions (`admin_0001_initial.py`)
1. **`operations.kind` expansion (per D1)**:
   - `provision | repair_runtime | disable | enable | rebind | retire | maintenance_release | reissue_invitation | refresh_source`.
2. **`operator_source_observations` (per D2)**:
   - Columns: `operator_id` (PK), `workspace_id`, `access_epoch`, `effective_enabled` (nullable boolean), `usage_bytes` (nullable count), `usable_bytes` (nullable positive), `source_revision` (nullable rev), `observed_at` (nullable time), `checked_at` (time), `freshness_state` (`known | stale | unknown | unavailable`), `revision`.
   - FK `(operator_id, workspace_id) -> operators(operator_id, workspace_id)`.
3. **Capacity ledger tables (per D3)**:
   - `capacity_profiles`: `profile_ref` (PK), `profile_revision`, `measurement_sha256`, `source_sha256`, `runtime_policy_sha256`, `maximum_observation_age_ms`, `shared_reserve_json`, `recovery_reserve_json`, `free_budget_json`, `created_at` (immutable via trigger).
   - `capacity_snapshots`: `id` (singleton `=1`), `snapshot_revision`, `profile_ref`, `profile_revision`, `observed_at`, `complete`, `total_json`, `available_json`, `shared_observed_json`.
   - `capacity_commitments`: `operator_id` (PK), `workspace_id` (unique), `state` (`pending | active | retained | unknown | cleanup_pending`), `reserved_json`, `observed_json`, `updated_at`, `revision`.
     - **State semantics** (all five unreleased states count at 100% of `reserved_json` in `plan_reservation()`; capacity is freed only after retirement/cleanup completes and the commitment is released):
       - `pending`: admitted by Admin; provisioning has not completed yet.
       - `active`: provisioned and live; actively holds runtime and disk reservation.
       - `retained`: no longer active (e.g., disabled, stopped, or held for investigation/recovery before retirement), but host directories, quotas, and re-enablement headroom remain retained on the host.
       - `unknown`: provisioning or lifecycle outcome is uncertain; must be reconciled before trusting or freeing resources.
       - `cleanup_pending`: retirement confirmed; host teardown and resource deletion are still in progress.
4. **Free v1 Policy Seed**:
   - Deployment bootstrap idempotently inserts `storage_policies` Free v1: `plan_code='free'`, `policy_version=1`, `usable_bytes=50_000_000`, `backup_interval_seconds=86_400`, `retained_nightly_points=7`, `keep_warm=1`.

#### Serialized `CreateAssignment` Transaction
Executed inside `BEGIN IMMEDIATE` on Admin DB:
1. Validate recent Admin MFA session (`sensitive=True`), CSRF, exact origin, and `AdminCommand` envelope (`CreateAssignment`).
2. Check `(kind='provision', idempotency_key)` in `operations`:
   - Matching `request_hash` -> return original `OperationOutcome[AdminResult]`.
   - Different `request_hash` -> raise `SemanticConflict` (HTTP `409`).
3. Validate `slug` (not reserved, unique), normalized `email_key` (unique), `release_id` (`component='operator'`, `state='qualified'`), `policy_id` (Free v1), and `initial_data` / `seed_bundle` pairing.
4. Load active `capacity_profiles`, singleton `capacity_snapshots` (recheck `expected_snapshot_revision` and freshness), and all `capacity_commitments` (`pending`, `active`, `retained`, `unknown`, `cleanup_pending`). Run `plan_reservation()`. If `status != "within_candidate_envelope"`, abort cleanly (`409`/`503`) with limiting resources and zero DB writes.
5. Atomically insert:
   - `operators` (`setup_state='pending'`, `desired_access='enabled'`, `access_epoch=1`, `revision=1`),
   - `component_deployments` (`component='operator'`, `scope_kind='workspace'`, `desired_release_id=release_id`, `state='pending'`, `operation_id`),
   - `capacity_commitments` (`state='pending'`, `reserved_json`, `observed_json=Resources()`),
   - `operations` (`kind='provision'`, `state='pending'`, `operator_id`, `component_deployment_id`),
   - `operation_events` (`sequence=1`, `event_code='provision_queued'`),
   - `admin_audit` (`action='create_assignment'`).

#### Set-Based Reads & Explicit Source Refresh
- `AdminList` (`GET /api/admin/operators`): single bounded set-based SQL query joining `operators`, `component_deployments`, `operator_source_observations`, `workspace_recovery_status`, and latest `operations` row. Keyset cursor bound to `(deployment_id, scope, endpoint='admin_operators', filter_hash, as_of, source_revision, limit)`.
- `AdminDetail` (`GET /api/admin/operators/{operator_id}`): single bounded read returning `OperatorSummary`, 5-gate `Readiness`, recent `operations` + `operation_events`, active/latest `invitations` metadata (never returning raw token hashes), and enabled/disabled `Actions`.
- `RefreshSource` (`POST /api/admin/operators/{operator_id}/refresh`): creates an idempotent `refresh_source` operation, queries the Operator source over the private Unix relay, updates `operator_source_observations`, and records the operation outcome.

### 4.2 Manual Provisioning, Seeding & Host Agent Admission (`host_agent`)
- **`AdmissionPort` (`admit_host_effect` on private Unix relay)**:
  - Host Agent authenticates its UID/socket identity and sends the `HostEffect` command referencing `operation_id`.
  - Admin verifies `operations.state IN ('pending','running','needs_attention','unknown')`, `operators.access_epoch`, `component_deployments.desired_release_id`, and `capacity_commitments`, returning a short-lived `AdmittedEffect` with pinned `ResourcePlan` (image digest, qualified Free `workspace`/`control`/`scratch` byte & inode ceilings, `public_origin`).
- **Manual Provisioning Runner (`epm-host-agent provision --operation-id <id>`)**:
  1. Transitions operation to `running`, `operators.setup_state='preparing'`, `component_deployments.state='applying'`.
  2. Executes deterministic, receipt-backed child `EffectIdentity` slots in order:
     - `prepare_resources`: allocate UID/GID/ext4 project IDs, create private `workspace`/`control`/`scratch` directories on `/srv/epm/data`, enforce qualified Free byte & inode project quotas, verify quota enforcement.
     - `initialize_container`: initialize business DB (`alembic upgrade head`) and access DB (`access_0001_initial`), invoke `initialize_binding` (creating `access_meta` disabled/unbound with Free v1 `usable_bytes=50_000_000`, `effective_policy_id`, `policy_revision=1`) and initial `usage_state`.
     - **Optional synthetic seed** (`initial_data == 'synthetic'`): run `demo/seed.py` offline against the initialized workspace with pinned `seed_bundle` journal in `scratch`, then measure and commit `usage_state`. Fail closed if seeded usage exceeds `50,000,000` bytes.
     - `apply_auth_routes`: register Operator held auth-only routes (`GET /auth/start`, `POST /auth/complete`, `GET /auth/status`) on `desired_state='held'`.
     - `start_container`: start Operator container under `restricted_host_supervisor` (`docker_restart_policy='no'`).
  3. Posts verified receipts back to Admin: marks `component_deployments.state='applied'` (with `observed_release_id`, `observation_ref`, `observed_at`), `capacity_commitments.state='active'`, `operators.setup_state='ready_for_claim'`, `operations.state='succeeded'`, and appends `operation_events` + `admin_audit`.
  4. On failure or interruption: marks `operations.state='needs_attention'` (or `'unknown'`), `operators.setup_state='needs_attention'`, keeps ingress `held`, retains `capacity_commitments` so capacity is never overcommitted. Re-running `epm-host-agent provision --operation-id <id>` reconciles existing `host_receipts` idempotently.

### 4.3 Source Lifecycle & Two-Layer Free Storage Admission (`hosted_access`)
- **New `SourceLifecycle` Commands**:
  - `initialize_binding`: one-time creation of `access_meta` (`effective_access='disabled'`, `subject=NULL`, Free v1 `effective_policy_id`, `usable_bytes=50_000_000`, `policy_revision=1`) + initial `usage_state` + `access_receipts` + `access_audit`.
  - `apply_policy`: Admin-only fenced command validating `policy_revision > meta.policy_revision`, `access_epoch`, and `AdmittedFreePolicy` hash; updates `access_meta` atomically with `access_receipts` and `access_audit`. Rejects tampering or stale epochs.
- **Two-Layer Storage Admission (replaces legacy 250 MiB loop-volume budget)**:
  1. **Logical Free Admission (`access.sqlite`)**:
     - Before admitting any mutating business request in `ManagedBusiness.dispatch`, compute `maximum_growth_bytes` (declared/bounded request size with write/multipart overhead, or fixed small reserve for JSON mutations).
     - In `BEGIN IMMEDIATE` on `access.sqlite`: load `access_meta.usable_bytes`, `usage_state` (`committed_db_bytes + retained_file_bytes`), and `SUM(reserved_bytes)` for `usage_reservations WHERE state IN ('held','unknown')`.
     - If `used + active_reserved + maximum_growth_bytes > usable_bytes`, reject with HTTP `507` (`code: "hosted_storage_quota_exceeded"`), making zero business mutations.
     - Otherwise insert `usage_reservations` (`state='held'`, `operation_id`, `request_hash`, `reserved_bytes`, `source_epoch`).
  2. **Physical Project-Quota Headroom Check**:
     - Read-only check of remaining physical bytes and inodes for the Operator's `workspace`, `control`, and `scratch` project quotas against the qualified safety floor. Reject with `507`/`503` before touching SQLite or files if headroom is exhausted.
  3. **Post-Commit Settlement & Crash Reconciliation**:
     - On business commit success: recompute `committed_db_bytes` and `retained_file_bytes` (per D6), update `usage_state` (`business_revision`, `observed_at`, `revision+1`), and mark the reservation `committed`.
     - On rollback/error: mark the reservation `released` (or `unknown` on uncertain failure, reconciled on next startup/write by re-measuring actual DB + retained files before releasing).
- **Hosted Operator Composition**:
  - `operator_entry.py` wires `ManagedBusinessInputs` (readiness gate, two-layer storage admission, `files=True` when qualified) into `create_app()`.
  - `DestinationHTTP` serves existing Operator frontend routes and `BUSINESS_ROOTS`, keeps `FORBIDDEN_PREFIXES` blocked, and exposes `GET /api/hosted/settings` returning the `Settings` contract (`FreeUsage`, `Protection`, `support_contact`, `MaintenanceNotice`, `actions`).

### 4.4 Admin-lite & Operator Settings UI Contracts & Acceptance Criteria

#### Admin-lite UI (`application/apps/web/src/admin/`)
- **Operator Directory (`AdminList`)**:
  - Search input, `setup_state` filter, `access_state` filter, bounded pagination, and **Add operator** action.
  - Each row displays display name, slug, setup state badge, desired vs cached effective access (with freshness or `Unavailable`), cached Free usage (with freshness or `Unavailable`), protection state (`Unavailable` until H05), and release ID.
- **Add Operator (`AdminAdd`)**:
  - Fields: Display name, Invited email, Workspace slug, Support contact, Qualified Operator release, Initial data (`Empty workspace` default vs `Synthetic sample portfolio` with pinned bundle summary), pinned **Free pilot (50 MB)** summary, and current host capacity headroom.
  - Preserves invalid or conflicted draft inputs without clearing fields; preserves original `idempotency_key` on uncertain responses; never auto-replays commands.
- **Operator Detail (`AdminDetail`)**:
  - Independent sections for Identity/Assignment, 5-gate Readiness (`isolation`, `schema`, `routing`, `protection`, `binding`), Storage Usage & Policy, Operations & Event Log (showing `operation_id` and safe summaries for manual provisioning/retry), **Refresh source** action, and **Issue / Reissue invitation** action (enabled only when `ready_for_claim` & unbound; displays one-time claim link with explicit delivery confirmation per D4).
- **Accessibility & Responsive Acceptance**: semantic landmarks, keyboard navigation, focus restoration, error summaries, restrained status announcements, and clean layout at `390px`, `900px`, and `1440px` with zero secrets in browser storage.

#### Operator Settings UI (`application/apps/web/src/app/`)
- Rendered **only** in hosted mode (`managedHostedMode()`); local single-operator mode remains completely unchanged.
- Displays:
  - **Plan**: `Free pilot` (`50.0 MB` logical allowance).
  - **Storage usage**: used bytes, remaining bytes, percentage bar, and `observed_at` freshness timestamp (or honest `Unavailable` if unreadable).
  - **Backup protection**: honest `Unavailable — backup protection is not yet active` until H05 (never fabricates `"protected"` or a verified point timestamp).
  - **Support contact**: administrator email from `access_meta` / `Settings` contract.
  - **Maintenance notice**: shown when announced; otherwise absent.
- **Explicit exclusions**: zero paid-upgrade, billing, plan-change, individual maintenance scheduling, or idle-wake controls.
- **Storage-limit UX (`507 hosted_storage_quota_exceeded`)**: forms and file uploaders retain unfinished input, present clear non-destructive guidance naming the Free 50 MB limit and administrator contact, and never report partial/failed writes as committed.

### 4.5 Free (`50,000,000`-Byte) Physical Storage Sizing Qualification Protocol
Executed on native Linux/Docker/GCP (ext4 `prjquota`, `nodev,nosuid,noexec`) — never macOS or arbitrary trial constants:
1. Measure actual allocated-byte and inode high-water marks across `workspace`, `control`, and `scratch` for three workload shapes up to the `50,000,000`-byte logical ceiling:
   - **Database-heavy**: dense properties, units, leases, ledger entries, maintenance issues, audit logs, plus WAL/checkpoint and vacuum spikes.
   - **Retained-file-heavy**: large PDF/photo attachments approaching `50,000,000` bytes plus multipart staging and content-store atomic rename.
   - **Many-small-file / history**: thousands of small receipts/documents plus draft-lease and access-receipt churn (inode pressure).
2. Compute justified nonzero byte and inode margins for `workspace`, `control`, and `scratch` (explicitly leaving H05 to qualify backup/restore reservations separately).
3. Run independent **physical byte exhaustion** and **physical inode exhaustion** tests against the qualified ceilings, proving: kernel `EDQUOT`/`ENOSPC` is handled cleanly, SQLite and file operations roll back atomically without corruption, `usage_reservations` reconciles accurately, and the Operator UI preserves input with an honest error.
4. Record pinned Linux/Docker/GCP measurements and resulting `OperatorBudget` / `CandidateCapacityProfile` JSON in `docs/hosting/qualification/`.

---

## 5. Ordered Implementation Plan

| Slice | Status & Checkpoint | Scope | Primary Files / Modules | Exit Evidence |
|---|---|---|---|---|
| **H04.1** | **Done** | **Greenfield Admin schema & Free v1 bootstrap**: add `operator_source_observations`, `capacity_profiles`, `capacity_snapshots`, `capacity_commitments`, expand `operations.kind` (D1–D3), seed Free v1 `storage_policies`. | `application/database/admin-migrations/versions/admin_0001_initial.py`, `hosted_admin/infrastructure/policy_bootstrap.py` | Schema validation + constraint/trigger tests pass. |
| **H04.2** | **Done** | **Admin-lite control plane (`AdminPort`)**: serialized `CreateAssignment`, set-based `AdminList` / `AdminDetail`, `ReissueInvitation`, `RefreshSource`. | `hosted_admin/application/errors.py`, `hosted_admin/infrastructure/capacity_store.py`, `hosted_admin/infrastructure/admin_control.py` | Unit/integration tests for capacity serialization, idempotency, conflict, rollback, and query budget. |
| **H04.3** | **Done** | **Admin-lite HTTP API & Gateway allowlist**: wire Admin-lite endpoints into `admin_identity.py` and version `SharedIdentityManifest` allowlist (D8). | `hosted_admin/api/router.py`, `hosted_access/api/admin_identity.py`, `host_agent/application/auth_routes.py`, `host_agent/infrastructure/auth_projection.py` | API auth/CSRF/origin tests + gateway projection tests. |
| **H04.4** | **Done** | **Source lifecycle & logical storage accounting**: implement `initialize_binding`, `apply_policy`, `usage_state` measurement, `usage_reservations` reserve/settle/reconcile, and `GET /api/hosted/settings`. | `hosted_access/infrastructure/source_lifecycle.py`, `hosted_access/infrastructure/usage_accounting.py`, `hosted_access/api/operator_settings.py` | Focused tests for 50 MB admission, rollback, crash reconciliation, policy revision fencing. |
| **H04.5** | **Done** | **Hosted business composition**: replace legacy 250 MiB loop-volume `HostedStorageBudget` with two-layer admission in `ManagedBusiness` + `operator_entry.py`. | `hosted_access/infrastructure/free_storage_admission.py`, `hosted_access/api/managed_business.py`, `hosted_access/infrastructure/operator_entry.py`, `hosted_access/infrastructure/operator_identity_runtime.py` | End-to-end hosted business integration tests (portfolio, money, maintenance, files, unfinished forms, 2 devices, `507` preservation). |
| **H04.6** | **Done** | **Host Agent `AdmissionPort`, manual provisioning & synthetic seeding**: implement relay admission, `epm-host-agent provision` / retry, offline `demo/seed.py` with pinned `seed_bundle`. | `hosted_admin/infrastructure/provisioning_admission.py`, `hosted_admin/infrastructure/synthetic_seed.py`, `host_agent/infrastructure/manual_provision.py` | Provisioning, retry, rollback, and synthetic-seed usage tests. |
| **H04.7** | **Done** | **Admin-lite UI**: Operator Directory, Add Operator, Operator Detail (readiness, operations, refresh source, explicit invitation delivery/reissue). | `application/apps/web/src/admin/admin-api.ts`, `application/apps/web/src/admin/AdminWorkspace.tsx`, `application/apps/web/src/admin/main.tsx`, `application/apps/web/src/admin/style.css` | `npm run lint`, `format:check`, `typecheck`, Playwright Admin-lite specs (`390px`/`900px`/`1440px`, keyboard/focus). |
| **H04.8** | **Done** | **Operator Settings & storage-limit UI**: hosted Free-pilot Settings panel + `507` input-preservation UX + local-mode preservation. | `application/apps/web/src/app/hosted-settings.tsx`, `application/apps/web/src/app/preferences.tsx`, `application/apps/web/src/app/shell.tsx`, `application/apps/web/src/shared/mutations.ts` | `npm run lint`, `format:check`, `typecheck`, Playwright hosted Settings + local-mode regression + `507` UX specs. |
| **H04.9** | **Done** ([Free sizing](../qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json)) | **Native Linux/Docker/GCP Free physical sizing qualification**: run 3 workload shapes, derive qualified byte/inode ceilings, run byte & inode exhaustion/rollback/UI tests. | `application/deploy/hosted-mvp/gcp/free_sizing_actor.py`, `application/deploy/hosted-mvp/gcp/qualify_free_sizing.py`, `docs/hosting/qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json` | Signed-off qualification report with pinned Linux/Docker/GCP hashes. |
| **H04.10** | **Done** ([Exit review](../qualification/reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md)) | **Deployed H04/H05 handoff verification**: provision 2 disposable Operator assignments on GCP, prove missing readiness/H05 protection holds both closed, verify Admin-lite + invitation/claim boundaries. | `application/deploy/hosted-mvp/gcp/qualify_h04_handoff.py`, `docs/hosting/qualification/reports/HOSTED_MVP_H04_10_HANDOFF.json`, `docs/hosting/qualification/reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md` | H04 exit review confirming handoff readiness for H05. |

---

## 6. Design Validation Matrix

| Validation Area | Required Test Coverage |
|---|---|
| **Happy paths** | Admin creates empty and synthetic Free operators; manual provisioning completes (`pending -> preparing -> ready_for_claim`); invitation issued and delivered; hosted business composition serves portfolio, money, maintenance, file upload, and unfinished-form workflows across two devices; Operator Settings shows Free pilot, exact logical usage/remaining/freshness, support contact, and unavailable H05 protection; local mode remains unchanged. |
| **Invalid combinations** | Reserved or duplicate slug/email; withdrawn or non-operator `release_id`; `initial_data='synthetic'` without `seed_bundle` (or `empty` with `seed_bundle`); stale `expected_snapshot_revision` or stale capacity snapshot; insufficient capacity across active + pending + unknown commitments; issuing invitation before `ready_for_claim` or after claim; `apply_policy` with stale epoch/revision; writes exceeding `50,000,000` logical bytes (`507`); accessing `FORBIDDEN_PREFIXES` or missing CSRF/origin; requesting `eligible` ingress without H05 protection gate. |
| **Idempotency & retry behavior** | Replaying `CreateAssignment`, `ReissueInvitation`, `RefreshSource`, `apply_policy`, and `epm-host-agent provision` with identical `idempotency_key` + `request_hash` returns the original operation/receipt without duplicating operators, commitments, or containers; reusing an `idempotency_key` with changed semantics returns `SemanticConflict` (`409`); retrying a failed/interrupted provision reconciles `host_receipts` without leaking UIDs or quotas. |
| **Transaction rollback** | Failed capacity check or DB constraint during `CreateAssignment` leaves zero partial `operators`, `component_deployments`, `capacity_commitments`, `operations`, or `admin_audit` rows; failed business write or kernel `EDQUOT`/`ENOSPC` during upload rolls back SQLite, deletes temp/unpublished blobs, marks `usage_reservations` released/reconciled without DB corruption, and preserves operator form input. |
| **Persistence & schema validation** | Greenfield `admin_0001_initial.py` and `access_0001_initial.py` pass `validate_schema`; immutability triggers enforce append-only `storage_policies`, `capacity_profiles`, `operation_events`, `admin_audit`, `access_receipts`, and `access_audit`; `usage_state` and `access_meta` singleton checks hold; `capacity_commitments` and `operator_source_observations` survive restart without drift. |
| **Backup / restore** | H04 never fabricates H05 backup protection (Admin Detail `protection` gate and Operator Settings `protection` section remain `unavailable`/`pending`); `workspace_recovery_status` and `access_meta.restore_generation` remain intact and H05-compatible; offline local backup paths remain unbroken. |
| **Query-budget & N+1 constraints** | `AdminList` and `AdminDetail` execute a constant, bounded number of SQL queries on Admin DB only (zero per-operator SQLite opens, zero container fan-out, strict page limit and bound cursor); `usage_state` calculation uses indexed aggregate queries (no per-file `stat()` loop during normal reads, only on commit settlement or explicit reconciliation). |
