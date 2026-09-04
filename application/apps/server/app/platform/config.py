"""Loading of the Git-ignored local workspace locator."""

from __future__ import annotations

import json
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

    workspace_value = raw_config.get("localWorkspacePath")
    if not isinstance(workspace_value, str) or not workspace_value.strip():
        raise LocalConfigError("localWorkspacePath must be a non-empty string.")

    workspace_path = Path(workspace_value).expanduser()
    if not workspace_path.is_absolute():
        raise LocalConfigError("localWorkspacePath must be an absolute path outside the application checkout.")

    return LocalConfig(config_path=resolved_config_path, workspace_path=workspace_path.resolve())
