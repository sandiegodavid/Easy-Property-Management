"""Shared source-owned concurrency, replay and receipt mechanics."""

import json
from uuid import uuid4

from app.modules.parties.application.errors import (
    PartyConflictError,
    PartyNotFoundError,
    PartyValidationError,
)
from app.modules.parties.application.identity_commands import (
    PartyCommandIdentity,
    canonical,
    fingerprint,
    identifier,
)
from app.modules.parties.application.ports import PartyTransaction, PartyUnitOfWork
from app.modules.parties.domain.models import Party, PartyContactMethod


def command_identity(action, party_id, revision, key, payload):
    try:
        return PartyCommandIdentity(action, party_id, revision, key, payload)
    except (ValueError, TypeError) as error:
        raise PartyValidationError(str(error)) from error


def start_command(tx: PartyTransaction, identity: PartyCommandIdentity):
    row = tx.operation_by_key(identity.idempotency_key)
    if row is not None:
        if row["request_fingerprint"] != fingerprint(identity.request()):
            raise PartyConflictError(
                "Idempotency key was used for another command.", code="party_idempotency_conflict"
            )
        return json.loads(row["result_json"])
    if identity.party_id is not None:
        current = tx.party(identity.party_id)
        if current is None:
            raise KeyError
        if current.revision != identity.expected_revision:
            raise PartyConflictError(
                "Party revision has changed.",
                code="party_revision_conflict",
                current=current.identity_snapshot(),
            )
    return None


def receipt_audit(operation):
    result = {
        "id": operation["id"],
        "partyId": operation["party_id"],
        "action": operation["action"],
        "expectedRevision": operation["expected_revision"],
        "revision": operation["resulting_revision"],
    }
    if operation["contact_method_id"] is not None:
        result["contactMethodId"] = operation["contact_method_id"]
    return result


def finish_command(
    tx: PartyTransaction,
    identity: PartyCommandIdentity,
    party: Party,
    now: str,
    correlation: str,
    *,
    contact: PartyContactMethod | None = None,
):
    operation_id = str(uuid4())
    result = {
        **(contact.to_dict() if contact else party.identity_snapshot()),
        "revision": party.revision,
        "operationId": operation_id,
    }
    operation = {
        "id": operation_id,
        "party_id": party.id,
        "contact_method_id": contact.id if contact else None,
        "action": identity.action,
        "idempotency_key": identity.idempotency_key,
        "request_json": canonical(identity.request()),
        "request_fingerprint": fingerprint(identity.request()),
        "expected_revision": identity.expected_revision,
        "resulting_revision": party.revision,
        "result_json": canonical(result),
        "created_at": now,
        "correlation_id": correlation,
    }
    tx.insert_operation(operation)
    tx.record_change(
        entity_type="party_command_operation",
        entity_id=operation_id,
        action="recorded",
        before=None,
        after=receipt_audit(operation),
        reason="party_command_recorded",
        correlation_id=correlation,
    )
    return result


def recover_command(uow: PartyUnitOfWork, *, operation_id=None, key=None):
    if (operation_id is None) == (key is None):
        raise PartyValidationError("Choose one receipt identity.")
    try:
        identifier(operation_id if operation_id is not None else key)
    except (ValueError, TypeError) as error:
        raise PartyValidationError("Receipt identity must be a canonical UUID.") from error
    row = uow.operation(operation_id=operation_id, key=key)
    if row is None:
        raise PartyNotFoundError("Party command receipt was not found.")
    return json.loads(row["result_json"])
