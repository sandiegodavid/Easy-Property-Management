"""Portfolio ownership-context commands and rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
import unicodedata
from uuid import uuid4

from app.modules.portfolio.application.ports import PortfolioTransaction, PortfolioUnitOfWork
from app.modules.portfolio.domain.models import Party, Property, PropertyOwnership, Space, active_on, ownership_context


class PortfolioError(RuntimeError):
    pass


class PortfolioNotFoundError(PortfolioError):
    pass


@dataclass(frozen=True)
class OwnershipInput:
    owner_kind: str
    party_id: str | None = None
    inline_party: "PartyCreateCommand | None" = None

    def __post_init__(self) -> None:
        if self.owner_kind not in {"local_operator", "client_owner"}:
            raise PortfolioError("Ownership kind must be local_operator or client_owner.")
        if self.owner_kind == "local_operator" and (self.party_id is not None or self.inline_party is not None):
            raise PortfolioError("Local-operator ownership cannot name a party.")
        if self.owner_kind == "client_owner" and ((self.party_id is None) == (self.inline_party is None)):
            raise PortfolioError("Client-owner ownership requires exactly one saved or inline party.")
        if self.party_id is not None and (not isinstance(self.party_id, str) or not self.party_id.strip()):
            raise PortfolioError("Client-owner ownership requires a nonblank party ID.")
        if self.inline_party is not None and not isinstance(self.inline_party, PartyCreateCommand):
            raise PortfolioError("Inline client owner must be a valid party command.")
        if isinstance(self.party_id, str) and self.party_id != self.party_id.strip():
            object.__setattr__(self, "party_id", self.party_id.strip())


@dataclass(frozen=True)
class PartyCreateCommand:
    party_kind: str
    display_name: str
    email: str | None = None
    phone: str | None = None

    def __post_init__(self) -> None:
        if self.party_kind not in {"individual", "organization"}:
            raise PortfolioError("Party kind must be individual or organization.")
        object.__setattr__(self, "display_name", _required(self.display_name, "Display name", 240))
        object.__setattr__(self, "email", _optional(self.email, "Email", 320))
        object.__setattr__(self, "phone", _optional(self.phone, "Phone", 80))


@dataclass(frozen=True)
class PropertyCreateCommand:
    display_name: str
    address_line_1: str
    city: str
    country_code: str
    property_type: str
    ownerships: tuple[OwnershipInput, ...]
    address_line_2: str | None = None
    region: str | None = None
    postal_code: str | None = None
    notes: str | None = None
    inventory_layout: str | None = None
    spaces: tuple["SpaceCreateCommand", ...] | None = None

    def __post_init__(self) -> None:
        for field, value in _normalize_property_identity(self).items():
            object.__setattr__(self, field, value)
        _validate_ownerships(self.ownerships)
        property_type, layout, spaces = _validate_inventory(
            self.property_type,
            self.inventory_layout,
            self.spaces,
        )
        object.__setattr__(self, "property_type", property_type)
        object.__setattr__(self, "inventory_layout", layout)
        object.__setattr__(self, "spaces", spaces)


@dataclass(frozen=True)
class SpaceCreateCommand:
    display_name: str
    suite_or_floor: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "display_name", _required(self.display_name, "Space name", 120))
        object.__setattr__(self, "suite_or_floor", _optional(self.suite_or_floor, "Suite or floor", 80))
        object.__setattr__(self, "notes", _optional(self.notes, "Space notes", 4000))


@dataclass(frozen=True)
class SpaceUpdateCommand:
    display_name: str
    suite_or_floor: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "display_name", _required(self.display_name, "Space name", 120))
        object.__setattr__(self, "suite_or_floor", _optional(self.suite_or_floor, "Suite or floor", 80))
        object.__setattr__(self, "notes", _optional(self.notes, "Space notes", 4000))


@dataclass(frozen=True)
class PropertyUpdateCommand:
    display_name: str
    address_line_1: str
    city: str
    country_code: str
    address_line_2: str | None = None
    region: str | None = None
    postal_code: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        for field, value in _normalize_property_identity(self).items():
            object.__setattr__(self, field, value)


class PortfolioService:
    def __init__(self, unit_of_work: PortfolioUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def create_party(self, command: PartyCreateCommand) -> Party:
        now, correlation_id = _now(), str(uuid4())
        party = Party(
            id=str(uuid4()),
            party_kind=command.party_kind,
            display_name=command.display_name,
            email=command.email,
            phone=command.phone,
            created_at=now,
            updated_at=now,
            archived_at=None,
        )
        def write(transaction: PortfolioTransaction) -> Party:
            transaction.insert_party(party)
            transaction.record_change(entity_type="party", entity_id=party.id, action="created", before=None,
                                      after=party.to_dict(), reason="party_created", correlation_id=correlation_id)
            return party
        return self.unit_of_work.write(write)

    def create_property(self, command: PropertyCreateCommand) -> Property:
        now, correlation_id = _now(), str(uuid4())
        property = Property(
            id=str(uuid4()),
            display_name=command.display_name,
            address_line_1=command.address_line_1,
            address_line_2=command.address_line_2,
            city=command.city,
            region=command.region,
            postal_code=command.postal_code,
            country_code=command.country_code,
            notes=command.notes,
            status="active",
            created_at=now,
            updated_at=now,
            archived_at=None,
            property_type=command.property_type,
            inventory_layout=command.inventory_layout,
        )
        def write(transaction: PortfolioTransaction) -> Property:
            ownership_inputs = self._resolve_ownership_inputs(transaction, command.ownerships, correlation_id, now)
            transaction.insert_property(property)
            transaction.record_change(entity_type="property", entity_id=property.id, action="created", before=None,
                                      after=property.to_dict(), reason="property_created", correlation_id=correlation_id)
            for ownership in self._new_ownerships(property.id, ownership_inputs, date.today().isoformat(), now):
                transaction.insert_ownership(ownership)
                transaction.record_change(entity_type="property_ownership", entity_id=ownership.id, action="created",
                                          before=None, after=ownership.to_dict(), reason="ownership_created",
                                          correlation_id=correlation_id)
            for space in self._new_spaces(property.id, command, now):
                transaction.insert_space(space)
                transaction.record_change(
                    entity_type="space",
                    entity_id=space.id,
                    action="created",
                    before=None,
                    after=space.to_dict(),
                    reason="space_created",
                    correlation_id=correlation_id,
                )
            return property
        return self.unit_of_work.write(write)

    def get_property(self, property_id: str) -> dict[str, object]:
        property = self.unit_of_work.get_property(property_id)
        if property is None: raise PortfolioNotFoundError("Property was not found.")
        ownerships = self.unit_of_work.ownerships(property_id)
        parties = self.unit_of_work.parties_for_ownerships(ownerships)
        spaces = self.unit_of_work.spaces(property_id)
        return self._property_view(property, ownerships, parties, spaces)

    def list_properties(self, *, status: str | None = None, ownership_context_filter: str | None = None) -> list[dict[str, object]]:
        if status is not None and status not in {"active", "archived"}: raise PortfolioError("Property status is invalid.")
        if ownership_context_filter is not None and ownership_context_filter not in {"self_owned", "managed_for_owner", "mixed"}:
            raise PortfolioError("Ownership context is invalid.")
        records = [
            self._property_view(property, ownerships, parties, spaces)
            for property, ownerships, parties, spaces in self.unit_of_work.property_views(status=status)
        ]
        return [record for record in records if ownership_context_filter is None or record["ownershipContext"] == ownership_context_filter]

    def add_space(self, property_id: str, command: SpaceCreateCommand) -> Space:
        correlation_id, now = str(uuid4()), _now()

        def write(transaction: PortfolioTransaction) -> Space:
            property = transaction.get_property(property_id)
            if property is None:
                raise KeyError
            if property.status != "active" or property.inventory_layout != "office_suites":
                raise PortfolioError("Spaces can only be added to an active office-suites property.")
            normalized_name = _space_name_key(command.display_name)
            self._ensure_space_name_available(transaction, property_id, normalized_name)
            space = Space(
                id=str(uuid4()), property_id=property_id, space_kind="office_suite",
                display_name=command.display_name, normalized_name=normalized_name,
                suite_or_floor=command.suite_or_floor,
                notes=command.notes, status="active", created_at=now, updated_at=now,
                archived_at=None, archived_by_property_operation_id=None,
            )
            transaction.insert_space(space)
            transaction.record_change(entity_type="space", entity_id=space.id, action="created",
                                      before=None, after=space.to_dict(), reason="space_created",
                                      correlation_id=correlation_id)
            return space

        return self._not_found_from_key_error(write)

    def archive_space(self, space_id: str, *, confirmed: bool) -> Space:
        if confirmed is not True:
            raise PortfolioError("Archiving a space requires explicit confirmation.")
        correlation_id, now = str(uuid4()), _now()

        def write(transaction: PortfolioTransaction) -> Space:
            current = transaction.get_space(space_id)
            if current is None:
                raise KeyError
            if current.status == "archived":
                return current
            property = transaction.get_property(current.property_id)
            if property is None or property.status != "active":
                raise PortfolioError("A space can only be archived under an active property.")
            active_spaces = transaction.spaces(current.property_id, active_only=True)
            if len(active_spaces) <= 1:
                raise PortfolioError("Archive the property and its last active space together.")
            archived = replace(
                current,
                status="archived",
                updated_at=now,
                archived_at=now,
                archived_by_property_operation_id=None,
            )
            transaction.replace_space(archived)
            transaction.record_change(entity_type="space", entity_id=space_id, action="status_changed",
                                      before=current.to_dict(), after=archived.to_dict(), reason="space_archived",
                                      correlation_id=correlation_id)
            return archived

        return self._not_found_from_key_error(write, label="Space")

    def patch_space(self, space_id: str, changes: dict[str, object]) -> Space:
        allowed = {"displayName", "suiteOrFloor", "notes"}
        if not changes or set(changes) - allowed:
            raise PortfolioError("A space patch requires supported fields.")
        correlation_id, now = str(uuid4()), _now()

        def write(transaction: PortfolioTransaction) -> Space:
            current = transaction.get_space(space_id)
            if current is None:
                raise KeyError
            property = transaction.get_property(current.property_id)
            if property is None or property.status != "active":
                raise PortfolioError("A space can only be edited under an active property.")
            command = SpaceUpdateCommand(
                display_name=changes.get("displayName", current.display_name),
                suite_or_floor=changes.get("suiteOrFloor", current.suite_or_floor),
                notes=changes.get("notes", current.notes),
            )
            normalized_name = _space_name_key(command.display_name)
            if current.status == "active":
                self._ensure_space_name_available(
                    transaction,
                    current.property_id,
                    normalized_name,
                    exclude_space_id=current.id,
                )
            updated = replace(
                current,
                display_name=command.display_name,
                normalized_name=normalized_name,
                suite_or_floor=command.suite_or_floor,
                notes=command.notes,
                updated_at=now,
            )
            transaction.replace_space(updated)
            transaction.record_change(
                entity_type="space", entity_id=space_id, action="updated",
                before=current.to_dict(), after=updated.to_dict(), reason="space_updated",
                correlation_id=correlation_id,
            )
            return updated

        return self._not_found_from_key_error(write, label="Space")

    def restore_space(self, space_id: str) -> Space:
        correlation_id, now = str(uuid4()), _now()

        def write(transaction: PortfolioTransaction) -> Space:
            current = transaction.get_space(space_id)
            if current is None:
                raise KeyError
            if current.status == "active":
                return current
            property = transaction.get_property(current.property_id)
            if property is None or property.status != "active":
                raise PortfolioError("A space cannot be restored while its property is archived.")
            if property.inventory_layout != "office_suites":
                raise PortfolioError("Whole-property spaces are restored with their property.")
            self._ensure_space_name_available(
                transaction,
                current.property_id,
                current.normalized_name,
                exclude_space_id=current.id,
            )
            restored = replace(
                current,
                status="active",
                updated_at=now,
                archived_at=None,
                archived_by_property_operation_id=None,
            )
            transaction.replace_space(restored)
            transaction.record_change(
                entity_type="space", entity_id=space_id, action="status_changed",
                before=current.to_dict(), after=restored.to_dict(), reason="space_restored",
                correlation_id=correlation_id,
            )
            return restored

        return self._not_found_from_key_error(write, label="Space")

    def patch_property(self, property_id: str, changes: dict[str, object]) -> Property:
        allowed = {"displayName", "addressLine1", "addressLine2", "city", "region", "postalCode", "countryCode", "notes"}
        if not changes or set(changes) - allowed: raise PortfolioError("A property patch requires supported fields.")
        correlation_id, now = str(uuid4()), _now()
        def write(transaction: PortfolioTransaction) -> Property:
            current = transaction.get_property(property_id)
            if current is None: raise KeyError
            values = {
                "display_name": changes.get("displayName", current.display_name),
                "address_line_1": changes.get("addressLine1", current.address_line_1),
                "address_line_2": changes.get("addressLine2", current.address_line_2),
                "city": changes.get("city", current.city),
                "region": changes.get("region", current.region),
                "postal_code": changes.get("postalCode", current.postal_code),
                "country_code": changes.get("countryCode", current.country_code),
                "notes": changes.get("notes", current.notes),
            }
            command = PropertyUpdateCommand(**values)
            updated = replace(
                current,
                display_name=command.display_name,
                address_line_1=command.address_line_1,
                address_line_2=command.address_line_2,
                city=command.city,
                region=command.region,
                postal_code=command.postal_code,
                country_code=command.country_code,
                notes=command.notes,
                updated_at=now,
            )
            transaction.replace_property(updated)
            transaction.record_change(
                entity_type="property", entity_id=updated.id, action="updated", before=current.to_dict(),
                after=updated.to_dict(), reason="property_updated", correlation_id=correlation_id,
            )
            return updated
        return self._not_found_from_key_error(write)

    def archive_property(self, property_id: str, *, confirmed: bool) -> Property:
        if confirmed is not True: raise PortfolioError("Archiving a property requires explicit confirmation.")
        return self._change_property_status(property_id, "archived")

    def restore_property(self, property_id: str) -> Property:
        return self._change_property_status(property_id, "active")

    def _change_property_status(self, property_id: str, status: str) -> Property:
        correlation_id, now = str(uuid4()), _now()
        def write(transaction: PortfolioTransaction) -> Property:
            current = transaction.get_property(property_id)
            if current is None: raise KeyError
            if current.status == status: return current
            if status == "active" and not transaction.ownerships_at(property_id, date.today().isoformat()):
                raise PortfolioError("An active property requires an active ownership relationship.")
            updated = replace(
                current,
                status=status,
                updated_at=now,
                archived_at=now if status == "archived" else None,
            )
            transaction.replace_property(updated)
            if status == "archived":
                for space in transaction.spaces(property_id, active_only=True):
                    archived_space = replace(
                        space,
                        status="archived",
                        updated_at=now,
                        archived_at=now,
                        archived_by_property_operation_id=correlation_id,
                    )
                    transaction.replace_space(archived_space)
                    transaction.record_change(entity_type="space", entity_id=space.id, action="status_changed",
                                              before=space.to_dict(), after=archived_space.to_dict(),
                                              reason="property_archived", correlation_id=correlation_id)
            if status == "active":
                for space in transaction.spaces(property_id):
                    if space.archived_by_property_operation_id is not None:
                        self._ensure_space_name_available(
                            transaction,
                            property_id,
                            space.normalized_name,
                            exclude_space_id=space.id,
                        )
                        restored_space = replace(
                            space,
                            status="active",
                            updated_at=now,
                            archived_at=None,
                            archived_by_property_operation_id=None,
                        )
                        transaction.replace_space(restored_space)
                        transaction.record_change(entity_type="space", entity_id=space.id, action="status_changed",
                                                  before=space.to_dict(), after=restored_space.to_dict(),
                                                  reason="property_restored", correlation_id=correlation_id)
            transaction.record_change(entity_type="property", entity_id=updated.id, action="status_changed",
                                      before=current.to_dict(), after=updated.to_dict(), reason="property_status_changed",
                                      correlation_id=correlation_id)
            return updated
        return self._not_found_from_key_error(write)

    def archive_party(self, party_id: str, *, confirmed: bool) -> Party:
        if confirmed is not True: raise PortfolioError("Archiving a party requires explicit confirmation.")
        correlation_id, now = str(uuid4()), _now()
        def write(transaction: PortfolioTransaction) -> Party:
            current = transaction.get_party(party_id)
            if current is None: raise KeyError
            if current.archived_at is not None: return current
            if transaction.open_ownerships_for_party(party_id, date.today().isoformat()):
                raise PortfolioError("A party with a current or scheduled property ownership cannot be archived.")
            updated = replace(current, updated_at=now, archived_at=now)
            transaction.replace_party(updated)
            transaction.record_change(entity_type="party", entity_id=party_id, action="status_changed",
                                      before=current.to_dict(), after=updated.to_dict(), reason="party_archived",
                                      correlation_id=correlation_id)
            return updated
        return self._not_found_from_key_error(write, label="Party")

    def restore_party(self, party_id: str) -> Party:
        correlation_id, now = str(uuid4()), _now()
        def write(transaction: PortfolioTransaction) -> Party:
            current = transaction.get_party(party_id)
            if current is None: raise KeyError
            if current.archived_at is None: return current
            updated = replace(current, updated_at=now, archived_at=None)
            transaction.replace_party(updated)
            transaction.record_change(entity_type="party", entity_id=party_id, action="status_changed",
                                      before=current.to_dict(), after=updated.to_dict(), reason="party_restored",
                                      correlation_id=correlation_id)
            return updated
        return self._not_found_from_key_error(write, label="Party")

    def replace_ownerships(self, property_id: str, ownerships: tuple[OwnershipInput, ...], effective_on: str) -> dict[str, object]:
        _validate_ownerships(ownerships); effective = _date(effective_on); correlation_id, now = str(uuid4()), _now()
        def write(transaction: PortfolioTransaction) -> list[PropertyOwnership]:
            property = transaction.get_property(property_id)
            if property is None: raise KeyError
            if property.status != "active": raise PortfolioError("Ownership can only be changed for an active property.")
            if transaction.future_ownerships(property_id, effective):
                raise PortfolioError("Ownership changes cannot be scheduled before an existing future change.")
            resolved_inputs = self._resolve_ownership_inputs(transaction, ownerships, correlation_id, now)
            existing = transaction.ownerships_at(property_id, effective)
            if effective > date.today().isoformat() and any(
                item.starts_on == effective for item in existing
            ):
                raise PortfolioError("Ownership changes cannot replace an existing change on the same date.")
            prior_snapshot = [item.to_dict() for item in existing]
            for item in existing:
                if effective < item.starts_on:
                    raise PortfolioError("Ownership effective date cannot precede an active relationship.")
                ended = replace(item, ends_on=effective, ended_at=now)
                transaction.end_ownership(ended)
                transaction.record_change(entity_type="property_ownership", entity_id=item.id, action="ended",
                                          before=item.to_dict(), after=ended.to_dict(), reason="ownership_replaced",
                                          correlation_id=correlation_id)
            created = self._new_ownerships(property_id, resolved_inputs, effective, now)
            for item in created:
                transaction.insert_ownership(item)
                transaction.record_change(entity_type="property_ownership", entity_id=item.id, action="created",
                                          before=None, after=item.to_dict(), reason="ownership_replaced",
                                          correlation_id=correlation_id)
            transaction.record_change(entity_type="property", entity_id=property_id, action="ownership_changed",
                                      before={"ownerships": prior_snapshot, "ownershipContext": ownership_context(existing)},
                                      after={"effectiveOn": effective, "ownerships": [item.to_dict() for item in created],
                                             "ownershipContext": ownership_context(created)},
                                      reason="ownership_replaced", correlation_id=correlation_id)
            return created
        self._not_found_from_key_error(write)
        return self.get_property(property_id)

    def list_parties(self, *, active_only: bool = False) -> list[dict[str, object]]:
        return [party.to_dict() for party in self.unit_of_work.parties(active_only=active_only)]

    def _not_found_from_key_error(self, operation, *, label: str = "Property"):
        try: return self.unit_of_work.write(operation)
        except KeyError as error: raise PortfolioNotFoundError(f"{label} was not found.") from error

    @staticmethod
    def _new_ownerships(property_id: str, inputs: tuple[OwnershipInput, ...], starts_on: str, now: str) -> list[PropertyOwnership]:
        return [
            PropertyOwnership(
                id=str(uuid4()),
                property_id=property_id,
                owner_kind=item.owner_kind,
                party_id=item.party_id,
                starts_on=starts_on,
                ends_on=None,
                created_at=now,
                ended_at=None,
            )
            for item in inputs
        ]

    @staticmethod
    def _new_spaces(property_id: str, command: PropertyCreateCommand, now: str) -> list[Space]:
        space_kind = "whole_home" if command.inventory_layout == "single_space" else (
            "whole_office" if command.inventory_layout == "whole_office" else "office_suite"
        )
        return [
            Space(
                id=str(uuid4()), property_id=property_id, space_kind=space_kind,
                display_name=item.display_name, normalized_name=_space_name_key(item.display_name),
                suite_or_floor=item.suite_or_floor,
                notes=item.notes, status="active", created_at=now, updated_at=now,
                archived_at=None, archived_by_property_operation_id=None,
            )
            for item in command.spaces or ()
        ]

    @staticmethod
    def _ensure_space_name_available(
        transaction: PortfolioTransaction,
        property_id: str,
        normalized_name: str,
        *,
        exclude_space_id: str | None = None,
    ) -> None:
        if any(
            item.normalized_name == normalized_name and item.id != exclude_space_id
            for item in transaction.spaces(property_id, active_only=True)
        ):
            raise PortfolioError("An active space with this name already exists in the property.")

    @staticmethod
    def _resolve_ownership_inputs(transaction: PortfolioTransaction, ownerships: tuple[OwnershipInput, ...], correlation_id: str, now: str) -> tuple[OwnershipInput, ...]:
        resolved = []
        for item in ownerships:
            if item.inline_party is not None:
                party = Party(
                    id=str(uuid4()),
                    party_kind=item.inline_party.party_kind,
                    display_name=item.inline_party.display_name,
                    email=item.inline_party.email,
                    phone=item.inline_party.phone,
                    created_at=now,
                    updated_at=now,
                    archived_at=None,
                )
                transaction.insert_party(party)
                transaction.record_change(entity_type="party", entity_id=party.id, action="created", before=None,
                                          after=party.to_dict(), reason="party_created", correlation_id=correlation_id)
                resolved.append(replace(item, party_id=party.id, inline_party=None))
            elif item.party_id is not None:
                party = transaction.get_party(item.party_id)
                if party is None or party.archived_at is not None: raise PortfolioError("Each client owner must be an active saved party.")
                resolved.append(item)
            else:
                resolved.append(item)
        return tuple(resolved)

    @staticmethod
    def _property_view(property: Property, ownerships: list[PropertyOwnership], parties: dict[str, Party], spaces: list[Space] | None = None) -> dict[str, object]:
        current = [item for item in ownerships if active_on(item, date.today())]
        return {**property.to_dict(), "ownershipContext": ownership_context(current),
                "ownerships": [item.to_dict(parties.get(item.party_id)) for item in current],
                "spaces": [item.to_dict() for item in spaces or []]}


def _required(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not (result := value.strip()) or len(result) > limit: raise PortfolioError(f"{label} must contain 1 to {limit} characters.")
    return result


def _optional(value: object, label: str, limit: int) -> str | None:
    if value is None: return None
    return _required(value, label, limit)


def _normalize_property_identity(command: object) -> dict[str, str | None]:
    country_value = getattr(command, "country_code")
    if (
        not isinstance(country_value, str)
        or len((country := country_value.strip())) != 2
        or not country.isalpha()
    ):
        raise PortfolioError("Country code must be a two-letter code.")
    return {
        "display_name": _required(getattr(command, "display_name"), "Property display name", 240),
        "address_line_1": _required(getattr(command, "address_line_1"), "Address line 1", 240),
        "address_line_2": _optional(getattr(command, "address_line_2"), "Address line 2", 240),
        "city": _required(getattr(command, "city"), "City", 120),
        "region": _optional(getattr(command, "region"), "Region", 120),
        "postal_code": _optional(getattr(command, "postal_code"), "Postal code", 40),
        "country_code": country.upper(),
        "notes": _optional(getattr(command, "notes"), "Notes", 4000),
    }


def _space_name_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _validate_ownerships(items: tuple[OwnershipInput, ...]) -> None:
    if not isinstance(items, tuple) or not items: raise PortfolioError("At least one ownership relationship is required.")
    if not all(isinstance(item, OwnershipInput) for item in items):
        raise PortfolioError("Each ownership relationship must be a valid ownership input.")
    local = [item for item in items if item.owner_kind == "local_operator"]
    clients = [item.party_id for item in items if item.owner_kind == "client_owner" and item.party_id is not None]
    if len(local) > 1 or len(set(clients)) != len(clients): raise PortfolioError("Ownership relationships must not contain duplicates.")


def _validate_inventory(
    property_type: object,
    inventory_layout: object,
    spaces: object,
) -> tuple[str, str, tuple[SpaceCreateCommand, ...]]:
    if property_type not in {"single_family_home", "condo", "townhome", "office"}:
        raise PortfolioError("Property type must be a supported residential or office type.")
    if inventory_layout is None:
        inventory_layout = "whole_office" if property_type == "office" else "single_space"
    if property_type == "office":
        allowed = {"whole_office", "office_suites"}
    else:
        allowed = {"single_space"}
    if inventory_layout not in allowed:
        raise PortfolioError("Property type and inventory layout are incompatible.")
    if spaces is None:
        if inventory_layout == "single_space":
            spaces = (SpaceCreateCommand("Whole home"),)
        elif inventory_layout == "whole_office":
            spaces = (SpaceCreateCommand("Whole office"),)
        else:
            raise PortfolioError("An office-suites property requires one or more suites.")
    if not isinstance(spaces, tuple) or not spaces or not all(isinstance(item, SpaceCreateCommand) for item in spaces):
        raise PortfolioError("Inventory spaces must be a nonempty set of valid space commands.")
    names = [_space_name_key(item.display_name) for item in spaces]
    if len(set(names)) != len(names):
        raise PortfolioError("Active space names must be unique within a property.")
    if inventory_layout != "office_suites" and len(spaces) != 1:
        raise PortfolioError("This property layout has exactly one rentable space.")
    return property_type, inventory_layout, spaces


def _date(value: object) -> str:
    if not isinstance(value, str): raise PortfolioError("Effective date is required.")
    try: return date.fromisoformat(value).isoformat()
    except ValueError as error: raise PortfolioError("Effective date must be ISO-8601 date text.") from error


def _now() -> str:
    return datetime.now(UTC).isoformat()
