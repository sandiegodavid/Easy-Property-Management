"""Shared SQLAlchemy engine configuration for local SQLite workspaces."""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine import URL


def sqlite_url(database: Path) -> URL:
    return URL.create("sqlite", database=str(database.resolve()))

def create_sqlite_engine(database: Path) -> Engine:
    engine = create_engine(sqlite_url(database))

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        # Explicit BEGIN keeps schema changes atomic across supported Python/SQLite
        # combinations while ordinary reads remain deferred and concurrent.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def begin_transaction(connection) -> None:
        statement = "BEGIN IMMEDIATE" if connection.info.pop("sqlite_immediate", False) else "BEGIN"
        connection.exec_driver_sql(statement)

    return engine


@contextmanager
def immediate_transaction(engine: Engine):
    """Acquire SQLite's write reservation without penalizing ordinary reads."""
    with engine.connect() as connection:
        connection.info["sqlite_immediate"] = True
        with connection.begin():
            yield connection
