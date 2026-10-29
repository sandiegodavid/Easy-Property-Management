"""Recovery proof uses remote bytes, never a browser assertion."""

import hashlib
import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.pre_enrollment import verify_remote
from app.modules.hosted_admin.infrastructure.verified_reports import VerifiedReports
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.archive_service import WorkspaceArchiveService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.hosted_admin.tests.test_setup import setup as setup, start
from app.modules.hosted_admin.tests.test_authority import authority as authority
from app.modules.hosted_admin.infrastructure.pre_enrollment import PreEnrollmentRecovery
from app.modules.hosted_admin.application.operations import Observation
from unittest.mock import Mock
from contextlib import contextmanager


def test_remote_archive_decrypts_and_validates_exact_workspace(tmp_path):
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    workspace = WorkspaceService.from_local_config(config)
    manifest = workspace.initialize()
    archives = WorkspaceArchiveService(workspace)
    archive = tmp_path / "original.epm-backup"
    phrase = "synthetic pre-enrollment recovery phrase"
    with fast_backup_encryption():
        archives.create(phrase, "backup", archive)
        raw = archive.read_bytes()
        point = SimpleNamespace(
            key="private-object", size=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        )
        bodies = []

        class Client:
            def get_object(self, **kwargs):
                assert kwargs == {"Bucket": "private-bucket", "Key": point.key}
                body = io.BytesIO(raw)
                bodies.append(body)
                return {"ContentLength": len(raw), "Body": body}

        remote = SimpleNamespace(client=Client(), bucket="private-bucket")
        destination = tmp_path / "readback"
        destination.mkdir()
        verify_remote(point, remote, archives, phrase, destination, manifest.workspace_id)
        assert bodies[-1].closed
        (destination / "readback.epm-backup").unlink()
        with pytest.raises(AdminError, match="workspace_conflict"):
            verify_remote(point, remote, archives, phrase, destination, str(uuid4()))
        assert bodies[-1].closed
        (destination / "readback.epm-backup").unlink()
        point.sha256 = "0" * 64
        with pytest.raises(AdminError, match="readback_invalid"):
            verify_remote(point, remote, archives, phrase, destination, manifest.workspace_id)


def test_private_signed_report_rejects_forgery_and_keeps_key_out(tmp_path):
    directory = tmp_path / "reports"
    directory.mkdir(mode=0o700)
    for name, content in (
        ("verifier.key", b"k" * 32),
        ("verifier.json", json.dumps({"verifier_digest": "a" * 64}).encode()),
    ):
        path = directory / name
        path.write_bytes(content)
        path.chmod(0o600)
    reports = VerifiedReports(directory, lambda: "b" * 64)
    identifier = str(uuid4())
    payload = {"operation_id": str(uuid4()), "observed": 1000.0, "verified": True}
    reports.publish(identifier, payload)
    assert reports.report(identifier) == payload
    path = directory / f"{identifier}.json"
    value = json.loads(path.read_bytes())
    assert (b"k" * 32) not in path.read_bytes()
    value["payload"]["verified"] = False
    path.write_text(json.dumps(value))
    with pytest.raises(AdminError, match="signature_invalid"):
        reports.report(identifier)


@pytest.mark.parametrize("failure", [None, "wrong_workspace", "authority_revoked"])
def test_private_handoff_registers_only_verified_current_evidence(
    setup, tmp_path, monkeypatch, failure
):
    from app.modules.hosted_admin.infrastructure import pre_enrollment as module

    service, host, _, _ = setup
    created = start(setup)
    host.provider_ready = True
    for _ in range(3):
        service.engine.run(created["operation_id"], host)
    original = host.inspect
    host.inspect = lambda payload, step: (
        Observation("waiting") if step == "readiness" else original(payload, step)
    )
    with pytest.raises(AdminError):
        service.engine.run(created["operation_id"], host)
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    workspace = WorkspaceService.from_local_config(config)
    with service.store.transaction() as connection:
        expected_workspace = json.loads(
            connection.execute(
                "SELECT plan FROM setup_draft WHERE id=?", (created["id"],)
            ).fetchone()[0]
        )["workspace_id"]
    workspace.initialize(workspace_id=expected_workspace)
    archive = tmp_path / "point.epm-backup"
    phrase = "synthetic handoff recovery passphrase"

    @contextmanager
    def lock():
        yield

    platform = Mock()
    platform.lock.side_effect = lock
    platform.owned.return_value = True
    platform.paths_for.return_value = {"local": config, "deployment": tmp_path / "deployment.json"}
    platform.deployment_digest.return_value = "a" * 64
    platform.h.paths.configs = tmp_path
    platform.source_status.return_value = {"active": False, "identity_approved": False}
    platform.backup.return_value = archive
    reports = Mock()
    # The workspace identity in the setup must remain exact; this fixture builds
    # a real empty archive for the source identity produced by its fresh seed.
    collector = PreEnrollmentRecovery(service, reports, platform)
    with fast_backup_encryption():
        WorkspaceArchiveService(workspace).create(phrase, "backup", archive)
        raw = archive.read_bytes()
        point = SimpleNamespace(key="point", size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        host.desired = Mock()
        real_validate = module.verify_remote

        def validate(point, remote, archives, phrase, directory, _workspace_id):
            if failure == "authority_revoked":
                service.store.revoke_identity()
            return real_validate(
                point,
                remote,
                archives,
                phrase,
                directory,
                str(uuid4()) if failure == "wrong_workspace" else _workspace_id,
            )

        monkeypatch.setattr(module, "verify_remote", validate)
        monkeypatch.setattr(
            module,
            "load_recovery_configuration",
            lambda _: SimpleNamespace(ledger_path=tmp_path / "ledger.json"),
        )
        monkeypatch.setattr(module, "publish_archive", lambda *_: {"key": "point"})
        monkeypatch.setattr(
            module, "FileRecoveryLedger", lambda _: SimpleNamespace(load=lambda: ([point], False))
        )
        remote = SimpleNamespace(
            bucket="bucket",
            client=SimpleNamespace(
                get_object=lambda **_: {"ContentLength": len(raw), "Body": io.BytesIO(raw)}
            ),
        )
        monkeypatch.setattr(module, "recovery_publisher", lambda _: SimpleNamespace(store=remote))
        if failure:
            with pytest.raises(AdminError, match="verification_failed"):
                collector.verify(created["operation_id"], phrase)
            reports.publish.assert_not_called()
        else:
            assert collector.verify(created["operation_id"], phrase)["verified"]
            report = reports.publish.call_args.args[1]
            assert report["configuration_digest"] == "a" * 64 and report["independent_readback"]
        if failure == "authority_revoked":
            platform.contain.assert_called_once()
            platform.restart_pending.assert_not_called()
        else:
            platform.restart_pending.assert_called_once()
