"""Opaque append marker for a caller-owned consistent read snapshot."""

from typing import Any, Protocol


class AuditReadMarker(Protocol):
    def marker(self, connection: Any) -> str: ...
