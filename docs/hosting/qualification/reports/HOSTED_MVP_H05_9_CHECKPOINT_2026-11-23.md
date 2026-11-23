# HOSTED-001 Slice H05.9 Checkpoint — Native Linux/Docker/GCP Backup/Restore Reserve Sizing

**Date:** 2026-11-23  
**Slice:** H05.9 (`HOSTED_MVP_H05_DESIGN.md` Section 8)  
**Status:** Harness & Validator Complete (Native GCP execution on `epm-h02-host` queued for live VM run in H05.11)

## Summary of Changes

1. **H05 Backup/Restore Sizing Actor** (`application/deploy/hosted-mvp/gcp/h05_sizing_actor.py`):
   - Exercises all three workload shapes (`database_heavy`, `retained_file_heavy`, `many_small_files_history`) at the Free `50,000,000`-byte logical allowance through:
     - 7 consecutive verified `Capture` operations via `HostedWorkspaceRecoveryService`, `ChunkedAeadBackupEngine`, and `BackupProxyHandler` (measuring true concurrent `scratch` staging peak bytes/inodes via `on_activity` sampling during chunk upload, plus `control` `recovery.sqlite` + audit churn).
     - Full `PreviewRestore` → `ConfirmRestore` into a concurrent sibling incarnation (`incarnation-2`) while retaining `incarnation-1` (measuring `workspace` live + concurrent staged restore + 1 retained prior/forensic incarnation).
   - Implements independent byte and inode exhaustion/rollback proofs (`backup_byte_exhaustion`, `backup_inode_exhaustion`, `restore_byte_exhaustion`, `restore_inode_exhaustion`) verifying Linux `EDQUOT`/`ENOSPC`, clean staging rollback, intact original business DB (`PRAGMA integrity_check`), zero silent empty initialization, and honest recovery status.
2. **Closed H05.9 Reserve Sizing Validator & GCP Image Builder** (`application/deploy/hosted-mvp/gcp/qualify_h05_sizing.py`):
   - Enforces native Linux (`platform == "Linux"`), verified ext4 `prjquota` with `nodev,nosuid,noexec`, all 3 workload shapes with >= 7 verified captures and concurrent restore staging, and all 4 independent byte/inode exhaustion proofs. Never accepts macOS or synthetic/unmeasured constants.
   - Derives updated Free physical ceilings with justified nonzero margins (`round_up(peak * margin_factor + min_headroom, quota_unit)`), replacing `"deferred_to_H05"` with pinned per-tree `h05_backup_restore_reserve` ceilings and deltas against `HOSTED_MVP_H04_9_FREE_SIZING.json`, and validates the closed document against bound evidence & source SHA-256 digests.
   - Includes offline Docker actor image builder (`build_h05_actor_image`) for native `epm-h02-host` execution.
3. **Unit & Contract Tests** (`application/scripts/tests/test_h05_sizing_qualification.py`):
   - Exercises all 3 workload shapes through 7 captures + concurrent restore staging, all 4 exhaustion/rollback proofs, and negative/positive validator cases (macOS rejection, missing `prjquota`, `< 7` captures, missing exhaustion proof, tampered digest).

## Validation Results

- `cd application && .venv/bin/python -m pytest scripts/tests/test_h05_sizing_qualification.py -v`: **8 passed**.
- `cd application && .venv/bin/ruff check --config pyproject.toml` and `ruff format --config pyproject.toml --check` on all 3 new Python files: **All checks passed**.

## Remaining Live-Host Execution Note
- `epm-h02-host` is currently stopped; `docs/hosting/qualification/reports/HOSTED_MVP_H05_9_RECOVERY_SIZING.json` must only be generated from native Linux ext4 `prjquota` evidence on `epm-h02-host` (never fabricated on macOS) and will be executed during the live GCP run in H05.11.
