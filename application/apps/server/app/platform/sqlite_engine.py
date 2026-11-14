"""Shared SQLAlchemy engine configuration for local SQLite workspaces."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from pathlib import Path
import unicodedata

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine
from app.platform.attempt_fences import install_prepared_edit_guards, raise_closed_attempt


def sqlite_url(database: Path) -> URL:
    return URL.create("sqlite", database=str(database.resolve()))


def create_sqlite_engine(database: Path) -> Engine:
    engine = create_engine(sqlite_url(database))

    event.listen(engine, "handle_error", raise_closed_attempt)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        # Explicit BEGIN keeps schema changes atomic across supported Python/SQLite
        # combinations while ordinary reads remain deferred and concurrent.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
            dbapi_connection.create_function(
                "unicode_casefold",
                1,
                _unicode_casefold,
                deterministic=True,
            )
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def begin_transaction(connection) -> None:
        statement = "BEGIN IMMEDIATE" if connection.info.pop("sqlite_immediate", False) else "BEGIN"
        connection.exec_driver_sql(statement)

    return engine


def _unicode_casefold(value: object) -> str | None:
    """SQLite sort/search key with the same Unicode semantics as application cursors."""
    if value is None:
        return None
    return unicodedata.normalize("NFKC", str(value)).casefold()


_workspace_mutation = ContextVar("workspace_mutation", default=None)
_prepared_edit = ContextVar("prepared_edit", default="")


@contextmanager
def workspace_mutation_scope(database: Path, admit, *, namespaces, prepared_form):
    """Install a request-specific guard for the owning workspace database."""
    token = _workspace_mutation.set((sqlite_url(database), admit, namespaces, prepared_form))
    try:
        yield
    finally:
        _workspace_mutation.reset(token)


@contextmanager
def immediate_transaction(engine: Engine):
    """Acquire SQLite's write reservation without penalizing ordinary reads."""
    scope = _workspace_mutation.get()
    managed = scope is not None and engine.url == scope[0]
    guard = scope[1]() if managed else nullcontext()
    with guard as validate_commit, engine.connect() as connection:
        if managed and not connection.info.get("prepared_edit_guards"):
            install_prepared_edit_guards(
                connection.connection.driver_connection, scope[2], _prepared_edit.get
            )
            connection.info["prepared_edit_guards"] = True
        connection.info["sqlite_immediate"] = True
        token = _prepared_edit.set(scope[3] if managed else "")
        try:
            with connection.begin():
                yield connection
                if validate_commit is not None:
                    validate_commit()
        finally:
            _prepared_edit.reset(token)
