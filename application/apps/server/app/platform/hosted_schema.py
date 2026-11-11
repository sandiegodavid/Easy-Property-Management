"""Current hosted schema initialization and resource-derived structural validation.

No DDL lives here: only owning Alembic resources may create a schema. No production
startup/route is registered. Schema readiness is not host, identity or access readiness.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat

from alembic import command, context
from alembic.config import Config
from sqlalchemy import Connection, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.platform.schema_resources import (
    HostedStore,
    IMPLEMENTED_REVISIONS,
    SchemaResourcesUnavailable,
    resource_config,
)

_RUN_PERMISSION = object()
PRIVATE_FILE_MODE = 0o600


class HostedSchemaError(RuntimeError):
    code = "hosted_schema_invalid"

    def __init__(self):
        super().__init__("The private store does not match its current owning schema or binding.")


class InitializationResult(StrEnum):
    INITIALIZED = "initialized"
    ALREADY_INITIALIZED = "already_initialized"


def run_resource_environment(store: HostedStore) -> None:
    """Alembic resource entry point: only the owning transactional runner may upgrade."""
    config = context.config
    connection = config.attributes.get("connection")
    if (
        config.attributes.get("run_permission") is not _RUN_PERMISSION
        or config.attributes.get("store") != store
        or context.is_offline_mode()
        or not isinstance(connection, Connection)
        or not connection.in_transaction()
    ):
        raise SchemaResourcesUnavailable(store)
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


def _connection_checks(connection: Connection) -> None:
    if connection.dialect.name != "sqlite":
        raise HostedSchemaError()
    databases = connection.exec_driver_sql("PRAGMA database_list").all()
    if any(row[1] not in {"main", "temp"} for row in databases):
        raise HostedSchemaError()
    if any(row[1] == "temp" for row in databases):
        if connection.exec_driver_sql("SELECT 1 FROM temp.sqlite_schema LIMIT 1").first():
            raise HostedSchemaError()
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
        raise HostedSchemaError()


def _structure(connection: Connection) -> tuple:
    return tuple(
        connection.exec_driver_sql(
            "SELECT type,name,tbl_name,sql FROM main.sqlite_schema "
            "WHERE name NOT GLOB 'sqlite_*' ORDER BY type,name"
        ).all()
    )


def _run_baseline(connection: Connection, config: Config, store: HostedStore) -> None:
    config.attributes.update(connection=connection, store=store, run_permission=_RUN_PERMISSION)
    try:
        command.upgrade(config, IMPLEMENTED_REVISIONS[store])
    finally:
        for key in ("connection", "store", "run_permission"):
            config.attributes.pop(key, None)


def _expected_structure(config: Config, store: HostedStore) -> tuple:
    engine = create_engine("sqlite://", poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            _run_baseline(connection, config, store)
            result = _structure(connection)
            tables = {row[1] for row in result if row[0] == "table"}
            if tables != {*config.attributes["expected_tables"], "alembic_version"}:
                raise SchemaResourcesUnavailable(store)
            connection.rollback()
            return result
    finally:
        engine.dispose()


def validate_schema(
    connection: Connection, store: HostedStore, *, application_directory: Path
) -> str:
    """Validate actual tables/checks/FKs/indexes/triggers and rows without committing.

    Caller owns the connection and snapshot. Return a resource-derived fingerprint,
    not a second editable registry or permission to dispatch effects.
    """
    store = HostedStore(store)
    config = resource_config(store, application_directory=application_directory)
    _connection_checks(connection)
    if not connection.connection.driver_connection.in_transaction:
        raise HostedSchemaError()
    expected = _expected_structure(config, store)
    actual = _structure(connection)
    if actual != expected:
        raise HostedSchemaError()
    versions = connection.exec_driver_sql("SELECT version_num FROM main.alembic_version").all()
    if versions != [(IMPLEMENTED_REVISIONS[store],)]:
        raise HostedSchemaError()
    if connection.exec_driver_sql("PRAGMA main.foreign_key_check").first() is not None:
        raise HostedSchemaError()
    if connection.exec_driver_sql("PRAGMA main.quick_check").all() != [("ok",)]:
        raise HostedSchemaError()
    return sha256(repr(expected).encode()).hexdigest()


def create_schema(
    connection: Connection, store: HostedStore, *, application_directory: Path
) -> None:
    """Create in an explicitly owned empty transaction; never commit/close the caller.

    SQLite must already be in a real transaction (not merely SQLAlchemy autobegin).
    A supplied store may not be attached to another authority's database.
    """
    store = HostedStore(store)
    config = resource_config(store, application_directory=application_directory)
    _connection_checks(connection)
    raw = connection.connection.driver_connection
    if not connection.in_transaction() or not raw.in_transaction or _structure(connection):
        raise HostedSchemaError()
    _run_baseline(connection, config, store)
    validate_schema(connection, store, application_directory=application_directory)


@contextmanager
def _private_file(destination: Path) -> Iterator[tuple[bool, os.stat_result]]:
    """Require a canonical, private caller-owned directory and a non-linked 0600 file."""
    parent = destination.parent
    if not destination.is_absolute() or parent.resolve() != parent:
        raise HostedSchemaError()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(parent, flags)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise HostedSchemaError()
        try:
            file = os.open(
                destination.name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=directory,
            )
            fresh = True
        except FileExistsError:
            file = os.open(
                destination.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            fresh = False
        try:
            info = os.fstat(file)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != PRIVATE_FILE_MODE
            ):
                raise HostedSchemaError()
            yield fresh, info
        finally:
            os.close(file)
    finally:
        os.close(directory)


def _open_existing(destination: Path, info: os.stat_result, *, readonly: bool):
    current = destination.lstat()
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise HostedSchemaError()
    mode = "ro" if readonly else "rw"
    raw = sqlite3.connect(destination.as_uri() + f"?mode={mode}", uri=True, isolation_level=None)
    raw.execute("PRAGMA foreign_keys=ON")
    if readonly:
        raw.execute("PRAGMA query_only=ON")
    return raw


def initialize_store(
    store: HostedStore, destination: Path, *, application_directory: Path
) -> InitializationResult:
    """Exclusive fresh reserve or exact read-only reinit; retain failed/partial evidence."""
    store = HostedStore(store)
    config = resource_config(store, application_directory=application_directory)
    _expected_structure(config, store)
    try:
        with _private_file(destination) as (fresh, info):
            engine = create_engine(
                "sqlite://",
                poolclass=NullPool,
                creator=lambda: _open_existing(destination, info, readonly=not fresh),
            )
            try:
                with engine.connect() as connection:
                    if fresh:
                        connection.exec_driver_sql("BEGIN IMMEDIATE")
                        try:
                            create_schema(
                                connection, store, application_directory=application_directory
                            )
                            connection.commit()
                        except BaseException:
                            connection.rollback()
                            raise
                    else:
                        connection.exec_driver_sql("BEGIN")
                        validate_schema(
                            connection, store, application_directory=application_directory
                        )
            finally:
                engine.dispose()
        return (
            InitializationResult.INITIALIZED if fresh else InitializationResult.ALREADY_INITIALIZED
        )
    except (OSError, sqlite3.Error, SQLAlchemyError) as error:
        raise HostedSchemaError() from error
