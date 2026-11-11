"""Protected singleton binding helper; schema-ready never implies host readiness."""

from pathlib import Path

from sqlalchemy import Connection, MetaData, Table, select

from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_schema import HostedSchemaError, validate_schema
from app.platform.schema_resources import HostedStore


def bind_metadata(
    connection: Connection,
    metadata: SemanticRequest,
    *,
    store: HostedStore,
    application_directory: Path,
) -> bool:
    """Bind only protected metadata in a caller-owned write; true means newly inserted.

    No commit/close, defaults, policy, release, principal, resource or session seed.
    Owning adapters provide their typed metadata; an existing mismatch is never reset.
    """
    names = {HostedStore.ADMIN: "control_meta", HostedStore.HOST_INVENTORY: "host_identity"}
    validate_schema(connection, store, application_directory=application_directory)
    if not connection.connection.driver_connection.in_transaction:
        raise HostedSchemaError()
    table = Table(names[store], MetaData(), autoload_with=connection, schema="main")
    expected = {"id": 1, **metadata.model_dump()}
    if set(expected) != set(table.c.keys()):
        raise HostedSchemaError()
    rows = list(connection.execute(select(table)).mappings())
    if rows:
        if rows != [expected]:
            raise HostedSchemaError()
        return False
    connection.execute(table.insert().values(**expected))
    return True
