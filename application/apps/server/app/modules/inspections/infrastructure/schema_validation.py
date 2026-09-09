"""Exact current INSP-001 schema validation."""
from sqlalchemy import inspect
from sqlalchemy.dialects import sqlite
from app.platform.migration_errors import MigrationSchemaError
from app.modules.inspections.infrastructure.sqlalchemy_models import ConditionAcknowledgmentModel, ConditionAreaModel, ConditionChecklistTemplateItemModel, ConditionChecklistTemplateModel, ConditionComparisonModel, ConditionObservationModel, ConditionReportModel

MODELS = (ConditionReportModel, ConditionAreaModel, ConditionObservationModel, ConditionAcknowledgmentModel, ConditionComparisonModel, ConditionChecklistTemplateModel, ConditionChecklistTemplateItemModel)
def _sql(value): return " ".join(str(value).replace('"','').replace("'", "'").replace("condition_reports.", "").replace("condition_comparisons.", "").split()).casefold()
def _index_where(value):
    if value is None or isinstance(value, str) and value == "": return ""
    return _sql(value.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})) if hasattr(value, "compile") else _sql(value)

def validate_inspection_schema(connection) -> None:
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__
        if not inspector.has_table(table.name): raise MigrationSchemaError(f"{table.name} is missing for INSP-001.")
        actual = {item["name"]: item for item in inspector.get_columns(table.name)}
        expected = {item.name: item for item in table.columns}
        if set(actual) != set(expected): raise MigrationSchemaError(f"{table.name} columns are incompatible with INSP-001.")
        for name, column in expected.items():
            if str(actual[name]["type"]).upper() != str(column.type).upper() or bool(actual[name]["nullable"]) != bool(column.nullable): raise MigrationSchemaError(f"{table.name}.{name} is incompatible with INSP-001.")
        if {item["name"] for item in inspector.get_columns(table.name) if item["primary_key"]} != {item.name for item in table.primary_key.columns}: raise MigrationSchemaError(f"{table.name} primary key is incompatible with INSP-001.")
        actual_fks = {(item["constrained_columns"][0], item["referred_table"], item["referred_columns"][0]) for item in inspector.get_foreign_keys(table.name)}
        expected_fks = {(fk.parent.name, fk.column.table.name, fk.column.name) for column in table.columns for fk in column.foreign_keys}
        if actual_fks != expected_fks: raise MigrationSchemaError(f"{table.name} foreign keys are incompatible with INSP-001.")
        actual_indexes = {(item["name"], tuple(item["column_names"]), bool(item["unique"]), _index_where(item.get("dialect_options", {}).get("sqlite_where", ""))) for item in inspector.get_indexes(table.name)}
        expected_indexes = {(item.name, tuple(column.name for column in item.columns), bool(item.unique), _index_where(item.dialect_options["sqlite"].get("where", ""))) for item in table.indexes}
        if actual_indexes != expected_indexes: raise MigrationSchemaError(f"{table.name} indexes are incompatible with INSP-001.")
        actual_checks = {_sql(item["sqltext"]) for item in inspector.get_check_constraints(table.name)}
        expected_checks = {_sql(item.sqltext) for item in table.constraints if item.__class__.__name__ == "CheckConstraint"}
        if actual_checks != expected_checks: raise MigrationSchemaError(f"{table.name} constraints are incompatible with INSP-001.")
        actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        expected_unique = {tuple(item.columns.keys()) for item in table.constraints if item.__class__.__name__ == "UniqueConstraint"}
        expected_unique |= {(column.name,) for column in table.columns if column.unique}
        if actual_unique != expected_unique: raise MigrationSchemaError(f"{table.name} unique constraints are incompatible with INSP-001.")
