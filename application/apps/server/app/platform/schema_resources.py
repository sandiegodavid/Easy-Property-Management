"""Independent hosted resource discovery; discovery never grants database readiness.

No schema DDL, engine, initializer or production composition is defined here.
The owning H02–H05 slice replaces its scaffold environment atomically with a real
baseline, validation and initializer; discovering these resources grants no readiness.
"""

from configparser import Error as ConfigurationError
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError


class HostedStore(StrEnum):
    ADMIN = "admin"
    ADMIN_RECOVERY = "admin-recovery"
    HOST_INVENTORY = "host-inventory"
    HOSTED_ACCESS = "hosted-access"
    RECOVERY = "recovery"


IMPLEMENTED_REVISIONS = {
    HostedStore.ADMIN: "admin_0001_initial",
    HostedStore.HOST_INVENTORY: "host_inventory_0001_initial",
}


class SchemaResourcesUnavailable(RuntimeError):
    """Safe unavailable outcome; never include database paths or connection URLs."""

    code = "schema_resources_unavailable"

    def __init__(self, store: HostedStore):
        self.store = store
        super().__init__(f"{store.value} schema resources are unavailable; initialization denied.")


def scaffold_config(store: HostedStore, *, application_directory: Path) -> Config:
    """Inspect one independent resource set, without resolving/opening a database.

    The root is supplied by trusted composition/packaging, never a browser request.
    A returned configuration means only that a scaffold exists, not a usable schema.
    """
    return _configuration(HostedStore(store), application_directory, "scaffold")


def resource_config(store: HostedStore, *, application_directory: Path) -> Config:
    """Require the complete current owning baseline before inspecting any destination."""
    store = HostedStore(store)
    if store not in IMPLEMENTED_REVISIONS:
        raise SchemaResourcesUnavailable(store)
    config = _configuration(store, application_directory, "implemented")
    resource = Path(config.get_main_option("script_location"))
    baseline = resource / "versions" / f"{IMPLEMENTED_REVISIONS[store]}.py"
    helper = application_directory / "database" / "hosted_ddl.py"
    if not all(path.is_file() and not path.is_symlink() for path in (baseline, helper)):
        raise SchemaResourcesUnavailable(store)
    if set((resource / "versions").glob("*.py")) != {baseline}:
        raise SchemaResourcesUnavailable(store)
    try:
        scripts = ScriptDirectory.from_config(config)
        if scripts.get_heads() != [IMPLEMENTED_REVISIONS[store]]:
            raise SchemaResourcesUnavailable(store)
        tables = getattr(scripts.get_revision(IMPLEMENTED_REVISIONS[store]).module, "TABLES", None)
        if not isinstance(tables, tuple) or not tables or len(set(tables)) != len(tables):
            raise SchemaResourcesUnavailable(store)
        config.attributes["expected_tables"] = tables
    except (OSError, ImportError, CommandError, SyntaxError, KeyError) as error:
        raise SchemaResourcesUnavailable(store) from error
    return config


def _configuration(store, application_directory, expected_state):
    if (
        not application_directory.is_absolute()
        or application_directory.resolve() != application_directory
    ):
        raise SchemaResourcesUnavailable(store)
    resource = application_directory / "database" / f"{store.value}-migrations"
    if resource.resolve() != resource:
        raise SchemaResourcesUnavailable(store)
    required = (resource / "alembic.ini", resource / "env.py", resource / "versions")
    if not all(path.exists() and not path.is_symlink() for path in (resource, *required)):
        raise SchemaResourcesUnavailable(store)
    if not required[0].is_file() or not required[1].is_file() or not required[2].is_dir():
        raise SchemaResourcesUnavailable(store)
    config = Config(str(required[0]))
    try:
        identity = config.get_section_option("epm_schema", "store")
        state = config.get_section_option("epm_schema", "resource_state")
        prefix = config.get_section_option("epm_schema", "revision_prefix")
        location = config.get_main_option("script_location")
        versions = config.get_main_option("version_locations")
        default_url = config.get_main_option("sqlalchemy.url")
    except (ConfigurationError, CommandError) as error:
        raise SchemaResourcesUnavailable(store) from error
    expected_prefix = (
        "access_" if store == HostedStore.HOSTED_ACCESS else store.value.replace("-", "_") + "_"
    )
    if (
        identity != store.value
        or prefix != expected_prefix
        or state != expected_state
        or location != str(resource)
        or versions != str(resource / "versions")
        or default_url is not None
    ):
        raise SchemaResourcesUnavailable(store)
    return config


def reject_schema_scaffold(store: HostedStore) -> NoReturn:
    """Scaffold env.py calls this before offline output, connection use or stamping."""
    raise SchemaResourcesUnavailable(store)
