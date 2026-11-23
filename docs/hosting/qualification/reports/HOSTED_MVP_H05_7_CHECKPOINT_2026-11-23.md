# HOSTED-001 Slice H05.7 Checkpoint — Positive Workspace Gateway Routing (`desired_state="eligible"`)

**Date:** 2026-11-23  
**Slice:** H05.7 (`HOSTED_MVP_H05_DESIGN.md` Section 6 & D9)  
**Status:** Complete

## Summary of Changes

1. **Workspace & H05 Admin Route Contracts** (`application/apps/server/app/modules/host_agent/application/auth_routes.py`):
   - Added `ADMIN_H05_ROUTES` and `route_policy = "separate_exact_host_method_allowlists_v3"` to `SharedIdentityManifest` (preserving `v1` and `v2` unchanged) covering `repair-runtime`, `operations/{operation_id}`, and `/api/admin/recovery/*`.
   - Added `WORKSPACE_FORBIDDEN_PREFIXES` (`/admin`, `/__/auth`, `/__/firebase`, `/internal`, `/debug`, `/.well-known`, `/metrics`), `WORKSPACE_ALLOWED_METHODS`, `WorkspaceRouteManifest` (`websocket_allowed: Literal[False] = False`, `recovery_proof_ref`, exact forbidden prefix enforcement), and `WorkspaceRouteObservation`.
2. **Positive Workspace Caddy Projection** (`application/apps/server/app/modules/host_agent/infrastructure/auth_projection.py`):
   - Extended `VerifiedAuthEndpoint.manifest` to accept `WorkspaceRouteManifest` and added `"{operation_id}"` to `UUID_PLACEHOLDERS`.
   - Added `_workspace_eligible_routes(origin, endpoint)` emitting a terminal `403` deny route for WebSocket `Upgrade` headers, `WORKSPACE_FORBIDDEN_PREFIXES`, and `..` path traversal, followed by a terminal exact-`hostport` HTTPS `reverse_proxy` route verifying `Cf-Connecting-Ip == X-Forwarded-For` and stripping forwarding + `X-Epm-Client-Network` + `Upgrade` headers.
   - Extended `auth_config(..., eligible=())` to fail closed (`HostAgentUnavailable`) whenever any `eligible` record in `IngressProjection` lacks a verified `(WorkspaceRouteObservation, VerifiedAuthEndpoint)` pair, and fail closed (`HostAgentDenied`) on manifest hash, epoch, generation, or route-state mismatch.
3. **Host Agent & Gateway Eligible Proof Gate** (`application/apps/server/app/modules/host_agent/application/dispatch.py`, `service.py`, `infrastructure/gateway.py`):
   - Extended `EffectObservation.ingress_state` to `Literal["held", "blocked", "eligible"] | None`.
   - Added optional `eligible_proof_verifier` to `HostAgent` and `Gateway`. Both continue to reject `desired_state="eligible"` with `HostAgentUnavailable` when `eligible_proof_verifier` is omitted or returns `False` (preserving all H02/H03 negative gate guarantees). When verified, `Gateway.apply`/`inspect` loads and verifies the positive workspace Caddy config without triggering container containment.
   - Kept `closed_config()` unconditionally rejecting `desired_state="eligible"`.
4. **Live Business Readiness Check** (`application/apps/server/app/modules/hosted_access/infrastructure/operator_entry.py`):
   - Replaced `readiness=lambda: False` with `_live_business_readiness(access_engine, recovery_service)` enforcing all three Section 6 conditions: `access_meta.effective_access == 'enabled'` and `maintenance_operation_id IS NULL`; `recovery_service.detect_startup_mode().mode == "normal"`; and `recovery_service.read_protection_status()` reporting a verified point (`last_point_id`, `last_verified_at`) in `{"healthy", "unchanged"}`. Fails closed (`False`) on any missing recovery service or error.
5. **Focused Tests** (`application/apps/server/app/modules/hosted_recovery/tests/test_h05_positive_workspace_gateway.py`):
   - Verified `WorkspaceRouteManifest` & `ADMIN_H05_ROUTES` contracts, `auth_config` unverified-eligible denial & verified Caddy projection, `HostAgent` eligible proof gate, `Gateway.apply`/`inspect` eligible without containment, and all `_live_business_readiness` transitions.

## Validation Results

- **Focused H05.7 tests**: `cd application && .venv/bin/python -m pytest apps/server/app/modules/hosted_recovery/tests/test_h05_positive_workspace_gateway.py -v` — **5 passed**.
- **Existing gateway regression suite**: `apps/server/app/modules/host_agent/tests/test_gateway.py` — **33 passed** (0 regressions).
- **Existing host-agent non-AF_UNIX suite**: `apps/server/app/modules/host_agent/tests/test_agent.py` — **51 passed** (the 3 sandboxed AF_UNIX `connect()` tests require unsandboxed execution on macOS as in prior checkpoints).
- **Ruff lint & format**: `ruff check --config pyproject.toml` and `ruff format --config pyproject.toml --check` on all 7 modified/added Python files — **All checks passed**.
