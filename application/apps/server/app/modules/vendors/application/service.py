"""Provider-directory use cases and invariants."""

import json
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.modules.parties.application.service import (
    ContactMethodCommand,
    PartyCreateCommand,
    PartyFactory,
    SharedPartyFactory,
)
from app.modules.parties.domain.models import PartyContactMethod
from app.modules.vendors.application.category_commands import (
    CategoryCommand,
    start_category,
    finish_category,
    check_category_revision,
)
from app.modules.vendors.application.commands import ProviderCommand, finish, start, identifier
from app.modules.vendors.application.errors import (
    ProviderError,
    ProviderNotFoundError,
    ProviderLifecycleConflict,
)
from app.modules.vendors.application.ports import (
    ProviderStorageConflict,
    ProviderTransaction,
    ProviderUnitOfWork,
)
from app.modules.vendors.domain.category_normalization import normalize_provider_category_name
from app.modules.vendors.domain.models import (
    ProviderCategory,
    ProviderCategoryAssignment,
    ProviderProfile,
)
from app.modules.vendors.domain.category_seeds import fingerprint as category_fingerprint
from app.modules.vendors.domain.models import ProviderReference as ProviderReferenceRecord
from app.modules.vendors.domain.models import ProviderReputationLink
from app.modules.vendors.domain.models import ProviderService as ProviderServiceRecord
from app.modules.vendors.domain.models import ProviderServiceArea as ProviderServiceAreaRecord
from app.modules.vendors.domain.models import ProviderWorkHistory as ProviderWorkHistoryRecord


class ProviderCategoryIdempotencyConflict(ProviderLifecycleConflict):
    pass


@dataclass(frozen=True)
class ProviderProfileCommand:
    selection_status: str = "neutral"
    selection_reason: str | None = None
    notes: str | None = None

    def __post_init__(self):
        if self.selection_status not in {"neutral", "preferred", "avoid"}:
            raise ProviderError("Selection status is invalid.")
        object.__setattr__(
            self, "selection_reason", _optional(self.selection_reason, "Selection reason", 1000)
        )
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
        if self.selection_status is not UNSET and self.selection_status not in {
            "neutral",
            "preferred",
            "avoid",
        }:
            raise ProviderError("Selection status is invalid.")
        if self.selection_reason is not UNSET:
            object.__setattr__(
                self, "selection_reason", _optional(self.selection_reason, "Selection reason", 1000)
            )
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
    category_id: str | None = None
    category_state: str | None = None
    limit: int = 100
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.archive_state not in {"active", "archived", "all"}:
            raise ProviderError("Archive state is invalid.")
        if self.selection_status is not None and self.selection_status not in {
            "neutral",
            "preferred",
            "avoid",
        }:
            raise ProviderError("Selection status is invalid.")
        if self.has_reference is not None and type(self.has_reference) is not bool:
            raise ProviderError("Reference filter is invalid.")
        if self.category_state is not None and self.category_state not in {
            "categorized",
            "uncategorized",
        }:
            raise ProviderError("Category-state filter is invalid.")
        if (
            type(self.limit) is not int
            or isinstance(self.limit, bool)
            or not 1 <= self.limit <= 200
        ):
            raise ProviderError("Provider-list limit must be between 1 and 200.")
        object.__setattr__(self, "search", _optional(self.search, "Search", 240))
        object.__setattr__(self, "service", _normalized_filter(self.service, "Service filter", 160))
        object.__setattr__(
            self, "service_area", _normalized_filter(self.service_area, "Service area filter", 160)
        )
        object.__setattr__(self, "property_id", _identifier(self.property_id, "Property ID"))
        object.__setattr__(self, "category_id", _identifier(self.category_id, "Category ID"))
        object.__setattr__(self, "cursor", _optional(self.cursor, "Provider-list cursor", 600))


@dataclass(frozen=True)
class ProviderCategoryCommand:
    display_name: str
    display_order: int
    idempotency_key: str
    description: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "display_name", _required(self.display_name, "Category name", 160))
        object.__setattr__(
            self, "description", _optional(self.description, "Category description", 1000)
        )
        if (
            type(self.display_order) is not int
            or isinstance(self.display_order, bool)
            or self.display_order < 0
        ):
            raise ProviderError("Category display order must be nonnegative.")
        object.__setattr__(self, "idempotency_key", _uuid(self.idempotency_key, "Idempotency key"))


@dataclass(frozen=True)
class ProviderCategoryPatchCommand:
    display_name: str | object = UNSET
    description: str | None | object = UNSET
    display_order: int | object = UNSET

    def __post_init__(self):
        if self.display_name is not UNSET:
            object.__setattr__(
                self, "display_name", _required(self.display_name, "Category name", 160)
            )
        if self.description is not UNSET:
            object.__setattr__(
                self, "description", _optional(self.description, "Category description", 1000)
            )
        if self.display_order is not UNSET and (
            type(self.display_order) is not int
            or isinstance(self.display_order, bool)
            or self.display_order < 0
        ):
            raise ProviderError("Category display order must be nonnegative.")
        if self.display_name is UNSET and self.description is UNSET and self.display_order is UNSET:
            raise ProviderError("Category patch cannot be empty.")


@dataclass(frozen=True)
class ProviderCategoryAssignmentCommand:
    category_id: str
    idempotency_key: str

    def __post_init__(self):
        object.__setattr__(self, "category_id", _uuid(self.category_id, "Category ID"))
        object.__setattr__(self, "idempotency_key", _uuid(self.idempotency_key, "Idempotency key"))


@dataclass(frozen=True)
class ServiceCommand:
    display_name: str

    def __post_init__(self):
        object.__setattr__(self, "display_name", _required(self.display_name, "Service label", 160))


