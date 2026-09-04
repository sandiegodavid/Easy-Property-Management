"""Stable, portable workspace metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


WORKSPACE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class WorkspaceManifest:
    workspace_id: str
    format_version: int
    created_at: datetime
    database_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "workspaceId": self.workspace_id,
            "formatVersion": self.format_version,
            "createdAt": self.created_at.isoformat(),
            "databasePath": self.database_path,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "WorkspaceManifest":
        if not isinstance(raw, dict):
            raise ValueError("Workspace manifest must be a JSON object.")
        try:
            workspace_id = raw["workspaceId"]
            format_version = raw["formatVersion"]
            created_at = raw["createdAt"]
            database_path = raw["databasePath"]
        except KeyError as error:
            raise ValueError(f"Workspace manifest is missing {error.args[0]}.") from error

        if not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError("workspaceId must be a non-empty string.")
        if not isinstance(format_version, int) or isinstance(format_version, bool):
            raise ValueError("formatVersion must be an integer.")
        if not isinstance(created_at, str) or not isinstance(database_path, str):
            raise ValueError("Workspace manifest has invalid values.")

        try:
            parsed_created_at = datetime.fromisoformat(created_at)
        except ValueError as error:
            raise ValueError("createdAt must be an ISO-8601 timestamp.") from error

        return cls(
            workspace_id=workspace_id,
            format_version=format_version,
            created_at=parsed_created_at,
            database_path=database_path,
        )
