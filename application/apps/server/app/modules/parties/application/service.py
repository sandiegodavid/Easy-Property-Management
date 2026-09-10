"""Reusable creation boundary for shared party identities."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.modules.parties.application.ports import PartyTransaction, PartyUnitOfWork
from app.modules.parties.domain.contact_values import normalize_contact_value
from app.modules.parties.domain.models import Party, PartyContactMethod


class PartyValidationError(ValueError):
    pass


class PartyNotFoundError(PartyValidationError):
    pass


class PartyConflictError(PartyValidationError):
    pass


@dataclass(frozen=True)
class PartyCreateCommand:
    party_kind: str
    display_name: str

    def __post_init__(self) -> None:
        if self.party_kind not in {"individual", "organization"}:
            raise PartyValidationError("Party kind is invalid.")
        object.__setattr__(self, "display_name", _required(self.display_name, "Display name", 240))


class PartyFactory(Protocol):
    def create(self, command: PartyCreateCommand, timestamp: str) -> Party: ...


class SharedPartyFactory:
    def create(self, command: PartyCreateCommand, timestamp: str) -> Party:
        if not isinstance(command, PartyCreateCommand):
            raise PartyValidationError("A valid party creation command is required.")
        return Party(
            id=str(uuid4()),
            party_kind=command.party_kind,
            display_name=command.display_name,
            created_at=timestamp,
            updated_at=timestamp,
            archived_at=None,
        )


@dataclass(frozen=True)
class ContactMethodCommand:
    method_kind: str
    value: str
    extension: str | None = None
    label: str | None = None
    normalized_value: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            normalized, extension, display = normalize_contact_value(
                self.method_kind,
                self.value,
                self.extension,
            )
        except ValueError as error:
            raise PartyValidationError(str(error)) from error
        object.__setattr__(self, "value", display)
        object.__setattr__(self, "extension", extension)
        object.__setattr__(self, "normalized_value", normalized)
        object.__setattr__(self, "label", _optional(self.label, "Contact label", 80))


@dataclass(frozen=True)
class ContactReferenceResolution:
    role: str
    role_record_id: str
    replacement_contact_method_id: str | None = None
    clear: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not (role := self.role.strip()):
            raise PartyValidationError("Reference resolution role must be nonblank.")
        if not isinstance(self.role_record_id, str) or not (record_id := self.role_record_id.strip()):
            raise PartyValidationError("Reference resolution record ID must be nonblank.")
        if not isinstance(self.clear, bool):
            raise PartyValidationError("Reference resolution clear must be a boolean.")
        replacement = self.replacement_contact_method_id
        if replacement is not None:
            if not isinstance(replacement, str) or not (replacement := replacement.strip()):
                raise PartyValidationError("Replacement contact method ID must be nonblank.")
        if (replacement is None) == (self.clear is False):
            raise PartyValidationError("Each reference resolution must choose exactly one action.")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "role_record_id", record_id)
        object.__setattr__(self, "replacement_contact_method_id", replacement)


class PartyContactService:
    def __init__(self, unit_of_work: PartyUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def list(self, party_id: str) -> list[dict[str, object]]:
        record = self.unit_of_work.methods(party_id)
        if record is None:
            raise PartyNotFoundError("Party was not found.")
        return [item.to_dict() for item in record[1]]

    def add(self, party_id: str, command: ContactMethodCommand) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction) -> PartyContactMethod:
            party = tx.party(party_id)
            if party is None:
                raise KeyError
            if party.archived_at is not None:
                raise PartyConflictError("An archived party cannot receive contact methods.")
            item = _contact(party_id, command, now)
            _unique([*tx.methods(party_id), item])
            tx.insert_method(item)
            tx.record_change(entity_type="party_contact_method", entity_id=item.id, action="created",
                             before=None, after=item.to_audit_dict(), reason="party_contact_created",
                             correlation_id=correlation)
            return item

        return self._write(write).to_dict()

    def update(self, party_id: str, method_id: str, command: ContactMethodCommand) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction) -> PartyContactMethod:
            party = tx.party(party_id)
            if party is None:
                raise KeyError
            if party.archived_at is not None:
                raise PartyConflictError("Restore the party before editing contact methods.")
            methods = tx.methods(party_id)
            current = _required_contact(methods, method_id)
            if current.status != "active":
                raise PartyConflictError("An archived contact method cannot be edited.")
            updated = replace(current, method_kind=command.method_kind, display_value=command.value,
                              normalized_value=command.normalized_value, extension=command.extension,
                              label=command.label, updated_at=now)
            _unique([item for item in methods if item.id != method_id] + [updated])
            tx.replace_method(updated)
            tx.record_change(entity_type="party_contact_method", entity_id=updated.id, action="updated",
                             before=current.to_audit_dict(), after=updated.to_audit_dict(),
                             reason="party_contact_updated", correlation_id=correlation)
            return updated

        return self._write(write).to_dict()

    def archive(self, party_id: str, method_id: str, *, confirmed: bool,
                reference_resolutions: tuple[ContactReferenceResolution, ...] = ()) -> dict[str, object]:
        if confirmed is not True:
            raise PartyValidationError("Archiving a contact method requires explicit confirmation.")
        if not isinstance(reference_resolutions, tuple) or not all(
            isinstance(item, ContactReferenceResolution) for item in reference_resolutions
        ):
            raise PartyValidationError("Reference resolutions must be valid resolution commands.")
        keys = [(item.role, item.role_record_id) for item in reference_resolutions]
        if len(keys) != len(set(keys)):
            raise PartyValidationError("Reference resolutions must not repeat a role record.")
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction) -> PartyContactMethod:
            if tx.party(party_id) is None:
                raise KeyError
            current = _required_contact(tx.methods(party_id), method_id)
            if current.status != "active":
                raise PartyConflictError("Contact method is already archived.")
            methods = tx.methods(party_id)
            for resolution in reference_resolutions:
                if resolution.replacement_contact_method_id is not None and not any(
                    item.id == resolution.replacement_contact_method_id
                    and item.id != method_id
                    and item.status == "active"
                    for item in methods
                ):
                    raise PartyValidationError(
                        "Replacement contact method must be active and belong to this party."
                    )
            consumed = tx.resolve_contact_references(
                party_id, method_id, reference_resolutions, now, correlation
            )
            if set(consumed) != set(reference_resolutions):
                raise PartyValidationError("Reference resolutions include an unknown or unused role reference.")
            updated = replace(current, status="archived", archived_at=now, updated_at=now)
            tx.replace_method(updated)
            tx.record_change(entity_type="party_contact_method", entity_id=updated.id, action="archived",
                             before=current.to_audit_dict(), after=updated.to_audit_dict(),
                             reason="party_contact_archived", correlation_id=correlation)
            return updated

        return self._write(write).to_dict()

    def restore(self, party_id: str, method_id: str) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction) -> PartyContactMethod:
            party = tx.party(party_id)
            if party is None:
                raise KeyError
            if party.archived_at is not None:
                raise PartyConflictError("Restore the party before restoring contact methods.")
            methods = tx.methods(party_id)
            current = _required_contact(methods, method_id)
            if current.status != "archived":
                raise PartyConflictError("Contact method is already active.")
            updated = replace(current, status="active", archived_at=None, updated_at=now)
            _unique([item for item in methods if item.id != method_id] + [updated])
            tx.replace_method(updated)
            tx.record_change(entity_type="party_contact_method", entity_id=updated.id, action="restored",
                             before=current.to_audit_dict(), after=updated.to_audit_dict(),
                             reason="party_contact_restored", correlation_id=correlation)
            return updated

        return self._write(write).to_dict()

    def _write(self, operation):
        try:
            return self.unit_of_work.write(operation)
        except KeyError as error:
            raise PartyNotFoundError("Party or contact method was not found.") from error


def _contact(party_id: str, command: ContactMethodCommand, now: str) -> PartyContactMethod:
    return PartyContactMethod(id=str(uuid4()), party_id=party_id, method_kind=command.method_kind,
                              display_value=command.value, normalized_value=command.normalized_value,
                              extension=command.extension, label=command.label, status="active",
                              created_at=now, updated_at=now, archived_at=None)


def _unique(methods: list[PartyContactMethod]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for item in methods:
        if item.status != "active":
            continue
        key = (item.method_kind, item.normalized_value, item.extension or "")
        if key in seen:
            raise PartyConflictError("Active party contact methods must be unique.")
        seen.add(key)


def _required_contact(methods: list[PartyContactMethod], method_id: str) -> PartyContactMethod:
    for item in methods:
        if item.id == method_id:
            return item
    raise KeyError


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not (text := value.strip()) or len(text) > limit:
        raise PartyValidationError(f"{label} must contain 1 to {limit} characters.")
    return text


def _optional(value: object, label: str, limit: int) -> str | None:
    if value is None:
        return None
    return _required(value, label, limit)
