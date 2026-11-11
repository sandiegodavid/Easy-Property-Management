"""Unimplemented resources cannot initialize, stamp or touch a destination."""

from io import StringIO
from pathlib import Path
import shutil
import sqlite3

from alembic import command
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, event

from app.platform.schema_resources import (
    HostedStore,
    SchemaResourcesUnavailable,
    scaffold_config,
)

APPLICATION = Path(__file__).resolve().parents[5]
STORES = tuple(HostedStore)


@pytest.mark.parametrize("store", STORES)
def test_independent_resource_discovery_has_no_baseline_or_default_url(
    store, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    config = scaffold_config(store, application_directory=APPLICATION)
    scripts = ScriptDirectory.from_config(config)
    assert Path(scripts.dir) == APPLICATION / "database" / f"{store.value}-migrations"
    assert scripts.get_heads() == []
    assert list(scripts.walk_revisions()) == []
    assert config.get_main_option("sqlalchemy.url") is None
    assert config.get_section_option("epm_schema", "resource_state") == "scaffold"
    prefixes = {
        scaffold_config(item, application_directory=APPLICATION).get_section_option(
            "epm_schema", "revision_prefix"
        )
        for item in STORES
    }
    assert len(prefixes) == len(STORES)


@pytest.mark.parametrize("store", STORES)
@pytest.mark.parametrize("action", ["upgrade", "stamp", "ensure_version"])
@pytest.mark.parametrize("offline", [False, True])
def test_alembic_scaffold_rejects_before_creating_database(store, action, offline, tmp_path):
    config = scaffold_config(store, application_directory=APPLICATION)
    target = tmp_path / "must-not-exist.sqlite"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{target}")
    output = StringIO()
    config.output_buffer = output
    with pytest.raises(SchemaResourcesUnavailable) as caught:
        if action == "ensure_version":
            command.ensure_version(config, sql=offline)
        else:
            getattr(command, action)(config, "head", sql=offline)
    assert caught.value.code == "schema_resources_unavailable"
    assert caught.value.store == store
    assert str(target) not in str(caught.value)
    assert output.getvalue() == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("store", STORES)
@pytest.mark.parametrize("state", ["empty", "wrong_store", "version_only", "interrupted"])
def test_existing_destinations_are_never_adopted_or_modified(store, state, tmp_path):
    config = scaffold_config(store, application_directory=APPLICATION)
    prefix = config.get_section_option("epm_schema", "revision_prefix")
    target = tmp_path / "existing.sqlite"
    if state in {"wrong_store", "version_only"}:
        with sqlite3.connect(target) as connection:
            connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO alembic_version VALUES (?)", (f"{prefix}0001",))
            if state == "wrong_store":
                connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    else:
        target.write_bytes(b"" if state == "empty" else b"incomplete initialization evidence")
    before = target.read_bytes()
    config.set_main_option("sqlalchemy.url", f"sqlite:///{target}")
    for _ in range(2):
        with pytest.raises(SchemaResourcesUnavailable):
            command.upgrade(config, "head")
        assert target.read_bytes() == before
    assert {path.name for path in tmp_path.iterdir()} == {target.name}


@pytest.mark.parametrize("store", STORES)
def test_supplied_connection_is_not_used_committed_or_closed(store):
    engine = create_engine("sqlite://")
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            config = scaffold_config(store, application_directory=APPLICATION)
            config.attributes["connection"] = connection
            with pytest.raises(SchemaResourcesUnavailable):
                command.stamp(config, "head")
            assert not statements
            assert transaction.is_active
            assert not connection.closed
    finally:
        engine.dispose()


@pytest.mark.parametrize("store", STORES)
@pytest.mark.parametrize("missing", ["alembic.ini", "env.py", "versions"])
def test_incomplete_installed_resources_have_safe_unavailable_outcome(store, missing, tmp_path):
    resource = tmp_path / "database" / f"{store.value}-migrations"
    shutil.copytree(APPLICATION / "database" / resource.name, resource)
    absent = resource / missing
    if absent.is_dir():
        shutil.rmtree(absent)
    else:
        absent.unlink()
    with pytest.raises(SchemaResourcesUnavailable) as caught:
        scaffold_config(store, application_directory=tmp_path)
    assert str(tmp_path) not in str(caught.value)
    assert caught.value.code == "schema_resources_unavailable"


def test_unknown_store_and_mismatched_config_cannot_dispatch(tmp_path):
    with pytest.raises(ValueError):
        scaffold_config("business", application_directory=tmp_path)
    resource = tmp_path / "database/admin-migrations"
    shutil.copytree(APPLICATION / "database/admin-migrations", resource)
    ini = resource / "alembic.ini"
    ini.write_text(ini.read_text().replace("store = admin", "store = recovery"))
    with pytest.raises(SchemaResourcesUnavailable):
        scaffold_config(HostedStore.ADMIN, application_directory=tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        "not a configuration",
        "[alembic]\nscript_location = .\n",
        "[epm_schema]\nstore = admin\nresource_state = ready\n",
    ],
)
def test_malformed_or_false_ready_configuration_fails_safely(tmp_path, content):
    resource = tmp_path / "database/admin-migrations"
    shutil.copytree(APPLICATION / "database/admin-migrations", resource)
    (resource / "alembic.ini").write_text(content)
    with pytest.raises(SchemaResourcesUnavailable) as caught:
        scaffold_config(HostedStore.ADMIN, application_directory=tmp_path)
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize("store", STORES)
def test_missing_resource_set_never_falls_back_to_business(store, tmp_path):
    business = tmp_path / "database/sqlite-migrations/versions"
    business.mkdir(parents=True)
    (business / "0001_initial_schema.py").write_text("raise AssertionError('must not load')")
    with pytest.raises(SchemaResourcesUnavailable):
        scaffold_config(store, application_directory=tmp_path)
