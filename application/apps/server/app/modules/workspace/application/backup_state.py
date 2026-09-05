"""Typed local backup-operation history and retention inventory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.modules.workspace.application.backup_models import BackupError, BackupResult
from app.modules.workspace.application.backup_policy import secure_file
from app.modules.workspace.infrastructure.encrypted_archive import ArchiveError, _read_archive_layout

AUTOMATIC_INTERVAL = timedelta(days=1)
STATE_VERSION = 5
MAX_HISTORY = 100
MAX_REPORTED_RETENTION_DELETIONS = 100
PACKAGE_TYPES = {"backup", "export"}


def _timestamp(value: object, *, label: str = "timestamp") -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} is not timezone-aware")
    return parsed.astimezone(UTC)


def _simple_archive_name(value: object) -> str:
    if not isinstance(value, str) or Path(value).name != value or value in {"", ".", ".."}:
        raise ValueError("invalid archive name")
    return value


def _digest(value: Path) -> str:
    digest = hashlib.sha256()
    with value.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BackupFailure:
    at: datetime
    reason: str

    @classmethod
    def from_dict(cls, value: object) -> "BackupFailure":
        if not isinstance(value, dict) or set(value) != {"at", "reason"} or not isinstance(value["reason"], str):
            raise ValueError("invalid retention failure")
        return cls(_timestamp(value["at"], label="retention failure time"), value["reason"])

    def to_dict(self) -> dict[str, str]:
        return {"at": self.at.isoformat(), "reason": self.reason}


@dataclass(frozen=True)
class BackupOperationRecord:
    """An operator-visible outcome, including failures with unavailable fields explicit."""

    occurred_at: datetime
    package_type: str
    destination: Path | None
    archive_name: str | None
    archive_sha256: str | None
    bytes: int | None
    validated: bool
    validation_result: str
    failure_reason: str | None

    @classmethod
    def from_result(cls, result: BackupResult, now: datetime) -> "BackupOperationRecord":
        archive = result.archive_path
        return cls(
            occurred_at=now,
            package_type=result.package_type,
            destination=archive.parent.resolve(),
            archive_name=archive.name,
            archive_sha256=_digest(archive),
            bytes=archive.stat().st_size,
            validated=True,
            validation_result="succeeded",
            failure_reason=None,
        )

    @classmethod
    def failure(cls, reason: str, package_type: str, *, destination: Path | None = None,
                archive_name: str | None = None) -> "BackupOperationRecord":
        if package_type not in PACKAGE_TYPES:
            raise ValueError("invalid package type")
        return cls(datetime.now(UTC), package_type, destination.resolve() if destination else None,
                   archive_name, None, None, False, "failed", reason)

    @classmethod
    def from_dict(cls, value: object) -> "BackupOperationRecord":
        fields = {"occurredAt", "packageType", "destination", "archiveName", "archiveSha256", "bytes", "validated", "validationResult", "failureReason"}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("invalid backup operation record")
        package_type = value["packageType"]
        destination, archive_name, digest, byte_count = value["destination"], value["archiveName"], value["archiveSha256"], value["bytes"]
        succeeded = value["validationResult"] == "succeeded"
        if (package_type not in PACKAGE_TYPES or value["validationResult"] not in {"succeeded", "failed"}
                or not isinstance(value["validated"], bool)
                or (destination is not None and (not isinstance(destination, str) or not destination))
                or (archive_name is not None and _simple_archive_name(archive_name) != archive_name)
                or (digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)))
                or (byte_count is not None and (not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0))
                or (value["failureReason"] is not None and not isinstance(value["failureReason"], str))):
            raise ValueError("invalid backup operation record")
        if succeeded != value["validated"] or (succeeded and (destination is None or archive_name is None or digest is None or byte_count is None or value["failureReason"] is not None)):
            raise ValueError("invalid backup operation record")
        if not succeeded and (value["failureReason"] is None or any(item is not None for item in (digest, byte_count))):
            raise ValueError("invalid backup operation record")
        return cls(_timestamp(value["occurredAt"], label="operation time"), package_type,
                   Path(destination) if destination else None, archive_name, digest, byte_count,
                   value["validated"], value["validationResult"], value["failureReason"])

    def to_dict(self) -> dict[str, object]:
        return {
            "occurredAt": self.occurred_at.isoformat(),
            "packageType": self.package_type,
            "destination": None if self.destination is None else str(self.destination),
            "archiveName": self.archive_name,
            "archiveSha256": self.archive_sha256,
            "bytes": self.bytes,
            "validated": self.validated,
            "validationResult": self.validation_result,
            "failureReason": self.failure_reason,
        }


def _failure_from_dict(value: object, package_type: str) -> BackupOperationRecord | None:
    if value is None:
        return None
    operation = BackupOperationRecord.from_dict(value)
    if operation.package_type != package_type or operation.validation_result != "failed":
        raise ValueError("invalid package failure")
    return operation


def _failure_status(operation: BackupOperationRecord | None) -> dict[str, str | None] | None:
    if operation is None:
        return None
    return {"at": operation.occurred_at.isoformat(), "reason": operation.failure_reason}


@dataclass(frozen=True)
class BackupInventoryRecord:
    """A validated backup that is currently eligible for retention."""

    archive_name: str
    archive_sha256: str
    bytes: int
    created_at: datetime
    destination: Path
    validated_at: datetime

    @classmethod
    def from_operation(cls, operation: BackupOperationRecord, result: BackupResult) -> "BackupInventoryRecord":
        if not operation.validated or result.package_type != "backup":
            raise ValueError("only validated backup packages may enter retention inventory")
        assert operation.destination and operation.archive_name and operation.archive_sha256 is not None and operation.bytes is not None
        return cls(operation.archive_name, operation.archive_sha256, operation.bytes,
                   _timestamp(result.archive_contents.header["createdAt"], label="archive time"),
                   operation.destination, operation.occurred_at)

    @classmethod
    def from_dict(cls, value: object) -> "BackupInventoryRecord":
        fields = {"archiveName", "archiveSha256", "bytes", "createdAt", "destination", "validatedAt"}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("invalid backup inventory record")
        name, digest, destination = value["archiveName"], value["archiveSha256"], value["destination"]
        if (_simple_archive_name(name) != name or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or not isinstance(value["bytes"], int) or isinstance(value["bytes"], bool) or value["bytes"] < 0
                or not isinstance(destination, str) or not destination):
            raise ValueError("invalid backup inventory record")
        return cls(name, digest, value["bytes"], _timestamp(value["createdAt"], label="archive time"),
            Path(destination), _timestamp(value["validatedAt"], label="validation time"))

    def to_dict(self) -> dict[str, object]:
        return {
            "archiveName": self.archive_name,
            "archiveSha256": self.archive_sha256,
            "bytes": self.bytes,
            "createdAt": self.created_at.isoformat(),
            "destination": str(self.destination),
            "validatedAt": self.validated_at.isoformat(),
        }

    def archive_path_in(self, destination: Path) -> Path | None:
        resolved_destination = destination.resolve()
        if self.destination != resolved_destination:
            return None
        candidate = (resolved_destination / self.archive_name).resolve()
        return candidate if candidate.parent == resolved_destination else None


@dataclass(frozen=True)
class BackupState:
    automatic_enabled: bool = False
    history: tuple[BackupOperationRecord, ...] = ()
    retention_inventory: tuple[BackupInventoryRecord, ...] = ()
    last_backup_failure: BackupOperationRecord | None = None
    last_export_failure: BackupOperationRecord | None = None
    last_retention_failure: BackupFailure | None = None
    last_success_at: datetime | None = None
    next_automatic_backup_at: datetime | None = None

    @classmethod
    def from_dict(cls, value: object) -> "BackupState":
        fields = {"version", "automaticEnabled", "history", "retentionInventory", "lastBackupFailure", "lastExportFailure", "lastRetentionFailure", "lastSuccessAt", "nextAutomaticBackupAt"}
        if (not isinstance(value, dict) or set(value) != fields or not isinstance(value.get("version"), int)
                or isinstance(value.get("version"), bool) or value.get("version") != STATE_VERSION):
            raise ValueError("unsupported backup state")
        if not isinstance(value["automaticEnabled"], bool) or not isinstance(value["history"], list) or not isinstance(value["retentionInventory"], list):
            raise ValueError("unsupported backup state")
        if len(value["history"]) > MAX_HISTORY:
            raise ValueError("backup history is too large")
        history = tuple(BackupOperationRecord.from_dict(record) for record in value["history"])
        last_backup_failure = _failure_from_dict(value["lastBackupFailure"], "backup")
        last_export_failure = _failure_from_dict(value["lastExportFailure"], "export")
        return cls(
            automatic_enabled=value["automaticEnabled"],
            history=history,
            retention_inventory=tuple(BackupInventoryRecord.from_dict(record) for record in value["retentionInventory"]),
            last_backup_failure=last_backup_failure,
            last_export_failure=last_export_failure,
            last_retention_failure=None if value["lastRetentionFailure"] is None else BackupFailure.from_dict(value["lastRetentionFailure"]),
            last_success_at=None if value["lastSuccessAt"] is None else _timestamp(value["lastSuccessAt"], label="last success time"),
            next_automatic_backup_at=None if value["nextAutomaticBackupAt"] is None else _timestamp(value["nextAutomaticBackupAt"], label="next automatic backup time"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": STATE_VERSION,
            "automaticEnabled": self.automatic_enabled,
            "history": [record.to_dict() for record in self.history],
            "retentionInventory": [record.to_dict() for record in self.retention_inventory],
            "lastBackupFailure": None if self.last_backup_failure is None else self.last_backup_failure.to_dict(),
            "lastExportFailure": None if self.last_export_failure is None else self.last_export_failure.to_dict(),
            "lastRetentionFailure": None if self.last_retention_failure is None else self.last_retention_failure.to_dict(),
            "lastSuccessAt": None if self.last_success_at is None else self.last_success_at.isoformat(),
            "nextAutomaticBackupAt": None if self.next_automatic_backup_at is None else self.next_automatic_backup_at.isoformat(),
        }

    def status_dict(self) -> dict[str, object]:
        stored = self.to_dict()
        return {
            "automaticEnabled": stored["automaticEnabled"],
            "lastFailure": _failure_status(self.last_backup_failure),
            "lastExportFailure": _failure_status(self.last_export_failure),
            "lastRetentionFailure": None if self.last_retention_failure is None else self.last_retention_failure.to_dict(),
            "lastSuccessAt": stored["lastSuccessAt"],
            "nextAutomaticBackupAt": stored["nextAutomaticBackupAt"],
            "history": stored["history"],
        }

    def with_success(self, result: BackupResult, *, automatic: bool, now: datetime) -> "BackupState":
        operation = BackupOperationRecord.from_result(result, now)
        history = (operation, *self.history)[:MAX_HISTORY]
        inventory = self.retention_inventory
        if result.package_type == "backup":
            item = BackupInventoryRecord.from_operation(operation, result)
            inventory = (item, *(record for record in inventory if not (
                record.destination == item.destination and record.archive_name == item.archive_name
            )))
        return replace(
            self,
            history=history,
            retention_inventory=inventory,
            last_backup_failure=None if result.package_type == "backup" else self.last_backup_failure,
            last_export_failure=None if result.package_type == "export" else self.last_export_failure,
            last_success_at=now if result.package_type == "backup" else self.last_success_at,
            next_automatic_backup_at=now + AUTOMATIC_INTERVAL if automatic else self.next_automatic_backup_at,
        )

    def with_failure(self, reason: str, package_type: str, *, automatic: bool, destination: Path | None = None,
                     archive_name: str | None = None) -> "BackupState":
        operation = BackupOperationRecord.failure(reason, package_type, destination=destination, archive_name=archive_name)
        failure_field = "last_backup_failure" if package_type == "backup" else "last_export_failure"
        return replace(
            self,
            history=(operation, *self.history)[:MAX_HISTORY],
            next_automatic_backup_at=operation.occurred_at + timedelta(hours=1) if automatic else self.next_automatic_backup_at,
            **{failure_field: operation},
        )

    def with_retention_failure(self, reason: str, now: datetime) -> "BackupState":
        return replace(self, last_retention_failure=BackupFailure(now, reason))

    def with_retention_success(self) -> "BackupState":
        return replace(self, last_retention_failure=None)


class BackupStateStore:
    def __init__(self, backups_path: Path) -> None:
        self.path = backups_path / "backup-state.json"
        self.retention_journal_path = backups_path / ".retention-pending.json"

    def load(self) -> BackupState:
        if not self.path.exists():
            return BackupState()
        try:
            return BackupState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise BackupError(f"Backup status is unreadable: {error}") from error

    def save(self, state: BackupState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            secure_file(temporary)
            temporary.replace(self.path)
            secure_file(self.path)
        except OSError as error:
            raise BackupError(f"Unable to save backup status: {error}") from error

    def status(self) -> dict[str, object]:
        return self.load().status_dict()

    def record_success(self, result: BackupResult, *, automatic: bool = False) -> None:
        self.save(self.load().with_success(result, automatic=automatic, now=datetime.now(UTC)))

    def record_failure(self, reason: str, package_type: str, *, automatic: bool = False,
                       destination: Path | None = None, archive_name: str | None = None) -> None:
        self.save(self.load().with_failure(reason, package_type, automatic=automatic,
                                           destination=destination, archive_name=archive_name))

    def record_retention_failure(self, reason: str) -> None:
        self.save(self.load().with_retention_failure(reason, datetime.now(UTC)))

    def configure_automatic(self, enabled: bool, *, now: datetime | None = None) -> None:
        state = self.load()
        next_attempt = (now or datetime.now(UTC)) if enabled else None
        self.save(replace(state, automatic_enabled=enabled, next_automatic_backup_at=next_attempt))

    def apply_retention(self, workspace_id: str, destination: Path, *, correlation_id: str | None = None,
                        archive_name: str | None = None) -> "RetentionResult":
        state = self.load()
        current_destination = destination.resolve()
        candidates: list[tuple[datetime, Path, BackupInventoryRecord]] = []
        preserved_inventory: list[BackupInventoryRecord] = []
        for record in state.retention_inventory:
            if record.destination != current_destination:
                preserved_inventory.append(record)
                continue
            archive = record.archive_path_in(current_destination)
            if archive is None:
                continue
            try:
                if not archive.is_file() or _digest(archive) != record.archive_sha256:
                    continue
                header, _, _, _ = _read_archive_layout(archive)
                if header.get("sourceWorkspaceId") != workspace_id or header.get("packageType") != "backup":
                    continue
                candidates.append((_timestamp(header.get("createdAt"), label="archive time"), archive, record))
            except (ArchiveError, OSError, ValueError):
                continue
        candidates.sort(reverse=True, key=lambda item: item[0])
        keep = _retention_keep_set(candidates)
        planned_deletions = [record for _, archive, record in candidates if archive not in keep]
        self._write_retention_journal(
            current_destination, planned_deletions, correlation_id or str(uuid4()), archive_name,
            considered_count=len(candidates), retained_count=len(keep),
        )
        deleted: list[str] = []
        result = RetentionResult(
            considered_count=len(candidates),
            retained_count=len(keep),
            deleted_count=0,
            deleted_archives=(),
        )
        try:
            for _, archive, _ in candidates:
                if archive not in keep:
                    archive.unlink(missing_ok=True)
                    deleted.append(archive.name)
            result = replace(result, deleted_count=len(deleted),
                             deleted_archives=tuple(deleted[:MAX_REPORTED_RETENTION_DELETIONS]))
            updated_inventory = (*preserved_inventory, *(record for _, archive, record in candidates if archive in keep))
            self.save(replace(state, retention_inventory=updated_inventory).with_retention_success())
        except (BackupError, OSError) as error:
            result = replace(result, deleted_count=len(deleted),
                             deleted_archives=tuple(deleted[:MAX_REPORTED_RETENTION_DELETIONS]))
            try:
                self.recover_pending_retention()
            except BackupError:
                # The durable journal remains for the next retention attempt.
                pass
            raise RetentionExecutionError(f"Retention did not finish: {error}", result) from error
        self._mark_retention_audit_pending(result)
        return result

    def _write_retention_journal(self, destination: Path, records: list[BackupInventoryRecord], correlation_id: str,
                                 archive_name: str | None, *, considered_count: int, retained_count: int) -> None:
        """Record a deletion plan before unlinking so an interrupted run can reconcile."""
        self.retention_journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal = {
            "auditEventId": str(uuid5(NAMESPACE_URL, f"epm-retention:{correlation_id}")),
            "archiveName": archive_name,
            "destination": str(destination),
            "archiveNames": [record.archive_name for record in records],
            "consideredArchiveCount": considered_count,
            "correlationId": correlation_id,
            "deletedArchiveCount": 0,
            "deletedArchiveNames": [],
            "operationAt": datetime.now(UTC).isoformat(),
            "retainedArchiveCount": retained_count,
            "state": "deletion_pending",
        }
        temporary = self.retention_journal_path.with_name(f".{self.retention_journal_path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(journal, sort_keys=True) + "\n", encoding="utf-8")
            secure_file(temporary)
            temporary.replace(self.retention_journal_path)
            secure_file(self.retention_journal_path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise BackupError(f"Unable to record retention plan: {error}") from error

    def recover_pending_retention(self) -> "RetentionRecovery | None":
        """Reconcile only planned deletions and expose them for a recovery audit event."""
        journal = self._read_retention_journal()
        if journal is None:
            return None
        destination = Path(journal["destination"]).resolve()
        names = {_simple_archive_name(name) for name in journal["archiveNames"]}
        recorded_deletions = tuple(_simple_archive_name(name) for name in journal["deletedArchiveNames"])
        if journal["state"] == "deletion_pending":
            state = self.load()
            deleted = tuple(sorted(name for name in names if not (destination / name).is_file()))
            inventory = tuple(
                record for record in state.retention_inventory
                if not (record.destination == destination and record.archive_name in names
                        and not (destination / record.archive_name).is_file())
            )
            self.save(replace(state, retention_inventory=inventory).with_retention_success())
            journal["deletedArchiveNames"] = list(deleted[:MAX_REPORTED_RETENTION_DELETIONS])
            journal["deletedArchiveCount"] = len(deleted)
            self._save_audit_pending_journal(journal)
        else:
            deleted = tuple(sorted(recorded_deletions))
        return RetentionRecovery(
            correlation_id=journal["correlationId"],
            audit_event_id=journal["auditEventId"],
            occurred_at=_timestamp(journal["operationAt"], label="retention operation time"),
            audit_action=_retention_audit_payload(journal)[0],
            audit_after=_retention_audit_payload(journal)[1],
            result=_retention_result_from_journal(journal),
        )

    def complete_retention_audit(self, audit_event_id: str) -> None:
        """Clear an audit-pending journal only after its deterministic event committed."""
        journal = self._read_retention_journal()
        if journal is None:
            return
        if journal["state"] != "audit_pending" or journal["auditEventId"] != audit_event_id:
            raise BackupError("Retention journal does not match the completed audit event.")
        self.retention_journal_path.unlink(missing_ok=True)

    def _mark_retention_audit_pending(self, result: "RetentionResult") -> None:
        journal = self._read_retention_journal()
        if journal is None:
            raise BackupError("Retention journal disappeared before its audit could be recorded.")
        journal["deletedArchiveNames"] = list(result.deleted_archives)
        journal["deletedArchiveCount"] = result.deleted_count
        journal["consideredArchiveCount"] = result.considered_count
        journal["retainedArchiveCount"] = result.retained_count
        self._save_audit_pending_journal(journal)

    def _save_audit_pending_journal(self, journal: dict[str, object]) -> None:
        journal["state"] = "audit_pending"
        self._save_retention_journal(journal)

    def _read_retention_journal(self) -> dict[str, object] | None:
        if not self.retention_journal_path.exists():
            return None
        try:
            journal = json.loads(self.retention_journal_path.read_text(encoding="utf-8"))
            _validate_retention_journal(journal)
            return journal
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise BackupError(f"Retention recovery journal is unreadable: {error}") from error

    def _save_retention_journal(self, journal: dict[str, object]) -> None:
        temporary = self.retention_journal_path.with_name(f".{self.retention_journal_path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(journal, sort_keys=True) + "\n", encoding="utf-8")
            secure_file(temporary)
            temporary.replace(self.retention_journal_path)
            secure_file(self.retention_journal_path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise BackupError(f"Unable to save retention recovery journal: {error}") from error


def _validate_retention_journal(value: object) -> None:
    fields = {
        "auditEventId", "archiveName", "destination", "archiveNames", "consideredArchiveCount",
        "correlationId", "deletedArchiveCount", "deletedArchiveNames", "operationAt", "retainedArchiveCount", "state",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid retention journal")
    if (not isinstance(value["destination"], str) or not value["destination"]
            or not isinstance(value["correlationId"], str) or not value["correlationId"]
            or not isinstance(value["auditEventId"], str) or not value["auditEventId"]
            or not isinstance(value["state"], str)
            or value["state"] not in {"deletion_pending", "audit_pending"}
            or not isinstance(value["archiveNames"], list)
            or not isinstance(value["deletedArchiveNames"], list)
            or not isinstance(value["deletedArchiveCount"], int)
            or isinstance(value["deletedArchiveCount"], bool)
            or value["deletedArchiveCount"] < 0
            or not isinstance(value["consideredArchiveCount"], int)
            or isinstance(value["consideredArchiveCount"], bool)
            or value["consideredArchiveCount"] < 0
            or not isinstance(value["retainedArchiveCount"], int)
            or isinstance(value["retainedArchiveCount"], bool)
            or value["retainedArchiveCount"] < 0):
        raise ValueError("invalid retention journal")
    value["correlationId"] = _canonical_uuid(value["correlationId"], "correlation ID")
    value["auditEventId"] = _canonical_uuid(value["auditEventId"], "audit event ID")
    _timestamp(value["operationAt"], label="retention operation time")
    if value["archiveName"] is not None:
        _simple_archive_name(value["archiveName"])
    archive_names = tuple(_simple_archive_name(name) for name in value["archiveNames"])
    deleted_names = tuple(_simple_archive_name(name) for name in value["deletedArchiveNames"])
    invalid_plan = (
        len(set(archive_names)) != len(archive_names)
        or len(set(deleted_names)) != len(deleted_names)
        or not set(deleted_names).issubset(archive_names)
        or value["deletedArchiveCount"] < len(deleted_names)
        or len(deleted_names) != min(value["deletedArchiveCount"], MAX_REPORTED_RETENTION_DELETIONS)
        or value["deletedArchiveCount"] > len(archive_names)
        or value["retainedArchiveCount"] > value["consideredArchiveCount"]
        or value["deletedArchiveCount"] + value["retainedArchiveCount"] > value["consideredArchiveCount"]
        or (value["state"] == "deletion_pending" and (value["deletedArchiveCount"] != 0 or deleted_names))
    )
    if invalid_plan:
        raise ValueError("invalid retention journal")


def _canonical_uuid(value: str, label: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError(f"invalid retention {label}") from error


def _retention_result_from_journal(journal: dict[str, object]) -> "RetentionResult":
    return RetentionResult(
        considered_count=journal["consideredArchiveCount"],
        retained_count=journal["retainedArchiveCount"],
        deleted_count=journal["deletedArchiveCount"],
        deleted_archives=tuple(journal["deletedArchiveNames"]),
    )


def _retention_audit_payload(journal: dict[str, object]) -> tuple[str, dict[str, object]]:
    result = _retention_result_from_journal(journal)
    return (
        "deleted" if result.deleted_count else "evaluated",
        {"destination": journal["destination"], "archiveName": journal["archiveName"], **result.to_dict()},
    )


@dataclass(frozen=True)
class RetentionResult:
    """Bounded retention outcome suitable for an operational audit record."""

    considered_count: int
    retained_count: int
    deleted_count: int
    deleted_archives: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "consideredArchiveCount": self.considered_count,
            "retainedArchiveCount": self.retained_count,
            "deletedArchiveCount": self.deleted_count,
            "deletedArchives": list(self.deleted_archives),
            "deletedArchivesTruncated": self.deleted_count > len(self.deleted_archives),
        }


class RetentionExecutionError(BackupError):
    """A retention failure that still exposes all deletions completed so far."""

    def __init__(self, message: str, result: RetentionResult) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class RetentionRecovery:
    """A completed subset of a crashed retention run and its original operation ID."""

    correlation_id: str
    audit_event_id: str
    occurred_at: datetime
    audit_action: str
    audit_after: dict[str, object]
    result: RetentionResult


def _retention_keep_set(candidates: list[tuple[datetime, Path, BackupInventoryRecord]]) -> set[Path]:
    now, keep = datetime.now(UTC), set()
    days: set[tuple[int, int, int]] = set()
    weeks: set[tuple[int, int]] = set()
    months: set[tuple[int, int]] = set()
    for created, archive, _ in candidates:
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
    return keep