@dataclass(frozen=True)
class ServiceAreaCommand:
    display_name: str
    country_code: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "display_name", _required(self.display_name, "Service area", 160))
        country = _optional(self.country_code, "Country code", 2)
        if country is not None and (
            len(country) != 2 or not country.isalpha() or not country.isascii()
        ):
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
        object.__setattr__(
            self, "outcome_notes", _optional(self.outcome_notes, "Outcome notes", 4000)
        )


@dataclass(frozen=True)
class ReferenceCommand:
    reference_name: str | None = None
    organization_name: str | None = None
    relationship: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None

    def __post_init__(self):
        for field_name, label, limit in (
            ("reference_name", "Reference name", 240),
            ("organization_name", "Organization name", 240),
            ("relationship", "Relationship", 240),
            ("email", "Reference email", 320),
            ("phone", "Reference phone", 320),
            ("notes", "Reference notes", 4000),
        ):
            object.__setattr__(self, field_name, _optional(getattr(self, field_name), label, limit))
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
        source_kind, source_name, source_key = _reputation_source(
            self.source_kind, self.source_name
        )
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
        if self.source_kind is not UNSET and self.source_kind not in {
            "google",
            "yelp",
            "angi",
            "other",
        }:
            raise ProviderError("Reputation source kind is invalid.")
        if self.url is not UNSET:
            object.__setattr__(self, "url", canonical_reputation_url(self.url))
        if self.source_name is not UNSET:
            object.__setattr__(
                self, "source_name", _optional(self.source_name, "Reputation source name", 80)
            )
        if self.notes is not UNSET:
            object.__setattr__(self, "notes", _optional(self.notes, "Reputation notes", 4000))
        if self.last_checked_on is not UNSET:
            object.__setattr__(self, "last_checked_on", _reputation_date(self.last_checked_on))


