# HOSTED-001 H04.9 Implementation Checkpoint — Native Linux/Docker/GCP Free Physical Storage Sizing Qualification

- **Date**: 2026-11-22
- **Slice**: `H04.9` (Native Linux/Docker/GCP Free physical storage sizing qualification) from [`HOSTED_MVP_H04_DESIGN.md`](HOSTED_MVP_H04_DESIGN.md)
- **Status**: **Complete (Native Linux/Docker/GCP Signed Off)**

## Target & Pinned Evidence

- **Host**: `epm-h02-host` (`project-47b72bb7-ba90-42c9-910`, `us-west1-b`, Linux `7.0.0-1017-gcp`, `x86_64`)
- **Filesystem**: `/srv/epm/data` (`UUID=8d2fd2e0-274b-4535-90d5-da78aa6bd9b6`, ext4 `rw,relatime,nodev,nosuid,noexec,prjquota`)
- **Base Operator Image**: `us-west1-docker.pkg.dev/project-47b72bb7-ba90-42c9-910/epm-h02-candidates/operator@sha256:6c264a90ff2f9a64e1d66b8e5b1405680d517210b4e3d1c586816603c486c995`
- **Source Snapshot SHA-256**: `e5f250357a7ac1eb36951a2146f566d8c83a7d09040a09a31b493d2ac681fcf4`
- **Evidence SHA-256**: `da1acb506aef5ca87a7500d841ef1e75cf76f3a5c255a1a0d6873e0970eead41`
- **Artifacts**:
  - [`HOSTED_MVP_H04_9_EVIDENCE.json`](../qualification/reports/HOSTED_MVP_H04_9_EVIDENCE.json)
  - [`HOSTED_MVP_H04_9_FREE_SIZING.json`](../qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json)

## Native Measurements & Derived Physical Ceilings

| Tree | Measured Peak Bytes | Measured Peak Inodes | Derived Byte Ceiling (`1.35×` + headroom) | Derived Inode Ceiling (`1.35×` + headroom) |
|---|---:|---:|---:|---:|
| **`workspace`** | `100,249,600` (95.6 MiB) | `3,075` | **`169,869,312` (162 MiB)** | **`5,376`** |
| **`control`** | `1,257,472` (1.2 MiB) | `4` | **`18,874,368` (18 MiB)** | **`768`** |
| **`scratch`** | `8,192` | `2` | **`34,603,008` (33 MiB)** | **`768`** |

- **Workload shapes (all under `50,000,000`-byte logical Free ceiling with logical `507` verified)**:
  - `database_heavy`: `49,913,856` logical bytes (`11,648` rows + WAL checkpoint + `VACUUM`), `workspace` peak `100,249,600` bytes.
  - `retained_file_heavy`: `48,234,496` logical bytes (`22` large blobs), `workspace` peak `48,939,008` bytes.
  - `many_small_files_history`: `49,987,584` logical bytes (`2,808` 16 KiB files + reservation history), `workspace` peak `3,075` inodes, `control` peak `1,257,472` bytes.
- **Independent physical exhaustion proofs (ext4 `prjquota`)**:
  - `byte_exhaustion`: observed kernel `errno=122` (`EDQUOT`), `PRAGMA integrity_check == 'ok'`, acknowledged rows preserved, `usage_reservations` reconciled, post-fault HTTP `507` verified.
  - `inode_exhaustion`: observed kernel `errno=122` (`EDQUOT`), `PRAGMA integrity_check == 'ok'`, acknowledged rows preserved, `usage_reservations` reconciled, post-fault HTTP `507` verified.
- **Explicit H05 boundary**: `h05_backup_restore_reserve="deferred_to_H05"`, `restore_readiness="unavailable_pending_H05"`, `admission_enabled=False`.

## Real Linux/Docker Findings Resolved During Qualification

1. **`--read-only` SQLite `VACUUM`**: SQLite `VACUUM` failed with `disk I/O error` when `TMPDIR`/`SQLITE_TMPDIR` defaulted to read-only `/tmp`. Setting `TMPDIR=/scratch` and `SQLITE_TMPDIR=/scratch` routed `VACUUM` temp files into the bounded `/scratch` project-quota tree.
2. **ext4 `prjquota` Cross-Project `EXDEV`**: `os.replace()` from `/scratch` to `/workspace` fails with `Errno 18 (EXDEV)` across distinct ext4 project-quota IDs. Staging must copy into a temporary file within `/workspace`, atomically `os.replace()` inside `/workspace`, and unlink the `/scratch` staging file.

## Summary of Code & Validation

- **Harness & Validator**:
  - `application/deploy/hosted-mvp/gcp/free_sizing_actor.py`
  - `application/deploy/hosted-mvp/gcp/qualify_free_sizing.py`
  - `application/scripts/tests/test_h04_free_sizing_qualification.py`
- **Validation**:
  - `validate_free_sizing_document()` verified `HOSTED_MVP_H04_9_FREE_SIZING.json` against `HOSTED_MVP_H04_9_EVIDENCE.json` and `source_sha256`.
  - `cd application && .venv/bin/pytest scripts/tests/test_h04_free_sizing_qualification.py`: **11 passed**.
  - `ruff check` and `ruff format --check` on all 3 Python files: **Passed**.
  - `epm-h02-host` stopped cleanly after artifact retrieval.

## Next Slice

- **H04.10**: Deployed H04/H05 handoff verification (provision 2 disposable Operator assignments on GCP, prove missing readiness/H05 protection holds both closed, verify Admin-lite + invitation/claim boundaries).
