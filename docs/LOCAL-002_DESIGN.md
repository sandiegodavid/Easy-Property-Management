# LOCAL-002 — Local Backup, Export, Validation, and Restore Design

## Purpose

`LOCAL-002` protects the single-operator local workspace by creating encrypted, portable, verifiable recovery packages. The same package format supports routine backup, intentional export, future SaaS migration preparation, and restore to a new workspace.

It builds on `LOCAL-001`'s external workspace, stable workspace ID, private filesystem permissions, manifest, and SQLite identity store.

## Decisions already made

- Portable backup and export archives require passphrase-based authenticated encryption.
- Archives are written to a separately selected destination, not only inside the live workspace.
- Manual backup is always available.
- Automatic backup is supported after a destination exists, but the operator is not required to create or understand a schedule.
- Future risky operations such as database migration and workspace relocation will request a fresh backup; this MVP has no such operations yet.
- Restore creates and validates a new workspace; it never overwrites the active workspace in place.
- External-provider credentials and tokens are excluded from every archive, export, restore, and migration package.

## Package format

Use one versioned archive format with an application-specific extension, for example:

```text
easy-property-management-backup-YYYY-MM-DDTHH-MM-SSZ.epm-backup
```

The encrypted payload contains:

```text
backup-manifest.json
workspace/
├── workspace.json
├── database/
│   └── property-management.sqlite
└── files/
```

`backup-manifest.json` contains only non-secret package metadata:

- Package format version
- Package type: `backup` or `export`
- Source workspace ID and source workspace format version
- Application and database-schema version
- Creation time in UTC
- Encryption algorithm and key-derivation metadata, excluding the passphrase
- A file inventory with workspace-relative path, byte size, and SHA-256 digest
- Counts and sizes for quick inspection
- Explicit declaration that credentials, live SQLite journal files, and nested backup/export directories are excluded

The archive includes a consistent SQLite snapshot, not the live `.sqlite-wal` or `.sqlite-shm` files. It includes only workspace-relative attachments under `files/`; the live `backups/` and `exports/` directories are never recursively included.

## Encryption and passphrases

Archives use a well-maintained cryptography library to provide authenticated encryption and a memory-hard passphrase-derived key. The implementation should use an audited modern construction such as AES-256-GCM with Argon2id-derived key material; an equivalent reviewed construction is acceptable only if it preserves confidentiality and tamper detection.

The passphrase is never written to:

- The archive or its manifest
- `config.local.json`
- The SQLite workspace database
- Git-tracked files
- Logs, errors, or analytics
- The operating-system credential store by default

The operator must supply the passphrase to create or restore an archive. The UI must explain that an unrecoverable passphrase means an unrecoverable archive. Passphrase confirmation is required when creating a new backup destination policy; restore asks once and may permit a limited, rate-controlled retry flow.

## Backup flow

1. The operator selects **Back up now**, or the local scheduler starts a due backup or a pre-risk-operation backup.
2. The application confirms the workspace is valid, writable, and not already in a conflicting restore or relocation operation.
3. The application creates a private temporary staging directory outside the live workspace and target archive.
4. It creates a consistent SQLite snapshot through SQLite's backup API.
5. It copies the `workspace.json`, snapshot database, and attachment files into staging using only workspace-relative paths.
6. It calculates a SHA-256 digest and byte size for each included file, then writes `backup-manifest.json`.
7. It encrypts the complete payload with the supplied passphrase.
8. It writes the encrypted result to a temporary file in the selected backup destination, flushes it, validates it, and atomically renames it to the final `.epm-backup` filename.
9. It records a local backup result: success or failure, time, destination, package identifier, size, package type, and validation result. It never records the passphrase.
10. It applies retention only after the new archive has been validated successfully.

If any stage fails, the application removes only its uniquely named staging files, reports a clear failure, and leaves the live workspace unchanged. A failed backup must not replace or delete a prior successful backup.

## Export flow

Export uses the exact same package format and validation flow as backup. Its differences are user intent and naming:

- The operator explicitly chooses the destination and export name.
- The result is suitable for transfer, support, or future SaaS migration preparation.
- It may include a human-readable summary outside the encrypted archive only if that summary contains no user data or identifiers; the default is to include no sidecar summary.
- It does not alter backup retention or replace routine backup history.

## Validation

Validation is available for the active workspace and for a selected archive.

### Active workspace validation

- Confirm `workspace.json` is parseable and has a supported format version.
- Confirm the workspace ID in the manifest matches the SQLite identity record.
- Run SQLite `PRAGMA integrity_check` on a read-only connection.
- Confirm expected directories are present and private permissions are enforced where supported.
- Confirm database and manifest paths remain workspace-relative and inside the configured workspace.
- Once `FILE-001` exists, confirm attachment references resolve to files inside `files/` and report missing or unexpected files.

