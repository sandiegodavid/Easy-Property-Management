"""Current-format validation owned by FILE-001."""
from sqlalchemy import inspect
from app.platform.migration_errors import MigrationSchemaError


def validate_file_schema(connection) -> None:
    inspector = inspect(connection)
    expected = {"file_records": {"id", "original_name", "media_type", "size_bytes", "content_sha256", "relative_path", "created_at"}, "file_links": {"id", "file_id", "entity_type", "entity_id", "purpose", "created_at"}}
    all_indexes = []
    for table, columns in expected.items():
        actual_columns = inspector.get_columns(table)
        if table not in inspector.get_table_names() or {item["name"] for item in actual_columns} != columns:
            raise MigrationSchemaError(f"{table} has an incompatible shape.")
        if {item["name"] for item in actual_columns if item["primary_key"]} != {"id"}:
            raise MigrationSchemaError(f"{table} has an incompatible primary key.")
        for column in actual_columns:
            expected_integer = table == "file_records" and column["name"] == "size_bytes"
            actual_type = str(column["type"]).upper()
            if (expected_integer and "INT" not in actual_type) or (not expected_integer and not ("TEXT" in actual_type or "CHAR" in actual_type)):
                raise MigrationSchemaError(f"{table} has incompatible column types.")
            if column["nullable"] and not column["primary_key"]:
                raise MigrationSchemaError(f"{table} has incompatible nullability.")
        all_indexes.extend(inspector.get_indexes(table))
    indexes = {item["name"]: tuple(item["column_names"]) for item in all_indexes}
    if indexes.get("file_records_content") != ("content_sha256",) or indexes.get("file_links_entity") != ("entity_type", "entity_id"):
        raise MigrationSchemaError("FILE-001 indexes are incompatible.")
    if any(item.get("unique") for item in all_indexes) or inspector.get_unique_constraints("file_records") or inspector.get_unique_constraints("file_links"):
        raise MigrationSchemaError("FILE-001 uniqueness is incompatible.")
    foreign_keys = inspector.get_foreign_keys("file_links")
    if not any(key["constrained_columns"] == ["file_id"] and key["referred_table"] == "file_records" for key in foreign_keys):
        raise MigrationSchemaError("file_links foreign key is missing.")
    checks = {"".join((item.get("sqltext") or "").lower().replace("(", "").replace(")", "").split()) for item in inspector.get_check_constraints("file_records")}
    if checks != {"size_bytes>=0"}:
        raise MigrationSchemaError("file_records constraints are incompatible.")
