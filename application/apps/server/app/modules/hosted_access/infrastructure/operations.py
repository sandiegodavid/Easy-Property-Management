"""Private offline operational commands, never registered in the business HTTP API."""

import os
from pathlib import Path

from app.modules.hosted_access.application.configuration import HostedConfigurationError
from app.modules.hosted_access.infrastructure.configuration import (
    load_hosted_deployment,
    validate_workspace_binding,
)
from app.modules.hosted_access.infrastructure.storage_budget import build_storage_budget
from app.platform.locking import WorkspaceOperationLock


def create_hosted_backup(path, backups, output: Path, passphrase):
    deployment = load_hosted_deployment(path)
    service = backups.workspace_service
    validate_workspace_binding(deployment, service, require_unexpired=False)
    staging = backups.archives.staging_directory
    if staging is None or deployment.storage_volume in staging.resolve().parents:
        raise HostedConfigurationError(
            "Hosted backup staging must be explicit and outside the bounded volume."
        )
    if deployment.storage_volume in output.resolve().parents:
        raise HostedConfigurationError("Hosted archives must be outside the bounded volume.")
    for directory in (staging, output.parent):
        info = directory.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise HostedConfigurationError(
                "Backup staging and archive directories must be private to their owner."
            )
    budget = build_storage_budget(deployment, service.paths.root)
    lock_path = service.paths.root.parent / f".{service.paths.root.name}.server.lock"
    # Holding the same lifetime lock proves the server drained/stopped and also
    # prevents it restarting during the complete DB + attachment snapshot.
    with WorkspaceOperationLock(lock_path), budget.reserve(0, write=True):
        result = backups.create_backup(passphrase, output_path=output)
        contents = backups.validate_archive(result.archive_path, passphrase)
        if contents.header["sourceWorkspaceId"] != str(deployment.workspace_id):
            raise HostedConfigurationError("Validated backup has a different workspace identity.")
        return result
