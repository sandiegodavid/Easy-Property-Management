"""Conservative in-flight admission above a kernel-enforced workspace capacity."""

from contextlib import contextmanager
from dataclasses import dataclass
import logging
from threading import Lock
from time import monotonic
from typing import Callable

from app.modules.hosted_access.application.configuration import WORKSPACE_BYTES
from app.modules.hosted_access.domain.models import HostedAccessError

MIB = 1024 * 1024
WRITE_HEADROOM = 16 * MIB
READ_HEADROOM = MIB
COPY_MULTIPLIER = 3
HOST_WARN_PERCENT = 80
HOST_MAINTENANCE_PERCENT = 89
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageFacts:
    capacity_bytes: int
    available_bytes: int
    host_total_bytes: int
    host_available_bytes: int
    available_inodes: int


class HostedStorageBudget:
    def __init__(self, facts: Callable[[], StorageFacts]):
        self.facts = facts
        self._lock = Lock()
        self._reserved = 0
        self._last_warning = -float("inf")

    @property
    def reserved_bytes(self):
        with self._lock:
            return self._reserved

    def exhausted(self):
        """Classify an owning storage failure without interpreting its SQL/error text."""
        try:
            current = self.facts()
            return current.available_bytes < WRITE_HEADROOM or current.available_inodes < 128
        except OSError, ValueError:
            return False

    @contextmanager
    def reserve(self, body_bytes: int, *, write: bool):
        # Body spool + owning multipart staging + immutable content publication.
        # Already-allocated bytes also reduce statvfs availability: intentionally
        # double-count in-flight work, never assume it will soon be reclaimed.
        amount = (WRITE_HEADROOM if write else READ_HEADROOM) + COPY_MULTIPLIER * body_bytes
        with self._lock:
            try:
                current = self.facts()
            except (OSError, ValueError) as error:
                raise HostedAccessError(
                    "hosted_storage_unavailable",
                    "Storage accounting unavailable; contact the administrator.",
                    503,
                ) from error
            if not (
                0 < current.capacity_bytes <= WORKSPACE_BYTES
                and 0 <= current.available_bytes <= current.capacity_bytes
                and 0 <= current.host_available_bytes <= current.host_total_bytes
                and current.host_total_bytes > 0
            ):
                raise HostedAccessError(
                    "hosted_storage_unavailable", "Storage boundary is invalid.", 503
                )
            used_percent = 100 * (1 - current.host_available_bytes / current.host_total_bytes)
            if used_percent >= HOST_WARN_PERCENT and monotonic() - self._last_warning >= 60:
                logger.warning(
                    "Hosted backing disk needs administrator attention (at least 80% used)."
                )
                self._last_warning = monotonic()
            if write and used_percent >= HOST_MAINTENANCE_PERCENT:
                raise HostedAccessError(
                    "hosted_write_maintenance",
                    "Writes are paused for host disk maintenance. Contact the administrator.",
                    503,
                )
            if (
                current.available_inodes < 128
                or amount + self._reserved > current.available_bytes
                or amount + self._reserved > current.host_available_bytes
            ):
                raise HostedAccessError(
                    "hosted_storage_quota_exceeded",
                    "Workspace storage cannot admit this request safely. Keep your input and contact the administrator.",
                    507,
                )
            self._reserved += amount
        try:
            yield
        finally:
            with self._lock:
                self._reserved -= amount
