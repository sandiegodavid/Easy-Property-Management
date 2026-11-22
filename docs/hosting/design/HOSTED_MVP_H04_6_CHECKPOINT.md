# H04.6 Host Agent AdmissionPort, manual provisioning and synthetic seeding

H04.6 implements the Admin-owned `AdmissionPort` adapter, pinned offline
synthetic portfolio seeding, and the idempotent manual provisioning / retry
orchestrator per [HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md)
(decisions D7 and D10).

- **Admin-owned `AdmissionPort` & receipt transitions**
  (`hosted_admin/infrastructure/provisioning_admission.py`):
  `AdminEffectAdmission` implements `AdmissionPort.resolve(HostEffect) ->
  AdmittedEffect`, authenticating original `operations` (`kind = 'provision'`),
  verifying `deployment_id`, `scope`, `idempotency_key`, `request_hash`,
  `access_epoch`, qualified release, and `inputs_hash` against the pinned
  `ResourcePlan` and `public_origin`, and returning a short-lived
  `AdmittedEffect`. Also exposes `load_provision_intent()`, `mark_running()`,
  `mark_succeeded()` (atomically updating `component_deployments = 'applied'`,
  `capacity_commitments = 'active'`, `operators.setup_state =
  'ready_for_claim'`, `operations = 'succeeded'`, and
  `operator_source_observations = 'known'`), and `mark_needs_attention()`
  (retaining `capacity_commitments` as `'pending'`/`'unknown'` so capacity is
  never overcommitted).
- **Pinned synthetic seed runner**
  (`hosted_admin/infrastructure/synthetic_seed.py`):
  `canonical_seed_bundle_ref()` pins `synthetic-demo-v1:<sha256(dataset.json)>`,
  `verify_seed_bundle_ref()` fails closed on mismatch, and
  `seed_synthetic_workspace()` runs the resumable `demo/seed.py` seeder offline
  with config/journal files stored strictly inside `scratch_dir`.
- **Manual provisioner & idempotent retry**
  (`host_agent/infrastructure/manual_provision.py`):
  `ManualProvisioner` orchestrates directory setup (`0700`), workspace DB and
  `access.sqlite` initialization, deterministic `SourceLifecycle`
  `initialize_disabled` (`provision-init:<operation_id>`), optional pinned
  synthetic seeding, logical Free budget verification (`used_bytes <
  50,000,000`), and host effect hooks (`prepare_resources`,
  `apply_auth_routes`, `start_container`), transitioning Admin receipts cleanly
  on both success and failure/retry.

## Local validation

3 focused Python tests passed in `test_h04_manual_provision.py`. `ruff check`
and `ruff format --check` passed on all 4 files using
`application/pyproject.toml`.

| Area | Observed evidence |
| --- | --- |
| `AdmissionPort.resolve()` | Resolves pinned `ResourcePlan` and `public_origin` matching `inputs_hash` and `require_admission()`; rejects tampered `inputs_hash` and mismatched `access_epoch` with `HostAgentDenied`. |
| Manual provision & retry | Simulated failure during `start_container` marks `needs_attention` while retaining `capacity_commitments = 'pending'`; retrying the same `operation_id` replays `initialize_binding` idempotently and transitions `operators = 'ready_for_claim'`, `component_deployments = 'applied'`, `capacity_commitments = 'active'`, and `operator_source_observations = 'known'`. Repeat call on succeeded operation is a safe no-op. |
| Pinned synthetic seeding | Mismatched `seed_bundle` fails closed (`seed_bundle_mismatch`) with workspace held closed; matching `canonical_seed_bundle_ref(dataset.json)` runs seeder with scratch-only journals, verifies post-seed logical usage `< 50,000,000` bytes, and succeeds. |

H04.7 will build the Admin-lite UI (Operator Directory, Add Operator, Operator
Detail with 5-gate readiness, refresh source, and explicit invitation
delivery/reissue).
