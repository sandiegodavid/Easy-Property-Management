# Local workspace, backup and restore

## Workspace boundary

The operator's data lives in one configurable external folder, outside the Git checkout. The non-secret manifest carries stable workspace identity/version. SQLite is under `database/`; retained files are under `files/`; exports/backups have separate locations. Machine-local configuration points to the workspace; opening never silently initializes a replacement empty database.

Initialization/open checks paths, private permissions, exact current schema, retained records and runtime writer ownership. The latest greenfield baseline is the only accepted schema/format; legacy upgrade/adoption compatibility is not provided. A server-lifetime writer lock and runtime readiness protect writes. Reopen/restore changes runtime epoch so old continuations cannot cross runtime boundaries.

## Portable recovery

Backup/export create one versioned authenticated-encrypted package with manifest, consistent SQLite snapshot and verified retained files. Passphrases require at least 12 characters. Credentials and machine-local external authorization are excluded. The package keeps stable IDs, audit, command receipts, source history and managed evidence.

Publish only complete verified encrypted archives to a separately configured destination. Destination checks require atomic hard-link publication; unsupported filesystems fail configuration. Restore validates into a new/empty external destination and never overwrites or switches the active workspace automatically. Validate identity, exact schema, retained data, file hashes and archive path safety before using it.

Manual backup is available through CLI. Optional daily backup stores the passphrase in the OS credential store only after explicit opt-in; startup composes the scheduler and exposes outcome/failure state. A remote File provider must supply the exact retained object versions for a complete archive, without copying provider credentials.

## Operational entry points

Follow the [root README](../../README.md#local-workspace-foundation) for environment/configuration and CLI commands. `WorkspaceService` initializes/opens; archive/backup services validate, publish and restore; `runtime.py` owns readiness/lifetime; bootstrap composes API and scheduling. Operator bootstrap supplies safe browser guidance when a workspace is unavailable.

Keep portable identity separate from host configuration and runtime epoch. Recovery must never mistake a missing workspace for a verified empty portfolio.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/workspace/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/workspace/application).
- [HTTP contracts](../../application/apps/server/app/modules/workspace/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/workspace/infrastructure).

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_api.py](../../application/apps/server/app/modules/workspace/tests/test_api.py).
- [test_backup_service.py](../../application/apps/server/app/modules/workspace/tests/test_backup_service.py).
- [test_bootstrap_gate.py](../../application/apps/server/app/modules/workspace/tests/test_bootstrap_gate.py).
- [test_command_baseline.py](../../application/apps/server/app/modules/workspace/tests/test_command_baseline.py).
- [test_locking.py](../../application/apps/server/app/modules/workspace/tests/test_locking.py).
- [test_service.py](../../application/apps/server/app/modules/workspace/tests/test_service.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
