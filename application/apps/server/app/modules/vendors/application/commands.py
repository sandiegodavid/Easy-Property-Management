"""Provider-owned command concurrency and immutable original results."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.modules.vendors.application.errors import (
    ProviderError,
    ProviderLifecycleConflict,
    ProviderNotFoundError,
)
from app.modules.vendors.application.ports import ProviderTransaction
from app.modules.vendors.domain.models import ProviderProfile

CHILD_KINDS = ("service", "area", "work", "reference", "reputation")
CHILD_ACTIONS = {
    f"{kind}_{verb}" for kind in CHILD_KINDS for verb in ("create", "update", "archive", "restore")
}
ASSIGNMENT_ACTIONS = {"assignment_create", "assignment_archive", "assignment_restore"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identifier(value):
    try:
        valid = isinstance(value, str) and str(UUID(value)) == value
    except TypeError, ValueError:
        valid = False
    if not valid:
        raise ProviderError("Command identities must be canonical UUIDs.")
    return value


@dataclass(frozen=True)
class ProviderCommand:
    action: str
    party_id: str | None
    expected_revision: int
    idempotency_key: str
    payload: dict

    def __post_init__(self):
        if (
            self.action
            not in {"create", "designate", "patch", "archive", "restore"}
            | CHILD_ACTIONS
            | ASSIGNMENT_ACTIONS
        ):
            raise ProviderError("Unsupported Provider command.")
        initial = self.action in {"create", "designate"}
        if type(self.expected_revision) is not int or (
            self.expected_revision != 0 if initial else self.expected_revision < 1
        ):
            raise ProviderError("expectedRevision must be zero for creation or a positive integer.")
        identifier(self.idempotency_key)
        if self.action == "create":
            if self.party_id is not None:
                raise ProviderError("Creation cannot select an existing identity.")
        else:
            identifier(self.party_id)
        if self.action in CHILD_ACTIONS:
            if set(self.payload) != {"item_id", "fields"} or not isinstance(
                self.payload["fields"], dict
            ):
                raise ProviderError("Child command payload is invalid.")
            if self.action.endswith("_create"):
                if self.payload["item_id"] is not None:
                    raise ProviderError("Child creation cannot select an existing record.")
            else:
                identifier(self.payload["item_id"])

    def request(self):
        return {
            "action": self.action,
            "partyId": self.party_id,
            "expectedRevision": self.expected_revision,
            "payload": self.payload,
        }


def start(tx: ProviderTransaction, command: ProviderCommand):
    previous = tx.operation_by_key(command.idempotency_key)
    if previous is not None:
        if previous["request_fingerprint"] != fingerprint(command.request()):
            raise ProviderLifecycleConflict(
                "Idempotency key was used for another command.",
                code="provider_idempotency_conflict",
            )
        return json.loads(previous["result_json"])
    if command.party_id is not None:
        profile = tx.profile(command.party_id)
        if profile is None and command.action != "designate":
            raise ProviderNotFoundError("Provider was not found.")
        if (profile.revision if profile else 0) != command.expected_revision:
            raise ProviderLifecycleConflict(
                "Provider revision has changed.",
                code="provider_revision_conflict",
                current=profile.to_dict() if profile else None,
            )
    return None


def receipt_audit(operation):
    return {
        "id": operation["id"],
        "partyId": operation["party_id"],
        "action": operation["action"],
        "expectedRevision": operation["expected_revision"],
        "revision": operation["resulting_revision"],
    }


def finish(
    tx: ProviderTransaction,
    command: ProviderCommand,
    profile: ProviderProfile,
    now: str,
    correlation: str,
    *,
    child=None,
    category=None,
):
    operation_id = str(uuid4())
    result = {
        "profile": profile.to_dict(),
        "revision": profile.revision,
        "operationId": operation_id,
    }
    if child is None:
        party = tx.party(profile.party_id)
        result.update(party=party.to_dict(), partyRevision=party.revision)
    else:
        result.update(kind=command.action.rsplit("_", 1)[0], item=child.to_dict())
        if category is not None:
            result["category"] = category.to_dict()
    operation = {
        "id": operation_id,
        "party_id": profile.party_id,
        "action": command.action,
        "idempotency_key": command.idempotency_key,
        "request_json": canonical(command.request()),
        "request_fingerprint": fingerprint(command.request()),
        "expected_revision": command.expected_revision,
        "resulting_revision": profile.revision,
        "result_json": canonical(result),
        "correlation_id": correlation,
        "created_at": now,
    }
    tx.insert_operation(operation)
    tx.record_change(
        entity_type="provider_command_operation",
        entity_id=operation_id,
        action="recorded",
        before=None,
        after=receipt_audit(operation),
        reason="provider_command_recorded",
        correlation_id=correlation,
    )
    return result
