"""Tenant role use cases over shared party identities and contacts."""
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import uuid4

from app.modules.parties.application.service import ContactMethodCommand, PartyCreateCommand, PartyFactory, PartyValidationError
from app.modules.parties.domain.models import PartyContactMethod
from app.modules.tenants.application.ports import TenantTransaction, TenantUnitOfWork
from app.modules.tenants.domain.models import TenantProfile

class TenantError(RuntimeError): pass
class TenantNotFoundError(TenantError): pass
class TenantConflictError(TenantError): pass
class PossibleDuplicatePartyError(TenantConflictError):
    def __init__(self, candidate_party_ids: list[str]):
        super().__init__("A possible duplicate party requires explicit confirmation.")
        self.candidate_party_ids = candidate_party_ids

_UNSET = object()

@dataclass(frozen=True)
class TenantCreateCommand:
    party_kind: str
    display_name: str
    contacts: tuple[ContactMethodCommand, ...] = ()
    notes: str | None = None
    do_not_contact: bool = False
    confirmed_new_party: bool = False
    def __post_init__(self):
        try:
            party = PartyCreateCommand(self.party_kind, self.display_name)
        except PartyValidationError as error:
            raise TenantError(str(error)) from error
        if not isinstance(self.do_not_contact, bool): raise TenantError("doNotContact must be a boolean.")
        if not isinstance(self.confirmed_new_party, bool): raise TenantError("confirmedNewParty must be a boolean.")
        if not isinstance(self.contacts, tuple) or not all(isinstance(item, ContactMethodCommand) for item in self.contacts): raise TenantError("Contacts must be valid contact commands.")
        object.__setattr__(self, "party_kind", party.party_kind)
        object.__setattr__(self, "display_name", party.display_name)
        object.__setattr__(self, "notes", _optional(self.notes, "Notes", 4000))

@dataclass(frozen=True)
class TenantProfilePatchCommand:
    preferred_contact_method_id: object = _UNSET
    do_not_contact: object = _UNSET
    notes: object = _UNSET

    def __post_init__(self) -> None:
        if all(value is _UNSET for value in (self.preferred_contact_method_id, self.do_not_contact, self.notes)):
            raise TenantError("At least one tenant profile field must be supplied.")
        if self.do_not_contact is not _UNSET and not isinstance(self.do_not_contact, bool):
            raise TenantError("doNotContact must be a boolean.")
        if self.preferred_contact_method_id is not _UNSET and self.preferred_contact_method_id is not None:
            if not isinstance(self.preferred_contact_method_id, str) or not (identifier := self.preferred_contact_method_id.strip()):
                raise TenantError("Preferred contact method ID must be nonblank or null.")
            object.__setattr__(self, "preferred_contact_method_id", identifier)
        if self.notes is not _UNSET:
            object.__setattr__(self, "notes", _optional(self.notes, "Notes", 4000))

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> "TenantProfilePatchCommand":
        return cls(
            preferred_contact_method_id=values.get("preferredContactMethodId", _UNSET),
            do_not_contact=values.get("doNotContact", _UNSET),
            notes=values.get("notes", _UNSET),
        )

