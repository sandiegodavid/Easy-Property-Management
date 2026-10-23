"""Full archive checks remain intact when staging is outside the bounded volume."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.storage_budget import (
    HostedStorageBudget,
    StorageFacts,
    MIB,
)
from app.modules.hosted_access.infrastructure.operations import create_hosted_backup
from app.modules.hosted_access.infrastructure import recovery_publication as publication
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.backup_models import BackupError
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.locking import WorkspaceOperationLock, WorkspaceOperationInProgressError


def test_offline_backup_refuses_live_server_then_validates_external_staging(
    tmp_path, deployment_values, monkeypatch
):
    root = tmp_path / "volume"
    root.mkdir()
    root.chmod(0o700)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}))
    workspace = WorkspaceService.from_local_config(config)
    manifest = workspace.initialize()
    staging, archives = tmp_path / "staging", tmp_path / "archives"
    for directory in (staging, archives):
        directory.mkdir(mode=0o700)
    deployment = HostedDeployment.model_validate(
        {
            **deployment_values,
            "workspace_id": manifest.workspace_id,
            "storage_volume": root,
        }
    )
    backups = BackupService(
        workspace,
        AuditRecorder(SQLiteAuditRepository(workspace.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        archive_staging_directory=staging,
    )
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.operations.load_hosted_deployment",
        lambda _: deployment,
    )
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.operations.build_storage_budget",
        lambda *_: HostedStorageBudget(
            lambda: StorageFacts(250 * MIB, 220 * MIB, 1000 * MIB, 900 * MIB, 10000)
        ),
    )
    output = archives / "recovery.epm-backup"
    args = (Path("/protected.json"), backups, output, "synthetic offline backup phrase")
    with WorkspaceOperationLock(root / ".workspace.server.lock"):
        with pytest.raises(WorkspaceOperationInProgressError):
            create_hosted_backup(*args)
    assert not output.exists()
    with fast_backup_encryption():
        result = create_hosted_backup(*args)
        assert result.archive_contents.header["sourceWorkspaceId"] == manifest.workspace_id
        restored = backups.restore(output, args[-1], tmp_path / "restored")
    assert restored.archive_contents.header["sourceWorkspaceId"] == manifest.workspace_id
    assert not any(staging.iterdir())


def test_publication_validates_complete_private_copy_before_constructing_remote_adapter(
    tmp_path, deployment_values, monkeypatch
):
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    workspace = WorkspaceService.from_local_config(config)
    manifest = workspace.initialize()
    staging = tmp_path / "external-staging"
    staging.mkdir(mode=0o700)
    backups = BackupService(
        workspace,
        AuditRecorder(SQLiteAuditRepository(workspace.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        archive_staging_directory=staging,
    )
    deployment = HostedDeployment.model_validate(
        {**deployment_values, "workspace_id": manifest.workspace_id}
    )
    recovery = publication.RecoveryConfiguration(
        deployment_id=uuid4(),
        workspace_id=manifest.workspace_id,
        endpoint="https://" + "a" * 32 + ".r2.cloudflarestorage.com",
        bucket="private-backups",
        access_key_id="synthetic-key",
        secret_access_key="synthetic-secret",
        ledger_path=tmp_path / "ledger.json",
    )
    remote = Mock()
    remote.status.return_value = {"needsAttention": False}

    def uploaded(source, **kwargs):
        assert source.parent != tmp_path and source.read_bytes() == archive.read_bytes()
        assert kwargs["size"] == archive.stat().st_size
        return SimpleNamespace(key="verified-object"), False

    remote.publish.side_effect = uploaded
    factory = Mock(return_value=remote)
    monkeypatch.setattr(publication, "load_hosted_deployment", lambda _: deployment)
    monkeypatch.setattr(publication, "load_recovery_configuration", lambda _: recovery)
    monkeypatch.setattr(publication, "recovery_publisher", factory)
    archive = tmp_path / "validated.epm-backup"
    with fast_backup_encryption():
        backups.create_backup("test publication phrase", output_path=archive)
        result = publication.publish_archive(
            None, None, archive, backups, "test publication phrase"
        )
        assert result["key"] == "verified-object" and not result["retentionPending"]
        factory.reset_mock()
        with pytest.raises(BackupError):
            publication.publish_archive(None, None, archive, backups, "wrong phrase")
        factory.assert_not_called()
    assert not list(tmp_path.glob("epm-publish-*"))
    assert not any(staging.iterdir())
