"""Reusable creation boundary for shared party identities."""

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.modules.parties.application.ports import (
    PartyReadOperations,
    PartyRoleSummaryReader,
    PartyTransaction,
    PartyUnitOfWork,
)
from app.modules.parties.domain.contact_values import normalize_contact_value
from app.modules.parties.domain.models import Party, PartyContactMethod
from app.modules.parties.application.identity_commands import identifier
from app.modules.parties.application.errors import (
    PartyValidationError,
    PartyConflictError,
    PartyNotFoundError,
)
from app.modules.parties.application.command_execution import (
    command_identity,
    start_command,
    finish_command,
    recover_command,
)


class PossibleDuplicatePartyError(PartyConflictError):
    def __init__(self, candidate_party_ids: list[str]) -> None:
        super().__init__("A matching active party already exists.")
        self.candidate_party_ids = candidate_party_ids


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
    expected_tenant_revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not (role := self.role.strip()):
            raise PartyValidationError("Reference resolution role must be nonblank.")
        if not isinstance(self.role_record_id, str) or not (
            record_id := self.role_record_id.strip()
        ):
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
        if role == "tenant" and (
            type(self.expected_tenant_revision) is not int or self.expected_tenant_revision < 1
        ):
            raise PartyValidationError(
                "Tenant reference resolution requires expectedTenantRevision."
            )
        if role != "tenant" and self.expected_tenant_revision is not None:
            raise PartyValidationError(
                "expectedTenantRevision is only valid for Tenant references."
            )
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

    def add(
        self,
        party_id: str,
        command: ContactMethodCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        if not isinstance(command, ContactMethodCommand):
            raise PartyValidationError("A valid contact command is required.")
        identity = command_identity(
            "contact_add",
            party_id,
            expected_revision,
            idempotency_key,
            {"command": asdict(command)},
        )
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction):
            if replay := start_command(tx, identity):
                return replay
            party = _required_party(tx, party_id)
            if party.archived_at is not None:
                raise PartyConflictError("An archived party cannot receive contact methods.")
            item = _contact(party_id, command, now)
            _unique([*tx.methods(party_id), item])
            tx.insert_method(item)
            return self._finish(tx, identity, party, None, item, now, correlation)

        return self._write(write)

    def update(
        self,
        party_id: str,
        method_id: str,
        command: ContactMethodCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        if not isinstance(command, ContactMethodCommand):
            raise PartyValidationError("A valid contact command is required.")
        _contact_identifier(method_id)
        identity = command_identity(
            "contact_update",
            party_id,
            expected_revision,
            idempotency_key,
            {"methodId": method_id, "command": asdict(command)},
        )
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction):
            if replay := start_command(tx, identity):
                return replay
            party = _required_party(tx, party_id)
            if party.archived_at is not None:
                raise PartyConflictError("Restore the party before editing contact methods.")
            methods = tx.methods(party_id)
            current = _required_contact(methods, method_id)
            if current.status != "active":
                raise PartyConflictError("An archived contact method cannot be edited.")
            updated = replace(
                current,
                method_kind=command.method_kind,
                display_value=command.value,
                normalized_value=command.normalized_value,
                extension=command.extension,
                label=command.label,
            )
            _unique([item for item in methods if item.id != method_id] + [updated])
            if updated != current:
                updated = replace(updated, updated_at=now)
                tx.replace_method(updated)
            return self._finish(tx, identity, party, current, updated, now, correlation)

        return self._write(write)

    def archive(
        self,
        party_id: str,
        method_id: str,
        *,
        confirmed: bool,
        expected_revision: int,
        idempotency_key: str,
        reference_resolutions: tuple[ContactReferenceResolution, ...] = (),
    ) -> dict[str, object]:
        if confirmed is not True:
            raise PartyValidationError("Archiving a contact method requires explicit confirmation.")
        if (
            not isinstance(reference_resolutions, tuple)
            or len(reference_resolutions) > 20
            or not all(
                isinstance(item, ContactReferenceResolution) for item in reference_resolutions
            )
        ):
            raise PartyValidationError(
                "Reference resolutions must be at most twenty valid commands."
            )
        keys = [(item.role, item.role_record_id) for item in reference_resolutions]
        if len(keys) != len(set(keys)):
            raise PartyValidationError("Reference resolutions must not repeat a role record.")
        _contact_identifier(method_id)
        for resolution in reference_resolutions:
            _contact_identifier(resolution.role_record_id)
            if resolution.replacement_contact_method_id is not None:
                _contact_identifier(resolution.replacement_contact_method_id)
        identity = command_identity(
            "contact_archive",
            party_id,
            expected_revision,
            idempotency_key,
            {
                "methodId": method_id,
                "confirmed": confirmed,
                "referenceResolutions": [
                    asdict(item)
                    for item in sorted(
                        reference_resolutions, key=lambda item: (item.role, item.role_record_id)
                    )
                ],
            },
        )
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction):
            if replay := start_command(tx, identity):
                return replay
            party = _required_party(tx, party_id)
            methods = tx.methods(party_id)
            current = _required_contact(methods, method_id)
            if current.status != "active":
                raise PartyConflictError("Contact method is already archived.")
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
                raise PartyValidationError(
                    "Reference resolutions include an unknown or unused role reference."
                )
            updated = replace(current, status="archived", archived_at=now, updated_at=now)
            tx.replace_method(updated)
            return self._finish(tx, identity, party, current, updated, now, correlation)

        return self._write(write)

    def restore(
        self, party_id: str, method_id: str, *, expected_revision: int, idempotency_key: str
    ) -> dict[str, object]:
        _contact_identifier(method_id)
        identity = command_identity(
            "contact_restore", party_id, expected_revision, idempotency_key, {"methodId": method_id}
        )
        now, correlation = _now(), str(uuid4())

        def write(tx: PartyTransaction):
            if replay := start_command(tx, identity):
                return replay
            party = _required_party(tx, party_id)
            if party.archived_at is not None:
                raise PartyConflictError("Restore the party before restoring contact methods.")
            methods = tx.methods(party_id)
            current = _required_contact(methods, method_id)
            if current.status != "archived":
                raise PartyConflictError("Contact method is already active.")
            updated = replace(current, status="active", archived_at=None, updated_at=now)
            _unique([item for item in methods if item.id != method_id] + [updated])
            tx.replace_method(updated)
            return self._finish(tx, identity, party, current, updated, now, correlation)

        return self._write(write)

    @staticmethod
    def _finish(tx, identity, party, before, contact, now, correlation):
        if before != contact:
            revised = replace(party, revision=party.revision + 1, updated_at=now)
            tx.replace_party(revised)
            tx.record_change(
                entity_type="party",
                entity_id=party.id,
                action="contact_changed",
                before=party.identity_snapshot(),
                after=revised.identity_snapshot(),
                reason="party_contact_changed",
                correlation_id=correlation,
            )
            action = {
                "contact_add": "created",
                "contact_update": "updated",
                "contact_archive": "archived",
                "contact_restore": "restored",
            }[identity.action]
            tx.record_change(
                entity_type="party_contact_method",
                entity_id=contact.id,
                action=action,
                before=before.to_audit_dict() if before else None,
                after=contact.to_audit_dict(),
                reason=f"party_contact_{action}",
                correlation_id=correlation,
            )
            party = revised
        return finish_command(tx, identity, party, now, correlation, contact=contact)

    def _write(self, operation):
        try:
            return self.unit_of_work.write(operation)
        except KeyError as error:
            raise PartyNotFoundError("Party or contact method was not found.") from error


