"""Provider-directory use cases and invariants."""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
import unicodedata
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import uuid4

from app.modules.parties.application.service import (
    ContactMethodCommand, PartyCreateCommand, PartyFactory, SharedPartyFactory,
)
from app.modules.parties.domain.models import Party, PartyContactMethod
from app.modules.vendors.application.ports import ProviderStorageConflict, ProviderTransaction, ProviderUnitOfWork
from app.modules.vendors.domain.models import (
    ProviderProfile, ProviderReference as ProviderReferenceRecord,
    ProviderReputationLink,
    ProviderService as ProviderServiceRecord, ProviderServiceArea as ProviderServiceAreaRecord,
    ProviderWorkHistory as ProviderWorkHistoryRecord,
)


class ProviderError(RuntimeError):
    pass


class ProviderNotFoundError(ProviderError):
    pass


class ProviderLifecycleConflict(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderProfileCommand:
    selection_status: str = "neutral"
    selection_reason: str | None = None
    notes: str | None = None

    def __post_init__(self):
        if self.selection_status not in {"neutral", "preferred", "avoid"}:
            raise ProviderError("Selection status is invalid.")
        object.__setattr__(self, "selection_reason", _optional(self.selection_reason, "Selection reason", 1000))
        object.__setattr__(self, "notes", _optional(self.notes, "Provider notes", 4000))
        if self.selection_status == "avoid" and self.selection_reason is None:
            raise ProviderError("Avoid status requires a selection reason.")


UNSET = object()


@dataclass(frozen=True)
class ProviderProfilePatchCommand:
    selection_status: str | object = UNSET
    selection_reason: str | None | object = UNSET
    notes: str | None | object = UNSET

    def __post_init__(self) -> None:
        if self.selection_status is not UNSET and self.selection_status not in {"neutral", "preferred", "avoid"}:
            raise ProviderError("Selection status is invalid.")
        if self.selection_reason is not UNSET:
            object.__setattr__(self, "selection_reason", _optional(self.selection_reason, "Selection reason", 1000))
        if self.notes is not UNSET:
            object.__setattr__(self, "notes", _optional(self.notes, "Provider notes", 4000))


@dataclass(frozen=True)
class ProviderSearchCommand:
    archive_state: str = "active"
    search: str | None = None
    service: str | None = None
    service_area: str | None = None
    selection_status: str | None = None
    property_id: str | None = None
    has_reference: bool | None = None

    def __post_init__(self) -> None:
        if self.archive_state not in {"active", "archived", "all"}:
            raise ProviderError("Archive state is invalid.")
        if self.selection_status is not None and self.selection_status not in {"neutral", "preferred", "avoid"}:
            raise ProviderError("Selection status is invalid.")
        if self.has_reference is not None and type(self.has_reference) is not bool:
            raise ProviderError("Reference filter is invalid.")
        object.__setattr__(self, "search", _optional(self.search, "Search", 240))
        object.__setattr__(self, "service", _normalized_filter(self.service, "Service filter", 160))
        object.__setattr__(self, "service_area", _normalized_filter(self.service_area, "Service area filter", 160))
        object.__setattr__(self, "property_id", _identifier(self.property_id, "Property ID"))


@dataclass(frozen=True)
class ServiceCommand:
    display_name: str
    def __post_init__(self): object.__setattr__(self, "display_name", _required(self.display_name, "Service label", 160))


@dataclass(frozen=True)
class ServiceAreaCommand:
    display_name: str
    country_code: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "display_name", _required(self.display_name, "Service area", 160))
        country = _optional(self.country_code, "Country code", 2)
        if country is not None and (len(country) != 2 or not country.isalpha() or not country.isascii()):
            raise ProviderError("Country code must be a two-letter ISO code.")
        object.__setattr__(self, "country_code", country.upper() if country else None)


@dataclass(frozen=True)
class WorkHistoryCommand:
    performed_on: str
    summary: str
    property_id: str | None = None
    outcome_notes: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "performed_on", _date(self.performed_on))
        object.__setattr__(self, "summary", _required(self.summary, "Work summary", 1000))
        object.__setattr__(self, "property_id", _identifier(self.property_id, "Property ID"))
        object.__setattr__(self, "outcome_notes", _optional(self.outcome_notes, "Outcome notes", 4000))


