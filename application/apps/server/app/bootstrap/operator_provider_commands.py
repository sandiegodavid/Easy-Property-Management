"""Approved Provider/category OPS bindings using owning command identities."""

from dataclasses import asdict

from app.modules.operator.application.provider_forms import PROVIDER_SCHEMAS, provider_source_kind
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError
from app.modules.parties.application.service import PartyCreateCommand
from app.bootstrap.operator_identity_commands import contact
from app.modules.parties.infrastructure.recovery_reader import SQLitePartyRecoveryReader
from app.modules.vendors.application.commands import ProviderCommand, fingerprint, identifier
from app.modules.vendors.application.category_commands import CategoryCommand
from app.modules.vendors.application.service import (
    UNSET,
    ProviderCategoryCommand,
    ProviderCategoryPatchCommand,
    ProviderError,
    ProviderProfileCommand,
    ProviderProfilePatchCommand,
    ReferenceCommand,
    ReputationLinkCommand,
    ReputationLinkPatchCommand,
    ServiceAreaCommand,
    ServiceCommand,
    WorkHistoryCommand,
)
from app.modules.vendors.infrastructure.recovery_reader import SQLiteProviderRecoveryReader


FIELD_NAMES = {
    "displayName": "display_name",
    "countryCode": "country_code",
    "performedOn": "performed_on",
    "propertyId": "property_id",
    "summary": "summary",
    "outcomeNotes": "outcome_notes",
    "referenceName": "reference_name",
    "organizationName": "organization_name",
    "relationship": "relationship",
    "email": "email",
    "phone": "phone",
    "notes": "notes",
    "sourceKind": "source_kind",
    "sourceName": "source_name",
    "url": "url",
    "lastCheckedOn": "last_checked_on",
    "selectionStatus": "selection_status",
    "selectionReason": "selection_reason",
    "description": "description",
    "displayOrder": "display_order",
}
CHILD_COMMANDS = {
    "service": ServiceCommand,
    "area": ServiceAreaCommand,
    "work": WorkHistoryCommand,
    "reference": ReferenceCommand,
    "reputation": ReputationLinkCommand,
}
CHILD_FIELDS = {
    "service": {"displayName"},
    "area": {"displayName", "countryCode"},
    "work": {"performedOn", "summary", "propertyId", "outcomeNotes"},
    "reference": {"referenceName", "organizationName", "relationship", "email", "phone", "notes"},
    "reputation": {"sourceKind", "sourceName", "url", "notes", "lastCheckedOn"},
}


def fields(command):
    return {name: value for name, value in command.__dict__.items() if value is not UNSET}


def converted(payload, names):
    return {FIELD_NAMES[name]: payload[name] for name in names if name in payload}


def child_fields(kind, payload, *, patch=False):
    definition = (
        ReputationLinkPatchCommand if kind == "reputation" and patch else CHILD_COMMANDS[kind]
    )
    return fields(definition(**converted(payload, CHILD_FIELDS[kind])))


def create_payload(payload):
    party = payload["party"]
    categories = [identifier(item) for item in payload.get("categoryIds", ())]
    if len(categories) != len(set(categories)):
        raise OperatorError("A category can be assigned only once.")
    return {
        "party": asdict(PartyCreateCommand(party["partyKind"], party["displayName"])),
        "profile": profile_payload(payload),
        "contacts": [asdict(contact(item)) for item in payload.get("contacts", ())],
        **{
            name: [child_fields(kind, item) for item in payload.get(public, ())]
            for name, public, kind in (
                ("services", "services", "service"),
                ("areas", "serviceAreas", "area"),
                ("work_history", "workHistory", "work"),
                ("references", "references", "reference"),
            )
        },
        "category_ids": sorted(categories),
        "confirmed_new_party": payload.get("confirmedNewParty", False),
    }


def profile_payload(payload, *, patch=False):
    definition = ProviderProfilePatchCommand if patch else ProviderProfileCommand
    return fields(definition(**converted(payload, {"selectionStatus", "selectionReason", "notes"})))


def category_payload(action, payload, key):
    names = {"displayName", "description", "displayOrder"}
    if action == "create":
        result = asdict(ProviderCategoryCommand(idempotency_key=key, **converted(payload, names)))
        result.pop("idempotency_key")
        return result
    if action == "patch":
        return fields(ProviderCategoryPatchCommand(**converted(payload, names)))
    return lifecycle_payload(action, payload, reason=True)


def lifecycle_payload(action, payload, *, reason=False):
    if action == "restore" and not reason:
        return {}
    if payload.get("confirmed") is not True:
        raise OperatorError("Confirm the lifecycle action before starting an attempt.")
    result = {"confirmed": True}
    if action == "archive" and reason:
        value = payload["reason"].strip()
        if not value:
            raise OperatorError("Archive reason must contain nonblank text.")
        result["reason"] = value
    return result


