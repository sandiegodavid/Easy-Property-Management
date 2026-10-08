"""Opaque append marker for a caller-owned consistent read snapshot."""

from typing import Any, Protocol


class AuditReadMarker(Protocol):
    def marker(self, connection: Any) -> str: ...


class AuditEntityReadMarker(Protocol):
    """Revision over source-owned set-based entity identity relations."""

    def marker_for_references(self, connection: Any, references: Any) -> str: ...
    def markers_for_groups(self, connection: Any, references: Any) -> dict[str, str]: ...
