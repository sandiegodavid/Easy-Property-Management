"""Portfolio inventory normalization and explicit read-only OPS bindings."""

from dataclasses import asdict

from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError
from app.modules.portfolio.application.inventory_commands import (
    InventoryCommand,
    fingerprint,
    address_time_zone_changed,
)
from app.modules.portfolio.application.service import (
    AvailabilityCommand,
    OccupancyCommand,
    OwnershipInput,
    PartyCreateCommand,
    PropertyCreateCommand,
    PropertyUpdateCommand,
    PortfolioError,
    SpaceCreateCommand,
)
from app.modules.portfolio.infrastructure.inventory_recovery_reader import (
    SQLiteInventoryRecoveryReader,
)
from app.platform.command_recovery import CommandRecoveryReader
from app.modules.parties.application.service import ContactMethodCommand, PartyValidationError
from app.modules.portfolio.domain.models import ownership_share_basis_points
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver


def inventory_preflight(connection, source, payload):
    """Resolve address evidence without creating or changing a property."""
    if source is None:
        address = payload
    else:
        changes = payload.get("changes", {})
        if not set(changes) & {
            "addressLine1",
            "city",
            "region",
            "postalCode",
            "countryCode",
            "timeZone",
        }:
            return
        state = SQLiteInventoryRecoveryReader().state(connection, source)
        address = {
            "addressLine1": state["address_line_1"],
            "city": state["city"],
            "region": state["region"],
            "postalCode": state["postal_code"],
            "countryCode": state["country_code"],
            **changes,
        }
    try:
        if source is not None and "timeZone" not in changes:
            proposed = PropertyUpdateCommand(
                display_name="Time-zone preflight",
                address_line_1=address["addressLine1"],
                city=address["city"],
                region=address.get("region"),
                postal_code=address.get("postalCode"),
                country_code=address["countryCode"],
            )
            if not address_time_zone_changed(state, asdict(proposed)):
                return
        if address.get("timeZone"):
            ZoneInfo(address["timeZone"])
            return
        BundledAddressTimeZoneResolver().resolve(
            address_line_1=address["addressLine1"],
            city=address["city"],
            region=address.get("region"),
            postal_code=address.get("postalCode"),
            country_code=address["countryCode"],
        )
    except (PortfolioError, ZoneInfoNotFoundError, ValueError) as error:
        raise OperatorError(
            "We couldn't determine this property's time zone. Check the address or choose "
            "a time zone manually; the bundled lookup has limited coverage."
        ) from error


def owners(items):
    if not items:
        raise OperatorError("Complete at least one ownership.")
    return tuple(
        OwnershipInput(
            item["ownerKind"],
            item.get("partyId"),
            PartyCreateCommand(item["inlineParty"]["partyKind"], item["inlineParty"]["displayName"])
            if item.get("inlineParty") is not None
            else None,
            tuple(
                ContactMethodCommand(
                    contact["methodKind"],
                    contact["value"],
                    contact.get("extension"),
                    contact.get("label"),
                    contact.get("isPrimary"),
                )
                for contact in (item.get("inlineParty") or {}).get("contacts", [])
            ),
            share_basis_points=ownership_share_basis_points(item.get("sharePercent")),
        )
        for item in items
    )


def initial_space(payload):
    occupancy, availability = payload.get("occupancy"), payload.get("availability")
    return SpaceCreateCommand(
        payload["displayName"],
        payload.get("suiteOrFloor"),
        payload.get("notes"),
        OccupancyCommand(
            occupancy["occupancyStatus"], occupancy["effectiveOn"], occupancy.get("note")
        )
        if occupancy is not None
        else None,
        AvailabilityCommand(
            availability["availabilityStatus"],
            availability.get("availableOn"),
            availability.get("note"),
        )
        if availability is not None
        else None,
    )


def inventory_fingerprint(action, source_id, payload, key):
    try:
        return _inventory_fingerprint(action, source_id, payload, key)
    except (PortfolioError, PartyValidationError, KeyError, TypeError, ValueError) as error:
        raise OperatorError("Complete a valid Portfolio inventory command.") from error


def property_command(payload):
    return PropertyCreateCommand(
        payload["displayName"],
        payload["addressLine1"],
        payload["city"],
        payload["countryCode"],
        payload["propertyType"],
        owners(payload["ownerships"]),
        payload.get("addressLine2"),
        payload.get("region"),
        payload.get("postalCode"),
        payload.get("notes"),
        payload.get("inventoryLayout"),
        tuple(initial_space(item) for item in payload["spaces"])
        if payload.get("spaces") is not None
        else None,
        time_zone=payload.get("timeZone"),
    )


def archival_payload(payload):
    if payload.get("confirmed") is not True:
        raise OperatorError("Confirm archival before starting an attempt.")
    return {"confirmed": True}


def _inventory_fingerprint(action, source_id, payload, key):
    expected = payload.get("expectedPropertyRevision")
    if type(expected) is not int or expected < 0:
        raise OperatorError("Complete the expected Property revision.")
    target = source_id
    if action == "create_property":
        if expected != 0:
            raise OperatorError("Property creation requires revision zero.")
        body = asdict(property_command(payload))
    elif action == "add_space":
        body = asdict(initial_space(payload))
    elif action == "replace_ownerships":
        body = {
            "ownerships": [asdict(item) for item in owners(payload["ownerships"])],
            "effectiveOn": payload["effectiveOn"],
        }
    elif action.startswith("patch_"):
        body = payload.get("changes")
        if not body:
            raise OperatorError("Complete at least one patch field.")
    elif action.startswith("archive_"):
        body = archival_payload(payload)
    else:
        body = {}
    if action in {"patch_space", "archive_space", "restore_space"}:
        target = payload["spaceId"]
    return fingerprint(InventoryCommand(action, target, expected, key, body).request_json())


def inventory_form_state(connection, binding, state, source_id, payload):
    restoring = binding.action == "restore_property"
    if state["status"] != ("archived" if restoring else "active"):
        return "source_unavailable"
    if binding.action == "add_space" and state["inventory_layout"] != "office_suites":
        return "source_unavailable"
    if binding.action in {"patch_space", "archive_space", "restore_space"}:
        if payload.get("spaceId") is None:
            return "available"  # incomplete save only
        child = binding.reader.related_state(connection, "space", payload["spaceId"])
        if child is None or child["source_id"] != source_id:
            return "source_unavailable"
        expected = "archived" if binding.action == "restore_space" else "active"
        if child["status"] != expected:
            return "source_unavailable"
    return "available"


def compose_inventory_forms():
    reader: CommandRecoveryReader = SQLiteInventoryRecoveryReader()
    actions = {
        "portfolio.property.create": "create_property",
        "portfolio.property.patch": "patch_property",
        "portfolio.property.archive": "archive_property",
        "portfolio.property.restore": "restore_property",
        "portfolio.ownerships.replace": "replace_ownerships",
        "portfolio.space.create": "add_space",
        "portfolio.space.patch": "patch_space",
        "portfolio.space.archive": "archive_space",
        "portfolio.space.restore": "restore_space",
    }
    return {
        form: RecoveryBinding(
            None if action == "create_property" else "property",
            action,
            "inventory",
            reader,
            lambda source, payload, key, action=action: inventory_fingerprint(
                action, source, payload, key
            ),
            "property",
            preflight=inventory_preflight
            if action in {"create_property", "patch_property"}
            else None,
        )
        for form, action in actions.items()
    }
