"""Read-only receipts for caller-owned command-outcome reconciliation."""

from typing import Protocol, TypedDict


class IssueCommandReceipt(TypedDict):
    id: str
    result_issue_id: str
    request_fingerprint: str
    request_payload: str
    response_payload: str
    revision: int


class IssueCommandReceiptReader(Protocol):
    def receipt(self, connection, key: str) -> IssueCommandReceipt | None: ...
