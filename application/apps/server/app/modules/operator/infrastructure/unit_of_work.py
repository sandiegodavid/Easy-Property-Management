"""OPS-owned persistence on a caller-owned source snapshot."""

import json
from dataclasses import dataclass

from sqlalchemy import func, select, update, literal_column
from sqlalchemy.exc import DBAPIError

from app.modules.finance.application.money_ports import MoneyContextReader
from app.modules.portfolio.application.directory_ports import PortfolioDirectoryReader
from app.modules.tasks.application.ports import TaskContextReader
from app.modules.operator.infrastructure.overview_sources import OverviewSources
from app.modules.finance.application.money_models import MoneyBusy, MoneyUnavailable
from app.modules.operator.application.search_ports import MetadataSearchRegistry
from app.modules.operator.application.coverage_sources import CoverageSources
from app.modules.operator.infrastructure.sqlalchemy_models import OperatorCoverageReviewModel

from app.modules.operator.domain.models import (
    Preferences,
    OperatorStorageFailure,
    OperatorUnavailable,
    OperatorSectionUnavailable,
    canonical,
)
from app.modules.operator.infrastructure.sqlalchemy_models import (
    OperatorPreferenceModel,
    OperatorRecoveryModel,
    OperatorOperationModel,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
from app.platform.coverage import CoverageSubject
from app.platform.context_reads import ReadPage
from app.modules.operator.application.coverage_models import coverage_view


@dataclass(frozen=True)
class OperatorReadSources:
    directory: PortfolioDirectoryReader | None = None
    money: MoneyContextReader | None = None
    tasks: TaskContextReader | None = None
    overview: OverviewSources | None = None
    search: MetadataSearchRegistry | None = None
    coverage: CoverageSources | None = None


class SQLiteOperatorUnitOfWork:
    def __init__(
        self,
        database,
        recorder,
        references,
        marker,
        *,
        sources: OperatorReadSources = OperatorReadSources(),
    ):
        self.engine = create_sqlite_engine(database)
        self.recorder, self.references = recorder, references
        self.marker = marker
        self.sources = sources

    def read(self, operation):
        try:
            with self.engine.connect() as connection, connection.begin():
                return operation(
                    SQLiteOperatorTransaction(
                        connection,
                        self.recorder,
                        self.references,
                        self.marker,
                        self.sources,
                    )
                )
        except DBAPIError as error:
            if "locked" in str(error.orig).lower() or "busy" in str(error.orig).lower():
                raise OperatorUnavailable("Workspace storage is busy. Retry shortly.") from error
            raise OperatorStorageFailure(
                "Operator information could not be read safely."
            ) from error

    def write(self, operation):
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(
                    SQLiteOperatorTransaction(
                        connection,
                        self.recorder,
                        self.references,
                        self.marker,
                        self.sources,
                    )
                )
        except DBAPIError as error:
            if "locked" in str(error.orig).lower() or "busy" in str(error.orig).lower():
                raise OperatorUnavailable("Workspace storage is busy. Retry shortly.") from error
            raise OperatorStorageFailure(
                "Operator information could not be saved safely."
            ) from error


class SQLiteOperatorTransaction:
    def __init__(
        self,
        connection,
        recorder,
        references,
        marker,
        sources: OperatorReadSources = OperatorReadSources(),
    ):
        self.connection, self.recorder, self.references = connection, recorder, references
        self.marker = marker
        self.directory_reader = sources.directory
        self.money_reader, self.task_reader = sources.money, sources.tasks
        self.overview = sources.overview
        self.search = sources.search
        self.coverage = sources.coverage

    def _coverage_items(self, rows, as_of):
        references = tuple(
            dict.fromkeys(
                (CoverageSubject(row["subject_kind"], row["id"]), row["area"]) for row in rows
            )
        )
        facts = self.coverage.facts_for_subjects(self.connection, references, as_of=as_of)
        table = OperatorCoverageReviewModel.__table__
        reviews = {}
        if references:
            subjects = {subject.id for subject, _ in references}
            ranked = (
                select(
                    table.c.subject_kind,
                    table.c.subject_id,
                    table.c.area,
                    table.c.evidence_revision,
                    table.c.next_review_on,
                    table.c.created_at,
                    func.row_number()
                    .over(
                        partition_by=(table.c.subject_kind, table.c.subject_id, table.c.area),
                        order_by=literal_column("rowid").desc(),
                    )
                    .label("position"),
                )
                .where(table.c.subject_id.in_(subjects))
                .subquery()
            )
            reviews = {
                (CoverageSubject(row["subject_kind"], row["subject_id"]), row["area"]): row
                for row in self.connection.execute(
                    select(ranked).where(ranked.c.position == 1)
                ).mappings()
            }
        if any(reference not in facts for reference in references):
            raise OperatorSectionUnavailable("Coverage subject could not be read safely.")
        return {
            reference: coverage_view(reference[0], facts[reference], reviews.get(reference), as_of)
            for reference in references
        }

    def coverage_page(self, subject, window):
        if self.coverage is None or self.overview is None:
            raise OperatorSectionUnavailable("Coverage sources are not configured.")
        try:
            properties = self.overview.portfolio.property_scope(
                self.connection, subject, as_of=window.as_of
            )
            page = self.coverage.portfolio.page_for_properties(self.connection, properties, window)
            items = self._coverage_items(page.items, window.as_of)
            return ReadPage(
                page.total,
                [
                    items[CoverageSubject(row["subject_kind"], row["id"]), row["area"]]
                    for row in page.items
                ],
                page.next_key,
            )
        except DBAPIError as error:
            raise OperatorSectionUnavailable("Coverage source could not be read safely.") from error

    def coverage_previews(self, kind, ids, query, *, as_of):
        if self.coverage is None or self.overview is None:
            raise OperatorSectionUnavailable("Coverage sources are not configured.")
        if not ids:
            return {}
        try:
            groups = self.overview.portfolio.coverage_preview_groups(
                self.connection, kind, ids, query, as_of=as_of
            )
            pages = self.coverage.portfolio.previews_for_groups(
                self.connection,
                groups,
                as_of=as_of,
                include_history=query.status != "active"
                if kind == "property"
                else query.relationship_scope != "current",
            )
            items = self._coverage_items(
                [row for page in pages.values() for row in page.items], as_of
            )
            return {
                key: ReadPage(
                    page.total,
                    [
                        items[CoverageSubject(row["subject_kind"], row["id"]), row["area"]]
                        for row in page.items
                    ],
                    None,
                )
                for key, page in pages.items()
            }
        except DBAPIError as error:
            raise OperatorSectionUnavailable("Coverage source could not be read safely.") from error

    def coverage_facts(self, subject, area, *, as_of):
        if self.coverage is None:
            raise OperatorSectionUnavailable("Coverage sources are not configured.")
        try:
            return self.coverage.facts(self.connection, subject, area, as_of=as_of)
        except DBAPIError as error:
            raise OperatorSectionUnavailable("Coverage source could not be read safely.") from error

    def coverage_review(self, subject, area):
        table = OperatorCoverageReviewModel.__table__
        return (
            self.connection.execute(
                select(table)
                .where(
                    table.c.subject_kind == subject.kind,
                    table.c.subject_id == subject.id,
                    table.c.area == area,
                )
                .order_by(literal_column("rowid").desc())
                .limit(1)
            )
            .mappings()
            .first()
        )

    def coverage_operation(self, key):
        table = OperatorCoverageReviewModel.__table__
        return (
            self.connection.execute(select(table).where(table.c.idempotency_key == key))
            .mappings()
            .first()
        )

    def insert_coverage_review(self, value):
        self.connection.execute(OperatorCoverageReviewModel.__table__.insert().values(**value))

    def search_sources(self):
        if self.search is None:
            raise OperatorUnavailable("Metadata search is not configured.")
        return self.search.definitions

    def search_group(self, kind, term, window):
        if self.search is None:
            raise OperatorSectionUnavailable("Metadata search is not configured.")
        try:
            return self.search.reader(kind).search(self.connection, term, window)
        except DBAPIError as error:
            raise OperatorSectionUnavailable("Metadata source could not be read safely.") from error

    def owner_directory(self, query, *, as_of, after):
        if self.overview is None:
            raise OperatorUnavailable("Owner directory source is unavailable.")
        return self.overview.portfolio.owners(self.connection, query, as_of=as_of, after=after)

    def context_identity(self, subject):
        if self.overview is None:
            raise OperatorUnavailable("Portfolio context source is unavailable.")
        return self.overview.portfolio.identity(self.connection, subject)

    def context_collection(self, section, subject, window):
        if self.overview is None:
            raise OperatorSectionUnavailable("Context sources are not configured.")
        try:
            return self.overview.page(self.connection, section, subject, window)
        except DBAPIError as error:
            raise OperatorSectionUnavailable("Context source could not be read safely.") from error

    def context_money(self, subject, query, *, as_of, identity):
        if self.overview is None or self.money_reader is None:
            raise OperatorSectionUnavailable("Money context is not configured.")
        try:
            properties = self.overview.portfolio.property_scope(
                self.connection, subject, as_of=as_of
            )
            return self.money_reader.summary(
                self.connection, query, as_of=as_of, identity=identity, property_scope=properties
            )
        except (DBAPIError, MoneyBusy, MoneyUnavailable) as error:
            raise OperatorSectionUnavailable("Recorded money could not be read safely.") from error

    def money_summary(self, query, *, as_of, identity):
        if self.money_reader is None:
            raise OperatorUnavailable("Recorded money source is unavailable.")
        return self.money_reader.summary(self.connection, query, as_of=as_of, identity=identity)

    def task_previews(self, entity_type, entity_ids, *, as_of, limit=10):
        if self.task_reader is None:
            raise OperatorUnavailable("Task preview source is unavailable.")
        return self.task_reader.previews_for_related_entities(
            self.connection, entity_type, entity_ids, now=as_of, limit_per_parent=limit
        )

    def property_directory(self, query, *, as_of, after):
        if self.directory_reader is None:
            raise OperatorUnavailable("Property directory source is unavailable.")
        return self.directory_reader.properties(self.connection, query, as_of=as_of, after=after)

    def property_calendar_signature(self, as_of):
        if self.directory_reader is None:
            raise OperatorUnavailable("Property directory source is unavailable.")
        return self.directory_reader.calendar_signature(self.connection, as_of)

    def source_marker(self):
        return self.marker.marker(self.connection)

    def preferences(self):
        row = self.connection.execute(select(OperatorPreferenceModel.__table__)).mappings().first()
        if row is None:
            return Preferences()
        return Preferences(
            appearance=row["appearance"],
            destination_order=json.loads(row["destination_order"]),
            hidden_destination_ids=json.loads(row["hidden_destination_ids"]),
            revision=row["revision"],
            updated_at=row["updated_at"],
        )

    def save_preferences(self, value):
        values = {
            **value.model_dump(),
            "id": "workspace",
            "destination_order": canonical(value.destination_order),
            "hidden_destination_ids": canonical(value.hidden_destination_ids),
        }
        table = OperatorPreferenceModel.__table__
        if value.revision == 1:
            self.connection.execute(table.insert().values(**values))
        else:
            self.connection.execute(update(table).where(table.c.id == "workspace").values(**values))

    def operation(self, key):
        return (
            self.connection.execute(
                select(OperatorOperationModel.__table__).where(
                    OperatorOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )

    def insert_operation(self, value):
        self.connection.execute(OperatorOperationModel.__table__.insert().values(**value))

    def recovery(self, record_id):
        return (
            self.connection.execute(
                select(OperatorRecoveryModel.__table__).where(OperatorRecoveryModel.id == record_id)
            )
            .mappings()
            .first()
        )

    def save_recovery(self, value):
        table = OperatorRecoveryModel.__table__
        if value["revision"] == 1:
            self.connection.execute(table.insert().values(**value))
        else:
            self.connection.execute(update(table).where(table.c.id == value["id"]).values(**value))

    def active_recovery_count(self):
        return self.connection.execute(
            select(func.count())
            .select_from(OperatorRecoveryModel)
            .where(OperatorRecoveryModel.status.in_(("active", "outcome_unknown", "reconciled")))
        ).scalar_one()

    def recovery_page(self, *, limit, after):
        t = OperatorRecoveryModel.__table__
        predicates = [t.c.status.in_(("active", "outcome_unknown", "reconciled"))]
        total = self.connection.execute(
            select(func.count()).select_from(t).where(*predicates)
        ).scalar_one()
        if after:
            predicates.append(
                (t.c.saved_at < after[0]) | ((t.c.saved_at == after[0]) & (t.c.id < after[1]))
            )
        rows = (
            self.connection.execute(
                select(
                    t.c.id,
                    t.c.form_key,
                    t.c.schema_version,
                    t.c.revision,
                    t.c.status,
                    t.c.saved_at,
                    t.c.expires_at,
                    t.c.source_kind,
                    t.c.source_id,
                    t.c.base_source_revision,
                )
                .where(*predicates)
                .order_by(t.c.saved_at.desc(), t.c.id.desc())
                .limit(limit + 1)
            )
            .mappings()
            .all()
        )
        return total, rows

    def expired_recovery(self, now, limit):
        t = OperatorRecoveryModel.__table__
        return (
            self.connection.execute(
                select(t)
                .where(t.c.status.in_(("active", "reconciled")), t.c.expires_at <= now)
                .order_by(t.c.expires_at, t.c.id)
                .limit(limit)
            )
            .mappings()
            .all()
        )

    def validate_recovery(self, value):
        return self.references.validate(self.connection, value)

    def attempt_fingerprint(self, value, key):
        return self.references.attempt_fingerprint(value, key)

    def resolve_attempt(self, value):
        from app.modules.operator.application.command_forms import COMMAND_SCHEMAS

        if value["form_key"] in COMMAND_SCHEMAS:
            return self.references.resolve_attempt(
                self.connection,
                value["form_key"],
                value["attempt_key"],
                value["request_fingerprint"],
                source_id=value["source_id"],
            )
        return self.references.resolve_attempt(
            self.connection, value["form_key"], value["attempt_key"], value["request_fingerprint"]
        )

    def record_change(self, **change):
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            reason="Operator support record changed.",
            **change,
        )
