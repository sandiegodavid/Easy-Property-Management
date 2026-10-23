"""Publish only validated encrypted artifacts; never prune before durable read-back proof."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol


class RecoveryPublicationError(ValueError):
    pass


@dataclass(frozen=True)
class RecoveryPoint:
    key: str
    sha256: str
    size: int
    created_at: datetime
    verified_at: datetime


class RecoveryObjectStore(Protocol):
    def upload(self, key: str, source: Path, size: int) -> None: ...
    def digest(self, key: str, size: int) -> str: ...
    def delete(self, key: str) -> None: ...


class RecoveryPublicationLedger(Protocol):
    def load(self) -> tuple[list[RecoveryPoint], bool]: ...
    def save(self, points: list[RecoveryPoint], *, retention_pending: bool) -> None: ...


def recovery_status(ledger: RecoveryPublicationLedger, *, now=None):
    instant = now or datetime.now(UTC)
    points, pending = ledger.load()
    latest = max((point.created_at for point in points), default=None)
    return {
        "lastVerifiedBackupAt": latest.isoformat() if latest else None,
        "recoveryAgeSeconds": max(0, int((instant - latest).total_seconds())) if latest else None,
        "needsAttention": pending or latest is None or instant - latest > timedelta(hours=24),
        "retentionPending": pending,
    }


class RecoveryPublicationService:
    def __init__(
        self,
        store: RecoveryObjectStore,
        ledger: RecoveryPublicationLedger,
        prefix: str,
        *,
        now=None,
    ):
        self.store, self.ledger, self.prefix = store, ledger, prefix
        self.now = now or (lambda: datetime.now(UTC))

    def key(self, created_at, digest):
        return f"{self.prefix}/{created_at.astimezone(UTC).date().isoformat()}/{digest}.epm-backup"

    def publish(self, source, *, digest, size, created_at):
        now = self.now()
        if created_at.tzinfo is None or created_at > now + timedelta(minutes=1):
            raise RecoveryPublicationError("Archive creation time is not a valid recovery point.")
        points, _pending = self.ledger.load()
        if any(point.key != self.key(point.created_at, point.sha256) for point in points):
            raise RecoveryPublicationError(
                "Recovery ledger contains a different deployment prefix."
            )
        if points and created_at < max(point.created_at for point in points):
            raise RecoveryPublicationError(
                "This archive predates the latest verified recovery point."
            )
        key = self.key(created_at, digest)
        self.store.upload(key, source, size)
        if self.store.digest(key, size) != digest:
            raise RecoveryPublicationError(
                "Off-host read-back checksum failed; no recovery point was pruned."
            )
        point = RecoveryPoint(key, digest, size, created_at.astimezone(UTC), now)
        points = [item for item in points if item.key != key] + [point]
        # A durable verified checkpoint must precede any destructive retention.
        self.ledger.save(points, retention_pending=True)
        latest_daily = {}
        for item in sorted(points, key=lambda item: (item.created_at, item.key)):
            latest_daily[item.created_at.astimezone(UTC).date()] = item
        retained = [latest_daily[day] for day in sorted(latest_daily, reverse=True)[:7]]
        keep = {item.key for item in retained}
        try:
            for old in points:
                if old.key not in keep:
                    self.store.delete(old.key)
            self.ledger.save(retained, retention_pending=False)
        except OSError, RecoveryPublicationError:
            # Publication is already verified and durable. The ledger still records
            # pending retention; a failed prune cannot reverse or erase this point.
            return point, True
        return point, False

    def status(self):
        return recovery_status(self.ledger, now=self.now())