class ProviderService:
    def __init__(
        self, unit_of_work: ProviderUnitOfWork, party_factory: PartyFactory | None = None
    ) -> None:
        self.unit_of_work = unit_of_work
        self.party_factory = party_factory or SharedPartyFactory()

    def create(
        self,
        party_command: PartyCreateCommand,
        profile: ProviderProfileCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
        contacts: tuple[ContactMethodCommand, ...] = (),
        services: tuple[ServiceCommand, ...] = (),
        areas: tuple[ServiceAreaCommand, ...] = (),
        work_history: tuple[WorkHistoryCommand, ...] = (),
        references: tuple[ReferenceCommand, ...] = (),
        category_ids: tuple[str, ...] = (),
        confirmed_new_party: bool = False,
    ) -> dict[str, object]:
        if not isinstance(party_command, PartyCreateCommand) or not isinstance(
            profile, ProviderProfileCommand
        ):
            raise ProviderError("A valid party and provider profile command are required.")
        if not isinstance(contacts, tuple) or not all(
            isinstance(item, ContactMethodCommand) for item in contacts
        ):
            raise ProviderError("Provider contacts are invalid.")
        if type(confirmed_new_party) is not bool:
            raise ProviderError("confirmedNewParty must be a boolean.")
        initial = (
            ("service", services),
            ("area", areas),
            ("work", work_history),
            ("reference", references),
        )
        for kind, items in initial:
            if not isinstance(items, tuple):
                raise ProviderError("Initial provider records are invalid.")
            for item in items:
                _check_command(item, kind)
        if not isinstance(category_ids, tuple):
            raise ProviderError("Initial provider categories are invalid.")
        category_ids = tuple(_uuid(value, "Category ID") for value in category_ids)
        if len(category_ids) != len(set(category_ids)):
            raise ProviderLifecycleConflict("A category can be assigned only once.")
        identity = ProviderCommand(
            "create",
            None,
            expected_revision,
            idempotency_key,
            {
                "party": asdict(party_command),
                "profile": asdict(profile),
                "contacts": [asdict(c) for c in contacts],
                "services": [asdict(c) for c in services],
                "areas": [asdict(c) for c in areas],
                "work_history": [asdict(c) for c in work_history],
                "references": [asdict(c) for c in references],
                "category_ids": sorted(category_ids),
                "confirmed_new_party": confirmed_new_party,
            },
        )
        correlation = str(uuid4())

        def write(tx: ProviderTransaction):
            if replay := start(tx, identity):
                return replay
            now = _now()
            methods = [_new_contact("", command, now) for command in contacts]
            _unique_contacts(methods)
            candidates = tx.duplicate_party_ids(methods, 10)
            if candidates and confirmed_new_party is not True:
                raise PossibleDuplicateParty(candidates)
            party = self.party_factory.create(party_command, now)
            tx.insert_party(party)
            tx.record_change(
                entity_type="party",
                entity_id=party.id,
                action="created",
                before=None,
                after=party.identity_snapshot(),
                reason="provider_party_created",
                correlation_id=correlation,
            )
            for method in methods:
                item = replace(method, party_id=party.id)
                tx.insert_method(item)
                tx.record_change(
                    entity_type="party_contact_method",
                    entity_id=item.id,
                    action="created",
                    before=None,
                    after=item.to_audit_dict(),
                    reason="provider_contact_created",
                    correlation_id=correlation,
                )
            provider = _profile(party.id, profile, now)
            tx.insert_profile(provider)
            tx.record_change(
                entity_type="provider_profile",
                entity_id=party.id,
                action="created",
                before=None,
                after=provider.to_dict(),
                reason="provider_created",
                correlation_id=correlation,
            )
            for category_id in category_ids:
                category = tx.category(category_id)
                if category is None:
                    raise KeyError
                if category.archived_at is not None:
                    raise ProviderLifecycleConflict("An archived category cannot be assigned.")
                assignment = _assignment(
                    party.id,
                    category_id,
                    now,
                    str(
                        uuid5(NAMESPACE_URL, f"provider-initial-category:{party.id}:{category_id}")
                    ),
                )
                tx.insert_assignment(assignment)
                tx.record_change(
                    entity_type="provider_category_assignment",
                    entity_id=assignment.id,
                    action="created",
                    before=None,
                    after=assignment.to_dict(),
                    reason="provider_category_assigned",
                    correlation_id=correlation,
                )
            for kind, items in initial:
                created = []
                for command in items:
                    child = _new_child(kind, party.id, command, now, tx)
                    _unique_child([*created, *_children(tx, kind, party.id)], child, kind)
                    _insert(tx, kind, child)
                    created.append(child)
                    tx.record_change(
                        entity_type=_entity(kind),
                        entity_id=child.id,
                        action="created",
                        before=None,
                        after=child.to_dict(),
                        reason=f"provider_{kind}_created",
                        correlation_id=correlation,
                    )
            return finish(tx, identity, provider, now, correlation)

        return self._command_write(write)

    def designate(
        self,
        party_id: str,
        profile: ProviderProfileCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        if not isinstance(profile, ProviderProfileCommand):
            raise ProviderError("A valid Provider profile command is required.")
        identity = ProviderCommand(
            "designate", party_id, expected_revision, idempotency_key, asdict(profile)
        )
        correlation = str(uuid4())

        def write(tx):
            if replay := start(tx, identity):
                return replay
            now = _now()
            party = tx.party(party_id)
            if party is None:
                raise KeyError
            if party.archived_at is not None:
                raise ProviderLifecycleConflict("An archived party cannot become a provider.")
            if tx.profile(party_id) is not None:
                raise ProviderLifecycleConflict("Party already has a provider profile.")
            item = _profile(party_id, profile, now)
            tx.insert_profile(item)
            tx.record_change(
                entity_type="provider_profile",
                entity_id=party_id,
                action="created",
                before=None,
                after=item.to_dict(),
                reason="provider_designated",
                correlation_id=correlation,
            )
            return finish(tx, identity, item, now, correlation)

        return self._command_write(write)

    def detail(self, party_id: str, *, include_archived: bool = False) -> dict[str, object]:
        record = self.unit_of_work.detail(party_id, include_archived=include_archived)
        if record is None:
            raise ProviderNotFoundError("Provider was not found.")
        return _detail(record)

    def list(self, command: ProviderSearchCommand) -> list[dict[str, object]]:
        if not isinstance(command, ProviderSearchCommand):
            raise ProviderError("Provider search command is invalid.")
        return [
            _summary(item)
            for item in self.unit_of_work.list(
                archive_state=command.archive_state,
                search=command.search,
                service=command.service,
                service_area=command.service_area,
                selection_status=command.selection_status,
                property_id=command.property_id,
                has_reference=command.has_reference,
                category_id=command.category_id,
                category_state=command.category_state,
                limit=None,
                cursor=None,
            )
        ]

    def page(self, command: ProviderSearchCommand) -> dict[str, object]:
        if not isinstance(command, ProviderSearchCommand):
            raise ProviderError("Provider search command is invalid.")
        cursor = _decode_cursor(command.cursor) if command.cursor else None
        records = self.unit_of_work.list(
            archive_state=command.archive_state,
            search=command.search,
            service=command.service,
            service_area=command.service_area,
            selection_status=command.selection_status,
            property_id=command.property_id,
            has_reference=command.has_reference,
            category_id=command.category_id,
            category_state=command.category_state,
            limit=command.limit + 1,
            cursor=cursor,
        )
        items = [_summary(item) for item in records[: command.limit]]
        next_cursor = (
            _encode_cursor(records[command.limit - 1][0]) if len(records) > command.limit else None
        )
        return {"items": items, "nextCursor": next_cursor}

    def list_categories(
        self, *, archive_state: str = "active", search: str | None = None
    ) -> list[dict[str, object]]:
        if archive_state not in {"active", "archived", "all"}:
            raise ProviderError("Archive state is invalid.")
        search = (
            None
            if search is None
            else normalize_provider_category_name(
                _required(search, "Category search", 160),
            )
        )
        categories = self.unit_of_work.categories(archive_state, search)
        counts = self.unit_of_work.effective_assignment_counts([item.id for item in categories])
        return [
            {**item.to_dict(), "effectiveProviderCount": counts.get(item.id, 0)}
            for item in categories
        ]

    def create_category(
        self, command: ProviderCategoryCommand, *, expected_revision: int
    ) -> dict[str, object]:
        if not isinstance(command, ProviderCategoryCommand):
            raise ProviderError("Category command is invalid.")
        identity = CategoryCommand(
            "create",
            None,
            expected_revision,
            command.idempotency_key,
            {key: value for key, value in asdict(command).items() if key != "idempotency_key"},
        )
        now, correlation, fingerprint = (
            _now(),
            str(uuid4()),
            _fingerprint(command.display_name, command.description, command.display_order),
        )

        def write(tx):
            replay = start_category(tx, identity)
            if replay is not None:
                return replay
            active = next(
                (
                    item
                    for item in tx.categories("active")
                    if item.normalized_name
                    == normalize_provider_category_name(command.display_name)
                ),
                None,
            )
            if active:
                raise ProviderLifecycleConflict("An active category already uses this name.")
            item = ProviderCategory(
                str(uuid4()),
                command.display_name,
                normalize_provider_category_name(command.display_name),
                command.description,
                command.display_order,
                now,
                now,
                None,
                None,
                command.idempotency_key,
                fingerprint,
            )
            tx.insert_category(item)
            tx.record_change(
                entity_type="provider_category",
                entity_id=item.id,
                action="created",
                before=None,
                after=item.to_dict(),
                reason="provider_category_created",
                correlation_id=correlation,
            )
            return finish_category(tx, identity, item, now, correlation)

        return self._command_write(write)

    def update_category(
        self,
        category_id: str,
        command: ProviderCategoryPatchCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        if not isinstance(command, ProviderCategoryPatchCommand):
            raise ProviderError("Category patch is invalid.")
        identity = CategoryCommand(
            "patch",
            category_id,
            expected_revision,
            idempotency_key,
            {key: value for key, value in command.__dict__.items() if value is not UNSET},
        )
        now, correlation = _now(), str(uuid4())

        def write(tx):
            replay = start_category(tx, identity)
            if replay is not None:
                return replay
            current = tx.category(category_id)
            if current is None:
                raise KeyError
            if current.archived_at is not None:
                raise ProviderLifecycleConflict("An archived category cannot be edited.")
            requested = replace(
                current,
                display_name=current.display_name
                if command.display_name is UNSET
                else command.display_name,
                normalized_name=(
                    current.normalized_name
                    if command.display_name is UNSET
                    else normalize_provider_category_name(command.display_name)
                ),
                description=current.description
                if command.description is UNSET
                else command.description,
                display_order=current.display_order
                if command.display_order is UNSET
                else command.display_order,
            )
            if requested == current:
                return finish_category(tx, identity, current, now, correlation)
            updated = replace(requested, updated_at=now, revision=current.revision + 1)
            conflict = next(
                (
                    item
                    for item in tx.categories("active")
                    if item.id != current.id and item.normalized_name == updated.normalized_name
                ),
                None,
            )
            if conflict:
                raise ProviderLifecycleConflict("An active category already uses this name.")
            tx.replace_category(updated)
            tx.record_change(
                entity_type="provider_category",
                entity_id=current.id,
                action="updated",
                before=current.to_dict(),
                after=updated.to_dict(),
                reason="provider_category_updated",
                correlation_id=correlation,
            )
            return finish_category(tx, identity, updated, now, correlation)

        return self._command_write(write)

    def archive_category(
        self,
        category_id: str,
        *,
        confirmed: bool,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        if confirmed is not True:
            raise ProviderError("Archiving a category requires explicit confirmation.")
        reason = _required(reason, "Archive reason", 1000)
        identity = CategoryCommand(
            "archive",
            category_id,
            expected_revision,
            idempotency_key,
            {"confirmed": confirmed, "reason": reason},
        )
        now, correlation = _now(), str(uuid4())

        def write(tx):
            replay = start_category(tx, identity)
            if replay is not None:
                return replay
            current = tx.category(category_id)
            if current is None:
                raise KeyError
            if current.archived_at is not None:
                if current.archive_reason != reason:
                    raise ProviderLifecycleConflict(
                        "An archived category cannot be retried with a different archive reason."
                    )
                return finish_category(tx, identity, current, now, correlation)
            updated = replace(
                current,
                archived_at=now,
                archive_reason=reason,
                updated_at=now,
                revision=current.revision + 1,
            )
            tx.replace_category(updated)
            tx.record_change(
                entity_type="provider_category",
                entity_id=current.id,
                action="archived",
                before=current.to_dict(),
                after=updated.to_dict(),
                reason="provider_category_archived",
                correlation_id=correlation,
            )
            return finish_category(tx, identity, updated, now, correlation)

        return self._command_write(write)

    def restore_category(
        self, category_id: str, *, confirmed: bool, expected_revision: int, idempotency_key: str
    ) -> dict[str, object]:
        if confirmed is not True:
            raise ProviderError("Restoring a category requires explicit confirmation.")
        identity = CategoryCommand(
            "restore", category_id, expected_revision, idempotency_key, {"confirmed": confirmed}
        )
        now, correlation = _now(), str(uuid4())

        def write(tx):
            replay = start_category(tx, identity)
            if replay is not None:
                return replay
            current = tx.category(category_id)
            if current is None:
                raise KeyError
            if current.archived_at is None:
                return finish_category(tx, identity, current, now, correlation)
            if any(
                item.id != current.id and item.normalized_name == current.normalized_name
                for item in tx.categories("active")
            ):
                raise ProviderLifecycleConflict("An active category already uses this name.")
            updated = replace(
                current,
                archived_at=None,
                archive_reason=None,
                updated_at=now,
                revision=current.revision + 1,
            )
            tx.replace_category(updated)
            tx.record_change(
                entity_type="provider_category",
                entity_id=current.id,
                action="restored",
                before=current.to_dict(),
                after=updated.to_dict(),
                reason="provider_category_restored",
                correlation_id=correlation,
            )
            return finish_category(tx, identity, updated, now, correlation)

        return self._command_write(write)

    def assign_category(
        self,
        party_id: str,
        command: ProviderCategoryAssignmentCommand,
        *,
        expected_revision: int,
        expected_category_revision: int,
    ):
        if not isinstance(command, ProviderCategoryAssignmentCommand):
            raise ProviderError("Category assignment command is invalid.")
        return self._assignment_mutate(
            party_id,
            None,
            "create",
            expected_revision,
            command.idempotency_key,
            {
                "category_id": command.category_id,
                "expected_category_revision": expected_category_revision,
            },
        )

    def archive_category_assignment(
        self,
        party_id: str,
        assignment_id: str,
        *,
        confirmed: bool,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ):
        if confirmed is not True:
            raise ProviderError("Archiving a category assignment requires explicit confirmation.")
        reason = _required(reason, "Archive reason", 1000)
        return self._assignment_mutate(
            party_id,
            assignment_id,
            "archive",
            expected_revision,
            idempotency_key,
            {"confirmed": confirmed, "reason": reason},
        )

    def restore_category_assignment(
        self,
        party_id: str,
        assignment_id: str,
        *,
        confirmed: bool,
        expected_revision: int,
        expected_category_revision: int,
        idempotency_key: str,
    ):
        if confirmed is not True:
            raise ProviderError("Restoring a category assignment requires explicit confirmation.")
        return self._assignment_mutate(
            party_id,
            assignment_id,
            "restore",
            expected_revision,
            idempotency_key,
            {"confirmed": confirmed, "expected_category_revision": expected_category_revision},
        )

    def _assignment_mutate(self, party_id, assignment_id, verb, expected_revision, key, fields):
        if assignment_id is not None:
            identifier(assignment_id)
        if verb in {"create", "restore"} and (
            type(fields["expected_category_revision"]) is not int
            or fields["expected_category_revision"] < 1
        ):
            raise ProviderError("expectedCategoryRevision must be a positive integer.")
        identity = ProviderCommand(
            f"assignment_{verb}",
            party_id,
            expected_revision,
            key,
            {"assignment_id": assignment_id, **fields},
        )
        now, correlation = _now(), str(uuid4())

        def write(tx):
            replay = start(tx, identity)
            if replay is not None:
                return replay
            profile = _available_provider(tx, party_id)
            current = tx.assignment(assignment_id) if assignment_id else None
            if verb != "create" and (current is None or current.provider_party_id != party_id):
                raise ProviderNotFoundError("Provider category assignment was not found.")
            category = tx.category(
                fields["category_id"] if verb == "create" else current.category_id
            )
            if category is None:
                raise ProviderNotFoundError("Provider category was not found.")
            if verb in {"create", "restore"}:
                check_category_revision(category, fields["expected_category_revision"])
                if category.archived_at is not None:
                    raise ProviderLifecycleConflict("Restore the category before assigning it.")
            if verb == "archive" and current.archived_at is not None:
                if current.archive_reason != fields["reason"]:
                    raise ProviderLifecycleConflict("Archive reason differs.")
                return finish(
                    tx, identity, profile, now, correlation, child=current, category=category
                )
            if verb == "restore" and current.archived_at is None:
                return finish(
                    tx, identity, profile, now, correlation, child=current, category=category
                )
            if verb in {"create", "restore"} and any(
                item.archived_at is None
                and item.category_id == category.id
                and (current is None or item.id != current.id)
                for item in tx.assignments(party_id)
            ):
                raise ProviderLifecycleConflict(
                    "This category is already assigned to the provider."
                )
            if verb == "create":
                updated = _assignment(
                    party_id, category.id, now, key, _fingerprint(party_id, category.id)
                )
                tx.insert_assignment(updated)
            else:
                updated = replace(
                    current,
                    updated_at=now,
                    archived_at=now if verb == "archive" else None,
                    archive_reason=fields["reason"] if verb == "archive" else None,
                )
                tx.replace_assignment(updated)
            action = {"create": "created", "archive": "archived", "restore": "restored"}[verb]
            tx.record_change(
                entity_type="provider_category_assignment",
                entity_id=updated.id,
                action=action,
                before=current.to_dict() if current else None,
                after=updated.to_dict(),
                reason=f"provider_category_assignment_{action}",
                correlation_id=correlation,
            )
            revised = replace(profile, revision=profile.revision + 1, updated_at=now)
            tx.replace_profile(revised)
            tx.record_change(
                entity_type="provider_profile",
                entity_id=party_id,
                action="updated",
                before=profile.to_dict(),
                after=revised.to_dict(),
                reason=f"provider_category_assignment_{action}",
                correlation_id=correlation,
            )
            return finish(tx, identity, revised, now, correlation, child=updated, category=category)

        return self._command_write(write)

    def update_profile(
        self,
        party_id: str,
        command: ProviderProfilePatchCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        if not isinstance(command, ProviderProfilePatchCommand):
            raise ProviderError("Provider patch command is invalid.")
        identity = ProviderCommand(
            "patch",
            party_id,
            expected_revision,
            idempotency_key,
            {name: value for name, value in command.__dict__.items() if value is not UNSET},
        )
        correlation = str(uuid4())

        def write(tx):
            if replay := start(tx, identity):
                return replay
            now = _now()
            current = _active_profile(tx, party_id)
            status = (
                current.selection_status
                if command.selection_status is UNSET
                else command.selection_status
            )
            reason = (
                current.selection_reason
                if command.selection_reason is UNSET
                else command.selection_reason
            )
            notes = current.notes if command.notes is UNSET else command.notes
            if status == "avoid" and reason is None:
                raise ProviderError("Avoid status requires a selection reason.")
            if (status, reason, notes) == (
                current.selection_status,
                current.selection_reason,
                current.notes,
            ):
                return finish(tx, identity, current, now, correlation)
            updated = replace(
                current,
                selection_status=status,
                selection_reason=reason,
                notes=notes,
                updated_at=now,
                revision=current.revision + 1,
            )
            tx.replace_profile(updated)
            tx.record_change(
                entity_type="provider_profile",
                entity_id=party_id,
                action="updated",
                before=current.to_dict(),
                after=updated.to_dict(),
                reason="provider_updated",
                correlation_id=correlation,
            )
            return finish(tx, identity, updated, now, correlation)

        return self._command_write(write)

    def archive(
        self, party_id: str, *, confirmed: bool, expected_revision: int, idempotency_key: str
    ) -> dict[str, object]:
        if confirmed is not True:
            raise ProviderError("Archiving a provider requires explicit confirmation.")
        identity = ProviderCommand(
            "archive", party_id, expected_revision, idempotency_key, {"confirmed": confirmed}
        )
        correlation = str(uuid4())

        def write(tx):
            if replay := start(tx, identity):
                return replay
            now = _now()
            current = _active_profile(tx, party_id)
            updated = replace(
                current, archived_at=now, updated_at=now, revision=current.revision + 1
            )
            tx.replace_profile(updated)
            tx.record_change(
                entity_type="provider_profile",
                entity_id=party_id,
                action="archived",
                before=current.to_dict(),
                after=updated.to_dict(),
                reason="provider_archived",
                correlation_id=correlation,
            )
            return finish(tx, identity, updated, now, correlation)

        return self._command_write(write)

    def restore(
        self, party_id: str, *, expected_revision: int, idempotency_key: str
    ) -> dict[str, object]:
        identity = ProviderCommand("restore", party_id, expected_revision, idempotency_key, {})
        correlation = str(uuid4())

        def write(tx):
            if replay := start(tx, identity):
                return replay
            now = _now()
            current = tx.profile(party_id)
            if current is None:
                raise KeyError
            party = tx.party(party_id)
            if party is None:
                raise KeyError
            if party.archived_at is not None:
                raise ProviderLifecycleConflict(
                    "Restore the party before restoring its provider profile."
                )
            if current.archived_at is None:
                raise ProviderLifecycleConflict("Provider profile is already active.")
            updated = replace(
                current, archived_at=None, updated_at=now, revision=current.revision + 1
            )
            tx.replace_profile(updated)
            tx.record_change(
                entity_type="provider_profile",
                entity_id=party_id,
                action="restored",
                before=current.to_dict(),
                after=updated.to_dict(),
                reason="provider_restored",
                correlation_id=correlation,
            )
            return finish(tx, identity, updated, now, correlation)

        return self._command_write(write)

    def add_service(self, party_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, None, command, "service", "create", expected_revision, idempotency_key
        )

    def update_service(self, party_id, item_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, command, "service", "update", expected_revision, idempotency_key
        )

    def archive_service(self, party_id, item_id, *, confirmed, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id,
            item_id,
            {"confirmed": confirmed},
            "service",
            "archive",
            expected_revision,
            idempotency_key,
        )

    def restore_service(self, party_id, item_id, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, {}, "service", "restore", expected_revision, idempotency_key
        )

    def add_area(self, party_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, None, command, "area", "create", expected_revision, idempotency_key
        )

    def update_area(self, party_id, item_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, command, "area", "update", expected_revision, idempotency_key
        )

    def archive_area(self, party_id, item_id, *, confirmed, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id,
            item_id,
            {"confirmed": confirmed},
            "area",
            "archive",
            expected_revision,
            idempotency_key,
        )

    def restore_area(self, party_id, item_id, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, {}, "area", "restore", expected_revision, idempotency_key
        )

    def add_work_history(self, party_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, None, command, "work", "create", expected_revision, idempotency_key
        )

    def update_work_history(
        self, party_id, item_id, command, *, expected_revision, idempotency_key
    ):
        return self._child_mutate(
            party_id, item_id, command, "work", "update", expected_revision, idempotency_key
        )

    def archive_work_history(
        self, party_id, item_id, *, confirmed, expected_revision, idempotency_key
    ):
        return self._child_mutate(
            party_id,
            item_id,
            {"confirmed": confirmed},
            "work",
            "archive",
            expected_revision,
            idempotency_key,
        )

    def restore_work_history(self, party_id, item_id, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, {}, "work", "restore", expected_revision, idempotency_key
        )

    def add_reference(self, party_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, None, command, "reference", "create", expected_revision, idempotency_key
        )

    def update_reference(self, party_id, item_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, command, "reference", "update", expected_revision, idempotency_key
        )

    def archive_reference(
        self, party_id, item_id, *, confirmed, expected_revision, idempotency_key
    ):
        return self._child_mutate(
            party_id,
            item_id,
            {"confirmed": confirmed},
            "reference",
            "archive",
            expected_revision,
            idempotency_key,
        )

    def restore_reference(self, party_id, item_id, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, {}, "reference", "restore", expected_revision, idempotency_key
        )

    def add_reputation_link(self, party_id, command, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, None, command, "reputation", "create", expected_revision, idempotency_key
        )

    def update_reputation_link(
        self, party_id, item_id, command, *, expected_revision, idempotency_key
    ):
        return self._child_mutate(
            party_id, item_id, command, "reputation", "update", expected_revision, idempotency_key
        )

    def archive_reputation_link(
        self, party_id, item_id, *, confirmed, expected_revision, idempotency_key
    ):
        return self._child_mutate(
            party_id,
            item_id,
            {"confirmed": confirmed},
            "reputation",
            "archive",
            expected_revision,
            idempotency_key,
        )

    def restore_reputation_link(self, party_id, item_id, *, expected_revision, idempotency_key):
        return self._child_mutate(
            party_id, item_id, {}, "reputation", "restore", expected_revision, idempotency_key
        )

    def _child_mutate(
        self, party_id, item_id, command, kind, verb, expected_revision, idempotency_key
    ):
        if verb in {"create", "update"}:
            if kind == "reputation":
                definition = (
                    ReputationLinkCommand if verb == "create" else ReputationLinkPatchCommand
                )
                if not isinstance(command, definition):
                    raise ProviderError("Reputation-link command is invalid.")
            else:
                _check_command(command, kind)
            fields = {name: value for name, value in command.__dict__.items() if value is not UNSET}
        else:
            fields = command
            if verb == "archive" and fields["confirmed"] is not True:
                raise ProviderError("Archiving a provider record requires explicit confirmation.")
        if item_id is not None:
            identifier(item_id)
        identity = ProviderCommand(
            f"{kind}_{verb}",
            party_id,
            expected_revision,
            idempotency_key,
            {"item_id": item_id, "fields": fields},
        )
        now, correlation = _now(), str(uuid4())

        def write(tx):
            replay = start(tx, identity)
            if replay is not None:
                return replay
            profile = _available_provider(tx, party_id)
            current = None
            children = (
                tx.reputation_links(party_id)
                if kind == "reputation"
                else _children(tx, kind, party_id)
            )
            if verb == "create":
                updated = (
                    _new_reputation_link(party_id, command, now)
                    if kind == "reputation"
                    else _new_child(kind, party_id, command, now, tx)
                )
            else:
                current = _required_child(children, item_id)
                if verb in {"update", "archive"} and current.archived_at is not None:
                    raise ProviderLifecycleConflict(
                        "An archived provider record cannot be edited or archived."
                    )
                if verb == "restore" and current.archived_at is None:
                    raise ProviderLifecycleConflict("Provider record is already active.")
                if verb == "update":
                    updated = (
                        _update_reputation(current, command, now)
                        if kind == "reputation"
                        else _update_child(current, command, now, tx)
                    )
                    if replace(updated, updated_at=current.updated_at) == current:
                        return finish(tx, identity, profile, now, correlation, child=current)
                else:
                    updated = replace(
                        current, archived_at=now if verb == "archive" else None, updated_at=now
                    )
            siblings = [item for item in children if current is None or item.id != current.id]
            if kind == "reputation":
                _unique_reputation_link(siblings, updated)
                (tx.insert_reputation_link if verb == "create" else tx.replace_reputation_link)(
                    updated
                )
            else:
                _unique_child(siblings, updated, kind)
                (_insert if verb == "create" else _replace)(tx, kind, updated)
            action = {
                "create": "created",
                "update": "updated",
                "archive": "archived",
                "restore": "restored",
            }[verb]
            tx.record_change(
                entity_type="provider_reputation_link" if kind == "reputation" else _entity(kind),
                entity_id=updated.id,
                action=action,
                before=current.to_dict() if current else None,
                after=updated.to_dict(),
                reason=f"provider_{kind}_{action}",
                correlation_id=correlation,
            )
            revised = replace(profile, revision=profile.revision + 1, updated_at=now)
            tx.replace_profile(revised)
            tx.record_change(
                entity_type="provider_profile",
                entity_id=party_id,
                action="updated",
                before=profile.to_dict(),
                after=revised.to_dict(),
                reason=f"provider_{kind}_{action}",
                correlation_id=correlation,
            )
            return finish(tx, identity, revised, now, correlation, child=updated)

        return self._command_write(write)

    def recover(self, *, operation_id=None, key=None):
        if (operation_id is None) == (key is None):
            raise ProviderError("Choose one receipt identity.")
        identifier(operation_id if operation_id is not None else key)
        row = self.unit_of_work.operation(operation_id=operation_id, key=key)
        if row is None:
            raise ProviderNotFoundError("Provider command receipt was not found.")
        return json.loads(row["result_json"])

    def recover_category(self, *, operation_id=None, key=None):
        if (operation_id is None) == (key is None):
            raise ProviderError("Choose one category receipt identity.")
        identifier(operation_id if operation_id is not None else key)
        row = self.unit_of_work.category_operation(operation_id=operation_id, key=key)
        if row is None:
            raise ProviderNotFoundError("Category receipt was not found.")
        return json.loads(row["result_json"])

    def _command_write(self, write):
        try:
            return self.unit_of_work.write(write)
        except KeyError as error:
            raise ProviderNotFoundError("Provider, party, or property was not found.") from error
        except ProviderStorageConflict as error:
            raise ProviderLifecycleConflict(str(error)) from error


class PossibleDuplicateParty(ProviderLifecycleConflict):
    def __init__(self, candidate_party_ids):
        super().__init__("A matching active party already exists.")
        self.candidate_party_ids = candidate_party_ids


def _active_profile(tx, party_id):
    item = tx.profile(party_id)
    if item is None:
        raise KeyError
    if item.archived_at is not None:
        raise ProviderLifecycleConflict("Restore the provider before changing its records.")
    return item


def _available_provider(tx, party_id):
    profile = _active_profile(tx, party_id)
    party = tx.party(party_id)
    if party is None:
        raise KeyError
    if party.archived_at is not None:
        raise ProviderLifecycleConflict("Restore the party before changing provider records.")
    return profile


def _assignment(party_id, category_id, now, idempotency_key, fingerprint=None):
    return ProviderCategoryAssignment(
        str(uuid4()),
        party_id,
        category_id,
        now,
        now,
        None,
        None,
        idempotency_key,
        fingerprint or _fingerprint(party_id, category_id),
    )


def _new_contact(party_id, item, now):
    return PartyContactMethod(
        str(uuid4()),
        party_id,
        item.method_kind,
        item.value,
        item.normalized_value,
        item.extension,
        item.label,
        "active",
        now,
        now,
        None,
    )


def _profile(party_id, command, now):
    return ProviderProfile(
        party_id, command.selection_status, command.selection_reason, command.notes, now, now, None
    )


def _children(tx, kind, party_id):
    return {
        "service": tx.services,
        "area": tx.areas,
        "work": tx.work_history,
        "reference": tx.references,
    }[kind](party_id)


def _insert(tx, kind, item):
    getattr(tx, f"insert_{'work_history' if kind == 'work' else kind}")(item)


def _replace(tx, kind, item):
    getattr(tx, f"replace_{'work_history' if kind == 'work' else kind}")(item)


def _entity(kind):
    return {
        "service": "provider_service",
        "area": "provider_service_area",
        "work": "provider_work_history",
        "reference": "provider_reference",
    }[kind]


def _required_child(items, item_id):
    for item in items:
        if item.id == item_id:
            return item
    raise KeyError


def _check_command(item, kind):
    expected = {
        "service": ServiceCommand,
        "area": ServiceAreaCommand,
        "work": WorkHistoryCommand,
        "reference": ReferenceCommand,
    }[kind]
    if not isinstance(item, expected):
        raise ProviderError("Provider command is invalid.")


def _new_child(kind, party_id, command, now, tx):
    if kind == "service":
        return ProviderServiceRecord(
            str(uuid4()),
            party_id,
            command.display_name,
            _normalized(command.display_name),
            now,
            now,
            None,
        )
    if kind == "area":
        return ProviderServiceAreaRecord(
            str(uuid4()),
            party_id,
            command.display_name,
            _normalized(command.display_name),
            command.country_code or "",
            now,
            now,
            None,
        )
    if kind == "work":
        if command.property_id and not tx.property_exists(command.property_id):
            raise KeyError
        return ProviderWorkHistoryRecord(
            str(uuid4()),
            party_id,
            command.property_id,
            command.performed_on,
            command.summary,
            command.outcome_notes,
            now,
            now,
            None,
        )
    return ProviderReferenceRecord(
        str(uuid4()),
        party_id,
        command.reference_name,
        command.organization_name,
        command.relationship,
        command.email,
        command.phone,
        command.notes,
        now,
        now,
        None,
    )


def _update_child(current, command, now, tx):
    item = _new_child(
        "service"
        if isinstance(command, ServiceCommand)
        else "area"
        if isinstance(command, ServiceAreaCommand)
        else "work"
        if isinstance(command, WorkHistoryCommand)
        else "reference",
        current.party_id,
        command,
        now,
        tx,
    )
    return replace(item, id=current.id, created_at=current.created_at)


def _update_reputation(current, command, now):
    complete = ReputationLinkCommand(
        current.source_kind if command.source_kind is UNSET else command.source_kind,
        current.url if command.url is UNSET else command.url,
        current.source_name if command.source_name is UNSET else command.source_name,
        current.notes if command.notes is UNSET else command.notes,
        current.last_checked_on if command.last_checked_on is UNSET else command.last_checked_on,
    )
    return replace(
        _new_reputation_link(current.party_id, complete, now),
        id=current.id,
        created_at=current.created_at,
    )


def _unique_child(items, candidate, kind):
    if candidate.archived_at is not None or kind not in {"service", "area"}:
        return
    for item in items:
        if item.archived_at is None and (
            item.normalized_name,
            getattr(item, "country_code", ""),
        ) == (candidate.normalized_name, getattr(candidate, "country_code", "")):
            raise ProviderLifecycleConflict("Active provider labels must be unique.")


def _unique_contacts(items):
    keys = [(item.method_kind, item.normalized_value, item.extension or "") for item in items]
    if len(keys) != len(set(keys)):
        raise ProviderLifecycleConflict("Active provider contact methods must be unique.")


def _detail(record):
    party, profile, contacts, services, areas, work, references, reputation_links, categories = (
        record
    )
    return {
        "party": party.to_dict(),
        "profile": profile.to_dict(),
        "contactMethods": [item.to_dict() for item in contacts],
        "services": [item.to_dict() for item in services],
        "serviceAreas": [item.to_dict() for item in areas],
        "workHistory": [item.to_dict() for item in work],
        "references": [item.to_dict() for item in references],
        "reputationLinks": [item.to_dict() for item in reputation_links],
        "categories": [
            _category_summary(assignment, category) for assignment, category in categories
        ],
    }


def _summary(record):
    (
        party,
        profile,
        services,
        areas,
        work_count,
        reference_count,
        reputation_link_count,
        categories,
    ) = record
    return {
        "party": party.to_dict(),
        "profile": profile.to_dict(),
        "services": [item.to_dict() for item in services],
        "serviceAreas": [item.to_dict() for item in areas],
        "workHistoryCount": work_count,
        "referenceCount": reference_count,
        "reputationLinkCount": reputation_link_count,
        "categories": [
            _category_summary(assignment, category) for assignment, category in categories
        ],
    }


def _category_summary(assignment, category):
    return {
        **category.to_dict(),
        "assignmentId": assignment.id,
        "assignmentArchivedAt": assignment.archived_at,
        "assignmentArchiveReason": assignment.archive_reason,
    }


def _normalized(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _normalized_filter(value, label, limit):
    return None if value is None else _normalized(_required(value, label, limit))


def _required(value, label, limit):
    if (
        not isinstance(value, str)
        or not (text := unicodedata.normalize("NFKC", value).strip())
        or len(text) > limit
    ):
        raise ProviderError(f"{label} must contain 1 to {limit} characters.")
    return text


def _optional(value, label, limit):
    return None if value is None else _required(value, label, limit)


def _identifier(value, label):
    return None if value is None else _required(value, label, 80)


def _uuid(value, label):
    import uuid

    if not isinstance(value, str):
        raise ProviderError(f"{label} is invalid.")
    try:
        return str(uuid.UUID(value))
    except ValueError as error:
        raise ProviderError(f"{label} is invalid.") from error


def _encode_cursor(party):
    return f"{unicodedata.normalize('NFKC', party.display_name).casefold()}|{party.id}"


def _fingerprint(*values):
    return category_fingerprint(*values)


def _decode_cursor(cursor):
    try:
        name, party_id = cursor.rsplit("|", 1)
        return unicodedata.normalize("NFKC", name).casefold(), _uuid(
            party_id, "Provider-list cursor"
        )
    except ValueError as error:
        raise ProviderError("Provider-list cursor is invalid.") from error


def _date(value):
    if not isinstance(value, str):
        raise ProviderError("Date is invalid.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ProviderError("Date is invalid.") from error


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
    if value is None:
        return None
    normalized = _date(value)
    if normalized > date.today().isoformat():
        raise ProviderError("Last-checked date cannot be in the future.")
    return normalized


def canonical_reputation_url(value):
    if not isinstance(value, str):
        raise ProviderError("Reputation URL must be text.")
    display = unicodedata.normalize("NFKC", value).strip()
    if not display or any(
        character.isspace() or unicodedata.category(character) == "Cc" for character in display
    ):
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
        str(uuid4()),
        party_id,
        command.source_kind,
        command.source_name,
        command.normalized_source_key,
        command.url,
        command.normalized_url,
        command.notes,
        command.last_checked_on,
        now,
        now,
        None,
    )


def _unique_reputation_link(items, candidate):
    if candidate.archived_at is not None:
        return
    for item in items:
        if item.id == candidate.id or item.archived_at is not None:
            continue
        if item.normalized_source_key == candidate.normalized_source_key:
            raise ProviderLifecycleConflict("An active reputation link already uses this source.")
        if item.normalized_url == candidate.normalized_url:
            raise ProviderLifecycleConflict("An active reputation link already uses this URL.")


def _now():
    return datetime.now(UTC).isoformat()
