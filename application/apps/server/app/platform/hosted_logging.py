"""Standardized secret-free structured JSON logging for hosted services (H06.4 / D3)."""

from __future__ import annotations

import json
import logging
import re
from time import time_ns

REDACTED = "[REDACTED]"
MAX_STRING_VALUE_LEN = 512

SENSITIVE_KEY_MARKERS = (
    "secret",
    "token",
    "cookie",
    "authorization",
    "password",
    "private_key",
    "wrapped_dek",
    "raw_dek",
    "dek",
    "api_key",
    "bearer",
    "credential",
    "session_id",
    "grant",
    "payload",
    "business_data",
    "csrf",
    "oobcode",
    "oob_code",
    "handoff",
    "assertion",
    "signing_key",
    "access_key",
)

_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_COOKIE_KV_RE = re.compile(
    r"(?i)\b(__Host-[A-Za-z0-9_.-]+|session|csrf|oobCode|apiKey|key|code|token|x-csrf-token|x-epm-csrf)=[^;&\s]{4,}"
)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def redact_string(value: str) -> str:
    """Strip Bearer/Basic tokens, JWTs, query secrets, and cookie values from log strings."""
    cleaned = _BEARER_RE.sub(r"\1 [REDACTED]", value)
    cleaned = _JWT_RE.sub(REDACTED, cleaned)
    cleaned = _COOKIE_KV_RE.sub(r"\1=[REDACTED]", cleaned)
    if len(cleaned) > MAX_STRING_VALUE_LEN:
        return cleaned[:MAX_STRING_VALUE_LEN] + "..."
    return cleaned


def redact_value(value: object, *, key: str = "") -> object:
    """Recursively redact sensitive keys and token/cookie patterns."""
    if key and _is_sensitive_key(key):
        result: object = REDACTED
    elif isinstance(value, dict):
        result = {str(k): redact_value(v, key=str(k)) for k, v in value.items()}
    elif isinstance(value, (list, tuple, set, frozenset)):
        result = [redact_value(item) for item in value]
    elif isinstance(value, str):
        result = redact_string(value)
    elif isinstance(value, (bytes, bytearray)):
        result = REDACTED
    elif isinstance(value, (int, float, bool)) or value is None:
        result = value
    else:
        result = redact_string(str(value))
    return result


def format_structured_log(
    component: str,
    event: str,
    *,
    severity: str = "INFO",
    timestamp_ms: int | None = None,
    **fields: object,
) -> str:
    """Serialize a secret-redacted single-line JSON log record for Cloud Logging / Ops Agent."""
    record: dict[str, object] = {
        "component": redact_string(component),
        "event": redact_string(event),
        "severity": severity.upper(),
        "timestamp_ms": timestamp_ms if timestamp_ms is not None else time_ns() // 1_000_000,
    }
    for k, v in fields.items():
        if k in {"component", "event", "severity", "timestamp_ms"}:
            continue
        record[str(k)] = redact_value(v, key=str(k))
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def emit_structured_event(
    target_logger: logging.Logger,
    component: str,
    event: str,
    *,
    severity: str = "INFO",
    **fields: object,
) -> str:
    """Emit a redacted structured JSON event through Python logging and return the JSON line."""
    line = format_structured_log(component, event, severity=severity, **fields)
    level = getattr(logging, severity.upper(), logging.INFO)
    target_logger.log(level, "%s", line)
    return line


class StructuredJsonFormatter(logging.Formatter):
    """Stdlib logging formatter that emits redacted Cloud-Logging-compatible JSON lines."""

    def __init__(self, component: str):
        super().__init__()
        self.component = component

    def format(self, record: logging.LogRecord) -> str:
        raw_message = record.getMessage()
        try:
            parsed = json.loads(raw_message)
            if isinstance(parsed, dict) and "event" in parsed and "component" in parsed:
                return json.dumps(redact_value(parsed), sort_keys=True, separators=(",", ":"))
        except ValueError:
            pass
        return format_structured_log(
            self.component,
            record.name,
            severity=record.levelname,
            message=raw_message,
        )
