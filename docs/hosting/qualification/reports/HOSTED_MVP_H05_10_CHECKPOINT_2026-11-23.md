# HOSTED-001 Slice H05.10 Checkpoint — Security Review & Negative Gate Verification

**Date:** 2026-11-23  
**Slice:** H05.10 (`HOSTED_MVP_H05_DESIGN.md` Section 9 & Section 10)  
**Status:** Complete — **Security Gate Passed (Zero Unresolved P1/P2 Findings)**

## Security Findings Discovered & Resolved During H05.10

1. **[Resolved — P2] Auth/CSRF Error Misclassification on Recovery POST Endpoints** (`application/apps/server/app/modules/hosted_access/api/operator_recovery.py`):
   - `preview_restore`, `confirm_restore`, and `accept_restore` previously wrapped `_read_cookie_and_origin` / `authorize_with_restore` inside the same `try` block as JSON body validation (`except ValidationError, ValueError`), causing `ProviderDenied` (missing/invalid cookie or CSRF) to be returned as `400 invalid_*_request` instead of `401 signed_out`.
   - **Fix:** Split authentication/origin/CSRF validation into its own preceding `try` block routing exclusively to `_auth_error_response` (`401`/`403`) before parsing request JSON; updated `test_h05_operator_restore_and_recovery_mode.py` to use full 43-char session/CSRF tokens for the `400` extra-field assertion.
2. **[Resolved — P2] Explicit Authority Type Guard on `_require_operator_scope`** (`application/apps/server/app/modules/workspace/infrastructure/hosted_recovery.py`):
   - Passing a non-operator authority (such as `AdminAuthority`) to `_require_operator_scope` previously raised `AttributeError` on `actor.scope` instead of a typed `RestoreDeniedError`.
   - **Fix:** Added an explicit `isinstance(actor, (OperatorAuthority, OperatorRestoreAuthority, LocalRestoreAuthority))` guard raising `RestoreDeniedError`.

## Negative Security Gate Coverage (`application/apps/server/app/modules/hosted_access/tests/test_h05_recovery_security.py`)

| Security Boundary | Verified Negative Behavior | Result |
| --- | --- | --- |
| Stolen / ordinary session & CSRF / Origin / query smuggling | Missing CSRF (`401`), foreign `Origin` (`403`), query parameters (`403`), and forged `recent_auth_grant` (`401`) all fail closed without mutating `active_business_ref`. | Passed |
| Forged Admin / Operator role confusion | `AdminAuthority` and foreign `OperatorAuthority` both raise `RestoreDeniedError` on customer workspace restore. | Passed |
| Cross-workspace prefix, KMS key, and AEAD AAD isolation | `BackupProxyHandler` rejects `../`, absolute paths, and unauthorized KMS keys (`BackupProxyDenied`); `ChunkedAeadBackupEngine.verify_point` rejects cross-workspace AAD context (`HostedRecoveryError`). | Passed |
| Confirmation replay, semantic conflict, & hash mismatch | Mismatched `confirmed_request_hash` (`RestoreDeniedError`), foreign `point_id` (`RestoreNotFoundError`), replayed single-use `preview_id` (`RestoreDeniedError`), and changed semantics on reused `idempotency_key` (`SemanticConflict` 409). | Passed |
| Path traversal & symlink escape | `validate_relative_file_path` rejects `..`, absolute paths, null bytes, empty strings; `_read_retained_files` rejects symlinks escaping workspace root (`WorkspaceStateUnreadable`). | Passed |
| Tampered ciphertext chunk / manifest | Bit-flipping stored R2 chunk causes `confirm_restore` to fail closed (`state == "failed"`) while preserving `active_business_ref == "incarnation-1"`. | Passed |
| Zero offline workspace decrypt/restore bypass (D11) & gateway negative gate (D9) | Legacy `recovery_publication.py`/`recovery_bundle.py` absent, legacy CLI commands absent, and `auth_config` rejects unverified `eligible` records (`HostAgentUnavailable`). | Passed |

## Validation Results

- `cd application && .venv/bin/python -m pytest apps/server/app/modules/hosted_access/tests/test_h05_recovery_security.py apps/server/app/modules/hosted_recovery/tests/test_h05_operator_restore_and_recovery_mode.py -v`: **12 passed**.
- `cd application && .venv/bin/ruff check --config pyproject.toml` and `ruff format --config pyproject.toml --check` on all 4 modified/added Python files: **All checks passed**.