def assignment_payload(action, payload):
    target = None if action == "assignment_create" else identifier(payload.get("assignmentId"))
    result = {"assignment_id": target}
    if action != "assignment_create":
        result.update(lifecycle_payload(action.split("_")[1], payload, reason=True))
    if action in {"assignment_create", "assignment_restore"}:
        revision = payload["expectedCategoryRevision"]
        if type(revision) is not int or revision < 1:
            raise OperatorError("Complete the expected category revision.")
        result["expected_category_revision"] = revision
    if action == "assignment_create":
        result["category_id"] = identifier(payload.get("categoryId"))
    return result


def provider_payload(action, payload):
    if action == "create":
        return create_payload(payload)
    if action in {"designate", "patch"}:
        return profile_payload(payload, patch=action == "patch")
    if action.startswith("assignment_"):
        return assignment_payload(action, payload)
    if action in {"archive", "restore"}:
        return lifecycle_payload(action, payload)
    kind, verb = action.rsplit("_", 1)
    target = None if verb == "create" else identifier(payload.get("itemId"))
    if verb == "create" and payload.get("itemId") is not None:
        raise OperatorError("Child creation cannot select an existing record.")
    return {
        "item_id": target,
        "fields": child_fields(kind, payload, patch=verb == "update")
        if verb in {"create", "update"}
        else lifecycle_payload(verb, payload),
    }


def provider_fingerprint(family, action, source, payload, key):
    try:
        if any(
            payload.get(name, False) is None
            for name in (
                "selectionStatus",
                "contacts",
                "services",
                "serviceAreas",
                "workHistory",
                "references",
                "categoryIds",
                "confirmedNewParty",
            )
        ):
            raise OperatorError("Complete the supplied status, boolean and collection fields.")
        model = CategoryCommand if family == "provider_category" else ProviderCommand
        request = (
            category_payload(action, payload, key)
            if family == "provider_category"
            else provider_payload(action, payload)
        )
        return fingerprint(
            model(action, source, payload["expectedRevision"], key, request).request()
        )
    except ProviderError as error:
        raise OperatorError(str(error)) from error


def provider_form_state(connection, binding, state, source, payload):
    if binding.family == "provider_category":
        return (
            "available"
            if binding.action in {"archive", "restore"} or state["status"] == "active"
            else "source_unavailable"
        )
    if binding.action == "designate":
        return "available" if state["status"] == "eligible" else "source_unavailable"
    expected = "archived" if binding.action == "restore" else "active"
    if state["status"] != expected or state["party_status"] != "active":
        return "source_unavailable"
    if "_" not in binding.action:
        return "available"
    return related_provider_state(connection, binding, source, payload)


def related_provider_state(connection, binding, source, payload):
    kind, verb = binding.action.rsplit("_", 1)
    target = payload.get("assignmentId" if kind == "assignment" else "itemId")
    related = binding.related_state(connection, kind, target) if target else None
    if verb != "create" and target:
        if related is None or related["source_id"] != source:
            return "source_unavailable"
        if kind != "assignment" and related["status"] != (
            "archived" if verb == "restore" else "active"
        ):
            return "source_unavailable"
    if kind != "assignment" or verb == "archive":
        return "available"
    category_id = (
        payload.get("categoryId")
        if verb == "create"
        else related["category_id"]
        if related
        else None
    )
    if not category_id:
        return "available"
    category = binding.related_state(connection, "category", category_id)
    if category is None or category["status"] != "active":
        return "source_unavailable"
    return (
        "source_changed"
        if payload.get("expectedCategoryRevision") not in {None, category["revision"]}
        else "available"
    )


def compose_provider_forms():
    parties = SQLitePartyRecoveryReader()
    providers = SQLiteProviderRecoveryReader(parties)
    categories = SQLiteProviderRecoveryReader(parties, category=True)
    result = {}
    kinds = {
        "work_history": "work",
        "reputation_link": "reputation",
        "category_assignment": "assignment",
    }
    for form in PROVIDER_SCHEMAS:
        parts = form.split(".")
        category = parts[1] == "category"
        family = "provider_category" if category else "provider"
        verb = {"add": "create", "assign": "create"}.get(parts[-1], parts[-1])
        action = (
            f"{kinds.get(parts[1], parts[1])}_{verb}"
            if parts[1] in {*CHILD_COMMANDS, *kinds}
            else verb
        )
        reader = (
            categories
            if category
            else SQLiteProviderRecoveryReader(parties, designate=True)
            if action == "designate"
            else providers
        )
        result[form] = RecoveryBinding(
            provider_source_kind(form),
            action,
            family,
            reader,
            lambda source, payload, key, family=family, action=action: provider_fingerprint(
                family, action, source, payload, key
            ),
            family,
            related_state=providers.related_state,
        )
    return result
