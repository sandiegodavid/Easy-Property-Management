"""Latest-format-only Alembic schema initialization and validation."""
from __future__ import annotations
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.modules.audit.infrastructure.schema_validation import validate_audit_schema
from app.modules.files.infrastructure.schema_validation import validate_file_schema
from app.modules.tasks.infrastructure.schema_validation import validate_task_schema
from app.modules.tenants.infrastructure.schema_validation import validate_tenant_schema
from app.modules.portfolio.infrastructure.schema_validation import validate_portfolio_schema
from app.modules.workspace.infrastructure.schema_validation import validate_workspace_schema
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


class ProductSchemaError(MigrationSchemaError):
    """Raised when a workspace is not exactly the supported product schema."""


def _config() -> Config:
    root = Path(__file__).resolve().parents[4]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "database" / "sqlite-migrations"))
    return config


def current_revision() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def initialize_latest_schema(database_path: Path) -> None:
    """Apply the current baseline to a newly created, empty database."""
    engine = create_sqlite_engine(database_path)
    try:
        with immediate_transaction(engine) as connection:
            config = _config(); config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except Exception as error:
        raise ProductSchemaError(f"Unable to apply the current workspace schema: {error}") from error
    finally:
        engine.dispose()


def validate_latest_schema(database_path: Path) -> None:
    """Accept only the exact current Alembic revision and complete module schemas."""
    engine = create_sqlite_engine(database_path)
    try:
        with engine.connect() as connection:
            actual_tables = set(connection.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )).scalars())
            expected_tables = {
                "alembic_version", "workspace_metadata", "audit_events", "file_records",
                "file_links", "tasks", "task_reminders", "parties", "properties", "property_ownerships", "spaces",
                "space_occupancy_periods", "space_availability", "tenant_profiles", "tenant_contact_methods",
            }
            if actual_tables != expected_tables:
                raise ProductSchemaError("Workspace database contains unsupported application tables.")
            revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if revisions != [current_revision()]:
                raise ProductSchemaError("Workspace database is not at the current schema revision.")
            for validator in (validate_workspace_schema, validate_audit_schema, validate_file_schema, validate_task_schema, validate_portfolio_schema, validate_tenant_schema):
                validator(connection)
    except ProductSchemaError:
        raise
    except Exception as error:
        raise ProductSchemaError(f"Unable to validate workspace schema: {error}") from error
    finally:
        engine.dispose()
