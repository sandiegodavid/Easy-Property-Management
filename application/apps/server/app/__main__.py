"""Commands for the local application."""

from __future__ import annotations

import argparse
from getpass import getpass
from importlib import import_module
from pathlib import Path

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.content_store import S3ContentStore
from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.workspace.application.service import WorkspaceService


def _config_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Easy Property Management")
    parser.add_argument("--config", help="Path to the ignored local workspace configuration file.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("initialize-workspace", help="Create the configured workspace.")
    commands.add_parser("workspace-status", help="Validate and display the configured workspace.")
    destination = commands.add_parser(
        "configure-backup-destination",
        help="Save a separate external folder for encrypted backup archives.",
    )
    destination.add_argument("destination")
    commands.add_parser(
        "validate-workspace", help="Check the workspace and SQLite database before backup."
    )
    backup = commands.add_parser(
        "backup", help="Create an encrypted backup in the configured destination."
    )
    backup.add_argument("--output", help="Optional external path for this backup archive.")
    export = commands.add_parser("export", help="Create an encrypted portable export package.")
    export.add_argument("output", help="External path for the export archive.")
    for name, help_text in (
        ("validate-archive", "Decrypt and validate an archive without restoring it."),
        ("restore", "Restore an archive into a new or empty external folder."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("archive")
        if name == "restore":
            command.add_argument("destination")
    commands.add_parser(
        "enable-automatic-backups", help="Opt in to daily backups using the OS credential store."
    )
    commands.add_parser(
        "disable-automatic-backups",
        help="Disable automatic backups and remove its stored credential.",
    )
    commands.add_parser(
        "backup-status", help="Show automatic-backup state without exposing credentials."
    )
    commands.add_parser(
        "run-due-automatic-backup", help="Run the daily backup once when it is due."
    )
    serve = commands.add_parser("serve", help="Run the local FastAPI server.")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def _backup_service(service: WorkspaceService) -> BackupService:
    remote_materializer = None
    if service.config.s3_bucket:
        try:
            boto3 = import_module("boto3")
        except ImportError as error:
            raise RuntimeError("S3 file storage requires the boto3 package.") from error
        remote_materializer = S3ContentStore(
            boto3.client("s3"),
            service.config.s3_bucket,
            service.config.s3_prefix,
            service.paths.root / ".file-content-locks",
        ).materialize
    return BackupService(
        service,
        AuditRecorder(SQLiteAuditRepository(service.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        remote_materializer=remote_materializer,
    )


def _run_workspace_command(command: str, service: WorkspaceService) -> bool:
    if command == "initialize-workspace":
        manifest = service.initialize()
        print(f"Workspace ready: {service.paths.root}")
        print(f"Workspace ID: {manifest.workspace_id}")
        return True
    if command == "workspace-status":
        manifest = service.open()
        print(f"Workspace ready: {service.paths.root}")
        print(f"Workspace ID: {manifest.workspace_id}")
        print(f"Format version: {manifest.format_version}")
        return True
    return False


def _run_backup_command(
    args: argparse.Namespace, parser: argparse.ArgumentParser, backups: BackupService
) -> bool:
    command = args.command
    if command == "configure-backup-destination":
        updated = backups.configure_destination(Path(args.destination))
        print(f"Backup destination ready: {updated.backup_destination_path}")
    elif command == "validate-workspace":
        manifest = backups.validate_workspace()
        print(f"Workspace validated: {manifest.workspace_id}")
    elif command in {"backup", "export"}:
        result = backups.create_backup(
            getpass("Backup passphrase: "),
            package_type="backup" if command == "backup" else "export",
            output_path=Path(args.output) if args.output else None,
        )
        print(f"Encrypted {result.package_type} created: {result.archive_path}")
    else:
        return _run_other_backup_command(args, parser, backups)
    return True


def _run_other_backup_command(
    args: argparse.Namespace, parser: argparse.ArgumentParser, backups: BackupService
) -> bool:
    command = args.command
    if command == "validate-archive":
        contents = backups.validate_archive(Path(args.archive), getpass("Backup passphrase: "))
        print(f"Archive validated: {contents.file_count} files, {contents.byte_count} bytes")
    elif command == "restore":
        result = backups.restore(
            Path(args.archive), getpass("Backup passphrase: "), Path(args.destination)
        )
        print(f"Workspace restored: {result.workspace_path}")
    elif command == "enable-automatic-backups":
        backups.enable_automatic_backups(getpass("Backup passphrase: "))
        print("Automatic daily backups enabled.")
    elif command == "disable-automatic-backups":
        backups.disable_automatic_backups()
        print("Automatic backups disabled.")
    elif command == "backup-status":
        for key, value in backups.backup_status().items():
            print(f"{key}: {value}")
    elif command == "run-due-automatic-backup":
        _run_due_backup(parser, backups)
    else:
        return False
    return True


def _run_due_backup(parser: argparse.ArgumentParser, backups: BackupService) -> None:
    try:
        result = backups.run_due_automatic_backup()
    except BackupError as error:
        parser.exit(1, f"{error}\n")
    print(
        f"Automatic backup created: {result.archive_path}"
        if result
        else "No automatic backup is due."
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    config_path = _config_path(args.config)
    service = WorkspaceService.from_local_config(config_path)
    if _run_workspace_command(args.command, service):
        return
    backups = _backup_service(service)
    if _run_backup_command(args, parser, backups):
        return
    uvicorn = import_module("uvicorn")
    create_app = import_module("app.bootstrap.api").create_app
    uvicorn.run(create_app(config_path), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