@dataclass(frozen=True)
class ReferenceCommand:
    reference_name: str | None = None
    organization_name: str | None = None
    relationship: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    def __post_init__(self):
        for field, label, limit in (("reference_name", "Reference name", 240), ("organization_name", "Organization name", 240), ("relationship", "Relationship", 240), ("email", "Reference email", 320), ("phone", "Reference phone", 320), ("notes", "Reference notes", 4000)):
            object.__setattr__(self, field, _optional(getattr(self, field), label, limit))
        if not any((self.reference_name, self.organization_name, self.relationship)):
            raise ProviderError("A reference needs a name, organization, or relationship.")


@dataclass(frozen=True)
class ReputationLinkCommand:
    source_kind: str
    url: str
    source_name: str | None = None
    notes: str | None = None
    last_checked_on: str | None = None
    normalized_source_key: str = field(init=False)
    normalized_url: str = field(init=False)

    def __post_init__(self) -> None:
        source_kind, source_name, source_key = _reputation_source(self.source_kind, self.source_name)
        canonical_url = canonical_reputation_url(self.url)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "normalized_source_key", source_key)
        object.__setattr__(self, "url", canonical_url)
        object.__setattr__(self, "normalized_url", canonical_url)
        object.__setattr__(self, "notes", _optional(self.notes, "Reputation notes", 4000))
        object.__setattr__(self, "last_checked_on", _reputation_date(self.last_checked_on))


@dataclass(frozen=True)
class ReputationLinkPatchCommand:
    source_kind: str | object = UNSET
    url: str | object = UNSET
    source_name: str | None | object = UNSET
    notes: str | None | object = UNSET
    last_checked_on: str | None | object = UNSET

    def __post_init__(self) -> None:
        if self.source_kind is not UNSET and self.source_kind not in {"google", "yelp", "angi", "other"}:
            raise ProviderError("Reputation source kind is invalid.")
        if self.url is not UNSET:
            object.__setattr__(self, "url", canonical_reputation_url(self.url))
        if self.source_name is not UNSET:
            object.__setattr__(self, "source_name", _optional(self.source_name, "Reputation source name", 80))
        if self.notes is not UNSET:
            object.__setattr__(self, "notes", _optional(self.notes, "Reputation notes", 4000))
        if self.last_checked_on is not UNSET:
            object.__setattr__(self, "last_checked_on", _reputation_date(self.last_checked_on))


