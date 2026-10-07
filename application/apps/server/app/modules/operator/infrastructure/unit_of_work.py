"""OPS-owned persistence on a caller-owned source snapshot."""

import json

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from app.modules.operator.domain.models import (
    Preferences,
    OperatorStorageFailure,
    OperatorUnavailable,
    canonical,
)
from app.modules.operator.infrastructure.sqlalchemy_models import (
    OperatorPreferenceModel,
    OperatorRecoveryModel,
    OperatorOperationModel,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


class SQLiteOperatorUnitOfWork:
    def __init__(self, database, recorder, references, marker):
        self.engine = create_sqlite_engine(database)
        self.recorder, self.references = recorder, references
        self.marker = marker

    def read(self, operation):
        try:
            with self.engine.connect() as connection, connection.begin():
                return operation(
                    SQLiteOperatorTransaction(
                        connection, self.recorder, self.references, self.marker
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
                        connection, self.recorder, self.references, self.marker
                    )
                )
        except DBAPIError as error:
            if "locked" in str(error.orig).lower() or "busy" in str(error.orig).lower():
                raise OperatorUnavailable("Workspace storage is busy. Retry shortly.") from error
            raise OperatorStorageFailure(
                "Operator information could not be saved safely."
            ) from error


class SQLiteOperatorTransaction:
    def __init__(self, connection, recorder, references, marker):
        self.connection, self.recorder, self.references = connection, recorder, references
        self.marker = marker

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

    def resolve_attempt(self, value):
        return self.references.resolve_attempt(
            self.connection, value["form_key"], value["attempt_key"], value["request_fingerprint"]
        )

    def record_change(self, **change):
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            reason="Operator support record changed.",
            **change,
        )
