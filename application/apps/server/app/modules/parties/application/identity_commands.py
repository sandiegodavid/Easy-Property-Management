"""Source-owned Party command identity and immutable receipt values."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identifier(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Identity must be a canonical UUID.")
    return value


@dataclass(frozen=True)
class PartyCommandIdentity:
    action: str
    party_id: str | None
    expected_revision: int
    idempotency_key: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.action not in {
            "create",
            "patch",
            "archive",
            "restore",
            "contact_add",
            "contact_update",
            "contact_archive",
            "contact_restore",
        }:
            raise ValueError("Party command action is invalid.")
        if self.action == "create":
            if self.party_id is not None:
                raise ValueError("Party creation cannot select an existing identity.")
        else:
            identifier(self.party_id)
        minimum = 0 if self.action == "create" else 1
        if type(self.expected_revision) is not int or self.expected_revision < minimum:
            raise ValueError("Expected revision must be an exact nonnegative integer.")
        if self.action == "create" and self.expected_revision != 0:
            raise ValueError("Party creation requires revision zero.")
        identifier(self.idempotency_key)

    def request(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "partyId": self.party_id,
            "expectedRevision": self.expected_revision,
            "payload": self.payload,
        }
