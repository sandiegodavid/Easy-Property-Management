# H04.1 greenfield Admin schema and Free v1 bootstrap

H04.1 updates the greenfield main-Admin baseline schema and adds idempotent
Free v1 storage policy bootstrap per [HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md)
(decisions D1–D3).

The main-Admin Alembic baseline (`admin_0001_initial.py`) now expands
`operations.kind` with `reissue_invitation` and `refresh_source`, adds
`operator_source_observations` for set-based Admin directory/detail reads with
strict freshness-vs-nullability enforcement (`ck_source_obs_freshness`), and
adds the serialized capacity ledger tables (`capacity_profiles`,
`capacity_snapshots`, and `capacity_commitments`). `capacity_profiles` is
append-only/immutable at the store boundary, `capacity_snapshots` is a
singleton (`id = 1`) bound by composite foreign key to `capacity_profiles`, and
`capacity_commitments` tracks all five unreleased states (`pending`, `active`,
`retained`, `unknown`, `cleanup_pending`). `MAIN_ADMIN_TABLES` and the
`admin-registry.md` / `admin-operations.md` data dictionaries match the updated
22-table closure.

`policy_bootstrap.py` provides `FreeV1Policy`, deterministic
`free_v1_policy_id(deployment_id)`, and `bootstrap_free_v1_policy()`, pinning
Free v1 (`50,000,000` usable bytes, `86,400`s backup interval, `7` retained
nightly points, `keep_warm = 1`). It validates the Admin schema and active
caller transaction, fails closed if `control_meta` is unbound or an existing
Free v1 row has drifted, and returns `(policy, inserted)` idempotently.

## Local validation

211 focused Python tests passed across `test_h04_schema_bootstrap.py`,
`test_hosted_schema.py`, `test_admin_identity_schema.py`, and
`test_hosted_effect_contracts.py` (with `test_h04_schema_bootstrap.py` re-run:
14 passed after final formatting cleanup). Changed-file `ruff check` and
`ruff format --check` passed against `application/pyproject.toml`.

| Area | Observed evidence |
| --- | --- |
| Schema closure & FKs | `initialize_store(HostedStore.ADMIN)` and `validate_schema` pass with all 22 tables; `MAIN_ADMIN_TABLES` matches `admin-registry.md`, `admin-identity.md`, and `admin-operations.md`; all FKs on `capacity_snapshots`, `capacity_commitments`, and `operator_source_observations` enforce `ON DELETE RESTRICT` with leading-column indexes. |
| Constraints & immutability | `capacity_profiles` rejects `UPDATE`, `DELETE`, and `INSERT OR REPLACE`; `capacity_snapshots` rejects `id != 1`; `capacity_commitments` accepts all five unreleased states and rejects unknown states; `operator_source_observations` rejects fabricated fields when `unknown`/`unavailable` and missing fields or `checked_at < observed_at` when `known`/`stale`; `operations.kind` admits `reissue_invitation` and `refresh_source` and rejects unknown kinds. |
| Free v1 bootstrap | Deterministic `policy_id` from `control_meta.deployment_id`, idempotent repeat calls preserving original `created_at`, rollback leaving zero rows, and fail-closed rejection on unbound `control_meta`, invalid inputs, or drifted existing Free v1 rows. |

H04.2 will build the Admin-lite control-plane `AdminPort` adapter on top of
this schema and bootstrap baseline.
