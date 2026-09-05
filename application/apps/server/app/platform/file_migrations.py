"""Alembic-owned FILE-001 schema adoption and upgrade."""
from __future__ import annotations
from pathlib import Path
import sqlite3
from contextlib import closing
from uuid import uuid4
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from app.modules.audit.domain.models import AuditEvent
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.platform.sqlite_engine import create_sqlite_engine

REVISION = "0001_file_records"
class FileMigrationError(RuntimeError): pass

def _snapshot(database_path: Path, backups_path: Path) -> None:
    directory = backups_path / "migration-safety"
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{database_path.stem}.before-file-migration.sqlite"
    temporary = directory / f".{final.name}.{uuid4().hex}.tmp"
    try:
        with closing(sqlite3.connect(database_path)) as source, closing(sqlite3.connect(temporary)) as target:
            source.backup(target); target.commit()
        with closing(sqlite3.connect(temporary)) as check:
            if check.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise FileMigrationError("Migration safety snapshot failed integrity validation.")
            if check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_metadata'").fetchone() is None:
                raise FileMigrationError("Migration safety snapshot is missing workspace metadata.")
        temporary.replace(final)
    except (OSError, sqlite3.Error) as error:
        raise FileMigrationError(f"Unable to create FILE-001 migration safety snapshot: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)

def _validate_existing(connection) -> str:
    tables = set(inspect(connection).get_table_names())
    file_tables = tables & {"file_records", "file_links"}
    if file_tables and file_tables != {"file_records", "file_links"}:
        raise FileMigrationError("Partial FILE-001 schema cannot be adopted.")
    versions = set()
    if "alembic_version" in tables:
        versions = {row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))}
        if versions and versions != {REVISION}:
            raise FileMigrationError("Unknown Alembic revision state for FILE-001.")
    if not file_tables:
        if versions == {REVISION}:
            raise FileMigrationError("FILE-001 is marked current but its tables are missing.")
        return "upgrade"
    inspector = inspect(connection)
    expected = {"file_records": {"id", "original_name", "media_type", "size_bytes", "content_sha256", "relative_path", "created_at"}, "file_links": {"id", "file_id", "entity_type", "entity_id", "purpose", "created_at"}}
    for table, names in expected.items():
        columns = inspector.get_columns(table)
        if {c["name"] for c in columns} != names or any(c["nullable"] and not c["primary_key"] for c in columns):
            raise FileMigrationError(f"Existing {table} schema is incompatible with FILE-001.")
        for column in columns:
            actual = str(column["type"]).upper()
            expected_type = "INTEGER" if table == "file_records" and column["name"] == "size_bytes" else "TEXT"
            if expected_type == "INTEGER" and "INT" not in actual:
                raise FileMigrationError(f"Existing {table} schema has incompatible column types.")
            if expected_type == "TEXT" and not ("TEXT" in actual or "CHAR" in actual):
                raise FileMigrationError(f"Existing {table} schema has incompatible column types.")
        if {c["name"] for c in columns if c["primary_key"]} != {"id"}:
            raise FileMigrationError(f"Existing {table} primary key is incompatible with FILE-001.")
    all_indexes = [*inspector.get_indexes("file_records"), *inspector.get_indexes("file_links")]
    indexes = {i["name"]: tuple(i["column_names"]) for i in all_indexes}
    if indexes.get("file_records_content") != ("content_sha256",) or indexes.get("file_links_entity") != ("entity_type", "entity_id"):
        raise FileMigrationError("Existing FILE-001 indexes are incompatible.")
    if any(i.get("unique") for i in all_indexes) or inspector.get_unique_constraints("file_records") or inspector.get_unique_constraints("file_links"):
        raise FileMigrationError("Existing FILE-001 uniqueness constraints are incompatible.")
    foreign_keys = inspector.get_foreign_keys("file_links")
    if len(foreign_keys) != 1 or not any(fk.get("referred_table") == "file_records" and fk.get("constrained_columns") == ["file_id"] and fk.get("referred_columns") == ["id"] for fk in foreign_keys):
        raise FileMigrationError("Existing file_links foreign key is incompatible.")
    constraints = {"".join((c.get("sqltext") or "").lower().replace("(", "").replace(")", "").split()) for c in inspector.get_check_constraints("file_records")}
    if constraints != {"size_bytes>=0"}:
        raise FileMigrationError("Existing file_records checks are incompatible.")
    native_v2 = False
    if "platform_schema_migrations" in tables:
        marker = connection.execute(text("SELECT MAX(version) FROM platform_schema_migrations")).scalar()
        if marker not in (None, 1, 2):
            raise FileMigrationError("Unknown native migration state for FILE-001 adoption.")
        native_v2 = marker == 2
    if versions == {REVISION}:
        return "noop"
    if not native_v2:
        raise FileMigrationError("Existing FILE-001 tables are not owned by native migration version 2.")
    return "adopt_native"

def _record_native_adoption(connection, database_path: Path) -> None:
    event = AuditEvent.change(entity_type="file_schema", entity_id=REVISION, action="adopted",
                              before_snapshot={"owner": "native_v2"}, after_snapshot={"owner": "alembic"},
                              actor_kind="system", reason="file_schema_adopted")
    SQLiteAuditRepository(database_path).append(connection.connection.driver_connection, event)

def upgrade_file_schema(database_path: Path, backups_path: Path | None = None) -> None:
    engine = create_sqlite_engine(database_path)
    try:
        with engine.connect() as connection:
            action = _validate_existing(connection)
        if action == "noop":
            return
        if backups_path is not None:
            _snapshot(database_path, backups_path)
        app_root = Path(__file__).resolve().parents[4]
        config = Config(str(app_root / "alembic.ini"))
        config.set_main_option("script_location", str(app_root / "database" / "sqlite-migrations"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            if action.startswith("adopt"):
                command.stamp(config, REVISION)
                if action == "adopt_native":
                    _record_native_adoption(connection, database_path)
            else:
                command.upgrade(config, REVISION)
    except (SQLAlchemyError, OSError, sqlite3.Error, CommandError) as error:
        raise FileMigrationError(f"Unable to apply FILE-001 migration: {error}") from error
    finally:
        engine.dispose()
