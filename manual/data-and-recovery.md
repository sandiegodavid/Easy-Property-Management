# Data protection and recovery

[Manual contents](README.md)

These command-line steps are for the installer or an operator comfortable with the terminal. Run them from `application/` with `source .venv/bin/activate`; they use `config.local.json`. To select another file, put `--config /absolute/path/config.json` **before** the command.

For administrative operations, finish/reconcile open work and stop the server first, then restart after validation. Optional automatic backups run through the application's own scheduler while it is running.

## Understand the folders

The external workspace contains `workspace.json`, `database/property-management.sqlite`, managed `files/`, exports and backups. Treat it as a managed set. The checkout and machine configuration are separate; credentials live in the operating-system credential store. Never edit the SQLite database or rename retained files to correct a record.

## Set a backup destination

Select a separate supported local drive/folder, ideally separate from the live workspace:

```bash
python -m app configure-backup-destination /absolute/path/to/encrypted-backups
python -m app backup-status
```

The filesystem must support the application's atomic hard-link publication check. If rejected, select a supported destination rather than bypassing validation. Only completed encrypted archive files should be cloud-synchronized; do not synchronize the live database.

## Create and validate an encrypted backup

```bash
python -m app validate-workspace
python -m app backup
```

Read and retain the reported archive path. The command prompts for a passphrase of at least 12 characters. Keep it recoverable outside the workspace; an archive without its passphrase is not a usable recovery plan.

Validate the produced archive:

```bash
python -m app validate-archive /absolute/path/to/archive.epm-backup
```

A manual alternate output is supported with `python -m app backup --output /absolute/path/to/new-archive.epm-backup`. Use a new output path. Do not copy only the database file while it is live; the application backup creates a consistent database/files package.

## Export

```bash
python -m app export /absolute/path/to/portable-export
```

Export is also passphrase-encrypted. It does not mean an unencrypted spreadsheet/report or automatic cloud migration. Inspect the command's reported result/path and keep the necessary passphrase.

## Optional automatic daily backups

```bash
python -m app enable-automatic-backups
python -m app backup-status
```

This explicitly opts in to storing the backup passphrase in the device credential store. A backup destination must be configured. The automatic scheduler runs while the application server runs; it does not guarantee a backup while the computer/app is off. Inspect failures and keep a manual routine as needed.

Administrative commands also include:

```bash
python -m app run-due-automatic-backup
python -m app disable-automatic-backups
```

The first performs the due check; it may report nothing is due. Disabling removes the automatic-backup credential. These commands are unrelated to the deferred Dashboard cron proposal.

## Restore a backup

1. Stop the server; preserve the existing workspace and configuration.
2. Choose a new/empty external destination, distinct from the existing workspace.
3. Validate the archive, then run:

```bash
python -m app restore /absolute/path/to/archive.epm-backup /absolute/path/to/restored-workspace
```

4. Enter the archive passphrase when prompted. Restore validates the archive and retained data; it does not switch the active workspace automatically.
5. Change `localWorkspacePath` in `config.local.json` to the restored absolute folder.
6. Run `python -m app workspace-status`, then start the server.
7. Inspect known records, files and unfinished forms. Recover original unknown results before new submissions. Reconfigure device credentials/authorization as needed and check backup settings.
8. Retain the old workspace until you have verified the restored copy and its backup path.

Restore is into a new/empty destination; never delete live records to make room for it.

## Move or switch a workspace

For a safe move, use the backup/restore sequence above into the new folder, validate, then switch configuration with the server stopped. Do not move the open SQLite files in a file browser. Keep the old copy until verified. Switching among already valid workspaces similarly requires stopping the server, updating the absolute config path, validating and restarting. Browser folder selection alone cannot switch the server.

## Optional S3-managed files

Ask the installer to configure this optional adapter. From `application/`:

```bash
python -m pip install -e '.[dev,s3]'
```

Set `fileStorageProvider` to `"s3"`, configure `s3Bucket` and optionally `s3Prefix`, and use a versioned bucket with host-managed AWS credentials. Do not write AWS secrets into app configuration. Keep `s3Bucket` configured when changing new uploads back to local so existing remote files remain readable. Backups need access to the exact retained object versions. Changing the provider does not automatically relocate existing documents.

## Setup completion check

Have the installer demonstrate a backup, archive validation and restore into a separate test destination before relying on recovery. Keep an approved compatible application release with your recovery instructions. Configuration, OS credentials and unsupported legacy formats are not automatically reconstructed by restoring portable data.
