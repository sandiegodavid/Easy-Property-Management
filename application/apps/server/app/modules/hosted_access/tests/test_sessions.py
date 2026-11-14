"""Retired session entry points deny every destination without touching files.

Matrix: absent/partial/foreign/current files, symlinks, repeated calls and no
filesystem/SQLite access. No transaction, migration or session authority is issued.
"""

from importlib.util import find_spec
from pathlib import Path
import sqlite3

import pytest

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore


@pytest.mark.parametrize("entry", [SQLiteHostedSessionStore, SQLiteHostedSessionStore.initialize])
@pytest.mark.parametrize(
    "destination", ["missing_parent", "empty", "foreign", "current", "symlink"]
)
def test_legacy_entry_denies_without_mutating_any_destination(
    deployment_values, tmp_path, entry, destination
):
    path = tmp_path / "access.sqlite"
    if destination == "missing_parent":
        path = tmp_path / "absent" / "access.sqlite"
    elif destination == "empty":
        path.touch(mode=0o640)
    elif destination == "foreign":
        path.write_bytes(b"foreign store evidence")
    elif destination == "current":
        tmp_path.chmod(0o700)
        initialize_store(
            HostedStore.HOSTED_ACCESS,
            path,
            application_directory=Path(__file__).resolve().parents[6],
        )
    else:
        target = tmp_path / "target.sqlite"
        target.write_bytes(b"private target evidence")
        path.symlink_to(target)
    deployment = HostedDeployment.model_validate(
        {**deployment_values, "administration_database": str(path)}
    )

    def snapshot():
        return {
            str(p.relative_to(tmp_path)): (
                p.lstat().st_mode,
                p.lstat().st_ino,
                p.lstat().st_size,
                p.lstat().st_mtime_ns,
                p.readlink() if p.is_symlink() else p.read_bytes() if p.is_file() else None,
            )
            for p in tmp_path.rglob("*")
        }

    before = snapshot()
    for _ in range(2):
        with pytest.raises(HostedAccessError) as caught:
            entry(deployment)
        assert caught.value.code == "hosted_access_unavailable"
        assert caught.value.status == 503
        assert str(path) not in str(caught.value)
        assert snapshot() == before


def test_legacy_guard_does_not_even_inspect_paths_or_connect(deployment_values, monkeypatch):
    deployment = HostedDeployment.model_validate(deployment_values)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Legacy entry attempted filesystem or SQLite access")

    with monkeypatch.context() as guard:
        for method in ("is_file", "is_symlink", "stat", "lstat", "open", "mkdir", "chmod"):
            guard.setattr(Path, method, forbidden)
        guard.setattr(sqlite3, "connect", forbidden)
        for entry in (SQLiteHostedSessionStore, SQLiteHostedSessionStore.initialize):
            with pytest.raises(HostedAccessError) as caught:
                entry(deployment)
            assert caught.value.code == "hosted_access_unavailable"


def test_runtime_schema_exports_no_legacy_ddl_or_revision():
    assert find_spec("app.modules.hosted_access.infrastructure.schema") is None
