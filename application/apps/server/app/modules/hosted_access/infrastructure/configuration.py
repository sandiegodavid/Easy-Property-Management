"""Read administrator-owned configuration without initializing business data."""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from app.modules.hosted_access.application.configuration import (
    HostedConfigurationError,
    HostedDeployment,
)
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import repository_root

MAX_CONFIGURATION_BYTES = 16 * 1024


def _secure_file(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise HostedConfigurationError("Hosted configuration must be a regular file.")
    if os.name == "posix":
        for candidate in (path, *path.parents):
            info = candidate.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
                raise HostedConfigurationError(
                    "Hosted configuration and its parent directories must be root-owned "
                    "and not writable by group or others."
                )
    if metadata.st_size > MAX_CONFIGURATION_BYTES:
        raise HostedConfigurationError("Hosted configuration exceeds its size limit.")


def load_hosted_deployment(path: Path) -> HostedDeployment:
    try:
        if not path.is_absolute():
            raise HostedConfigurationError("Hosted configuration path must be absolute.")
        _secure_file(path)
        raw = path.read_bytes()
        if len(raw) > MAX_CONFIGURATION_BYTES:
            raise HostedConfigurationError("Hosted configuration exceeds its size limit.")
        deployment = HostedDeployment.model_validate(json.loads(raw))
    except (OSError, ValueError) as error:
        if isinstance(error, HostedConfigurationError):
            raise
        raise HostedConfigurationError("Hosted configuration is invalid or unreadable.") from error
    if not urlsplit(deployment.identity_issuer).hostname.endswith(".cloudflareaccess.com"):
        raise HostedConfigurationError("The identity issuer must be a Cloudflare Access team.")
    return deployment


def validate_workspace_binding(
    deployment: HostedDeployment, service: WorkspaceService, *, require_unexpired: bool = True
) -> None:
    root = service.paths.root.resolve()
    database = deployment.administration_database.resolve()
    repository = repository_root().resolve()
    if root == database or root in database.parents:
        raise HostedConfigurationError(
            "Hosted authorization must be outside portable workspace data."
        )
    if repository == database or repository in database.parents:
        raise HostedConfigurationError("Hosted authorization must be outside the source checkout.")
    if service.config.file_storage_provider != "local" or service.config.s3_bucket:
        raise HostedConfigurationError("Hosted demo requires local live file storage.")
    if require_unexpired and datetime.now(UTC) >= deployment.expires_at:
        raise HostedConfigurationError("The hosted demo has expired.")
    manifest = service.open()
    if str(deployment.workspace_id) != manifest.workspace_id:
        raise HostedConfigurationError("Hosted deployment does not match the selected workspace.")
