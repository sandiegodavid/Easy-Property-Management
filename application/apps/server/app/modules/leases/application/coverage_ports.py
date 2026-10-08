"""Current lease/term metadata needed to assess recorded context."""

from collections.abc import Mapping
from typing import Protocol


class LeaseCoverageReader(Protocol):
    def relevant_contexts(self, connection, dates: Mapping[str, str]) -> Mapping[str, Mapping]: ...
    def relevant_context(self, connection, space_id: str, on: str) -> Mapping | None: ...
