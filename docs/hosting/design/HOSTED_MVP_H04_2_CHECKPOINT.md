# H04.2 Admin-lite control plane (`AdminPort`)

H04.2 implements the main-Admin control-plane service, serialized capacity
admission ledger, explicit invitation issuance/delivery confirmation, source
refresh projection updates, and strictly set-based `AdminList` / `AdminDetail`
reads per [HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md).

- **Typed control-plane errors** (`hosted_admin/application/errors.py`):
  `AdminDeniedError` (`403`), `AdminNotFoundError` (`404`),
  `AdminConflictError` (`409`, carrying `limiting_resources` on capacity
  exhaustion), and `AdminUnavailableError` (`503`).
- **Serialized capacity ledger** (`hosted_admin/infrastructure/capacity_store.py`):
  `register_capacity_profile()`, `record_capacity_snapshot()`,
  `load_capacity_state()`, and `evaluate_admission()`, bridging the persisted
  `capacity_profiles` / `capacity_snapshots` / `capacity_commitments` tables to
  the pure `plan_reservation()` planner in `host_agent/application/capacity.py`
  and verifying that requested `AdmissionCommitment` values match the pinned
  Free budget.
- **Admin-lite control plane** (`hosted_admin/infrastructure/admin_control.py`):
  `AdminControlService` implements `AdminPort` (`execute`, `observe`,
  `original`), `list_operators()` (`AdminList`), `detail_operator()`
  (`AdminDetail`), `issue_invitation_with_token()`, and
  `mark_invitation_sent()`.
  - `CreateAssignment` runs inside `BEGIN IMMEDIATE`, enforces recent Admin
    MFA, validates deployment registry revision, reserved/duplicate slugs and
    emails, pinned Free v1 policy, qualified Operator release, and serialized
    capacity headroom (counting all unreleased commitments with no hard-coded
    5-operator cap), and atomically inserts `operators`, workspace-scoped
    `component_deployments`, `capacity_commitments` (`pending`), `operations`
    (`kind = 'provision'`), `operation_events`, and `admin_audit`.
  - `ReissueInvitation` enforces `ready_for_claim`, unclaimed `subject IS NULL`,
    `desired_access = 'enabled'`, and `applied` deployment state; revokes prior
    live invitations; records `pending_delivery`; and emits the raw token only
    on the original non-replayed call. `mark_invitation_sent()` transitions
    `pending_delivery -> sent` on explicit confirmation (D4).
  - `RefreshSource` invokes the private source inspector strictly outside any
    SQLite transaction and persists either `known` source observations or
    `unavailable` (with all observed fields `NULL` and `needs_attention`).
  - `list_operators()` and `detail_operator()` use constant-query set-based
    SQL on the Admin DB only, with keyset cursors bound to filter hash and
    registry revision, and 5-gate `Readiness` holding `protection` honestly
    `unavailable` until H05.

## Local validation

20 focused Python tests passed across `test_admin_control.py` (6 tests) and
`test_h04_schema_bootstrap.py` (14 tests). Changed-file `ruff check` and
`ruff format --check` passed against `application/pyproject.toml`.

| Area | Observed evidence |
| --- | --- |
| Atomic assignment & idempotency | Empty and synthetic `CreateAssignment` atomically create all six owning rows and bump `registry_generation`; replay with a new `operation_id` returns the original `OperationOutcome`; changed semantics with the same `idempotency_key` raises `SemanticConflict`. |
| Capacity admission | Host provisioned with 7 Free slots admits all 7 operators (no 5-operator cap) and rejects the 8th with `capacity_insufficient` and zero partial rows; stale snapshot fails closed as unavailable; forged smaller commitment is rejected. |
| Rollback & invalid combinations | Stale MFA, reserved slug, withdrawn release, stale registry revision, and mismatched commitment all reject cleanly with zero mutations to `operators`, `operations`, or `control_meta`. |
| Set-based reads & query budget | `list_operators()` executes at most 4 SELECT statements per page regardless of operator count; keyset continuation advances cleanly and rejects changed filter context (`cursor_context_changed`); `observe()` returns a valid `ObservationPage[AdminObservation]`. |
| Invitations & source refresh | `ReissueInvitation` blocks before `ready_for_claim`, succeeds once applied/ready, omits raw token on replay, and transitions to `sent` via `mark_invitation_sent()`; `RefreshSource` records `known` usage/access or honest `unavailable` without fabricating values; `Readiness` keeps `protection` `unavailable` pending H05. |

H04.3 will wire the Admin-lite HTTP endpoints into `admin_identity.py` and
version `SharedIdentityManifest` to admit them.
