"""Bounded OPS continuations tied to a retained snapshot and runtime identity."""

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict, NotRequired, Unpack
from app.platform.attention_reads import AttentionKey
from app.platform.coverage import AREAS
from app.modules.operator.application.home_vocabulary import Collection, SourceKind
from app.modules.operator.application.home_registry import COLLECTION_DEPENDENCIES

from app.modules.operator.domain.models import (
    OperatorConflict,
    OperatorError,
    canonical,
    fingerprint,
    identifier,
    utc,
    OperatorTooLarge,
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


@dataclass(frozen=True)
class AttentionCursor:
    """Composite attention ordering is distinct from metadata's two-part key."""

    filters: dict
    identity: tuple[str, str]
    source_revision: str
    as_of: datetime
    last: AttentionKey

    def encode(self):
        return (
            base64.urlsafe_b64encode(
                canonical(
                    {
                        "version": 1,
                        "orderingVersion": 1,
                        "endpoint": "home.items",
                        "filters": self.filters,
                        "identity": self.identity,
                        "sourceRevision": self.source_revision,
                        "asOf": self.as_of.isoformat(),
                        "last": [
                            self.last.priority,
                            self.last.at.isoformat(),
                            self.last.source_kind,
                            self.last.source_id,
                        ],
                    }
                ).encode()
            )
            .decode()
            .rstrip("=")
        )


def decode_attention_cursor(value, *, filters, identity, source_revision, now):
    if isinstance(value, str) and len(value.encode("utf-8")) > MAX_CURSOR_BYTES:
        raise OperatorTooLarge("Collection cursor exceeds its size limit.")
    try:
        if not isinstance(value, str) or not value:
            raise ValueError()
        data = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(data, dict) or set(data) != {
            "version",
            "orderingVersion",
            "endpoint",
            "filters",
            "identity",
            "sourceRevision",
            "asOf",
            "last",
        }:
            raise ValueError()
        if any(
            type(data[name]) is not int or data[name] != 1
            for name in ("version", "orderingVersion")
        ):
            raise ValueError()
        if (
            not isinstance(data["endpoint"], str)
            or not isinstance(data["filters"], dict)
            or not isinstance(data["identity"], list)
            or len(data["identity"]) != 2
            or not isinstance(data["sourceRevision"], str)
            or not 1 <= len(data["sourceRevision"]) <= 128
        ):
            raise ValueError()
        for component in data["identity"]:
            identifier(component)
        captured = utc(data["asOf"])
        if data["endpoint"] != "home.items" or canonical(data["filters"]) != canonical(filters):
            raise OperatorConflict("Restart this collection with the selected filters.")
        last = _attention_key(data["last"], filters["collection"], captured)
        if data["identity"] != list(identity) or data["sourceRevision"] != source_revision:
            raise OperatorConflict(
                "The workspace or recorded sources changed. Refresh this collection."
            )
        if captured > now or now - captured >= timedelta(minutes=15):
            raise OperatorConflict("This continuation expired. Refresh with the same filters.")
        return AttentionCursor(filters, identity, source_revision, captured, last)
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, RecursionError) as error:
        if isinstance(error, OperatorError):
            raise
        raise OperatorError("Malformed attention collection cursor.") from error


def _attention_key(value, collection, captured):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError()
    priority, at, kind, identity = value
    if not isinstance(kind, str) or not isinstance(identity, str):
        raise ValueError()
    bands = {
        "needs_action": (0, 1, 2, 3),
        "waiting": (0, 1),
        "upcoming": (0,),
        "appointments": (0,),
        "information_review": (0, 1),
    }
    if type(priority) is not int or priority not in bands[collection]:
        raise ValueError()
    if SourceKind(kind) not in COLLECTION_DEPENDENCIES[Collection(collection)]:
        raise ValueError()
    boundary = utc(at)
    if kind == "coverage":
        prop, subject_kind, subject_id, area = identity.split(":")
        identifier(prop)
        identifier(subject_id)
        if (
            area not in AREAS
            or subject_kind != ("property" if area == "maintenance" else "space")
            or boundary != captured
        ):
            raise ValueError()
    else:
        identifier(identity)
    return AttentionKey(priority, boundary, kind, identity)
