"""Restore an isolated browser fixture using the production encrypted archive service."""

import argparse
import json
from pathlib import Path

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    config = root / "config.json"
    workspace = WorkspaceService.from_local_config(config)
    backups = BackupService(
        workspace,
        AuditRecorder(SQLiteAuditRepository(workspace.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    # Test-only input: no OS credential store and no credential in the archive.
    passphrase = "browser acceptance temporary archive passphrase"
    archive = backups.create_backup(passphrase, output_path=root / "acceptance.epmbackup")
    restored = root / "restored"
    backups.restore(archive.archive_path, passphrase, restored)
    config.write_text(json.dumps({"localWorkspacePath": str(restored)}))


if __name__ == "__main__":
    main()
