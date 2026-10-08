"""Tenant-owned revision checks and immutable command receipts."""

import json
from dataclasses import dataclass, replace
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.modules.parties.application.identity_commands import canonical, fingerprint, identifier
from app.modules.tenants.application.errors import TenantConflictError, TenantError
from app.modules.tenants.application.ports import TenantProfileTransaction
from app.modules.tenants.domain.models import TenantProfile
from app.modules.parties.application.ports import ContactReferenceResolution


@dataclass(frozen=True)
class TenantCommand:
    action: str
    party_id: str | None
    expected_revision: int
    idempotency_key: str
    payload: dict

    def __post_init__(self):
        initial = self.action in {"create", "designate"}
        if self.action not in {
            "create",
            "designate",
            "patch",
            "archive",
            "restore",
            "resolve_contact",
        }:
            raise TenantError("Unsupported Tenant command.")
        if type(self.expected_revision) is not int or (
            self.expected_revision != 0 if initial else self.expected_revision < 1
        ):
            raise TenantError("expectedRevision must be zero for creation or a positive integer.")
        try:
            identifier(self.idempotency_key)
            if self.action == "create":
                if self.party_id is not None:
                    raise ValueError("Creation cannot select an existing Party.")
            else:
                identifier(self.party_id)
        except (ValueError, TypeError) as error:
            raise TenantError("Command identities must be canonical UUIDs.") from error

    def request(self):
        return {
            "action": self.action,
            "partyId": self.party_id,
            "expectedRevision": self.expected_revision,
            "payload": self.payload,
        }


def start(tx: TenantProfileTransaction, command: TenantCommand):
    previous = tx.tenant_operation_by_key(command.idempotency_key)
    if previous is not None:
        if previous["request_fingerprint"] != fingerprint(command.request()):
            raise TenantConflictError(
                "Idempotency key was used for another command.", code="tenant_idempotency_conflict"
            )
        return json.loads(previous["result_json"])
    if command.party_id is not None:
        profile = tx.profile(command.party_id)
        revision = profile.revision if profile else 0
        if revision != command.expected_revision:
            raise TenantConflictError(
                "Tenant revision has changed.",
                code="tenant_revision_conflict",
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
    tx: TenantProfileTransaction,
    command: TenantCommand,
    profile: TenantProfile,
    result: dict,
    now: str,
    correlation: str,
):
    operation_id = str(uuid4())
    result = {**result, "revision": profile.revision, "operationId": operation_id}
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
    tx.insert_tenant_operation(operation)
    tx.record_change(
        entity_type="tenant_command_operation",
        entity_id=operation_id,
        action="recorded",
        before=None,
        after=receipt_audit(operation),
        reason="tenant_command_recorded",
        correlation_id=correlation,
    )
    return result


def resolve_contact(
    tx: TenantProfileTransaction, resolution: ContactReferenceResolution, now: str, correlation: str
):
    """Resolve a Tenant preference in the contact owner's existing transaction."""
    command = TenantCommand(
        "resolve_contact",
        resolution.role_record_id,
        resolution.expected_tenant_revision,
        str(uuid5(NAMESPACE_URL, f"tenant-contact:{correlation}:{resolution.role_record_id}")),
        {"preferred_contact_method_id": resolution.replacement_contact_method_id},
    )
    if replay := start(tx, command):
        return replay
    profile = tx.profile(command.party_id)
    updated = replace(
        profile,
        preferred_contact_method_id=resolution.replacement_contact_method_id,
        updated_at=now,
        revision=profile.revision + 1,
    )
    tx.replace_profile(updated)
    tx.record_change(
        entity_type="tenant_profile",
        entity_id=profile.party_id,
        action="updated",
        before=profile.to_dict(),
        after=updated.to_dict(),
        reason="preferred_contact_updated",
        correlation_id=correlation,
    )
    return finish(tx, command, updated, updated.to_dict(), now, correlation)
