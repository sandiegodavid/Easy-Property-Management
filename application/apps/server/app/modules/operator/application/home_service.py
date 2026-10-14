"""Exact Home collections and live attention share one snapshot composition."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.finance.application.money_models import MoneyError
from app.modules.operator.application.home_contracts import (
    AvailableCollection,
    UnavailableCollection,
    Capture,
    CollectionTarget,
    HomeResponse,
    AttentionResponse,
    AvailableInventory,
    InventoryCount,
    InventoryTarget,
    UnavailableSummary,
    HomeQuery,
    AttentionQuery,
    CollectionQuery,
    CollectionResponse,
    InventoryQuery,
    InventorySpaceItem,
    HomeInventoryResponse,
)
from app.modules.operator.application.home_ports import (
    HomeUnitOfWork,
    HomeReadTransaction,
    HomeAdapterMissing,
)
from app.modules.operator.application.home_projection import home_item
from app.modules.operator.application.home_registry import COLLECTION_DEPENDENCIES
from app.modules.operator.application.home_vocabulary import Collection, SourceKind
from app.modules.operator.domain.models import OperatorSectionUnavailable, OperatorUnavailable
from app.platform.attention_reads import AttentionWindow, AttentionKey
from app.modules.operator.application.cursors import (
    AttentionCursor,
    decode_attention_cursor,
    ReadCursor,
    decode_cursor,
)


@dataclass(frozen=True)
class ComposedCollection:
    """Bounded merge result with the final returned key for continuation."""

    result: AvailableCollection | UnavailableCollection
    next_key: AttentionKey | None
    priority_totals: dict[str, int] | None
    reason_totals: dict[str, int] | None


class HomeCompositionService:
    def __init__(self, unit_of_work: HomeUnitOfWork, *, runtime, now=lambda: datetime.now(UTC)):
        self.unit_of_work, self.runtime, self.now = unit_of_work, runtime, now

    def _context(self):
        identity = self.runtime()
        if identity.state != "ready":
            raise OperatorUnavailable("Open and validate the workspace before reading Home.")
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise OperatorUnavailable("Home clock is unavailable.")
        return identity, instant.astimezone(UTC)

    def home(self, query: HomeQuery) -> HomeResponse:
        identity, instant = self._context()

        def read(tx):
            tx.validate_scope(query.scope)
            marker = tx.source_marker()
            supported = tx.supported_sources()
            sections = {
                collection.value: self._continued(
                    self._collection(
                        tx,
                        query.scope,
                        AttentionWindow(
                            instant,
                            collection.value,
                            query.scope.property_id,
                            query.horizon_days,
                            query.limit_per_section,
                        ),
                        marker,
                        supported,
                    ),
                    identity,
                ).result
                for collection in Collection
            }
            window = AttentionWindow(instant, "needs_action", query.scope.property_id)
            capture = _capture(instant, marker)
            try:
                inventory = tx.inventory(window)
                inventory_result = AvailableInventory(
                    capture=_capture(instant, marker, inventory.next_transition_at),
                    vacant=InventoryCount(
                        count=inventory.vacant_count,
                        target=InventoryTarget(scope=query.scope, occupancy="vacant"),
                        view_all_cursor=_inventory_cursor(
                            query.scope, "vacant", identity, marker, instant
                        ),
                    ),
                    unknown=InventoryCount(
                        count=inventory.unknown_count,
                        target=InventoryTarget(scope=query.scope, occupancy="unknown"),
                        view_all_cursor=_inventory_cursor(
                            query.scope, "unknown", identity, marker, instant
                        ),
                    ),
                )
            except HomeAdapterMissing:
                inventory_result = _unavailable_summary(capture, "adapter_missing")
            except OperatorSectionUnavailable:
                inventory_result = _unavailable_summary(capture, "source_unavailable")
            try:
                money = tx.money(query, window, identity=(identity.workspace_id, identity.epoch))
            except HomeAdapterMissing:
                money = _unavailable_summary(capture, "adapter_missing")
            except MoneyError, OperatorSectionUnavailable:
                money = _unavailable_summary(capture, "source_unavailable")
            transitions = [section.capture.next_transition_at for section in sections.values()]
            transitions.append(inventory_result.capture.next_transition_at)
            return HomeResponse(
                workspace_id=UUID(identity.workspace_id),
                runtime_epoch=UUID(identity.epoch),
                as_of=instant,
                source_revision=marker,
                scope=query.scope,
                next_transition_at=_earliest(transitions),
                supported_sources=supported,
                inventory=inventory_result,
                money=money,
                **sections,
            )

        return self.unit_of_work.read(read)

    def attention(self, query: AttentionQuery) -> AttentionResponse:
        identity, instant = self._context()

        def read(tx):
            tx.validate_scope(query.scope)
            marker = tx.source_marker()
            supported = tuple(
                kind for kind in tx.supported_sources() if kind != SourceKind.COVERAGE
            )
            composed = self._collection(
                tx,
                query.scope,
                AttentionWindow(
                    instant, "needs_action", query.scope.property_id, limit=query.limit
                ),
                marker,
                supported,
            )
            composed = self._continued(composed, identity)
            return AttentionResponse(
                workspace_id=UUID(identity.workspace_id),
                runtime_epoch=UUID(identity.epoch),
                scope=query.scope,
                as_of=instant,
                source_revision=marker,
                next_transition_at=composed.result.capture.next_transition_at,
                supported_sources=supported,
                needs_action=composed.result,
                priority_totals=composed.priority_totals,
                reason_totals=composed.reason_totals,
            )

        return self.unit_of_work.read(read)

    def inventory_items(self, query: InventoryQuery) -> HomeInventoryResponse:
        identity, now = self._context()

        def read(tx):
            tx.validate_scope(query.scope)
            marker = tx.source_marker()
            instant, after = now, None
            if query.cursor is not None:
                cursor = decode_cursor(
                    query.cursor,
                    endpoint="home.inventory",
                    filters=_inventory_filters(query.scope, query.occupancy),
                    identity=(identity.workspace_id, identity.epoch),
                    source_revision=marker,
                    now=now,
                    sort_kind="identity",
                    allow_start=True,
                )
                instant, after = datetime.fromisoformat(cursor.as_of), cursor.last
            try:
                page = tx.inventory_spaces(
                    AttentionWindow(
                        instant, "needs_action", query.scope.property_id, limit=query.limit
                    ),
                    query.occupancy,
                    after=after,
                )
            except OperatorSectionUnavailable as error:
                raise OperatorUnavailable("Inventory source is unavailable.") from error
            return HomeInventoryResponse(
                workspace_id=UUID(identity.workspace_id),
                runtime_epoch=UUID(identity.epoch),
                scope=query.scope,
                as_of=instant,
                source_revision=marker,
                occupancy=query.occupancy,
                matching_total=page.matching_total,
                items=tuple(
                    InventorySpaceItem(
                        property_id=item.property_id,
                        property_name=item.property_name,
                        space_id=item.space_id,
                        space_name=item.space_name,
                        occupancy=item.occupancy,
                        time_zone=item.time_zone,
                        effective_local_date=instant.astimezone(ZoneInfo(item.time_zone)).date(),
                    )
                    for item in page.items
                ),
                next_cursor=_inventory_cursor(
                    query.scope, query.occupancy, identity, marker, instant, page.next_key
                )
                if page.next_key
                else None,
            )

        return self.unit_of_work.read(read)

    def items(self, query: CollectionQuery) -> CollectionResponse:
        """Validate the HTTP continuation against the very snapshot it pages."""
        identity, now = self._context()

        def read(tx):
            tx.validate_scope(query.scope)
            marker, supported = tx.source_marker(), tx.supported_sources()
            instant, after = now, None
            if query.cursor is not None:
                cursor = decode_attention_cursor(
                    query.cursor,
                    filters=_filters(query.scope, query.collection, query.horizon_days),
                    identity=(identity.workspace_id, identity.epoch),
                    source_revision=marker,
                    now=now,
                )
                instant, after = cursor.as_of, cursor.last
            composed = self._continued(
                self._collection(
                    tx,
                    query.scope,
                    AttentionWindow(
                        instant,
                        query.collection.value,
                        query.scope.property_id,
                        query.horizon_days,
                        query.limit,
                        after,
                    ),
                    marker,
                    supported,
                ),
                identity,
            )
            return CollectionResponse(
                workspace_id=UUID(identity.workspace_id),
                runtime_epoch=UUID(identity.epoch),
                scope=query.scope,
                supported_sources=supported,
                result=composed.result,
                as_of=instant,
                source_revision=marker,
                next_transition_at=composed.result.capture.next_transition_at,
            )

        return self.unit_of_work.read(read)

    @staticmethod
    def _continued(composed, identity):
        if composed.result.status != "available":
            return composed
        section = composed.result
        target = section.view_all_target
        start = AttentionCursor(
            _filters(target.scope, target.collection, target.horizon_days),
            (identity.workspace_id, identity.epoch),
            section.capture.source_revision,
            section.capture.as_of,
            None,
        ).encode()
        cursor = (
            AttentionCursor(
                _filters(target.scope, target.collection, target.horizon_days),
                (identity.workspace_id, identity.epoch),
                section.capture.source_revision,
                section.capture.as_of,
                composed.next_key,
            ).encode()
            if composed.next_key is not None
            else None
        )
        return replace(
            composed,
            result=section.model_copy(update={"next_cursor": cursor, "view_all_cursor": start}),
        )

    def collection(
        self,
        query: CollectionQuery,
        *,
        as_of: datetime | None = None,
        after: AttentionKey | None = None,
    ) -> ComposedCollection:
        """Internal frozen-page operation for source composition checks."""
        _, instant = self._context()
        instant = as_of or instant

        def read(tx):
            tx.validate_scope(query.scope)
            return self._collection(
                tx,
                query.scope,
                AttentionWindow(
                    instant,
                    query.collection.value,
                    query.scope.property_id,
                    query.horizon_days,
                    query.limit,
                    after,
                ),
                tx.source_marker(),
                tx.supported_sources(),
            )

        return self.unit_of_work.read(read)

    @staticmethod
    def _collection(
        tx: HomeReadTransaction,
        scope,
        window: AttentionWindow,
        marker,
        supported,
    ):
        collection, instant, limit = Collection(window.collection), window.as_of, window.limit
        target = CollectionTarget(
            collection=collection, scope=scope, horizon_days=window.horizon_days
        )
        dependencies = COLLECTION_DEPENDENCIES[collection]
        if not dependencies.issubset(supported):
            return _unavailable_collection(target, instant, marker, "adapter_missing")
        try:
            pages = []
            for source in SourceKind:
                if source in dependencies:
                    page = tx.attention(source, window)
                    page.validate_window(replace(window, source_kind=source.value))
                    pages.append(page)
            facts = sorted(
                (fact for page in pages for fact in page.candidates), key=lambda f: f.key
            )
            if len({fact.key for fact in facts}) != len(facts):
                raise ValueError("Home source streams must have unique canonical identities.")
            selected = tx.hydrate_locations(tuple(facts[:limit]), window)
            total = sum(page.matching_total for page in pages)
            priorities, reasons = _totals(pages, "priority_counts"), _totals(pages, "reason_counts")
            if collection == Collection.NEEDS_ACTION and (
                sum(priorities.values()) != total
                or set(priorities) - {"urgent", "overdue", "today", "review"}
            ):
                raise ValueError("Needs action counts require complete grouped priority totals.")
            result = AvailableCollection(
                collection=collection,
                capture=_capture(
                    instant, marker, _earliest(page.next_transition_at for page in pages)
                ),
                matching_total=total,
                items=tuple(home_item(fact, collection) for fact in selected),
                view_all_target=target,
            )
            return ComposedCollection(
                result,
                selected[-1].key if len(facts) > limit else None,
                priorities,
                reasons,
            )
        except OperatorSectionUnavailable, MoneyError:
            return _unavailable_collection(target, instant, marker, "source_unavailable")
        except ValueError:
            return _unavailable_collection(target, instant, marker, "source_contract_invalid")


def _capture(instant, marker, transition=None):
    return Capture(
        as_of=instant,
        source_revision=marker,
        read_mode="live",
        freshness="checked",
        checked_at=instant,
        next_transition_at=transition,
    )


def _unavailable_collection(target, instant, marker, reason):
    capture = _capture(instant, marker).model_copy(update={"freshness": "unavailable"})
    return ComposedCollection(
        UnavailableCollection(
            collection=target.collection,
            capture=capture,
            reason_code=reason,
            retry_target=target,
        ),
        None,
        None,
        None,
    )


def _unavailable_summary(capture, reason):
    return UnavailableSummary(
        capture=capture.model_copy(update={"freshness": "unavailable"}), reason_code=reason
    )


def _earliest(values):
    return min((value for value in values if value is not None), default=None)


def _totals(pages, attribute):
    totals = {}
    for page in pages:
        for name, count in getattr(page, attribute):
            totals[name] = totals.get(name, 0) + count
    return totals


def _filters(scope, collection, horizon):
    return {
        "scope": scope.model_dump(mode="json", by_alias=True),
        "collection": collection.value,
        "horizonDays": horizon,
    }


def _inventory_filters(scope, occupancy):
    return {
        "scope": scope.model_dump(mode="json", by_alias=True),
        "occupancy": occupancy,
        "propertyState": "active",
    }


def _inventory_cursor(scope, occupancy, identity, marker, instant, last=None):
    return ReadCursor(
        "home.inventory",
        _inventory_filters(scope, occupancy),
        (identity.workspace_id, identity.epoch),
        marker,
        instant.isoformat(),
        last,
    ).encode()
