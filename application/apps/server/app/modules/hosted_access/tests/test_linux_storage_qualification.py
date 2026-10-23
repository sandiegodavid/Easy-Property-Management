"""Opt-in REAL kernel/SQLite FULL drill on a dedicated disposable Linux volume.

Never points at either invited operator's volume. Requires an explicit synthetic
deployment, a private marker and an unprivileged account. Ordinary test runs skip.
"""

import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

import pytest

from app.modules.hosted_access.application.configuration import WORKSPACE_BYTES
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.configuration import load_hosted_deployment
from app.modules.hosted_access.infrastructure.storage_budget import build_storage_budget
from app.modules.workspace.application.service import WorkspaceService

CONFIG = os.environ.get("EPM_TEST_HOSTED_QUOTA_DEPLOYMENT")
LOCAL = os.environ.get("EPM_TEST_HOSTED_QUOTA_LOCAL_CONFIG")
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not CONFIG or not LOCAL,
    reason="Requires an explicitly provisioned disposable Linux quota volume; not a mocked proof.",
)


def test_real_sqlite_full_rolls_back_and_kernel_retains_recovery_headroom():
    assert os.geteuid() != 0, "The drill must run as the unprivileged scratch service account."
    deployment = load_hosted_deployment(Path(CONFIG))
    assert deployment.allowed_email.endswith("@example.invalid")
    marker = deployment.storage_volume / ".epm-destructive-qualification"
    assert marker.read_text().strip() == "disposable synthetic quota qualification only"
    workspace = WorkspaceService.from_local_config(Path(LOCAL))
    assert workspace.open().workspace_id == str(deployment.workspace_id)
    budget = build_storage_budget(deployment, workspace.paths.root)
    with TemporaryDirectory(prefix="epm-quota-drill-", dir=deployment.storage_volume) as temporary:
        database = Path(temporary) / "full.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("CREATE TABLE effects(id INTEGER PRIMARY KEY, payload BLOB)")
            connection.execute("INSERT INTO effects VALUES(1, ?)", (b"acknowledged",))
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            with pytest.raises(sqlite3.OperationalError) as caught:
                for _ in range(1024):
                    connection.execute(
                        "INSERT INTO effects(payload) VALUES(?)", (b"x" * 1024 * 1024,)
                    )
                connection.commit()
                pytest.fail("An unprivileged writer escaped the fixed-size filesystem.")
            assert caught.value.sqlite_errorcode == sqlite3.SQLITE_FULL
            connection.rollback()
            assert connection.execute("SELECT id, payload FROM effects").fetchall() == [
                (1, b"acknowledged")
            ]
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert deployment.storage_image.stat().st_size == WORKSPACE_BYTES
            usage = os.statvfs(deployment.storage_volume)
            assert (usage.f_bfree - usage.f_bavail) * usage.f_frsize >= 16 * 1024 * 1024
            # Some SQLite builds reclaim aborted WAL frames immediately. Admission
            # must use the actual post-rollback state, not assume bytes remain used.
            if budget.facts().available_bytes < 166 * 1024 * 1024:
                with pytest.raises(HostedAccessError):
                    with budget.reserve(50 * 1024 * 1024, write=True):
                        pytest.fail(
                            "Upload admission ignored remaining capacity after the failure."
                        )
        finally:
            connection.close()
