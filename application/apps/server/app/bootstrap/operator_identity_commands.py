"""Explicit source-owned Party/Tenant fingerprints and recovery gates."""

from dataclasses import asdict

from app.modules.parties.application.identity_commands import (
    PartyCommandIdentity,
    fingerprint,
    identifier,
)
from app.modules.parties.application.service import (
    ContactMethodCommand,
    ContactReferenceResolution,
    PartyCreateCommand,
    PartyPatchCommand,
)
from app.modules.parties.infrastructure.recovery_reader import SQLitePartyRecoveryReader
from app.modules.tenants.application.commands import TenantCommand
from app.modules.tenants.application.service import TenantCreateCommand, TenantProfilePatchCommand
from app.modules.tenants.infrastructure.recovery_reader import SQLiteTenantRecoveryReader
from app.modules.operator.application.identity_forms import IDENTITY_SCHEMAS, identity_source_kind
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError


def contact(payload):
    return ContactMethodCommand(
        payload["methodKind"], payload["value"], payload.get("extension"), payload.get("label")
    )


def resolutions(payload):
    values = [
        ContactReferenceResolution(
            item["role"],
            item["roleRecordId"],
            item.get("replacementContactMethodId"),
            item.get("clear", False),
            item.get("expectedTenantRevision"),
        )
        for item in payload.get("referenceResolutions") or ()
    ]
    keys = [(item.role, item.role_record_id) for item in values]
    if len(keys) != len(set(keys)):
        raise OperatorError("Reference resolutions must not repeat a role record.")
    return [
        asdict(item) for item in sorted(values, key=lambda item: (item.role, item.role_record_id))
    ]


def party_payload(action, payload):
    if action in {"contact_update", "contact_archive", "contact_restore"}:
        identifier(payload.get("methodId"))
    if action == "create":
        return {
            "command": asdict(PartyCreateCommand(payload["partyKind"], payload["displayName"])),
            "contacts": [asdict(contact(item)) for item in payload.get("contacts") or ()],
            "confirmedNewParty": payload.get("confirmedNewParty") or False,
        }
    if action == "patch":
        return asdict(PartyPatchCommand(payload["displayName"]))
    if action == "contact_add":
        return {"command": asdict(contact(payload))}
    if action == "contact_update":
        return {"methodId": payload["methodId"], "command": asdict(contact(payload))}
    if action == "contact_archive":
        return {
            "methodId": payload["methodId"],
            "confirmed": True,
            "referenceResolutions": resolutions(payload),
        }
    return (
        {"methodId": payload["methodId"]}
        if action == "contact_restore"
        else {"confirmed": True}
        if action == "archive"
        else {}
    )


def tenant_payload(action, payload):
    if action == "create":
        return asdict(
            TenantCreateCommand(
                payload["partyKind"],
                payload["displayName"],
                tuple(contact(item) for item in payload.get("contacts") or ()),
                payload.get("notes"),
                payload.get("doNotContact") or False,
                payload.get("confirmedNewParty") or False,
            )
        )
    if action == "patch":
        command = TenantProfilePatchCommand.from_mapping(
            {key: value for key, value in payload.items() if key != "expectedRevision"}
        )
        names = {
            "preferredContactMethodId": "preferred_contact_method_id",
            "doNotContact": "do_not_contact",
            "notes": "notes",
        }
        return {name: getattr(command, name) for key, name in names.items() if key in payload}
    if action == "designate":
        notes = payload.get("notes")
        if notes is not None:
            notes = notes.strip()
            if not notes:
                raise OperatorError("Notes must contain nonblank text or null.")
        return {"notes": notes}
    return {"confirmed": True} if action == "archive" else {}


def identity_fingerprint(family, action, source, payload, key):
    if any(
        name in payload and payload[name] is None
        for name in ("confirmedNewParty", "doNotContact", "contacts", "referenceResolutions")
    ):
        raise OperatorError("Complete the supplied boolean and contact-list fields.")
    if action in {"archive", "contact_archive"} and payload.get("confirmed") is not True:
        raise OperatorError("Confirm archival before starting an attempt.")
    request = (
        party_payload(action, payload) if family == "party" else tenant_payload(action, payload)
    )
    model = PartyCommandIdentity if family == "party" else TenantCommand
    return fingerprint(model(action, source, payload["expectedRevision"], key, request).request())


def identity_form_state(connection, binding, state, source, payload):
    action = binding.action
    allowed = (
        {"archived"}
        if action == "restore"
        else {"eligible"}
        if action == "designate"
        else {"active"}
    )
    if state["status"] not in allowed:
        return "source_unavailable"
    reader = binding.related_state
    if action in {"contact_update", "contact_archive", "contact_restore"}:
        target = payload.get("methodId")
        if target is None:
            return "available"
        contact_state = reader(connection, "contact", target)
        allowed_contact = "archived" if action == "contact_restore" else "active"
        if (
            contact_state is None
            or contact_state["source_id"] != source
            or contact_state["status"] != allowed_contact
        ):
            return "source_unavailable"
    if binding.family == "tenant" and action == "patch" and payload.get("preferredContactMethodId"):
        target = reader(connection, "contact", payload["preferredContactMethodId"])
        if target is None or target["source_id"] != source or target["status"] != "active":
            return "source_unavailable"
    return (
        resolution_state(connection, reader, source, payload)
        if action == "contact_archive"
        else "available"
    )


def resolution_state(connection, reader, source, payload):
    for item in payload.get("referenceResolutions") or ():
        if item["role"] == "tenant":
            tenant = reader(connection, "tenant", item["roleRecordId"])
            if (
                item["roleRecordId"] != source
                or tenant is None
                or tenant["revision"] != item["expectedTenantRevision"]
            ):
                return "source_changed"
        replacement = item.get("replacementContactMethodId")
        if replacement:
            target = reader(connection, "contact", replacement)
            if (
                target is None
                or target["source_id"] != source
                or target["status"] != "active"
                or replacement == payload.get("methodId")
            ):
                return "source_unavailable"
    return "available"


def compose_identity_forms():
    parties = SQLitePartyRecoveryReader()
    tenants = SQLiteTenantRecoveryReader(parties)
    actions = {
        "party.contact.add": "contact_add",
        "party.contact.update": "contact_update",
        "party.contact.archive": "contact_archive",
        "party.contact.restore": "contact_restore",
        "tenant.profile.patch": "patch",
    }
    result = {}

    def related(connection, kind, target):
        return (
            tenants.state(connection, target)
            if kind == "tenant"
            else parties.related_state(connection, kind, target)
        )

    for form in IDENTITY_SCHEMAS:
        family = form.split(".")[0]
        action = actions.get(form, form.rsplit(".", 1)[1])
        reader = (
            parties
            if family == "party"
            else SQLiteTenantRecoveryReader(parties, designate=True)
            if action == "designate"
            else tenants
        )
        result[form] = RecoveryBinding(
            identity_source_kind(form),
            action,
            family,
            reader,
            lambda source, payload, key, family=family, action=action: identity_fingerprint(
                family, action, source, payload, key
            ),
            family,
            related_state=related,
        )
    return result
