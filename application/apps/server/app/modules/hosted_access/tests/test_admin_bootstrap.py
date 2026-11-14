"""Exercise platform-owner recovery with the actual Admin schema."""

from pathlib import Path

import pytest
from sqlalchemy import text

from app.modules.hosted_access.infrastructure.admin_principals import (
    SQLiteAdminPrincipalReader,
    change_admin_principal,
)
from app.modules.hosted_access.tests.test_identity_contracts import setup
from app.platform.hosted_schema import initialize_store, validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

APPLICATION = Path(__file__).resolve().parents[6]


def test_bootstrap_retry_rollback_and_revision_guard(tmp_path):
    path = tmp_path / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, path, application_directory=APPLICATION)
    engine = create_sqlite_engine(path)
    realm = setup().realm
    reader = SQLiteAdminPrincipalReader(engine)

    def change(connection, action="bootstrap", **values):
        return change_admin_principal(
            connection, realm=realm, subject="exact-provider-uid", action=action, now=1000, **values
        )

    try:
        assert reader.by_identity(realm.alias, "exact-provider-uid") is None
        with pytest.raises(RuntimeError, match="rollback"):
            with immediate_transaction(engine) as connection:
                change(connection)
                raise RuntimeError("rollback")
        assert reader.by_identity(realm.alias, "exact-provider-uid") is None
        with immediate_transaction(engine) as connection:
            principal = change(connection)
        with immediate_transaction(engine) as connection:
            assert change(connection) == principal
        assert reader.by_identity(realm.alias, "EXACT-provider-uid") is None

        with immediate_transaction(engine) as connection:
            change(connection, "suspend", expected_revision=1)
        assert not reader.by_identity(realm.alias, "exact-provider-uid").enabled
        with pytest.raises(ValueError, match="explicit restoration"):
            with immediate_transaction(engine) as connection:
                change(connection)
        with pytest.raises(ValueError, match="has changed"):
            with immediate_transaction(engine) as connection:
                change(connection, "restore", expected_revision=1)
        with immediate_transaction(engine) as connection:
            assert change(connection, "restore", expected_revision=2) == principal
            validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
            actions = connection.execute(text("SELECT action FROM main.admin_audit")).scalars()
            assert sorted(actions) == [
                "admin_principal_bootstrap",
                "admin_principal_restore",
                "admin_principal_suspend",
            ]
        restored = reader.by_identity(realm.alias, "exact-provider-uid")
        assert restored.enabled and restored.session_generation == 3
    finally:
        engine.dispose()


def test_offline_command_requires_private_input_and_unheld_lock(tmp_path, monkeypatch, capsys):
    import sys

    from app.modules.hosted_access.infrastructure.admin_bootstrap import main
    from app.platform.hosted_writer_lock import HostedWriterLock
    from app.platform.locking import WorkspaceOperationInProgressError

    directory = tmp_path.resolve()
    directory.chmod(0o700)
    database = directory / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, database, application_directory=APPLICATION)
    database.chmod(0o600)
    selected = directory / "setup.json"
    selected.write_text(setup().model_dump_json())
    lock = directory / "writer.lock"
    lock.touch(mode=0o600)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "admin_bootstrap",
            "bootstrap",
            "--database",
            str(database),
            "--writer-lock",
            str(lock),
            "--setup",
            str(selected),
            "--application-directory",
            str(APPLICATION),
            "--subject",
            "qualification-uid",
        ],
    )
    selected.chmod(0o644)
    with pytest.raises(ValueError, match="private input"):
        main()
    selected.chmod(0o600)
    with HostedWriterLock(lock), pytest.raises(WorkspaceOperationInProgressError):
        main()
    main()
    assert capsys.readouterr().out.strip().endswith("enabled revision 1")