### Archive validation

- Confirm the archive header and package format version are supported before requesting a passphrase where possible.
- Decrypt only after passphrase entry and authenticate the encrypted payload before processing its contents.
- Reject path traversal, absolute paths, symlinks, duplicate paths, oversized entries, and unexpected top-level files.
- Verify every payload file against the manifest's SHA-256 digest and byte size.
- Validate the restored workspace manifest, SQLite identity match, and SQLite integrity before marking an archive valid.
- Report valid, warning, or failed status with an actionable reason.

## Restore flow

1. The operator selects a `.epm-backup` archive and supplies its passphrase.
2. The application selects a **new or empty external workspace destination**. It rejects the Git repository, the current active workspace, and a nonempty unrecognized folder.
3. It validates and decrypts the archive into a private staging directory beside the requested destination.
4. It validates the reconstructed workspace completely: manifest, package inventory, file hashes, SQLite identity, and SQLite integrity.
5. It hardens workspace permissions and atomically publishes the validated staging directory as the restored workspace.
6. The application shows the restored workspace ID, source backup time, record/file counts, and validation result.
7. The operator explicitly chooses whether to update `config.local.json` to open the restored workspace. The current workspace is never changed automatically.
8. External mail, SMS, AI, and other provider accounts remain disconnected until reauthorized.

Restore cannot delete, overwrite, or mutate the active workspace. The operator may compare the restored workspace before switching. A failed restore deletes only its uniquely named staging directory.

## Backup destination and retention

The backup destination is configured separately from the live workspace. It may be a secondary local disk, removable drive, or synchronized folder. The application warns if it is the same volume as the live workspace and explains that synchronized folders are appropriate only for completed encrypted archives, never for the live SQLite database.

The default retention policy should be understandable and conservative:

- Keep the most recent 7 daily backups.
- Keep the most recent 4 weekly backups.
- Keep the most recent 12 monthly backups.
- Never delete an archive that has not been successfully validated.
- Show the operator which archives would be deleted before applying a changed retention policy.

Retention is scoped to archives created by the current workspace ID and destination policy. Exports are never removed automatically.

## Manual and automatic operation

Manual operations are always available from **Settings → Data & Backup** and through operator-run commands.

After the operator selects a backup destination, they may explicitly enable a sensible daily automated policy without configuring a schedule. Enabling it stores the passphrase only in the operating-system credential store; manual backups never do so. Operators can later pause or disable automatic backups.

If the application is not running when a scheduled backup is due, it runs at the next eligible application start rather than pretending the missed backup occurred. The status output shows the last successful backup, next scheduled attempt, and most recent failure; richer destination health and retention summaries remain future interface work.

## Interfaces

`LOCAL-002` adds local-only workspace capabilities:

- `Back up now`
- `Export workspace`
- `Validate workspace`
- `Validate archive`
- `Restore archive to new workspace`
- `Configure backup destination and retention`
- `View backup history and last failure`

Operator commands mirror those actions for assisted MVP setup and recovery. Public or remote backup endpoints are out of scope.

## Security and safety requirements

- Backup, export, restore, relocation, and schema migration must be mutually exclusive operations.
- The implementation must use private staging files and directories, owner-only permissions where the operating system supports them, and atomic publish operations on the same filesystem.
- Archive extraction must never follow symlinks or write outside its staging directory.
- Errors must redact passphrases, source content, access tokens, and sensitive file names where practical.
- The application must not label a backup successful until post-write validation completes.
- The active workspace must remain usable after a failed backup, export, validation, or restore attempt.

## Out of scope

- Cloud-hosted backup storage, account synchronization, or central key recovery
- Initiating a backup through a remote portal
- Restoring over an existing active workspace
- Preserving external-provider credentials in an archive
- Full SaaS migration; this archive format is only designed to prepare for it

## Acceptance criteria

`LOCAL-002` is complete when an operator can:

1. Create a passphrase-encrypted, validated backup in a separate destination while the local SQLite workspace is active.
2. Create an intentional export using the same portable format.
3. Validate both a workspace and an archive with clear failure messages.
4. Restore a valid archive to a new external workspace without altering the active one.
5. Reject a wrong passphrase, a modified archive, a corrupted database, missing files, unsafe archive paths, and unsupported format versions without creating a usable-looking partial restore.
6. See manual backup controls and automatic backup status without being required to configure a schedule.
7. Confirm that the archive contains no external-provider credentials or live SQLite journal files.
