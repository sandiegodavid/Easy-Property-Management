"""Read-only receipts for caller-owned command-outcome reconciliation."""

from typing import Mapping, Protocol


class IssueCommandReceiptReader(Protocol):
    def receipt(self, connection, key: str) -> Mapping | None: ...