class ProviderService:
    def __init__(self, unit_of_work: ProviderUnitOfWork, party_factory: PartyFactory | None = None) -> None:
        self.unit_of_work = unit_of_work
        self.party_factory = party_factory or SharedPartyFactory()

    def create(self, party_command: PartyCreateCommand, profile: ProviderProfileCommand,
               *, contacts: tuple[ContactMethodCommand, ...] = (),
               services: tuple[ServiceCommand, ...] = (), areas: tuple[ServiceAreaCommand, ...] = (),
               work_history: tuple[WorkHistoryCommand, ...] = (), references: tuple[ReferenceCommand, ...] = (),
               confirmed_new_party: bool = False) -> dict[str, object]:
        if not isinstance(party_command, PartyCreateCommand) or not isinstance(profile, ProviderProfileCommand):
            raise ProviderError("A valid party and provider profile command are required.")
        if not isinstance(contacts, tuple) or not all(isinstance(item, ContactMethodCommand) for item in contacts):
            raise ProviderError("Provider contacts are invalid.")
        initial = (("service", services), ("area", areas), ("work", work_history), ("reference", references))
        for kind, items in initial:
            if not isinstance(items, tuple):
                raise ProviderError("Initial provider records are invalid.")
            for item in items:
                _check_command(item, kind)
        now, correlation = _now(), str(uuid4())
        def write(tx: ProviderTransaction):
            methods = [_new_contact("", command, now) for command in contacts]
            _unique_contacts(methods)
            candidates = tx.duplicate_party_ids(methods, 10)
            if candidates and confirmed_new_party is not True:
                raise PossibleDuplicateParty(candidates)
            party = self.party_factory.create(party_command, now)
            tx.insert_party(party)
            tx.record_change(entity_type="party", entity_id=party.id, action="created", before=None,
                             after=party.to_dict(), reason="provider_party_created", correlation_id=correlation)
            for method in methods:
                item = replace(method, party_id=party.id)
                tx.insert_method(item)
                tx.record_change(entity_type="party_contact_method", entity_id=item.id, action="created", before=None,
                                 after=item.to_audit_dict(), reason="provider_contact_created", correlation_id=correlation)
            provider = _profile(party.id, profile, now)
            tx.insert_profile(provider)
            tx.record_change(entity_type="provider_profile", entity_id=party.id, action="created", before=None,
                             after=provider.to_dict(), reason="provider_created", correlation_id=correlation)
            for kind, items in initial:
                created = []
                for command in items:
                    child = _new_child(kind, party.id, command, now, tx)
                    _unique_child([*created, *_children(tx, kind, party.id)], child, kind)
                    _insert(tx, kind, child)
                    created.append(child)
                    tx.record_change(entity_type=_entity(kind), entity_id=child.id, action="created", before=None,
                                     after=child.to_dict(), reason=f"provider_{kind}_created", correlation_id=correlation)
            return party.id
        return self._write_detail(write)

    def designate(self, party_id: str, profile: ProviderProfileCommand) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())
        def write(tx):
            party = tx.party(party_id)
            if party is None: raise KeyError
            if party.archived_at is not None: raise ProviderLifecycleConflict("An archived party cannot become a provider.")
            if tx.profile(party_id) is not None: raise ProviderLifecycleConflict("Party already has a provider profile.")
            item = _profile(party_id, profile, now); tx.insert_profile(item)
            tx.record_change(entity_type="provider_profile", entity_id=party_id, action="created", before=None, after=item.to_dict(), reason="provider_designated", correlation_id=correlation)
            return party_id
        return self._write_detail(write)

    def detail(self, party_id: str, *, include_archived: bool = False) -> dict[str, object]:
        record = self.unit_of_work.detail(party_id, include_archived=include_archived)
        if record is None: raise ProviderNotFoundError("Provider was not found.")
        return _detail(record)

    def list(self, command: ProviderSearchCommand) -> list[dict[str, object]]:
        if not isinstance(command, ProviderSearchCommand):
            raise ProviderError("Provider search command is invalid.")
        return [_summary(item) for item in self.unit_of_work.list(
            archive_state=command.archive_state,
            search=command.search,
            service=command.service,
            service_area=command.service_area,
            selection_status=command.selection_status,
            property_id=command.property_id,
            has_reference=command.has_reference,
        )]

    def update_profile(self, party_id: str, command: ProviderProfilePatchCommand) -> dict[str, object]:
        if not isinstance(command, ProviderProfilePatchCommand):
            raise ProviderError("Provider patch command is invalid.")
        now, correlation = _now(), str(uuid4())
        def write(tx):
            current = _active_profile(tx, party_id)
            status = current.selection_status if command.selection_status is UNSET else command.selection_status
            reason = current.selection_reason if command.selection_reason is UNSET else command.selection_reason
            notes = current.notes if command.notes is UNSET else command.notes
            if status == "avoid" and reason is None:
                raise ProviderError("Avoid status requires a selection reason.")
            if (status, reason, notes) == (current.selection_status, current.selection_reason, current.notes):
                return party_id
            updated = replace(current, selection_status=status, selection_reason=reason, notes=notes, updated_at=now)
            tx.replace_profile(updated); tx.record_change(entity_type="provider_profile", entity_id=party_id, action="updated", before=current.to_dict(), after=updated.to_dict(), reason="provider_updated", correlation_id=correlation); return party_id
        return self._write_detail(write)

    def archive(self, party_id: str, *, confirmed: bool) -> dict[str, object]:
        if confirmed is not True: raise ProviderError("Archiving a provider requires explicit confirmation.")
        now, correlation = _now(), str(uuid4())
        def write(tx):
            current = _active_profile(tx, party_id); updated = replace(current, archived_at=now, updated_at=now)
            tx.replace_profile(updated); tx.record_change(entity_type="provider_profile", entity_id=party_id, action="archived", before=current.to_dict(), after=updated.to_dict(), reason="provider_archived", correlation_id=correlation); return party_id
        return self._write_detail(write, include_archived=True)

    def restore(self, party_id: str) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())
        def write(tx):
            current = tx.profile(party_id)
            if current is None: raise KeyError
            party = tx.party(party_id)
            if party is None: raise KeyError
            if party.archived_at is not None: raise ProviderLifecycleConflict("Restore the party before restoring its provider profile.")
            if current.archived_at is None: raise ProviderLifecycleConflict("Provider profile is already active.")
            updated = replace(current, archived_at=None, updated_at=now); tx.replace_profile(updated)
            tx.record_change(entity_type="provider_profile", entity_id=party_id, action="restored", before=current.to_dict(), after=updated.to_dict(), reason="provider_restored", correlation_id=correlation); return party_id
        return self._write_detail(write)

    def add_service(self, party_id, command): return self._child_create(party_id, command, "service")
    def update_service(self, party_id, item_id, command): return self._child_update(party_id, item_id, command, "service")
    def archive_service(self, party_id, item_id, *, confirmed): return self._child_archive(party_id, item_id, confirmed, "service")
    def restore_service(self, party_id, item_id): return self._child_restore(party_id, item_id, "service")
    def add_area(self, party_id, command): return self._child_create(party_id, command, "area")
    def update_area(self, party_id, item_id, command): return self._child_update(party_id, item_id, command, "area")
    def archive_area(self, party_id, item_id, *, confirmed): return self._child_archive(party_id, item_id, confirmed, "area")
    def restore_area(self, party_id, item_id): return self._child_restore(party_id, item_id, "area")
    def add_work_history(self, party_id, command): return self._child_create(party_id, command, "work")
    def update_work_history(self, party_id, item_id, command): return self._child_update(party_id, item_id, command, "work")
    def archive_work_history(self, party_id, item_id, *, confirmed): return self._child_archive(party_id, item_id, confirmed, "work")
    def restore_work_history(self, party_id, item_id): return self._child_restore(party_id, item_id, "work")
    def add_reference(self, party_id, command): return self._child_create(party_id, command, "reference")
    def update_reference(self, party_id, item_id, command): return self._child_update(party_id, item_id, command, "reference")
    def archive_reference(self, party_id, item_id, *, confirmed): return self._child_archive(party_id, item_id, confirmed, "reference")
    def restore_reference(self, party_id, item_id): return self._child_restore(party_id, item_id, "reference")

    def add_reputation_link(self, party_id: str, command: ReputationLinkCommand) -> dict[str, object]:
        if not isinstance(command, ReputationLinkCommand):
            raise ProviderError("Reputation-link command is invalid.")
        now, correlation = _now(), str(uuid4())

        def write(tx):
            _available_provider(tx, party_id)
            item = _new_reputation_link(party_id, command, now)
            _unique_reputation_link(tx.reputation_links(party_id), item)
            tx.insert_reputation_link(item)
            tx.record_change(
                entity_type="provider_reputation_link", entity_id=item.id, action="created",
                before=None, after=item.to_dict(), reason="provider_reputation_link_created",
                correlation_id=correlation,
            )
            return party_id

        return self._write_detail(write)

    def update_reputation_link(
        self, party_id: str, link_id: str, command: ReputationLinkPatchCommand,
    ) -> dict[str, object]:
        if not isinstance(command, ReputationLinkPatchCommand):
            raise ProviderError("Reputation-link patch command is invalid.")
        now, correlation = _now(), str(uuid4())

        def write(tx):
            _available_provider(tx, party_id)
            current = _required_reputation_link(tx.reputation_links(party_id), link_id)
            if current.archived_at is not None:
                raise ProviderLifecycleConflict("An archived reputation link cannot be edited.")
            complete = ReputationLinkCommand(
                current.source_kind if command.source_kind is UNSET else command.source_kind,
                current.url if command.url is UNSET else command.url,
                current.source_name if command.source_name is UNSET else command.source_name,
                current.notes if command.notes is UNSET else command.notes,
                current.last_checked_on if command.last_checked_on is UNSET else command.last_checked_on,
            )
            business_values = (
                complete.source_kind, complete.source_name, complete.normalized_source_key,
                complete.url, complete.normalized_url, complete.notes, complete.last_checked_on,
            )
            if business_values == (
                current.source_kind, current.source_name, current.normalized_source_key,
                current.url, current.normalized_url, current.notes, current.last_checked_on,
            ):
                return party_id
            updated = replace(
                current,
                source_kind=complete.source_kind,
                source_name=complete.source_name,
                normalized_source_key=complete.normalized_source_key,
                url=complete.url,
                normalized_url=complete.normalized_url,
                notes=complete.notes,
                last_checked_on=complete.last_checked_on,
                updated_at=now,
            )
            _unique_reputation_link(tx.reputation_links(party_id), updated)
            tx.replace_reputation_link(updated)
            tx.record_change(
                entity_type="provider_reputation_link", entity_id=link_id, action="updated",
                before=current.to_dict(), after=updated.to_dict(),
                reason="provider_reputation_link_updated", correlation_id=correlation,
            )
            return party_id

        return self._write_detail(write)

    def archive_reputation_link(
        self, party_id: str, link_id: str, *, confirmed: bool,
    ) -> dict[str, object]:
        if confirmed is not True:
            raise ProviderError("Archiving a reputation link requires explicit confirmation.")
        now, correlation = _now(), str(uuid4())

        def write(tx):
            _available_provider(tx, party_id)
            current = _required_reputation_link(tx.reputation_links(party_id), link_id)
            if current.archived_at is not None:
                raise ProviderLifecycleConflict("Reputation link is already archived.")
            updated = replace(current, archived_at=now, updated_at=now)
            tx.replace_reputation_link(updated)
            tx.record_change(
                entity_type="provider_reputation_link", entity_id=link_id, action="archived",
                before=current.to_dict(), after=updated.to_dict(),
                reason="provider_reputation_link_archived", correlation_id=correlation,
            )
            return party_id

        return self._write_detail(write, include_archived=True)

    def restore_reputation_link(self, party_id: str, link_id: str) -> dict[str, object]:
        now, correlation = _now(), str(uuid4())

        def write(tx):
            _available_provider(tx, party_id)
            current = _required_reputation_link(tx.reputation_links(party_id), link_id)
            if current.archived_at is None:
                raise ProviderLifecycleConflict("Reputation link is already active.")
            updated = replace(current, archived_at=None, updated_at=now)
            _unique_reputation_link(tx.reputation_links(party_id), updated)
            tx.replace_reputation_link(updated)
            tx.record_change(
                entity_type="provider_reputation_link", entity_id=link_id, action="restored",
                before=current.to_dict(), after=updated.to_dict(),
                reason="provider_reputation_link_restored", correlation_id=correlation,
            )
            return party_id

        return self._write_detail(write)

    def _child_create(self, party_id, command, kind):
        _check_command(command, kind); now, correlation = _now(), str(uuid4())
        def write(tx):
            _active_profile(tx, party_id); item = _new_child(kind, party_id, command, now, tx)
            _unique_child(_children(tx, kind, party_id), item, kind); _insert(tx, kind, item)
            tx.record_change(entity_type=_entity(kind), entity_id=item.id, action="created", before=None, after=item.to_dict(), reason=f"provider_{kind}_created", correlation_id=correlation); return party_id
        return self._write_detail(write)

    def _child_update(self, party_id, item_id, command, kind):
        _check_command(command, kind); now, correlation = _now(), str(uuid4())
        def write(tx):
            _active_profile(tx, party_id); current = _required_child(_children(tx, kind, party_id), item_id)
            if current.archived_at is not None: raise ProviderLifecycleConflict("An archived provider record cannot be edited.")
            updated = _update_child(current, command, now, tx); _unique_child([item for item in _children(tx, kind, party_id) if item.id != item_id], updated, kind)
            _replace(tx, kind, updated); tx.record_change(entity_type=_entity(kind), entity_id=item_id, action="updated", before=current.to_dict(), after=updated.to_dict(), reason=f"provider_{kind}_updated", correlation_id=correlation); return party_id
        return self._write_detail(write)

    def _child_archive(self, party_id, item_id, confirmed, kind):
        if confirmed is not True: raise ProviderError("Archiving a provider record requires explicit confirmation.")
        now, correlation = _now(), str(uuid4())
        def write(tx):
            _active_profile(tx, party_id); current = _required_child(_children(tx, kind, party_id), item_id)
            if current.archived_at is not None: raise ProviderLifecycleConflict("Provider record is already archived.")
            updated = replace(current, archived_at=now, updated_at=now); _replace(tx, kind, updated)
            tx.record_change(entity_type=_entity(kind), entity_id=item_id, action="archived", before=current.to_dict(), after=updated.to_dict(), reason=f"provider_{kind}_archived", correlation_id=correlation); return party_id
        return self._write_detail(write, include_archived=True)

    def _child_restore(self, party_id, item_id, kind):
        now, correlation = _now(), str(uuid4())
        def write(tx):
            _active_profile(tx, party_id); current = _required_child(_children(tx, kind, party_id), item_id)
            if current.archived_at is None: raise ProviderLifecycleConflict("Provider record is already active.")
            updated = replace(current, archived_at=None, updated_at=now); _unique_child([item for item in _children(tx, kind, party_id) if item.id != item_id], updated, kind); _replace(tx, kind, updated)
            tx.record_change(entity_type=_entity(kind), entity_id=item_id, action="restored", before=current.to_dict(), after=updated.to_dict(), reason=f"provider_{kind}_restored", correlation_id=correlation); return party_id
        return self._write_detail(write)

    def _write_detail(self, write, *, include_archived=False):
        try:
            party_id = self.unit_of_work.write(write)
        except KeyError as error: raise ProviderNotFoundError("Provider, party, or property was not found.") from error
        except ProviderStorageConflict as error: raise ProviderLifecycleConflict(str(error)) from error
        return self.detail(party_id, include_archived=include_archived)


