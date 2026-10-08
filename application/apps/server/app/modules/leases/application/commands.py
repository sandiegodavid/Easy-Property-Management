"""Lease-owned immutable command identities and receipts."""

from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from typing import Any, Literal, TypedDict

LeaseCommandAction = Literal[
    "create",
    "patch",
    "replace_initial_term",
    "add_participant",
    "update_participant",
    "remove_participant",
    "execute",
    "ended",
    "terminated",
    "void",
    "add_renewal_option",
    "decide_renewal_option",
    "update_renewal_option",
    "create_termination_case",
    "add_termination_proposal",
    "accept_termination_proposal",
    "transition_termination_case",
    "complete_termination_case",
]
COMMAND_ACTIONS = frozenset(LeaseCommandAction.__args__)
TIMELINE_ACTIONS = frozenset(
    {"execute", "ended", "terminated", "void", "complete_termination_case"}
)


def canonical_json(value: Any) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LeaseCommandIdentity:
    action: LeaseCommandAction
    target_kind: Literal["lease", "termination_case", "space"]
    target_id: str
    expected_revision: int
    idempotency_key: str
    payload: dict[str, object]

    def request_json(self) -> str:
        return canonical_json(
            {
                "action": self.action,
                "targetKind": self.target_kind,
                "targetId": self.target_id,
                "expectedLeaseRevision": self.expected_revision,
                "payload": self.payload,
            }
        )


class LeaseCommandReceipt(TypedDict):
    id: str
    lease_id: str
    idempotency_key: str
    action: str
    expected_revision: int
    result_revision: int
    effective: int
    request_json: str
    request_fingerprint: str
    response_json: str
    response_fingerprint: str
    correlation_id: str
    created_at: str


def receipt_audit(receipt: LeaseCommandReceipt) -> dict[str, object]:
    """Bind both payloads without putting private lease context in general activity."""
    return {
        key: value for key, value in receipt.items() if key not in {"request_json", "response_json"}
    }
