# H04.3 Admin-lite HTTP API and Gateway allowlist

H04.3 wires the authenticated Admin-lite HTTP API onto the protected Admin
origin (`admin.<domain>`) and versions `SharedIdentityManifest` and Caddy
gateway route projection to admit the exact Admin-lite route set per
[HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md) (decision D8).

- **Admin-lite HTTP router** (`hosted_admin/api/router.py`):
  `build_admin_lite_router()` exposes seven endpoints:
  - `GET /api/admin/bootstrap` — deployment metadata, pinned Free v1 policy,
    qualified Operator releases, pinned `AdmissionCommitment`, and capacity
    summary.
  - `GET /api/admin/operators` — set-based `AdminList` with bounded limit
    (`1..50`) and base64url continuation cursor.
  - `POST /api/admin/operators` — idempotent `CreateAssignment` (deriving
    deterministic `operator_id` / `workspace_id` from `(deployment_id,
    idempotency_key)` when omitted so retries preserve identical
    `request_hash`).
  - `GET /api/admin/operators/{operator_id}` — set-based `AdminDetail`.
  - `POST /api/admin/operators/{operator_id}/invitations` — explicit
    issue/reissue returning the one-time raw token only on the original call.
  - `POST /api/admin/operators/{operator_id}/invitations/{invitation_id}/delivered`
    — explicit out-of-band delivery confirmation (`pending_delivery -> sent`).
  - `POST /api/admin/operators/{operator_id}/refresh` — explicit
    `RefreshSource` dispatched via `run_in_threadpool`.
  All routes require a valid `__Host-epm-admin` session cookie, exact Admin
  origin, constant-time `X-CSRF-Token` verification on every `POST`, and recent
  MFA (`sensitive=True`) on create/invitation/delivery mutations.
- **Admin app composition** (`hosted_access/api/admin_identity.py`):
  `build_admin_identity_app()` accepts optional `admin_control` and mounts
  `build_admin_lite_router()` inside the existing security-header and origin
  boundary while leaving H03 identity-only callers unchanged.
- **Gateway allowlist & UUID projection** (`host_agent/application/auth_routes.py`,
  `host_agent/infrastructure/auth_projection.py`):
  Added `ADMIN_LITE_ROUTES` (11 routes) and versioned
  `SharedIdentityManifest.route_policy` to accept
  `separate_exact_host_method_allowlists_v1` (4 H03 routes, default) or
  `separate_exact_host_method_allowlists_v2` (11 Admin-lite routes). Updated
  `_uri_pattern()` to expand `{operator_id}` and `{invitation_id}` strictly to
  canonical lowercase UUIDs while keeping literal paths byte-for-byte
  identical.

## Local validation

102 focused Python tests passed across `test_admin_lite_http.py` (3 tests),
`test_admin_http.py`, `test_identity_contracts.py`, and `test_gateway.py`.
`ruff check` passed on all new/owned files and `ruff format --check` passed on
all 5 modified Python files using `application/pyproject.toml` (pre-existing
untouched `PLR2004`/`C901`/`PLR0915`/`PLC0415` findings remain in legacy lines
of `admin_identity.py` and `auth_projection.py`).

| Area | Observed evidence |
| --- | --- |
| Auth, CSRF & Origin | Unauthenticated calls to `/api/admin/bootstrap` and `/api/admin/operators` return `401`; missing `X-CSRF-Token` or cross-origin `POST /api/admin/operators` returns `401`; all responses carry `Cache-Control: no-store`. |
| End-to-end Admin-lite HTTP | Bootstrap, idempotent create + replay (including omitted `workspaceId`), `409` semantic conflict, list/detail (`400` on invalid UUID), source refresh updating cached usage, invitation gating (`409` before `ready_for_claim`, `201` with one-time token once ready, `200` with `token=None` on replay), and explicit `delivered -> sent` confirmation all verified. |
| Gateway allowlist & UUID regex | `SharedIdentityManifest` rejects mismatched `v1`/`v2` route sets; `v2` projects all 11 Admin routes + `/` + assets; `_uri_pattern()` accepts canonical lowercase UUIDs (with optional query) and rejects uppercase UUIDs, path traversal, non-UUIDs, and extra path segments. |

H04.4 will implement source lifecycle commands (`initialize_binding`,
`apply_policy`), logical Free storage accounting (`usage_state`,
`usage_reservations`), and `GET /api/hosted/settings`.