class PossibleDuplicateParty(ProviderLifecycleConflict):
    def __init__(self, candidate_party_ids):
        super().__init__("A matching active party already exists."); self.candidate_party_ids = candidate_party_ids


def _active_profile(tx, party_id):
    item = tx.profile(party_id)
    if item is None: raise KeyError
    if item.archived_at is not None: raise ProviderLifecycleConflict("Restore the provider before changing its records.")
    return item
def _available_provider(tx, party_id):
    profile = _active_profile(tx, party_id)
    party = tx.party(party_id)
    if party is None: raise KeyError
    if party.archived_at is not None:
        raise ProviderLifecycleConflict("Restore the party before changing reputation links.")
    return profile
def _new_contact(party_id, item, now): return PartyContactMethod(str(uuid4()), party_id, item.method_kind, item.value, item.normalized_value, item.extension, item.label, "active", now, now, None)
def _profile(party_id, command, now): return ProviderProfile(party_id, command.selection_status, command.selection_reason, command.notes, now, now, None)
def _children(tx, kind, party_id): return {"service": tx.services, "area": tx.areas, "work": tx.work_history, "reference": tx.references}[kind](party_id)
def _insert(tx, kind, item): getattr(tx, f"insert_{'work_history' if kind == 'work' else kind}")(item)
def _replace(tx, kind, item): getattr(tx, f"replace_{'work_history' if kind == 'work' else kind}")(item)
def _entity(kind): return {"service":"provider_service", "area":"provider_service_area", "work":"provider_work_history", "reference":"provider_reference"}[kind]
def _required_child(items, item_id):
    for item in items:
        if item.id == item_id: return item
    raise KeyError
