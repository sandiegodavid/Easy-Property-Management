"""Consumer-neutral durable communication operation receipts."""

from typing import Mapping, Protocol


class CommunicationReceiptReader(Protocol):
    def receipt(self, connection, key: str) -> Mapping | None: ...
