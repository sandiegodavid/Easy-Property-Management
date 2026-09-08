"""Commands for the local application."""

from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path

from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.content_store import S3ContentStore


def _config_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Easy Property Management")
    parser.add_argument(
        "--config",
        help="Path to the ignored local workspace configuration file.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("initialize-workspace", help="Create the configured workspace.")
    commands.add_parser("workspace-status", help="Validate and display the configured workspace.")
    destination_parser = commands.add_parser(
        "configure-backup-destination", help="Save a separate external folder for encrypted backup archives."
    )
    destination_parser.add_argument("destination")
    commands.add_parser("validate-workspace", help="Check the workspace and SQLite database before backup.")
    backup_parser = commands.add_parser("backup", help="Create an encrypted backup in the configured destination.")
    backup_parser.add_argument("--output", help="Optional external path for this backup archive.")
    export_parser = commands.add_parser("export", help="Create an encrypted portable export package.")
    export_parser.add_argument("output", help="External path for the export archive.")
    archive_parser = commands.add_parser("validate-archive", help="Decrypt and validate an archive without restoring it.")
    archive_parser.add_argument("archive")
    restore_parser = commands.add_parser("restore", help="Restore an archive into a new or empty external folder.")
    restore_parser.add_argument("archive")
    restore_parser.add_argument("destination")
    commands.add_parser("enable-automatic-backups", help="Opt in to daily backups using the OS credential store.")
    commands.add_parser("disable-automatic-backups", help="Disable automatic backups and remove its stored credential.")
    commands.add_parser("backup-status", help="Show automatic-backup state without exposing credentials.")
    commands.add_parser("run-due-automatic-backup", help="Run the daily backup once when it is due.")
    serve_parser = commands.add_parser("serve", help="Run the local FastAPI server.")
    serve_parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    config_path = _config_path(args.config)
    service = WorkspaceService.from_local_config(config_path)

    if args.command == "initialize-workspace":
        manifest = service.initialize()
        print(f"Workspace ready: {service.paths.root}")
        print(f"Workspace ID: {manifest.workspace_id}")
        return

    if args.command == "workspace-status":
        manifest = service.open()
        print(f"Workspace ready: {service.paths.root}")
        print(f"Workspace ID: {manifest.workspace_id}")
        print(f"Format version: {manifest.format_version}")
        return

    remote_materializer = None
    if service.config.s3_bucket:
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("S3 file storage requires the boto3 package.") from error
        remote_materializer = S3ContentStore(
            boto3.client("s3"),
            service.config.s3_bucket,
            service.config.s3_prefix,
            service.paths.root / ".file-content-locks",
        ).materialize
    backups = BackupService(
        service,
        AuditRecorder(SQLiteAuditRepository(service.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        remote_materializer=remote_materializer,
    )
    if args.command == "configure-backup-destination":
        updated = backups.configure_destination(Path(args.destination))
        print(f"Backup destination ready: {updated.backup_destination_path}")
        return

    if args.command == "validate-workspace":
        manifest = backups.validate_workspace()
        print(f"Workspace validated: {manifest.workspace_id}")
        return

    if args.command in {"backup", "export"}:
        passphrase = getpass("Backup passphrase: ")
        result = backups.create_backup(
            passphrase,
            package_type="backup" if args.command == "backup" else "export",
            output_path=Path(args.output) if args.output else None,
        )
        print(f"Encrypted {result.package_type} created: {result.archive_path}")
        return

    if args.command == "validate-archive":
        contents = backups.validate_archive(Path(args.archive), getpass("Backup passphrase: "))
        print(f"Archive validated: {contents.file_count} files, {contents.byte_count} bytes")
        return

    if args.command == "restore":
        result = backups.restore(Path(args.archive), getpass("Backup passphrase: "), Path(args.destination))
        print(f"Workspace restored: {result.workspace_path}")
        return

    if args.command == "enable-automatic-backups":
        backups.enable_automatic_backups(getpass("Backup passphrase: "))
        print("Automatic daily backups enabled.")
        return

    if args.command == "disable-automatic-backups":
        backups.disable_automatic_backups()
        print("Automatic backups disabled.")
        return

    if args.command == "backup-status":
        for key, value in backups.backup_status().items():
            print(f"{key}: {value}")
        return

    if args.command == "run-due-automatic-backup":
        try:
            result = backups.run_due_automatic_backup()
        except BackupError as error:
            parser.exit(1, f"{error}\n")
        print(f"Automatic backup created: {result.archive_path}" if result else "No automatic backup is due.")
        return

    from app.bootstrap.api import create_app
    import uvicorn

    uvicorn.run(create_app(config_path), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
