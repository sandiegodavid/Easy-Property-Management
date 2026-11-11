"""Discovery and fail-closed errors for not-yet-implemented hosted schema resources.

No schema DDL, engine, initializer or production composition is defined here.
The owning H02–H05 slice replaces its scaffold environment atomically with a real
baseline, validation and initializer; discovering these resources grants no readiness.
"""

from configparser import Error as ConfigurationError
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from alembic.config import Config
from alembic.util import CommandError


class HostedStore(StrEnum):
    ADMIN = "admin"
    ADMIN_RECOVERY = "admin-recovery"
    HOST_INVENTORY = "host-inventory"
    HOSTED_ACCESS = "hosted-access"
    RECOVERY = "recovery"


class SchemaResourcesUnavailable(RuntimeError):
    """Safe unavailable outcome; never include database paths or connection URLs."""

    code = "schema_resources_unavailable"

    def __init__(self, store: HostedStore):
        self.store = store
        super().__init__(
            f"{store.value} schema resources are not implemented; initialization denied."
        )


def scaffold_config(store: HostedStore, *, application_directory: Path) -> Config:
    """Inspect one independent resource set, without resolving/opening a database.

    The root is supplied by trusted composition/packaging, never a browser request.
    A returned configuration means only that a scaffold exists, not a usable schema.
    """
    store = HostedStore(store)
    resource = application_directory / "database" / f"{store.value}-migrations"
    required = (resource / "alembic.ini", resource / "env.py", resource / "versions")
    if not all(path.exists() and not path.is_symlink() for path in (resource, *required)):
        raise SchemaResourcesUnavailable(store)
    if not required[0].is_file() or not required[1].is_file() or not required[2].is_dir():
        raise SchemaResourcesUnavailable(store)
    config = Config(str(required[0]))
    try:
        identity = config.get_section_option("epm_schema", "store")
        state = config.get_section_option("epm_schema", "resource_state")
    except (ConfigurationError, CommandError) as error:
        raise SchemaResourcesUnavailable(store) from error
    if identity != store.value or state != "scaffold":
        raise SchemaResourcesUnavailable(store)
    return config


def reject_schema_scaffold(store: HostedStore) -> NoReturn:
    """Scaffold env.py calls this before offline output, connection use or stamping."""
    raise SchemaResourcesUnavailable(store)
