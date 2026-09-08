"""Loading of the Git-ignored local workspace locator."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class LocalConfigError(ValueError):
    """Raised when the local workspace locator cannot be used safely."""


def application_root() -> Path:
    """Return the repository's application directory, independent of the current shell directory."""
    return Path(__file__).resolve().parents[4]


def repository_root() -> Path:
    """Return the Git-maintained repository that contains the application directory."""
    return application_root().parent


def default_config_path() -> Path:
    return application_root() / "config.local.json"


@dataclass(frozen=True)
class LocalConfig:
    config_path: Path
    workspace_path: Path
    backup_destination_path: Path | None = None
    file_storage_provider: str = "local"
    s3_bucket: str | None = None
    s3_prefix: str = "managed"


def load_local_config(config_path: Path | None = None) -> LocalConfig:
    """Load an explicit local workspace path; relative paths are intentionally rejected."""
    resolved_config_path = (config_path or default_config_path()).expanduser().resolve()
    if not resolved_config_path.is_file():
        raise LocalConfigError(
            f"Local configuration not found: {resolved_config_path}. "
            "Copy config.example.json to config.local.json and choose an external workspace."
        )

    try:
        raw_config = json.loads(resolved_config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LocalConfigError(f"Local configuration is not valid JSON: {resolved_config_path}") from error
    if not isinstance(raw_config, dict):
        raise LocalConfigError("Local configuration must be a JSON object.")

    workspace_value = raw_config.get("localWorkspacePath")
    if not isinstance(workspace_value, str) or not workspace_value.strip():
        raise LocalConfigError("localWorkspacePath must be a non-empty string.")

    workspace_path = _absolute_path(workspace_value, "localWorkspacePath")
    backup_value = raw_config.get("backupDestinationPath")
    if backup_value is not None and (not isinstance(backup_value, str) or not backup_value.strip()):
        raise LocalConfigError("backupDestinationPath must be an absolute path when provided.")
    backup_destination_path = (
        _absolute_path(backup_value, "backupDestinationPath") if isinstance(backup_value, str) else None
    )
    file_storage_provider = raw_config.get("fileStorageProvider", "local")
    if file_storage_provider not in {"local", "s3"}:
        raise LocalConfigError("fileStorageProvider must be local or s3.")
    s3_bucket = raw_config.get("s3Bucket")
    s3_prefix = raw_config.get("s3Prefix", "managed")
    if file_storage_provider == "s3" and (not isinstance(s3_bucket, str) or not s3_bucket.strip()):
        raise LocalConfigError("s3Bucket is required when fileStorageProvider is s3.")
    if s3_bucket is not None and (not isinstance(s3_bucket, str) or not s3_bucket.strip()):
        raise LocalConfigError("s3Bucket must be nonblank text when provided.")
    if not isinstance(s3_prefix, str):
        raise LocalConfigError("s3Prefix must be text.")

    return LocalConfig(
        config_path=resolved_config_path,
        workspace_path=workspace_path,
        backup_destination_path=backup_destination_path,
        file_storage_provider=file_storage_provider,
        s3_bucket=s3_bucket.strip() if isinstance(s3_bucket, str) else None,
        s3_prefix=s3_prefix.strip("/"),
    )


def save_backup_destination(config: LocalConfig, destination_path: Path) -> LocalConfig:
    """Persist the non-secret, external backup destination in the ignored local config."""
    resolved_destination = _absolute_path(str(destination_path), "backupDestinationPath")
    try:
        raw_config = json.loads(config.config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LocalConfigError(f"Unable to update local configuration: {error}") from error
    if not isinstance(raw_config, dict):
        raise LocalConfigError("Unable to update local configuration: its root must be a JSON object.")

    raw_config["backupDestinationPath"] = str(resolved_destination)
    temporary_path = config.config_path.with_name(f".{config.config_path.name}.tmp")
    try:
        temporary_path.write_text(json.dumps(raw_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if os.name == "posix":
            temporary_path.chmod(0o600)
        temporary_path.replace(config.config_path)
        if os.name == "posix":
            config.config_path.chmod(0o600)
    except OSError as error:
        raise LocalConfigError(f"Unable to save local configuration: {error}") from error
    return load_local_config(config.config_path)


def _absolute_path(value: str, field_name: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise LocalConfigError(f"{field_name} must be an absolute path outside the application checkout.")
    return path.resolve()