def _check_command(item, kind):
    expected = {"service":ServiceCommand, "area":ServiceAreaCommand, "work":WorkHistoryCommand, "reference":ReferenceCommand}[kind]
    if not isinstance(item, expected): raise ProviderError("Provider command is invalid.")
def _new_child(kind, party_id, command, now, tx):
    if kind == "service": return ProviderServiceRecord(str(uuid4()), party_id, command.display_name, _normalized(command.display_name), now, now, None)
    if kind == "area": return ProviderServiceAreaRecord(str(uuid4()), party_id, command.display_name, _normalized(command.display_name), command.country_code or "", now, now, None)
    if kind == "work":
        if command.property_id and not tx.property_exists(command.property_id): raise KeyError
        return ProviderWorkHistoryRecord(str(uuid4()), party_id, command.property_id, command.performed_on, command.summary, command.outcome_notes, now, now, None)
    return ProviderReferenceRecord(str(uuid4()), party_id, command.reference_name, command.organization_name, command.relationship, command.email, command.phone, command.notes, now, now, None)
def _update_child(current, command, now, tx):
    item = _new_child("service" if isinstance(command, ServiceCommand) else "area" if isinstance(command, ServiceAreaCommand) else "work" if isinstance(command, WorkHistoryCommand) else "reference", current.party_id, command, now, tx)
    return replace(item, id=current.id, created_at=current.created_at)
