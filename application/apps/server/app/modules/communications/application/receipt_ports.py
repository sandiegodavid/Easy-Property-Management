"""Consumer-neutral durable communication operation receipts."""

from typing import Any, Protocol, TypedDict


class CommunicationReceipt(TypedDict):
    id: str
    result_communication_id: str
    request_fingerprint: str
    result_revision: int
    outcome: str
    response_json: str


class CommunicationReceiptReader(Protocol):
    def receipt(self, connection: Any, key: str) -> CommunicationReceipt | None: ...
