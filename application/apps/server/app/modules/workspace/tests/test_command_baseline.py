"""The current baseline creates and removes the scoped command-receipt objects."""

from alembic import command
from sqlalchemy import inspect

from app.platform.product_migrations import (
    _config,
    initialize_latest_schema,
    validate_latest_schema,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


def test_command_baseline_downgrade_removes_owning_receipt_objects(tmp_path):
    database = tmp_path / "commands.sqlite"
    initialize_latest_schema(database)
    validate_latest_schema(database)
    engine = create_sqlite_engine(database)
    try:
        with immediate_transaction(engine) as connection:
            config = _config()
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            receipt_tables = {
                "task_mutation_operations",
                "communication_operations",
                "maintenance_command_receipts",
                "space_status_operations",
            }
            assert not receipt_tables.intersection(inspect(connection).get_table_names())
            remaining_triggers = set(
                connection.exec_driver_sql(
                    "SELECT tbl_name FROM sqlite_master WHERE type='trigger'"
                ).scalars()
            )
            assert not receipt_tables.intersection(remaining_triggers)
    finally:
        engine.dispose()
