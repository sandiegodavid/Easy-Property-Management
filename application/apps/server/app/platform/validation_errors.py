"""Transport-neutral classification of structured schema validation errors."""

from collections.abc import Mapping
from typing import Any


def is_size_limit_violation(error: Mapping[str, Any]) -> bool:
    """Upper string/container bounds are size errors; lower bounds are malformed input."""
    return error.get("type") in {"string_too_long", "too_long"}
