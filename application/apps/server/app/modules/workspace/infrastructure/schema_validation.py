"""Current-format validation owned by the workspace module."""
from sqlalchemy import inspect
from app.platform.migration_errors import MigrationSchemaError


def validate_workspace_schema(connection) -> None:
    inspector = inspect(connection)
    if "workspace_metadata" not in inspector.get_table_names():
        raise MigrationSchemaError("workspace_metadata is missing.")
    columns = {column["name"]: column for column in inspector.get_columns("workspace_metadata")}
    if set(columns) != {"singleton", "workspace_id", "format_version", "created_at"}:
        raise MigrationSchemaError("workspace_metadata has an incompatible shape.")
    expected_types = {"singleton": "INT", "workspace_id": "TEXT_OR_CHAR", "format_version": "INT", "created_at": "TEXT_OR_CHAR"}
    for name, expected_type in expected_types.items():
        actual_type = str(columns[name]["type"]).upper()
        matches = expected_type in actual_type if expected_type != "TEXT_OR_CHAR" else ("TEXT" in actual_type or "CHAR" in actual_type)
        if not matches:
            raise MigrationSchemaError("workspace_metadata has incompatible column types.")
        if columns[name].get("nullable"):
            raise MigrationSchemaError("workspace_metadata has incompatible nullability.")
    if {name for name, column in columns.items() if column.get("primary_key")} != {"singleton"}:
        raise MigrationSchemaError("workspace_metadata singleton key is invalid.")
    unique = inspector.get_unique_constraints("workspace_metadata")
    if len(unique) != 1 or unique[0].get("column_names") != ["workspace_id"]:
        raise MigrationSchemaError("workspace_metadata workspace identity must be unique.")
    checks = {"".join((item.get("sqltext") or "").lower().replace("(", "").replace(")", "").split()) for item in inspector.get_check_constraints("workspace_metadata")}
    if checks != {"singleton=1"}:
        raise MigrationSchemaError("workspace_metadata singleton constraint is invalid.")
