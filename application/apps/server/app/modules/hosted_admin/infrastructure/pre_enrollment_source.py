"""Fixed target-user offline backup helper; passphrase arrives only on private stdin."""

import argparse
import json
import os
from pathlib import Path
import sys

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.hosted_access.infrastructure.operations import create_hosted_backup
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deployment", type=Path)
    parser.add_argument("local", type=Path)
    parser.add_argument("workspace_id")
    parser.add_argument("output", type=Path)
    parser.add_argument("staging", type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise ValueError("Run backup as the isolated service identity.")
    phrase = sys.stdin.read(1025)
    if not 1 <= len(phrase) <= 1024:
        raise ValueError("A bounded private passphrase is required.")
    service = WorkspaceService.from_local_config(args.local)
    if service.open(integrity_check=True).workspace_id != args.workspace_id:
        raise ValueError("Workspace differs from the reserved identity.")
    backups = BackupService(
        service,
        AuditRecorder(SQLiteAuditRepository(service.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        archive_staging_directory=args.staging,
    )
    create_hosted_backup(args.deployment, backups, args.output, phrase)
    print(json.dumps({"workspace_id": args.workspace_id, "verified": True}))


if __name__ == "__main__":
    main()
