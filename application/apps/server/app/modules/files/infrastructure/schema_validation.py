"""Current-format validation owned by FILE-001."""
from sqlalchemy import inspect
from app.platform.migration_errors import MigrationSchemaError


def validate_file_schema(connection) -> None:
    inspector = inspect(connection)
    expected = {
        "file_records": {"id", "original_name", "media_type", "size_bytes", "content_sha256", "created_at"},
        "file_links": {"id", "file_id", "entity_type", "entity_id", "purpose", "created_at"},
        "file_content_locations": {"file_id", "storage_provider", "storage_state", "local_relative_path", "s3_bucket", "s3_object_key", "s3_version_id", "provider_etag", "verified_at"},
    }
    all_indexes = []
    for table, columns in expected.items():
        actual_columns = inspector.get_columns(table)
        if table not in inspector.get_table_names() or {item["name"] for item in actual_columns} != columns:
            raise MigrationSchemaError(f"{table} has an incompatible shape.")
        expected_pk = {"file_id"} if table == "file_content_locations" else {"id"}
        if {item["name"] for item in actual_columns if item["primary_key"]} != expected_pk:
            raise MigrationSchemaError(f"{table} has an incompatible primary key.")
        for column in actual_columns:
            expected_integer = table == "file_records" and column["name"] == "size_bytes"
            actual_type = str(column["type"]).upper()
            if (expected_integer and "INT" not in actual_type) or (not expected_integer and not ("TEXT" in actual_type or "CHAR" in actual_type)):
                raise MigrationSchemaError(f"{table} has incompatible column types.")
            nullable = table == "file_content_locations" and column["name"] in {"local_relative_path", "s3_bucket", "s3_object_key", "s3_version_id", "provider_etag"}
            if bool(column["nullable"]) != nullable and not column["primary_key"]:
                raise MigrationSchemaError(f"{table} has incompatible nullability.")
        all_indexes.extend(inspector.get_indexes(table))
    indexes = {item["name"]: tuple(item["column_names"]) for item in all_indexes}
    if indexes.get("file_records_content") != ("content_sha256",) or indexes.get("file_links_entity") != ("entity_type", "entity_id") or indexes.get("file_content_locations_provider") != ("storage_provider", "local_relative_path", "s3_bucket", "s3_object_key"):
        raise MigrationSchemaError("FILE-001 indexes are incompatible.")
    if any(item.get("unique") for item in all_indexes) or any(inspector.get_unique_constraints(table) for table in expected):
        raise MigrationSchemaError("FILE-001 uniqueness is incompatible.")
    foreign_keys = inspector.get_foreign_keys("file_links")
    if not any(key["constrained_columns"] == ["file_id"] and key["referred_table"] == "file_records" for key in foreign_keys):
        raise MigrationSchemaError("file_links foreign key is missing.")
    location_foreign_keys = inspector.get_foreign_keys("file_content_locations")
    if not any(key["constrained_columns"] == ["file_id"] and key["referred_table"] == "file_records" for key in location_foreign_keys):
        raise MigrationSchemaError("file content location foreign key is missing.")
    checks = {"".join((item.get("sqltext") or "").lower().replace("(", "").replace(")", "").split()) for item in inspector.get_check_constraints("file_records")}
    if checks != {"size_bytes>=0"}:
        raise MigrationSchemaError("file_records constraints are incompatible.")
    location_checks = {"".join((item.get("sqltext") or "").lower().replace("(", "").replace(")", "").split()) for item in inspector.get_check_constraints("file_content_locations")}
    if location_checks != {"storage_providerin'local','s3'", "storage_statein'pending','available','missing','quarantined'", "storage_provider='local'andlocal_relative_pathisnotnullands3_bucketisnullands3_object_keyisnullands3_version_idisnullorstorage_provider='s3'andlocal_relative_pathisnullands3_bucketisnotnullands3_object_keyisnotnull"}:
        raise MigrationSchemaError("file content location constraints are incompatible.")
