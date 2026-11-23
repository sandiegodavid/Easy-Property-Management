# HOSTED-001 Slice H06.4 Checkpoint — Security Header Hardening & Redacted Structured Logging

**Date:** 2026-11-23  
**Slice:** H06.4  
**Owning Design:** [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md)  
**Owning Delivery Plan:** [delivery-plan.md](../../design/mvp/delivery-plan.md#implementation-slices)  
**Operations Runbook:** [H06_4_SECURITY_HEADERS_AND_LOGGING_RUNBOOK.md](../../runbooks/H06_4_SECURITY_HEADERS_AND_LOGGING_RUNBOOK.md)  
**Branch:** `hosted_mvp`

---

## 1. Completed Deliverables

1. **HTTP Security Header Hardening (`hosted_security_headers.py`, `auth_projection.py`, `admin_identity.py`, `central_identity.py`, `managed_business.py`, `operator_settings.py`):**
   - Created shared policy constants in [hosted_security_headers.py](../../../../application/apps/server/app/platform/hosted_security_headers.py) (`Strict-Transport-Security: max-age=31536000; includeSubDomains`, `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()`, `X-Content-Type-Options: nosniff`, and strict API `Content-Security-Policy`).
   - Added Caddy response security headers (`Strict-Transport-Security`, `Permissions-Policy`, `X-Content-Type-Options: nosniff`) to `_route()` and `_workspace_eligible_routes()` in [auth_projection.py](../../../../application/apps/server/app/modules/host_agent/infrastructure/auth_projection.py).
   - Added `Strict-Transport-Security` and `Permissions-Policy` to [admin_identity.py](../../../../application/apps/server/app/modules/hosted_access/api/admin_identity.py) and [central_identity.py](../../../../application/apps/server/app/modules/hosted_access/api/central_identity.py).
   - Hardened [managed_business.py](../../../../application/apps/server/app/modules/hosted_access/api/managed_business.py) (both `business_error()` and ASGI `private_send()` on all business API responses) and [operator_settings.py](../../../../application/apps/server/app/modules/hosted_access/api/operator_settings.py) with the complete `API_SECURITY_HEADERS` set.

2. **Secret-Free Structured JSON Logging (`hosted_logging.py`, `supervisor.py`):**
   - Created [hosted_logging.py](../../../../application/apps/server/app/platform/hosted_logging.py) providing `redact_string()`, `redact_value()`, `format_structured_log()`, `emit_structured_event()`, and `StructuredJsonFormatter` compatible with GCP Ops Agent / Cloud Logging, redacting cookies, Bearer tokens, JWTs, wrapped/raw DEKs, R2 credentials, and business payloads.
   - Updated `_emit_containment_alert()` in [supervisor.py](../../../../application/apps/server/app/modules/host_agent/infrastructure/supervisor.py) to emit structured JSON via `emit_structured_event()` with zero `print()` calls.

---

## 2. Validation Results

- **Focused tests:** [test_h06_security_headers_and_logging.py](../../../../application/apps/server/app/modules/hosted_access/tests/test_h06_security_headers_and_logging.py), `test_h06_runtime_wiring.py`, `test_admin_entry.py`, `test_gateway.py`, and `test_h05_positive_workspace_gateway.py` — **50/50 passed** (including negative log-redaction tests proving zero cookies, Bearer tokens, JWTs, DEKs, R2 secrets, or business payloads leak).
- **Lint & formatting:** `ruff check` and `ruff format --check` (`application/pyproject.toml`) on all 11 changed Python files — **All checks passed / 11 files already formatted**.
