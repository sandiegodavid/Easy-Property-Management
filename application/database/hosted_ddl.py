"""Shared column conventions for the current hosted baselines only.

Executable schema definitions remain in database resources, never runtime fallbacks.
Loaded relative to the installed owning revision, independent of sys.path/CWD.
"""

import sqlalchemy as sa


def field(name, kind, **options):
    numeric = kind in {"TIME", "COUNT", "REV", "POSITIVE", "BOOLEAN", "UID"}
    rule = _numeric_rule(name, kind) if numeric else _text_rule(name, kind)
    if options.get("nullable", False):
        rule = f"{name} IS NULL OR ({rule})"
    default = options.pop("default", None)
    primary = options.pop("primary", False)
    return sa.Column(
        name,
        sa.Integer() if numeric else sa.Text(),
        sa.CheckConstraint(rule, name=f"ck_{name}"),
        nullable=options.pop("nullable", False),
        primary_key=primary,
        server_default=sa.text(str(default)) if default is not None else None,
        **options,
    )


def _numeric_rule(name, kind):
    minimum = 1 if kind in {"REV", "POSITIVE", "UID"} else 0
    rule = f"typeof({name})='integer' AND {name}>={minimum}"
    if kind == "BOOLEAN":
        rule += f" AND {name} IN (0,1)"
    if kind == "UID":
        rule += f" AND {name}<4294967295"
    return rule


def _text_rule(name, kind):
    bounds = {
        "ID": 36,
        "HASH": 64,
        "REF": 1024,
        "KEY": 120,
        "CODE": 80,
        "NAME": 120,
        "EMAIL": 254,
        "SLUG": 63,
        "TEXT": 1000,
        "JSON": 16384,
        "AUDIT_JSON": 8192,
        "ORIGIN": 253,
        "DOMAIN": 253,
    }
    rule = f"typeof({name})='text' AND length({name}) BETWEEN 1 AND {bounds[kind]}"
    if kind == "ID":
        rule += (
            f" AND length({name})=36 AND substr({name},9,1)='-'"
            f" AND substr({name},14,1)='-' AND substr({name},19,1)='-'"
            f" AND substr({name},24,1)='-' AND length(replace({name},'-',''))=32"
            f" AND replace({name},'-','') NOT GLOB '*[^0-9a-f]*'"
        )
    elif kind == "HASH":
        rule += f" AND length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'"
    elif kind in {"REF", "KEY"}:
        rule += (
            f" AND substr({name},1,1) GLOB '[A-Za-z0-9]' AND {name} NOT GLOB '*[^A-Za-z0-9._:-]*'"
        )
    elif kind == "CODE":
        rule += f" AND substr({name},1,1) GLOB '[a-z]' AND {name} NOT GLOB '*[^a-z0-9_]*'"
    elif kind == "SLUG":
        rule += (
            f" AND {name} NOT GLOB '*[^a-z0-9-]*'"
            f" AND substr({name},1,1) GLOB '[a-z0-9]'"
            f" AND substr({name},-1,1) GLOB '[a-z0-9]'"
        )
    elif kind in {"DOMAIN", "ORIGIN"}:
        rule += _domain_rule(name, kind)
    elif kind in {"JSON", "AUDIT_JSON"}:
        maximum = bounds[kind]
        rule += (
            f" AND length(CAST({name} AS BLOB))<={maximum}"
            f" AND json_valid({name}) AND json_type({name})='object'"
        )
    return rule


def _domain_rule(name, kind):
    rule = ""
    host = f"substr({name},9)" if kind == "ORIGIN" else name
    if kind == "ORIGIN":
        rule += f" AND substr({name},1,8)='https://'"
    rule += (
        f" AND {host} NOT GLOB '*[^a-z0-9.-]*'"
        f" AND substr({host},1,1) GLOB '[a-z0-9]'"
        f" AND substr({host},-1,1) GLOB '[a-z0-9]'"
        f" AND instr({host},'.')>0 AND instr({host},'..')=0"
        f" AND instr({host},'.-')=0 AND instr({host},'-.')=0"
    )
    return rule


def choices(name, values):
    values = ",".join(repr(value) for value in values.split())
    return sa.CheckConstraint(f"{name} IN ({values})", name=f"ck_{name}_values")


def foreign(columns, target):
    return sa.ForeignKeyConstraint(columns.split(), target.split(), ondelete="RESTRICT")


def immutable(op, table, columns=None, *, retain=True):
    """Immutable intent columns, or complete append-only tables, at the store boundary."""
    condition = (
        " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in columns.split()) if columns else "1"
    )
    op.execute(
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} "
        f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'immutable hosted record'); END"
    )
    if retain:
        op.execute(
            f"CREATE TRIGGER {table}_retained BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'retained hosted record'); END"
        )
    _reject_replacement(op, table)


def _reject_replacement(op, table):
    """INSERT OR REPLACE must not bypass immutable/append-only UPDATE/DELETE guards."""
    inspector = sa.inspect(op.get_bind())
    keys = [inspector.get_pk_constraint(table)["constrained_columns"]]
    keys.extend(item["column_names"] for item in inspector.get_unique_constraints(table))
    conflicts = " OR ".join(
        "(" + " AND ".join(f"{column}=NEW.{column}" for column in key) + ")" for key in keys if key
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} "
        f"WHEN EXISTS (SELECT 1 FROM {table} WHERE {conflicts}) "
        "BEGIN SELECT RAISE(ABORT, 'retained hosted identity'); END"
    )
