"""Canonical non-secret, typed intent; not an authorization or persistence decision."""

from hashlib import sha256
import json

from pydantic import model_validator
from pydantic_core import PydanticKnownError

from app.platform.hosted_contracts.values import Contract, MAX_INTEGER, MAX_RECORD_BYTES

MAX_NESTING = 16


class SemanticRequest(Contract):
    """Owners declare every consequential field and normalize values before hashing.

    Defaults are included: omitted and explicitly supplied defaults are equivalent.
    Null remains a JSON null. If absence and null mean different actions, the owner
    must declare a tagged variant, rather than use an optional default for that field.
    Tuples preserve array order; mappings, floats, bytes and secret wrappers are refused.
    """

    @model_validator(mode="after")
    def bounded_intent(self):
        canonical_bytes(self)
        return self


def _semantic_value(value: object, depth: int):
    if depth > MAX_NESTING:
        raise ValueError("Hosted intent nesting exceeds its bound.")
    if isinstance(value, Contract):
        # Read declared fields directly: serialization aliases/exclusions cannot
        # silently drop consequential fields from the semantic hash.
        return {
            name: _semantic_value(getattr(value, name), depth + 1)
            for name in type(value).model_fields
        }
    if isinstance(value, tuple):
        return [_semantic_value(item, depth + 1) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int and -MAX_INTEGER - 1 <= value <= MAX_INTEGER:
        return value
    raise ValueError("Hosted intent requires declared immutable non-secret JSON values.")


def canonical_bytes(request: SemanticRequest) -> bytes:
    if not isinstance(request, SemanticRequest):
        raise TypeError("A validated owning SemanticRequest is required.")
    value = _semantic_value(request, 0)
    try:
        encoded = json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except UnicodeError as error:
        raise ValueError("Hosted intent requires valid Unicode.") from error
    if len(encoded) > MAX_RECORD_BYTES:
        raise PydanticKnownError(
            "too_long",
            {
                "field_type": "Hosted intent bytes",
                "max_length": MAX_RECORD_BYTES,
                "actual_length": len(encoded),
            },
        )
    return encoded


def semantic_hash(request: SemanticRequest) -> str:
    return sha256(canonical_bytes(request)).hexdigest()
