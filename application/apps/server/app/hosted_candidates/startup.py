"""Fail-closed fresh composition; later owners must supply access/recovery authority.

This is not the legacy hosted-demo bootstrap or an admission mechanism. Even valid
business data cannot enable routes while the owning hosted composition is absent.
"""

import os
from pathlib import Path
import sqlite3
import stat

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.hosted_artifacts import ArtifactUnavailable
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.hosted_schema import PRIVATE_FILE_MODE, validate_schema
from app.platform.schema_resources import HostedStore, resource_config


def validate_startup(binding, application_directory):
    """Check protected identity under the stable lock; never initialize a store.

    Validation is a prerequisite only, not a reusable readiness/ingress grant.
    The lock is released on every unavailable/error path.
    """
    control = Path(binding.control_path)
    with HostedWriterLock(control / "writer.lock"):
        if binding.component == "operator":
            service = WorkspaceService(
                LocalConfig(
                    config_path=control / "launch.json", workspace_path=Path(binding.workspace_path)
                )
            )
            # The enclosing stable lock replaces the local parent-directory lock.
            manifest = service.open(integrity_check=True)
            if manifest.workspace_id != binding.workspace_id:
                raise ArtifactUnavailable()
            stores = (HostedStore.HOSTED_ACCESS, HostedStore.RECOVERY)
        else:
            stores = (HostedStore.ADMIN, HostedStore.ADMIN_RECOVERY)
        for store in stores:
            resource_config(store, application_directory=application_directory)
            _validate_store(
                control / "data" / f"{store.value}.sqlite", store, application_directory, binding
            )
        # No production access/session/recovery composition exists yet. Do not use
        # a structural check, local app or injected test authority to enable routes.
        raise ArtifactUnavailable()


def _validate_store(path, store, application_directory, binding):
    """Existing owned stores only; SQLite ro mode must never create an empty file."""
    info = path.lstat()
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != PRIVATE_FILE_MODE
        or info.st_nlink != 1
    ):
        raise ArtifactUnavailable()
    engine = create_engine(
        "sqlite://",
        poolclass=NullPool,
        creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True),
    )
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA query_only=ON")
            connection.exec_driver_sql("BEGIN")
            validate_schema(connection, store, application_directory=application_directory)
            if store == HostedStore.ADMIN:
                identities = connection.exec_driver_sql(
                    "SELECT deployment_id FROM control_meta"
                ).all()
                if identities != [(binding.deployment_id,)]:
                    raise ArtifactUnavailable()
    finally:
        engine.dispose()
