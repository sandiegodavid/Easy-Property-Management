"""Lease directory continuations scoped to a runtime and a stable read view."""

import base64
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.modules.leases.application.commands import canonical_json
from app.modules.leases.application.ports import LeaseConflictError

MAX_CURSOR_LENGTH = 4096
KEY_PARTS = 2
CURSOR_LIFETIME = timedelta(minutes=15)
ENDPOINT = "/api/leases/directory"


def encode_cursor(scope: dict, last: tuple[str, str]) -> str:
    return (
        base64.urlsafe_b64encode(canonical_json({**scope, "last": last}).encode())
        .decode()
        .rstrip("=")
    )


def cursor_scope(*, identity, filters, marker, instant):
    return {
        "version": 1,
        "endpoint": ENDPOINT,
        "identity": list(identity),
        "filters": filters,
        "sourceRevision": marker,
        "asOf": instant.astimezone(UTC).isoformat(),
    }


def _position(last):
    if (
        not isinstance(last, list)
        or len(last) != KEY_PARTS
        or any(not isinstance(part, str) for part in last)
    ):
        raise ValueError
    if date.fromisoformat(last[0]).isoformat() != last[0] or str(UUID(last[1])) != last[1]:
        raise ValueError
    return last[0], last[1]


def decode_cursor(value: str, scope: dict) -> tuple[tuple[str, str], str]:
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_CURSOR_LENGTH:
            raise ValueError
        retained = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(retained, dict) or set(retained) != set(scope) | {"last"}:
            raise ValueError
        if type(retained["version"]) is not int or retained["version"] != 1:
            raise ValueError
        last = _position(retained["last"])
        captured = datetime.fromisoformat(retained["asOf"])
        if captured.tzinfo is None or captured.utcoffset() != timedelta(0):
            raise ValueError
        for field in ("endpoint", "identity", "filters", "sourceRevision"):
            if retained[field] != scope[field]:
                raise LeaseConflictError(
                    "Lease directory changed. Restart with the selected filters."
                )
        now = datetime.fromisoformat(scope["asOf"])
        if captured > now or now - captured >= CURSOR_LIFETIME:
            raise LeaseConflictError(
                "Lease directory continuation expired. Restart with the selected filters."
            )
        return last, retained["asOf"]
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise ValueError("Invalid lease directory cursor.") from error
