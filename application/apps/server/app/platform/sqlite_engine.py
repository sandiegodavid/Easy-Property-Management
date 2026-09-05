"""Shared SQLAlchemy engine configuration for local SQLite workspaces."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine import URL


def sqlite_url(database: Path) -> URL:
    return URL.create("sqlite", database=str(database.resolve()))

def create_sqlite_engine(database: Path) -> Engine:
    engine = create_engine(sqlite_url(database))

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        # sqlite3 legacy transaction control autocommits DDL. Explicit BEGIN restores
        # atomic schema changes across supported Python/SQLite combinations.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def begin_transaction(connection) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine
