# HOSTED-001 Slice H05.2 Checkpoint — Backup Engine, Envelope Encryption & `epm-backup-proxy`

**Date:** 2026-11-22
**Owning Design Doc:** [HOSTED_MVP_H05_DESIGN.md](../../design/HOSTED_MVP_H05_DESIGN.md#9-ordered-implementation-plan)
**Status:** Complete

## Summary of Changes

1. **Content-Addressed Chunked AEAD Backup Engine (D2)**:
   - Added `application/apps/server/app/modules/hosted_recovery/domain/models.py` defining strict contracts (`EnvelopeContext`, `ChunkRef`, `DatabaseSnapshotManifest`, `RetainedFileManifest`, `RecoveryPointManifest`, `ManifestEnvelope`, `BackupPointResult`, `RestorePointResult`, `PruneResult`), SHA-256 / relative-key / KMS `key_ref` validators, and deterministic canonical AAD derivation binding `(deployment_id, scope_kind, operator_id, workspace_id, point_id, schema_revisions, key_ref)`.
   - Added `application/apps/server/app/modules/hosted_recovery/application/ports.py` (`ObjectStorePort`, `KmsPort`, `BackupTransport`).
   - Added `application/apps/server/app/modules/hosted_recovery/infrastructure/engine.py` (`ChunkedAeadBackupEngine`): pure-Python `AES-256-GCM` chunked encryption (`EPMC` framed chunks), key-fingerprint-namespaced content-addressed deduplication across points via `head_object`, manifest-last publication, readback verification (`verify_point`), empty-directory safe restore with traversal/symlink/digest/AEAD checks (`restore_point`), and reference-safe chunk pruning (`prune_unreferenced_chunks`).
2. **Host-Side Cloudflare R2 & GCP Cloud KMS Adapters (D2)**:
   - Added `application/apps/server/app/modules/hosted_recovery/infrastructure/r2_store.py` (`R2ObjectStore` with strict HTTPS R2 endpoint/bucket validation, `s3v4`, `x-amz-meta-epm-sha256` verification, plus `LocalDirectoryObjectStore` test adapter).
   - Added `application/apps/server/app/modules/hosted_recovery/infrastructure/kms_provider.py` (`CloudKmsEnvelopeProvider` calling GCP Cloud KMS REST v1 `:encrypt`/`:decrypt` over HTTPS with AAD and metadata-server token support, plus `LocalAesKmsProvider` test adapter).
3. **`SO_PEERCRED` Prefix-Enforcing `epm-backup-proxy` (D3)**:
   - Added `application/apps/server/app/modules/host_agent/infrastructure/backup_proxy.py`:
     - `InventoryPeerResolver`: resolves kernel peer UID against read-only `host_inventory.sqlite` (zero Admin DB dependency), confining each active Operator to `deployments/<deployment_id>/operators/<operator_id>/` and Admin to `deployments/<deployment_id>/control/`, rejecting unknown and retired UIDs.
     - `BackupProxyHandler`: enforces relative-key traversal checks, per-scope KMS `key_ref` allowlists, and proxy-bound KMS AAD (preventing cross-operator DEK unwrap even with forged caller AAD).
     - `backup_proxy_listener`, `BackupProxyServer`, and `UnixBackupProxyClient`: bounded binary-framed `AF_UNIX` transport with mutual kernel `peer_uid` verification so zero R2/KMS credentials enter any container.
4. **Legacy Helper Retirement (D11)**:
   - Removed legacy `hosted_access/application/recovery_publication.py`, `hosted_access/infrastructure/recovery_publication.py`, `hosted_access/infrastructure/recovery_bundle.py`, and their obsolete tests (`test_recovery_publication.py`, `test_recovery_bundle.py`, and the legacy publication test in `test_offline_backup.py`).
   - Removed retired CLI subcommands (`hosted-publish-backup`, `hosted-recovery-status`, `hosted-recovery-bundle`, `hosted-unpack-recovery-bundle`) from `application/apps/server/app/__main__.py` while preserving all `LOCAL-002` local desktop backup/restore commands.
   - Removed legacy `load_recovery_configuration` / `prepare_recovery` wiring from `application/scripts/release_demo.py` and `application/scripts/tests/test_release_demo.py`.

## Validation Results

- `pytest` component proof (`apps/server/app/modules/hosted_recovery/tests/test_backup_engine_and_proxy.py`): **6 passed** (5 in-process sandboxed + 1 real `AF_UNIX` `SO_PEERCRED`/`getpeereid` test), proving deduplication across points, reference-safe pruning, key rotation, chunk/manifest tamper & missing-chunk rejection, cross-prefix & cross-operator KMS denial, unknown/retired UID denial, and R2/Cloud KMS protocol handling.
- `pytest` legacy retirement regression (`test_offline_backup.py`, `scripts/tests/test_release_demo.py`): **24 passed**.
- `ruff check --config application/pyproject.toml`: **All checks passed** across all 15 new/modified Python files.
- `ruff format --check --config application/pyproject.toml`: **15 files already formatted**.

## Next Slice

- **H05.3**: Internal Workspace Backup Runner & Stale Alerting (`WorkspaceRecoveryPort.capture`/`reconcile_checkpoint`, consistent SQLite+file snapshot, `healthy` vs. `unchanged` detection, 7-point reference-safe retention, overdue alerting, async signed `workspace_recovery_status` sync).