class TenantService:
    def __init__(self, unit_of_work: TenantUnitOfWork, party_factory: PartyFactory):
        self.unit_of_work = unit_of_work
        self.party_factory = party_factory
    def create(self, command: TenantCreateCommand) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())
        try:
            party = self.party_factory.create(PartyCreateCommand(command.party_kind, command.display_name), now)
        except PartyValidationError as error:
            raise TenantError(str(error)) from error
        profile = TenantProfile(party.id, None, command.do_not_contact, command.notes, now, now, None)
        methods = [_method(party.id, item, now) for item in command.contacts]
        def write(tx: TenantTransaction):
            _unique(methods)
            duplicates = tx.duplicate_party_ids(methods, 10)
            if duplicates and not command.confirmed_new_party:
                raise PossibleDuplicatePartyError(duplicates)
            tx.insert_party(party); tx.insert_profile(profile)
            tx.record_change(entity_type="party", entity_id=party.id, action="created", before=None, after=party.to_dict(), reason="tenant_created", correlation_id=correlation)
            tx.record_change(entity_type="tenant_profile", entity_id=party.id, action="created", before=None, after=profile.to_dict(), reason="tenant_created", correlation_id=correlation)
            for item in methods:
                tx.insert_method(item); tx.record_change(entity_type="party_contact_method", entity_id=item.id, action="created", before=None, after=item.to_audit_dict(), reason="party_contact_created", correlation_id=correlation)
            return _view(party, profile, methods)
        return self.unit_of_work.write(write)
    def designate(self, party_id: str, *, notes: str | None = None) -> dict[str, object]:
        now, correlation = _now(), str(uuid4()); notes = _optional(notes, "Notes", 4000)
        def write(tx: TenantTransaction):
            party = tx.party(party_id)
            if party is None: raise KeyError
            if party.archived_at is not None: raise TenantConflictError("An archived party cannot become a tenant.")
            if tx.profile(party_id) is not None: raise TenantConflictError("Party already has a tenant profile.")
            profile = TenantProfile(party_id, None, False, notes, now, now, None); tx.insert_profile(profile)
            tx.record_change(entity_type="tenant_profile", entity_id=party_id, action="created", before=None, after=profile.to_dict(), reason="tenant_designated", correlation_id=correlation)
            return _view(party, profile, [])
        return self._write(write)
    def get(self, party_id: str) -> dict[str, object]:
        row = self.unit_of_work.get(party_id)
        if row is None: raise TenantNotFoundError("Tenant was not found.")
        return _view(*row)
    def list(self, *, archive_state: str = "active", search: str | None = None) -> list[dict[str, object]]:
        if archive_state not in {"active", "archived", "all"}:
            raise TenantError("archiveState must be active, archived, or all.")
        return [_view(*row) for row in self.unit_of_work.list(archive_state=archive_state, search=_optional(search, "Search", 240))]
    def update_profile(self, party_id: str, command: TenantProfilePatchCommand) -> dict[str, object]:
        if not isinstance(command, TenantProfilePatchCommand): raise TenantError("A valid tenant profile patch is required.")
        now, correlation = _now(), str(uuid4())
        def write(tx: TenantTransaction):
            profile = tx.profile(party_id)
            if profile is None: raise KeyError
            _require_active(profile)
            methods = tx.methods(party_id)
            preferred = profile.preferred_contact_method_id if command.preferred_contact_method_id is _UNSET else command.preferred_contact_method_id
            if preferred is not None and not any(item.id == preferred and item.status == "active" for item in methods): raise TenantError("Preferred contact method must be an active method for this tenant.")
            updated = replace(
                profile,
                preferred_contact_method_id=preferred,
                do_not_contact=profile.do_not_contact if command.do_not_contact is _UNSET else command.do_not_contact,
                notes=profile.notes if command.notes is _UNSET else command.notes,
                updated_at=now,
            )
            tx.replace_profile(updated); tx.record_change(entity_type="tenant_profile", entity_id=party_id, action="updated", before=profile.to_dict(), after=updated.to_dict(), reason="tenant_profile_updated", correlation_id=correlation)
            party = tx.party(party_id)
            return _view(party, updated, methods)
        return self._write(write)
    def archive(self, party_id: str, *, confirmed: bool) -> dict[str, object]: return self._set_archived(party_id, confirmed, True)
    def restore(self, party_id: str) -> dict[str, object]: return self._set_archived(party_id, True, False)
    def _set_archived(self, party_id, confirmed, archive):
        if confirmed is not True: raise TenantError("Archiving a tenant requires explicit confirmation.")
        now, correlation = _now(), str(uuid4())
        def write(tx: TenantTransaction):
            profile = tx.profile(party_id)
            if profile is None: raise KeyError
            if archive == (profile.archived_at is not None):
                state = "archived" if archive else "active"
                raise TenantConflictError(f"Tenant profile is already {state}.")
            if archive and tx.has_open_lease_participation(party_id, date.today().isoformat()):
                raise TenantConflictError(
                    "A tenant with current or scheduled lease participation cannot be archived."
                )
            updated = replace(profile, archived_at=now if archive else None, updated_at=now)
            tx.replace_profile(updated); tx.record_change(entity_type="tenant_profile", entity_id=party_id, action="status_changed", before=profile.to_dict(), after=updated.to_dict(), reason="tenant_archived" if archive else "tenant_restored", correlation_id=correlation)
            return _view(tx.party(party_id), updated, tx.methods(party_id))
        return self._write(write)
    def _write(self, operation):
        try: return self.unit_of_work.write(operation)
        except KeyError as error: raise TenantNotFoundError("Tenant was not found.") from error

def _method(party_id, command, now):
    return PartyContactMethod(str(uuid4()), party_id, command.method_kind, command.value,
                              command.normalized_value, command.extension, command.label,
                              "active", now, now, None)
def _unique(methods):
    seen = set()
    for item in methods:
        if item.status != "active":
            continue
        key = (item.method_kind, item.normalized_value, item.extension or "")
        if key in seen: raise TenantConflictError("Active tenant contact methods must be unique.")
        seen.add(key)
def _require_active(profile):
    if profile.archived_at is not None: raise TenantConflictError("Restore the tenant before modifying its profile or contact methods.")
def _view(party, profile, methods): return {**party.to_dict(), "profile": profile.to_dict(), "contactMethods": [item.to_dict() for item in methods]}
def _now(): return datetime.now(UTC).isoformat()
def _optional(value, label, limit):
    if value is None: return None
    if not isinstance(value, str) or not (text := value.strip()) or len(text) > limit: raise TenantError(f"{label} must contain 1 to {limit} characters.")
    return text
