"""Commands for the local application."""

from __future__ import annotations

import argparse
import json
from getpass import getpass
from importlib import import_module
from pathlib import Path

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.content_store import S3ContentStore
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.admin import administer
from app.modules.hosted_access.infrastructure.operations import create_hosted_backup
from app.modules.hosted_access.infrastructure.recovery_publication import (
    publish_archive,
    load_recovery_configuration,
    FileRecoveryLedger,
)
from app.modules.hosted_access.application.recovery_publication import (
    recovery_status,
    RecoveryPublicationError,
)
from app.modules.hosted_access.infrastructure.recovery_bundle import (
    create_configuration_bundle,
    unpack_configuration_bundle,
)
from app.modules.hosted_access.infrastructure.configuration import (
    HostedConfigurationError,
    load_hosted_deployment,
    validate_workspace_binding,
)
from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.platform.browser_transport import BrowserTransportPolicy, MAX_PORT


def _config_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _archive_staging(args: argparse.Namespace) -> Path | None:
    value = getattr(args, "staging_directory", None)
    return Path(value).resolve() if value else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Easy Property Management")
    parser.add_argument("--config", help="Path to the ignored local workspace configuration file.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("initialize-workspace", help="Create the configured workspace.")
    commands.add_parser("workspace-status", help="Validate and display the configured workspace.")
    hosted_check = commands.add_parser(
        "validate-hosted-config",
        help="Validate a protected hosted-demo deployment without serving.",
    )
    hosted_check.add_argument("deployment", help="Absolute administrator-owned configuration path.")
    hosted_admin = commands.add_parser("hosted-admin", help="Administer protected demo enrollment.")
    hosted_admin.add_argument("deployment", help="Absolute administrator-owned configuration path.")
    hosted_admin.add_argument(
        "action", choices=("initialize", "enrollments", "activate", "disable", "revoke", "rebind")
    )
    hosted_admin.add_argument("--subject", help="Verified pending subject to activate.")
    hosted_backup = commands.add_parser(
        "hosted-backup", help="Create and validate an offline hosted recovery point."
    )
    hosted_backup.add_argument("deployment")
    hosted_backup.add_argument("--output", required=True)
    hosted_backup.add_argument("--staging-directory", required=True)
    publish = commands.add_parser(
        "hosted-publish-backup", help="Validate and publish an encrypted archive to private R2."
    )
    publish.add_argument("deployment")
    publish.add_argument("recovery_configuration")
    publish.add_argument("archive")
    publish.add_argument("--staging-directory", required=True)
    recovery_status = commands.add_parser(
        "hosted-recovery-status",
        help="Show verified recovery age without loading credentials into a network client.",
    )
    recovery_status.add_argument("recovery_configuration")
    bundle = commands.add_parser(
        "hosted-recovery-bundle",
        help="Encrypt configuration and enrollment references without usable sessions.",
    )
    bundle.add_argument("deployment")
    bundle.add_argument("--output", required=True)
    unpack = commands.add_parser(
        "hosted-unpack-recovery-bundle",
        help="Decrypt recovery references into a new private file; never grants access.",
    )
    unpack.add_argument("archive")
    unpack.add_argument("--output", required=True)
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
            command.add_argument(
                "--staging-directory", help="Existing external archive staging folder."
            )
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
    serve.add_argument(
        "--development-origin",
        action="append",
        default=[],
        help="Explicit loopback frontend origin (repeatable); omitted in production.",
    )
    hosted_serve = commands.add_parser(
        "serve-hosted", help="Run an explicitly configured private hosted origin."
    )
    hosted_serve.add_argument("--deployment", required=True)
    hosted_serve.add_argument("--port", type=int, default=8001)
    return parser


def _backup_service(
    service: WorkspaceService, staging_directory: Path | None = None
) -> BackupService:
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
        archive_staging_directory=staging_directory,
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


def _run_hosted_archive(args, parser, backups) -> bool:
    if args.command not in {"hosted-backup", "hosted-publish-backup"}:
        return False
    try:
        if args.command == "hosted-publish-backup":
            published = publish_archive(
                Path(args.deployment),
                Path(args.recovery_configuration),
                Path(args.archive),
                backups,
                getpass("Backup passphrase: "),
            )
            print(json.dumps(published, sort_keys=True))
            return True
        result = create_hosted_backup(
            Path(args.deployment),
            backups,
            Path(args.output).resolve(),
            getpass("Backup passphrase: "),
        )
    except (
        HostedConfigurationError,
        BackupError,
        RecoveryPublicationError,
        OSError,
        RuntimeError,
    ) as error:
        parser.exit(1, f"Hosted backup failed: {error}\n")
    print(f"Validated encrypted hosted recovery point: {result.archive_path}")
    return True


def _run_hosted_bundle(args, parser) -> bool:
    if args.command not in {"hosted-recovery-bundle", "hosted-unpack-recovery-bundle"}:
        return False
    try:
        phrase = getpass("Administrator recovery passphrase: ")
        if args.command == "hosted-recovery-bundle":
            create_configuration_bundle(Path(args.deployment), Path(args.output), phrase)
        else:
            unpack_configuration_bundle(Path(args.archive), Path(args.output), phrase)
    except (
        HostedConfigurationError,
        HostedAccessError,
        RecoveryPublicationError,
        OSError,
    ) as error:
        parser.exit(1, f"Administrator recovery failed: {error}\n")
    print("Private recovery file created. Fresh verified enrollment is required after recovery.")
    return True


def _run_hosted_configuration(args, parser, service) -> bool:
    if args.command == "hosted-admin":
        try:
            print(administer(Path(args.deployment), service, args.action, args.subject))
        except (HostedConfigurationError, HostedAccessError, OSError) as error:
            parser.exit(1, f"{error}\n")
        return True
    if args.command == "validate-hosted-config":
        try:
            deployment = load_hosted_deployment(Path(args.deployment))
            validate_workspace_binding(deployment, service)
        except HostedConfigurationError as error:
            parser.exit(1, f"{error}\n")
        print("Hosted deployment identity and existing workspace validated; no server was started.")
        return True
    if args.command == "hosted-recovery-status":
        try:
            config = load_recovery_configuration(Path(args.recovery_configuration))
            # Status reads the verification ledger only: no SDK/client or network.
            status = recovery_status(FileRecoveryLedger(config))
            print(json.dumps(status, sort_keys=True))
        except (RecoveryPublicationError, OSError) as error:
            parser.exit(1, f"{error}\n")
        return True
    return False


def _serve(args, parser, config_path):
    uvicorn = import_module("uvicorn")
    create_app = import_module("app.bootstrap.api").create_app
    try:
        if args.command == "serve-hosted":
            application = create_app(config_path, hosted_deployment_path=Path(args.deployment))
        else:
            policy = BrowserTransportPolicy(tuple(args.development_origin))
            application = create_app(config_path, transport_policy=policy)
    except (HostedConfigurationError, HostedAccessError, ValueError, OSError) as error:
        parser.exit(1, f"Server configuration rejected: {error}\n")
    uvicorn.run(application, host="127.0.0.1", port=args.port, proxy_headers=False)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command in {"serve", "serve-hosted"} and not 1 <= args.port <= MAX_PORT:
        parser.error("Server port must be between 1 and 65535.")
    config_path = _config_path(args.config)
    service = WorkspaceService.from_local_config(config_path)
    if _run_hosted_bundle(args, parser) or _run_hosted_configuration(args, parser, service):
        return
    if _run_workspace_command(args.command, service):
        return
    staging = _archive_staging(args)
    backups = _backup_service(service, staging)
    if _run_hosted_archive(args, parser, backups):
        return
    if _run_backup_command(args, parser, backups):
        return
    _serve(args, parser, config_path)


if __name__ == "__main__":
    main()
