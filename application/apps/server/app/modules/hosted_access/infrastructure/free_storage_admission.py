"""Two-layer Free storage admission: durable logical usage + physical project-quota headroom."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.usage_accounting import UsageAccountingStore

MIN_LOGICAL_WRITE_RESERVE = 4096
MIN_PHYSICAL_WRITE_BYTES = 4 * 1024 * 1024
MIN_PHYSICAL_READ_BYTES = 256 * 1024
MIN_PHYSICAL_INODES = 64
HTTP_ERROR_THRESHOLD = 400
HTTP_SERVER_ERROR_THRESHOLD = 500


@dataclass(frozen=True)
class PhysicalQuotaHeadroom:
    """Read-only remaining physical quota headroom across workspace, control, and scratch."""

    workspace_available_bytes: int
    workspace_available_inodes: int
    control_available_bytes: int
    control_available_inodes: int
    scratch_available_bytes: int
    scratch_available_inodes: int


class ReservationOutcome:
    """Mutable outcome handle updated by ManagedBusiness once response status is known."""

    def __init__(self) -> None:
        self.status_code: int | None = None


class FreeStorageAdmission:
    """Two-layer H04 storage admission replacing the legacy 250 MiB loop-volume budget."""

    def __init__(
        self,
        usage_store: UsageAccountingStore,
        *,
        physical_headroom: Callable[[], PhysicalQuotaHeadroom] | None = None,
    ) -> None:
        self.usage_store = usage_store
        self.physical_headroom = physical_headroom

    def _check_physical(self, body_bytes: int, *, write: bool) -> None:
        if self.physical_headroom is None:
            return
        try:
            facts = self.physical_headroom()
        except (OSError, ValueError) as error:
            raise HostedAccessError(
                "hosted_storage_unavailable",
                "Physical storage quota accounting is unavailable; contact the administrator.",
                503,
            ) from error
        required_bytes = MIN_PHYSICAL_WRITE_BYTES + body_bytes if write else MIN_PHYSICAL_READ_BYTES
        byte_pools = (
            facts.workspace_available_bytes,
            facts.control_available_bytes,
            facts.scratch_available_bytes,
        )
        inode_pools = (
            facts.workspace_available_inodes,
            facts.control_available_inodes,
            facts.scratch_available_inodes,
        )
        if any(value < 0 for value in (*byte_pools, *inode_pools)):
            raise HostedAccessError(
                "hosted_storage_unavailable", "Storage quota boundary is invalid.", 503
            )
        if any(value < MIN_PHYSICAL_INODES for value in inode_pools) or (
            facts.workspace_available_bytes < required_bytes
            or facts.scratch_available_bytes < required_bytes
            or (write and facts.control_available_bytes < MIN_PHYSICAL_READ_BYTES)
        ):
            raise HostedAccessError(
                "hosted_storage_quota_exceeded",
                "Workspace physical storage cannot admit this request safely. "
                "Keep your input and contact the administrator.",
                507,
            )

    @contextmanager
    def reserve_request(
        self,
        body_bytes: int,
        *,
        write: bool,
        source_epoch: int,
        purpose: str = "business_write",
    ):
        self._check_physical(body_bytes, write=write)
        outcome = ReservationOutcome()
        if not write:
            yield outcome
            return
        reserved_bytes = max(MIN_LOGICAL_WRITE_RESERVE, body_bytes)
        operation_id = str(uuid4())
        request_hash = sha256(f"{operation_id}:{purpose}:{reserved_bytes}".encode()).hexdigest()
        reservation = self.usage_store.reserve(
            operation_id,
            request_hash,
            reserved_bytes=reserved_bytes,
            purpose=purpose,
            source_epoch=source_epoch,
        )
        try:
            yield outcome
        except HostedAccessError:
            self.usage_store.release(reservation.reservation_id)
            raise
        except BaseException:
            self.usage_store.mark_unknown(reservation.reservation_id)
            raise
        else:
            status = outcome.status_code
            if status is None or status >= HTTP_SERVER_ERROR_THRESHOLD:
                self.usage_store.mark_unknown(reservation.reservation_id)
            elif status >= HTTP_ERROR_THRESHOLD:
                self.usage_store.release(reservation.reservation_id)
            else:
                try:
                    self.usage_store.settle_commit(reservation.reservation_id)
                except BaseException:
                    self.usage_store.mark_unknown(reservation.reservation_id)
                    raise

    @contextmanager
    def reserve(self, body_bytes: int, *, write: bool):
        """Compatibility shim when invoked without explicit source_epoch."""
        self._check_physical(body_bytes, write=write)
        yield
