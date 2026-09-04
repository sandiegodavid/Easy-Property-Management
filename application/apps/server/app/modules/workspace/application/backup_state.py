"""Persistent automatic-backup status and verified-archive retention."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.modules.workspace.application.backup_models import BackupError, BackupResult
from app.modules.workspace.application.backup_policy import secure_file
from app.modules.workspace.infrastructure.encrypted_archive import ArchiveError, _read_archive_layout

AUTOMATIC_INTERVAL = timedelta(days=1)


class BackupStateStore:
    def __init__(self, backups_path: Path) -> None:
        self.path = backups_path / "backup-state.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BackupError(f"Backup status is unreadable: {error}") from error
        if not isinstance(state, dict) or state.get("version") != 1:
            raise BackupError("Backup status has an unsupported format.")
        return state

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            secure_file(temporary)
            temporary.replace(self.path)
            secure_file(self.path)
        except OSError as error:
            raise BackupError(f"Unable to save backup status: {error}") from error

    def status(self) -> dict[str, Any]:
        state = self.load()
        return {
            key: state.get(key)
            for key in ("automaticEnabled", "lastFailure", "lastSuccessAt", "nextAutomaticBackupAt")
        }

    def record_success(self, result: BackupResult) -> None:
        state = self.load()
        now = datetime.now(UTC)
        state.update(
            {
                "lastArchiveName": result.archive_path.name,
                "lastFailure": None,
                "lastSuccessAt": now.isoformat(),
                "nextAutomaticBackupAt": (now + AUTOMATIC_INTERVAL).isoformat(),
                "version": 1,
            }
        )
        verified = state.setdefault("verifiedArchives", [])
        if isinstance(verified, list) and result.archive_path.name not in verified:
            verified.append(result.archive_path.name)
        self.save(state)

    def record_failure(self, reason: str) -> None:
        state = self.load()
        state["lastFailure"] = reason
        state["nextAutomaticBackupAt"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        self.save(state)

    def apply_retention(self, workspace_id: str, destination: Path) -> None:
        state = self.load()
        verified = state.get("verifiedArchives", [])
        if not isinstance(verified, list):
            return
        archives: list[tuple[datetime, Path]] = []
        for archive in destination.glob("*.epm-backup"):
            if archive.name not in verified:
                continue
            try:
                header, _, _, _ = _read_archive_layout(archive)
                created = datetime.fromisoformat(header["createdAt"])
                if header.get("sourceWorkspaceId") == workspace_id and header.get("packageType") == "backup":
                    archives.append((created, archive))
            except (ArchiveError, OSError, ValueError, KeyError):
                continue
        archives.sort(reverse=True, key=lambda item: item[0])
        now, keep = datetime.now(UTC), set()
        days, weeks, months = set(), set(), set()
        for created, archive in archives:
            day = (created.year, created.month, created.day)
            week = created.isocalendar()[:2]
            month = (created.year, created.month)
            if (now - created).days < 7 and day not in days:
                days.add(day)
                keep.add(archive)
            if (now - created).days < 28 and week not in weeks:
                weeks.add(week)
                keep.add(archive)
            if (now.year - created.year) * 12 + now.month - created.month < 12 and month not in months:
                months.add(month)
                keep.add(archive)
        for _, archive in archives:
            if archive not in keep:
                archive.unlink(missing_ok=True)
        state["verifiedArchives"] = [archive.name for _, archive in archives if archive in keep]
        self.save(state)
