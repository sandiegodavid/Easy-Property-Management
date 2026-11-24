"""Read-only shared maintenance announcement reader (H06.3 / D5).

Reads deployment-scoped `/run/epm/maintenance-notice.json` (root-owned, mounted
read-only into Operator containers). O(1) bounded read; fails safe to unavailable
on missing, inactive, oversized, or malformed files.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import time_ns
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from app.platform.hosted_contracts.reads import Freshness, FreshnessState
from app.platform.hosted_contracts.ui_states import MaintenanceNotice, Section
from app.platform.hosted_contracts.values import Contract, Count, Explanation

DEFAULT_MAINTENANCE_NOTICE_PATH = Path("/run/epm/maintenance-notice.json")
MAX_MAINTENANCE_NOTICE_BYTES = 8 * 1024


class MaintenanceNoticeDocument(Contract):
    """Schema of /run/epm/maintenance-notice.json written by Admin/Host Agent."""

    active: bool
    window_start_utc: Count | None = None
    window_end_utc: Count | None = None
    message: Explanation | None = None
    state: Literal["announced", "in_progress"] = Field(default="announced")

    @model_validator(mode="after")
    def _validate_active(self) -> MaintenanceNoticeDocument:
        if self.active:
            if self.window_start_utc is None or self.window_end_utc is None or self.message is None:
                raise ValueError("Active maintenance notice requires window times and message.")
            if self.window_end_utc <= self.window_start_utc:
                raise ValueError("window_end_utc must be strictly greater than window_start_utc.")
        return self


def _load_notice(path: Path) -> MaintenanceNoticeDocument | None:
    if path.is_symlink():
        raise ValueError("Maintenance notice path must not be a symlink.")
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        raw = handle.read(MAX_MAINTENANCE_NOTICE_BYTES + 1)
    if len(raw) > MAX_MAINTENANCE_NOTICE_BYTES:
        raise ValueError("Maintenance notice exceeds maximum byte bound.")
    return MaintenanceNoticeDocument.model_validate_json(raw)


def _is_active_at(doc: MaintenanceNoticeDocument | None, now: int) -> bool:
    return (
        doc is not None
        and doc.active
        and doc.window_end_utc is not None
        and now < doc.window_end_utc
    )


def read_maintenance_notice(
    path: Path = DEFAULT_MAINTENANCE_NOTICE_PATH,
    *,
    clock: Callable[[], int] | None = None,
) -> Section[MaintenanceNotice]:
    """Return a validated Section[MaintenanceNotice] for Operator Settings / shell."""
    now_clock = clock or (lambda: time_ns() // 1_000_000)
    now = now_clock()
    try:
        doc = _load_notice(path)
    except OSError, ValueError, ValidationError:
        return Section[MaintenanceNotice](
            state="unavailable",
            freshness=Freshness(
                state=FreshnessState.UNAVAILABLE,
                error_code="maintenance_notice_unavailable",
            ),
        )
    if not _is_active_at(doc, now):
        return Section[MaintenanceNotice](
            state="unavailable",
            freshness=Freshness(
                state=FreshnessState.UNAVAILABLE,
                error_code="no_announced_maintenance",
            ),
        )
    assert doc is not None
    assert doc.message is not None
    assert doc.window_start_utc is not None
    assert doc.window_end_utc is not None
    return Section[MaintenanceNotice](
        state="ready",
        data=MaintenanceNotice(
            message=doc.message,
            starts_at=doc.window_start_utc,
            ends_at=doc.window_end_utc,
        ),
        freshness=Freshness(
            state=FreshnessState.KNOWN,
            as_of=now,
            source_revision=f"maintenance:{doc.state}:{doc.window_start_utc}",
        ),
    )


def is_maintenance_in_progress(
    path: Path = DEFAULT_MAINTENANCE_NOTICE_PATH,
    *,
    clock: Callable[[], int] | None = None,
) -> bool:
    """Return True only when an active unexpired maintenance notice is explicitly in_progress."""
    now = (clock or (lambda: time_ns() // 1_000_000))()
    try:
        doc = _load_notice(path)
    except OSError, ValueError, ValidationError:
        return False
    return bool(_is_active_at(doc, now) and doc is not None and doc.state == "in_progress")