def _required_party(tx, party_id):
    party = tx.party(party_id)
    if party is None:
        raise KeyError
    return party


def _contact_identifier(value):
    try:
        identifier(value)
    except (ValueError, TypeError) as error:
        raise PartyValidationError("Contact and reference IDs must be canonical UUIDs.") from error


@dataclass(frozen=True)
class PartyPatchCommand:
    display_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "display_name", _required(self.display_name, "Display name", 240))


class PartyIdentityService:
    """Shared identity lifecycle; role modules only add role-specific profiles."""

    def __init__(
        self,
        unit_of_work: PartyUnitOfWork,
        party_reads: PartyReadOperations,
        party_factory: PartyFactory | None = None,
        role_summary_readers: tuple[PartyRoleSummaryReader, ...] = (),
    ) -> None:
        self.unit_of_work = unit_of_work
        self.party_reads = party_reads
        self.party_factory = party_factory or SharedPartyFactory()
        self.role_summary_readers = role_summary_readers

    def create(
        self,
        command: PartyCreateCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
        contacts: tuple[ContactMethodCommand, ...] = (),
        confirmed_new_party: bool = False,
    ) -> dict[str, object]:
        if not isinstance(command, PartyCreateCommand) or type(confirmed_new_party) is not bool:
            raise PartyValidationError(
                "Party creation requires a valid command and boolean confirmation."
            )
        if not isinstance(contacts, tuple) or not all(
            isinstance(item, ContactMethodCommand) for item in contacts
        ):
            raise PartyValidationError("Party contacts are invalid.")
        now, correlation = _now(), str(uuid4())
        identity = command_identity(
            "create",
            None,
            expected_revision,
            idempotency_key,
            {
                "command": asdict(command),
                "contacts": [asdict(item) for item in contacts],
                "confirmedNewParty": confirmed_new_party,
            },
        )

        def write(tx):
            if replay := start_command(tx, identity):
                return replay
            provisional = [_contact("", item, now) for item in contacts]
            _unique(provisional)
            candidates = tx.duplicate_party_ids(provisional, 10)
            if candidates and confirmed_new_party is not True:
                raise PossibleDuplicatePartyError(candidates)
            item = self.party_factory.create(command, now)
            tx.insert_party(item)
            tx.record_change(
                entity_type="party",
                entity_id=item.id,
                action="created",
                before=None,
                after=item.identity_snapshot(),
                reason="party_created",
                correlation_id=correlation,
            )
            for provisional_method in provisional:
                method = replace(provisional_method, party_id=item.id)
                tx.insert_method(method)
                tx.record_change(
                    entity_type="party_contact_method",
                    entity_id=method.id,
                    action="created",
                    before=None,
                    after=method.to_audit_dict(),
                    reason="party_contact_created",
                    correlation_id=correlation,
                )
            return finish_command(tx, identity, item, now, correlation)

        return self.unit_of_work.write(write)

    def get(self, party_id: str) -> tuple[Party, list[PartyContactMethod]]:
        record = self.unit_of_work.methods(party_id)
        if record is None:
            raise PartyNotFoundError("Party was not found.")
        return record

    def list(
        self, *, archive_state: str, search: str | None
    ) -> list[tuple[Party, list[PartyContactMethod]]]:
        if archive_state not in {"active", "archived", "all"}:
            raise PartyValidationError("Archive state is invalid.")
        parties = self.party_reads.search(
            active_only=archive_state == "active", search=_optional(search, "Search", 240)
        )
        if archive_state == "archived":
            parties = [item for item in parties if item.archived_at is not None]
        methods = self.party_reads.methods_for_parties([item.id for item in parties])
        return [(item, methods.get(item.id, [])) for item in parties]

    def active_roles(self, party_id: str) -> list[str]:
        return sorted(
            {role for reader in self.role_summary_readers for role in reader.active_roles(party_id)}
        )

    def patch(
        self,
        party_id: str,
        command: PartyPatchCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        if not isinstance(command, PartyPatchCommand):
            raise PartyValidationError("A valid Party patch command is required.")
        now, correlation = _now(), str(uuid4())
        identity = command_identity(
            "patch", party_id, expected_revision, idempotency_key, asdict(command)
        )

        def write(tx):
            if replay := start_command(tx, identity):
                return replay
            current = tx.party(party_id)
            if current is None:
                raise KeyError
            if current.archived_at is not None:
                raise PartyConflictError("An archived party cannot be edited.")
            updated = replace(current, display_name=command.display_name)
            if updated != current:
                updated = replace(updated, updated_at=now, revision=current.revision + 1)
                tx.replace_party(updated)
                tx.record_change(
                    entity_type="party",
                    entity_id=party_id,
                    action="updated",
                    before=current.identity_snapshot(),
                    after=updated.identity_snapshot(),
                    reason="party_updated",
                    correlation_id=correlation,
                )
            return finish_command(tx, identity, updated, now, correlation)

        return self._write(write)

    def archive(
        self, party_id: str, *, confirmed: bool, expected_revision: int, idempotency_key: str
    ) -> dict[str, object]:
        if confirmed is not True:
            raise PartyValidationError("Archiving a party requires explicit confirmation.")
        now, correlation = _now(), str(uuid4())
        identity = command_identity(
            "archive", party_id, expected_revision, idempotency_key, {"confirmed": confirmed}
        )

        def write(tx):
            if replay := start_command(tx, identity):
                return replay
            current = tx.party(party_id)
            if current is None:
                raise KeyError
            if current.archived_at is not None:
                raise PartyConflictError("Party is already archived.")
            if conflicts := tx.party_role_conflicts(party_id):
                raise PartyConflictError(" ".join(conflicts))
            updated = replace(
                current, archived_at=now, updated_at=now, revision=current.revision + 1
            )
            tx.replace_party(updated)
            tx.record_change(
                entity_type="party",
                entity_id=party_id,
                action="archived",
                before=current.identity_snapshot(),
                after=updated.identity_snapshot(),
                reason="party_archived",
                correlation_id=correlation,
            )
            return finish_command(tx, identity, updated, now, correlation)

        return self._write(write)

    def restore(
        self, party_id: str, *, expected_revision: int, idempotency_key: str
    ) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())
        identity = command_identity("restore", party_id, expected_revision, idempotency_key, {})

        def write(tx):
            if replay := start_command(tx, identity):
                return replay
            current = tx.party(party_id)
            if current is None:
                raise KeyError
            if current.archived_at is None:
                raise PartyConflictError("Party is already active.")
            updated = replace(
                current, archived_at=None, updated_at=now, revision=current.revision + 1
            )
            tx.replace_party(updated)
            tx.record_change(
                entity_type="party",
                entity_id=party_id,
                action="restored",
                before=current.identity_snapshot(),
                after=updated.identity_snapshot(),
                reason="party_restored",
                correlation_id=correlation,
            )
            return finish_command(tx, identity, updated, now, correlation)

        return self._write(write)

    def recovery(
        self, *, operation_id: str | None = None, key: str | None = None
    ) -> dict[str, object]:
        return recover_command(self.unit_of_work, operation_id=operation_id, key=key)

    def _write(self, operation):
        try:
            return self.unit_of_work.write(operation)
        except KeyError as error:
            raise PartyNotFoundError("Party was not found.") from error


def _contact(party_id: str, command: ContactMethodCommand, now: str) -> PartyContactMethod:
    return PartyContactMethod(
        id=str(uuid4()),
        party_id=party_id,
        method_kind=command.method_kind,
        display_value=command.value,
        normalized_value=command.normalized_value,
        extension=command.extension,
        label=command.label,
        status="active",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )


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
