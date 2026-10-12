"""Pure SQLite JSON bridges for source-owned coverage projections."""

import json
from dataclasses import asdict

from sqlalchemy import func, literal


def json_fields(columns, names):
    return func.json_object(*(value for name in names for value in (literal(name), columns[name])))


def register_json_function(connection, name, arguments, projection):
    def invoke(*values):
        result = projection(*(json.loads(value) if value is not None else None for value in values))
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    connection.connection.driver_connection.create_function(
        name, arguments, invoke, deterministic=True
    )


def fact_json(fact):
    return asdict(fact)
