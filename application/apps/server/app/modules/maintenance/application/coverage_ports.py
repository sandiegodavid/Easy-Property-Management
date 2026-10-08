"""Property-scoped source revision for explicit maintenance knowledge review."""

from typing import Protocol
from collections.abc import Collection, Mapping


class MaintenanceCoverageReader(Protocol):
    def evidence_revisions(
        self, connection, property_ids: Collection[str]
    ) -> Mapping[str, str]: ...
    def evidence_revision(self, connection, property_id: str) -> str: ...
