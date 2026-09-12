"""Exact current FIN-001 schema validation."""
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect

from app.modules.finance.infrastructure.sqlalchemy_models import (
    ExpenseCategoryModel, ExpenseModel, ExpenseRefundModel,
    RentExpectationModel, RentExpectationTimelinessReviewModel,
    RentReceiptModel, RentReceiptAllocationModel,
)
from app.platform.migration_errors import MigrationSchemaError

MODELS = (
    RentExpectationModel, RentExpectationTimelinessReviewModel,
    RentReceiptModel, RentReceiptAllocationModel,
    ExpenseCategoryModel, ExpenseModel, ExpenseRefundModel,
)

def validate_finance_schema(connection):
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__
        if not inspector.has_table(table.name): raise MigrationSchemaError("Finance schema is missing.")
        actual_columns = {item["name"]: item for item in inspector.get_columns(table.name)}
        if set(actual_columns) != {column.name for column in table.columns}: raise MigrationSchemaError("Finance columns are incompatible.")
        for expected in table.columns:
            actual = actual_columns[expected.name]
            if bool(actual["primary_key"]) != expected.primary_key or bool(actual["nullable"]) != expected.nullable:
                raise MigrationSchemaError("Finance column nullability or primary keys are incompatible.")
            expected_type = str(expected.type).upper()
            actual_type = str(actual["type"]).upper()
            if ("INT" in expected_type and "INT" not in actual_type) or ("INT" not in expected_type and not ("TEXT" in actual_type or "CHAR" in actual_type)):
                raise MigrationSchemaError("Finance column types are incompatible.")
        expected_fks = {(tuple(element.parent.name for element in item.elements), item.elements[0].column.table.name, tuple(element.column.name for element in item.elements)) for item in table.constraints if isinstance(item, ForeignKeyConstraint)}
        actual_fks = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table.name)}
        if actual_fks != expected_fks: raise MigrationSchemaError("Finance foreign keys are incompatible.")
        expected_indexes = {item.name: (tuple(column.name for column in item.columns), bool(item.unique), _where(item.dialect_options["sqlite"].get("where"))) for item in table.indexes}
        actual_indexes = {item["name"]: (tuple(item["column_names"]), bool(item.get("unique")), _where(item.get("dialect_options", {}).get("sqlite_where"))) for item in inspector.get_indexes(table.name)}
        if actual_indexes != expected_indexes: raise MigrationSchemaError("Finance indexes are incompatible.")
        expected_unique = {tuple(column.name for column in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)}
        actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        if actual_unique != expected_unique: raise MigrationSchemaError("Finance unique constraints are incompatible.")
        expected_checks = {_normalise(item.sqltext.text) for item in table.constraints if isinstance(item, CheckConstraint)}
        actual_checks = {_normalise(item.get("sqltext") or "") for item in inspector.get_check_constraints(table.name)}
        if actual_checks != expected_checks: raise MigrationSchemaError("Finance checks are incompatible.")

def _normalise(value: str) -> str:
    parts = value.split("'")
    return "'".join(part if index % 2 else "".join(part.lower().split()) for index, part in enumerate(parts))


def _where(value) -> str | None:
    return None if value is None else _normalise(str(value))