def _unique_child(items, candidate, kind):
    if candidate.archived_at is not None or kind not in {"service", "area"}: return
    for item in items:
        if item.archived_at is None and (item.normalized_name, getattr(item, "country_code", "")) == (candidate.normalized_name, getattr(candidate, "country_code", "")):
            raise ProviderLifecycleConflict("Active provider labels must be unique.")
def _unique_contacts(items):
    keys = [(item.method_kind, item.normalized_value, item.extension or "") for item in items]
    if len(keys) != len(set(keys)):
        raise ProviderLifecycleConflict("Active provider contact methods must be unique.")
def _detail(record):
    party, profile, contacts, services, areas, work, references, reputation_links = record
    return {"party": party.to_dict(), "profile": profile.to_dict(), "contactMethods": [item.to_dict() for item in contacts], "services": [item.to_dict() for item in services], "serviceAreas": [item.to_dict() for item in areas], "workHistory": [item.to_dict() for item in work], "references": [item.to_dict() for item in references], "reputationLinks": [item.to_dict() for item in reputation_links]}
def _summary(record):
    party, profile, services, areas, work_count, reference_count, reputation_link_count = record
    return {"party": party.to_dict(), "profile": profile.to_dict(), "services": [item.to_dict() for item in services], "serviceAreas": [item.to_dict() for item in areas], "workHistoryCount": work_count, "referenceCount": reference_count, "reputationLinkCount": reputation_link_count}
