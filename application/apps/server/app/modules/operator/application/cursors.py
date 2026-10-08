"""Bounded OPS continuations tied to a retained snapshot and runtime identity."""

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict, NotRequired, Unpack

from app.modules.operator.domain.models import (
    OperatorConflict,
    OperatorError,
    canonical,
    fingerprint,
    identifier,
    utc,
)

MAX_CURSOR_BYTES = 4096
CURSOR_KEY_PARTS = 2
MAX_SORT_KEY = 1000


class CursorArguments(TypedDict):
    endpoint: str
    filters: dict
    identity: tuple[str, str]
    source_revision: str
    now: datetime
    sort_kind: NotRequired[str]


@dataclass(frozen=True)
class ReadCursor:
    endpoint: str
    filters: dict
    identity: tuple[str, str]
    source_revision: str
    as_of: str
    last: tuple[str, str]

    def encode(self):
        return (
            base64.urlsafe_b64encode(
                canonical(
                    {
                        "version": 1,
                        "endpoint": self.endpoint,
                        "filters": self.filters,
                        "identity": self.identity,
                        "sourceRevision": self.source_revision,
                        "asOf": self.as_of,
                        "last": self.last,
                    }
                ).encode()
            )
            .decode()
            .rstrip("=")
        )


def decode_cursor(value, **scope: Unpack[CursorArguments]):
    endpoint, filters, identity = scope["endpoint"], scope["filters"], scope["identity"]
    source_revision, now = scope["source_revision"], scope["now"]
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_CURSOR_BYTES:
            raise ValueError()
        data = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if (
            set(data)
            != {"version", "endpoint", "filters", "identity", "sourceRevision", "asOf", "last"}
            or type(data["version"]) is not int
            or data["version"] != 1
        ):
            raise ValueError()
        if not isinstance(data["last"], list) or len(data["last"]) != CURSOR_KEY_PARTS:
            raise ValueError()
        last = tuple(data["last"])
        _validate_sort(last[0], scope.get("sort_kind", "instant"))
        identifier(last[1])
        captured = utc(data["asOf"])
        if data["endpoint"] != endpoint or canonical(data["filters"]) != canonical(filters):
            raise OperatorConflict("Restart this collection with the selected filters.")
        if data["identity"] != list(identity) or data["sourceRevision"] != source_revision:
            raise OperatorConflict(
                "The workspace or recorded sources changed. Refresh this collection."
            )
        if captured > now or now - captured >= timedelta(minutes=15):
            raise OperatorConflict("This continuation expired. Refresh with the same filters.")
        return ReadCursor(endpoint, filters, identity, source_revision, data["asOf"], last)
    except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
        if isinstance(error, OperatorError):
            raise
        raise OperatorError("Malformed collection cursor.") from error


def _validate_sort(value, kind):
    if kind == "instant":
        utc(value)
    elif kind != "label" or not isinstance(value, str) or len(value) > MAX_SORT_KEY:
        raise ValueError()


def read_revision(identity, marker):
    return fingerprint({"identity": identity, "marker": marker})
