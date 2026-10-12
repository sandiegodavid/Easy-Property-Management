"""Home sources share one deferred SQLite snapshot and no write authority."""

from dataclasses import replace

from sqlalchemy import select, union_all
from sqlalchemy.exc import DBAPIError
from app.modules.finance.application.money_models import MoneyError

from app.modules.operator.application.home_money import money_on_home_snapshot
from app.modules.operator.application.home_ports import HomeSources, HomeAdapterMissing
from app.modules.operator.application.home_vocabulary import SourceKind
from app.modules.operator.domain.models import (
    OperatorSectionUnavailable,
    OperatorStorageFailure,
    OperatorUnavailable,
)
from app.platform.sqlite_engine import create_sqlite_engine


class SQLiteHomeUnitOfWork:
    def __init__(self, database, sources: HomeSources, marker):
        self.engine = create_sqlite_engine(database)
        self.sources, self.marker = sources, marker

    def read(self, operation):
        try:
            with self.engine.connect() as connection, connection.begin():
                return operation(SQLiteHomeReadTransaction(connection, self.sources, self.marker))
        except DBAPIError as error:
            if "locked" in str(error.orig).lower() or "busy" in str(error.orig).lower():
                raise OperatorUnavailable("Workspace storage is busy. Retry shortly.") from error
            raise OperatorStorageFailure("Home information could not be read safely.") from error


class SQLiteHomeReadTransaction:
    def __init__(self, connection, sources, marker):
        self.connection, self.sources, self.marker = (
            connection,
            sources,
            marker,
        )

    def supported_sources(self):
        return self.sources.supported_sources()

    def source_marker(self):
        return self.marker.marker(self.connection)

    def validate_scope(self, scope):
        if not all(
            callable(getattr(self.sources.portfolio, method, None))
            for method in ("validate_scope", "attention_labels")
        ):
            raise HomeAdapterMissing("Home property context adapter is unavailable.")
        self.sources.portfolio.validate_scope(self.connection, scope.property_id)

    def attention(self, source, window):
        reader = self.sources.attention_registry()[source]
        if reader is None:
            raise OperatorSectionUnavailable("Home source adapter is unavailable.")
        window = replace(window, source_kind=source.value)
        if source == SourceKind.TASK:
            return reader.standalone_attention(self.connection, window, self._grouped_tasks(window))
        return reader.attention(self.connection, window)

    def _grouped_tasks(self, window):
        tasks = self.sources.tasks.facts(self.connection, window)
        relations = []
        for reader, kind, parent_column in (
            (self.sources.maintenance, "maintenance_issue", "issue_id"),
            (self.sources.concerns, "owner_concern", "concern_id"),
        ):
            if reader is None:
                raise OperatorSectionUnavailable("Task grouping source is unavailable.")
            links = reader.follow_up_relations()
            relations.append(
                select(tasks.c.id.label("task_id"))
                .join(links, tasks.c.id == links.c.task_id)
                .where(
                    tasks.c.related_entity_type == kind,
                    tasks.c.related_entity_id == links.c[parent_column],
                )
            )
        return union_all(*relations).subquery("home_grouped_tasks")

    def inventory(self, window):
        if not callable(getattr(self.sources.portfolio, "inventory", None)):
            raise HomeAdapterMissing("Home inventory adapter is unavailable.")
        return self.sources.portfolio.inventory(self.connection, window.property_id, window.as_of)

    def hydrate_locations(self, facts, window):
        properties = tuple(dict.fromkeys(fact.property_id for fact in facts if fact.property_id))
        spaces = tuple(dict.fromkeys(fact.space_id for fact in facts if fact.space_id))
        labels = self.sources.portfolio.attention_labels(self.connection, properties, spaces)
        if set(labels.property_names) != set(properties) or set(labels.space_names) != set(spaces):
            raise ValueError("Selected Home locations must retain their source identities.")
        return tuple(
            replace(
                fact,
                property_name=labels.property_names.get(fact.property_id),
                space_name=labels.space_names.get(fact.space_id),
            )
            for fact in facts
        )

    def money(self, query, window, *, identity):
        if not callable(getattr(self.sources.money, "summary", None)):
            raise HomeAdapterMissing("Home money adapter is unavailable.")
        try:
            return money_on_home_snapshot(
                self.sources.money,
                self.connection,
                query,
                as_of=window.as_of,
                identity=identity,
            )
        except MoneyError as error:
            if isinstance(error.__cause__, DBAPIError):
                raise error.__cause__
            raise
