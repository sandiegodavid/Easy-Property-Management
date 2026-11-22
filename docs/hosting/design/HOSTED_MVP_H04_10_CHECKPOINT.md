# HOSTED-001 H04.10 Checkpoint — Deployed H04/H05 Handoff Verification

- **Date**: 2026-11-22
- **Slice**: H04.10 (Deployed H04/H05 handoff verification)
- **Design Doc**: [HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md)
- **Exit Review**: [HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md](../qualification/reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md)
- **Status**: Done

## Scope Delivered

1. **Closed H04.10 handoff qualification runner and validator** ([qualify_h04_handoff.py](../../../application/deploy/hosted-mvp/gcp/qualify_h04_handoff.py)):
   - Runs end-to-end in both `component` mode (local/CI) and `gcp_native` mode (root Linux/GCP against `/srv/epm/data` ext4 `prjquota` using pinned H04.9 ceilings from [HOSTED_MVP_H04_9_FREE_SIZING.json](../qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json)).
   - Provisions two disposable Operator assignments (`h04-empty` and `h04-synth` with pinned `synthetic-demo-v1:<sha256>`) via `AdminControlService` -> `AdminEffectAdmission` -> `ManualProvisioner` with idempotent retry verification.
   - Verifies missing H05 protection holds both workspaces closed (`protection_state == "unavailable"`, `effective_access_cached == "disabled"`, `ManagedBusiness.capabilities() == []`, `Gateway` projects only held auth routes and rejects `desired_state="eligible"`).
   - Verifies Admin-lite `SharedIdentityManifest` `v2` (`11` `ADMIN_LITE_ROUTES`), pre-readiness invitation rejection, explicit delivery confirmation (`pending_delivery -> sent`), zero token leakage in `AdminDetail`, `RefreshSource`, and Operator `GET /api/hosted/settings`.
   - Enforces full cleanup of disposable operator trees and system users, and validates the resulting JSON report against a closed schema (`validate_h04_handoff_report`).
2. **Production host-agent fixes surfaced on native GCP execution**:
   - [synthetic_seed.py](../../../application/apps/server/app/modules/hosted_admin/infrastructure/synthetic_seed.py): replaced `LocalApiClient` (`fastapi.testclient.TestClient` / `httpx`) with a zero-`httpx` in-process `_OfflineAsgiClient` (with FastAPI lifespan support) so offline synthetic seeding runs cleanly inside `/opt/epm/host-agent`; synchronized `TZ="America/Los_Angeles"` during offline seeding so `leases` (`date.today()`) and `portfolio` (`ZoneInfo`) agree on UTC Linux hosts.
   - [seed.py](../../../application/demo/seed.py): deferred `LocalApiClient` import into `main()` via `importlib.import_module` so importing `Seeder` never requires `httpx`.
3. **Focused unit/integration tests** ([test_h04_handoff_qualification.py](../../../application/scripts/tests/test_h04_handoff_qualification.py)):
   - End-to-end `component` handoff qualification test plus 7 parameterized negative validator tests rejecting missing operators, fabricated H05 protection, unrejected `eligible` ingress, token leakage, paid-upgrade controls, incomplete cleanup, and unverified GCP quotas.
4. **Native GCP handoff report** ([HOSTED_MVP_H04_10_HANDOFF.json](../qualification/reports/HOSTED_MVP_H04_10_HANDOFF.json)):
   - Executed natively on `epm-h02-host` (`Linux 7.0.0-1017-gcp x86_64`), validated locally (`gcp_native ready_for_h05`), and stopped `epm-h02-host`.

## Validation Results

- `application/.venv/bin/pytest application/apps/server/app/modules/host_agent/tests/test_h04_manual_provision.py application/scripts/tests/test_h04_handoff_qualification.py -q`: **11 passed** in 6.05s.
- `application/.venv/bin/ruff check --config application/pyproject.toml` on all 4 changed Python files: **All checks passed!**
- `application/.venv/bin/ruff format --check --config application/pyproject.toml` on all 4 changed Python files: **4 files already formatted**.
- Native GCP `qualify_h04_handoff.py gcp_native` on `epm-h02-host`: **exit 0**, `validate_h04_handoff_report` passed (`gcp_native ready_for_h05`), disposable resources removed, `epm-h02-host` stopped.
