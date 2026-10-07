"""Portable OPS values and concurrency/error contracts."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

DESTINATIONS = (
    "home",
    "properties",
    "owners",
    "leasing",
    "money",
    "maintenance",
    "providers",
    "settings",
)
CUSTOMIZABLE = DESTINATIONS[1:-1]
MAX_RECOVERY_BYTES = 65536
MAX_ACTIVE_RECOVERY = 100


class OperatorError(ValueError):
    code = "operator_validation"
    status_code = 422


class OperatorConflict(OperatorError):
    code = "operator_conflict"
    status_code = 409

    def __init__(self, message, *, current_revision=None):
        super().__init__(message)
        self.current_revision = current_revision


class OperatorNotFound(OperatorError):
    code = "operator_not_found"
    status_code = 404


class OperatorUnavailable(OperatorError):
    code = "workspace_unavailable"
    status_code = 503


class OperatorStorageFailure(OperatorError):
    code = "operator_storage_failure"
    status_code = 500


class OperatorTooLarge(OperatorError):
    code = "operator_payload_too_large"
    status_code = 413


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Preferences(Contract):
    appearance: Literal["light", "dark"] = "light"
    destination_order: tuple[str, ...] = DESTINATIONS
    hidden_destination_ids: tuple[str, ...] = ()
    revision: StrictInt = Field(default=0, ge=0)
    updated_at: str | None = None

    @model_validator(mode="after")
    def valid_destinations(self):
        order, hidden = self.destination_order, self.hidden_destination_ids
        if len(set(order)) != len(order) or set(order) - set(DESTINATIONS):
            raise ValueError("Destination IDs must be known and unique.")
        if "home" in order and order[0] != "home":
            raise ValueError("Home must be first.")
        if "settings" in order and order[-1] != "settings":
            raise ValueError("Settings must be last.")
        if len(set(hidden)) != len(hidden) or set(hidden) - set(CUSTOMIZABLE):
            raise ValueError("Only customizable destinations may be hidden, once each.")
        middle = tuple(item for item in order if item in CUSTOMIZABLE)
        middle += tuple(item for item in CUSTOMIZABLE if item not in middle)
        object.__setattr__(self, "destination_order", ("home", *middle, "settings"))
        if self.updated_at is not None:
            utc(self.updated_at)
        return self


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def audit_metadata(result):
    """One canonical metadata-only snapshot for writers and retained validation."""
    excluded = {"payload", "receipt", "requestFingerprint", "attemptKey"}
    return {key: value for key, value in result.items() if key not in excluded}


def identifier(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise OperatorError("A canonical UUID is required.") from error
    return value


def utc(value):
    try:
        parsed = datetime.fromisoformat(value)
        if (
            parsed.tzinfo is None
            or parsed.utcoffset() is None
            or parsed.astimezone(UTC).isoformat() != value
        ):
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise OperatorError("A canonical UTC timestamp is required.") from error
    return parsed


def concurrency(expected_revision, idempotency_key):
    if type(expected_revision) is not int or expected_revision < 0:
        raise OperatorError("expectedRevision must be a nonnegative integer.")
    identifier(idempotency_key)