def _normalized(value): return unicodedata.normalize("NFKC", value).strip().casefold()
def _normalized_filter(value, label, limit):
    return None if value is None else _normalized(_required(value, label, limit))
def _required(value, label, limit):
    if not isinstance(value, str) or not (text := unicodedata.normalize("NFKC", value).strip()) or len(text) > limit: raise ProviderError(f"{label} must contain 1 to {limit} characters.")
    return text
def _optional(value, label, limit): return None if value is None else _required(value, label, limit)
def _identifier(value, label): return None if value is None else _required(value, label, 80)
def _date(value):
    if not isinstance(value, str): raise ProviderError("Date is invalid.")
    try: return date.fromisoformat(value).isoformat()
    except ValueError as error: raise ProviderError("Date is invalid.") from error
def _reputation_source(source_kind, source_name):
    if source_kind not in {"google", "yelp", "angi", "other"}:
        raise ProviderError("Reputation source kind is invalid.")
    if source_kind == "other":
        name = _required(source_name, "Reputation source name", 80)
        return source_kind, name, _normalized(name)
    if source_name is not None:
        raise ProviderError("Known reputation sources cannot have a source name.")
    return source_kind, None, source_kind
def _reputation_date(value):
    if value is None: return None
    normalized = _date(value)
    if normalized > date.today().isoformat():
        raise ProviderError("Last-checked date cannot be in the future.")
    return normalized
def canonical_reputation_url(value):
    if not isinstance(value, str):
        raise ProviderError("Reputation URL must be text.")
    display = unicodedata.normalize("NFKC", value).strip()
    if not display or any(character.isspace() or unicodedata.category(character) == "Cc" for character in display):
        raise ProviderError("Reputation URL is invalid.")
    try:
        parsed = urlsplit(display)
        port = parsed.port
    except ValueError as error:
        raise ProviderError("Reputation URL is invalid.") from error
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ProviderError("Reputation URL must be an absolute HTTPS URL with a host.")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderError("Reputation URL cannot contain user information.")
    if parsed.fragment or "#" in display:
        raise ProviderError("Reputation URL cannot contain a fragment.")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port in {None, 443} else f"{host}:{port}"
    canonical = urlunsplit(SplitResult("https", netloc, parsed.path, parsed.query, ""))
    if len(canonical) > 2048:
        raise ProviderError("Reputation URL must be at most 2048 characters.")
    return canonical
def _new_reputation_link(party_id, command, now):
    return ProviderReputationLink(
        str(uuid4()), party_id, command.source_kind, command.source_name,
        command.normalized_source_key, command.url, command.normalized_url,
        command.notes, command.last_checked_on, now, now, None,
    )
def _required_reputation_link(items, link_id):
    for item in items:
        if item.id == link_id: return item
    raise KeyError
def _unique_reputation_link(items, candidate):
    if candidate.archived_at is not None: return
    for item in items:
        if item.id == candidate.id or item.archived_at is not None: continue
        if item.normalized_source_key == candidate.normalized_source_key:
            raise ProviderLifecycleConflict("An active reputation link already uses this source.")
        if item.normalized_url == candidate.normalized_url:
            raise ProviderLifecycleConflict("An active reputation link already uses this URL.")
def _now(): return datetime.now(UTC).isoformat()
