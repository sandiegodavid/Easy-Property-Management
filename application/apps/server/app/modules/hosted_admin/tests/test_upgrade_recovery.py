"""Encrypted read-back, independent restore, signed proof and fail-closed retention."""

import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.hosted_admin.tests.test_upgrades import (
    upgrade as upgrade,
    started,
    request,
    submit,
    await_acceptance,
)
from app.modules.hosted_access.tests.conftest import deployment_values as deployment_values
from app.modules.hosted_access.tests.test_source_commands import source as source, approved_source
from app.modules.hosted_admin.infrastructure import upgrade_recovery as module
from app.modules.hosted_admin.infrastructure.verified_reports import VerifiedReports
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.archive_service import WorkspaceArchiveService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.hosted_admin.infrastructure.control_recovery import snapshot_control


@pytest.mark.parametrize("failure", [None, "readback", "restore"])
def test_private_upgrade_recovery_validates_remote_bytes_and_retains_proof(
    upgrade, source, tmp_path, monkeypatch, failure
):
    access, commands, _now = approved_source(source)
    service, host, identity, _clock = upgrade
    _clock[0] = max(_clock[0], _now.timestamp() + 1)
    original_prepare = host.prepare

    def prepare(*args):
        value = original_prepare(*args)
        value["instance"].update(
            workspace_id=str(access.deployment.workspace_id),
            operator_id=str(access.deployment.operator_id),
        )
        return value

    host.prepare = prepare
    _, _, _, _, start = started(upgrade)
    with service.store.transaction() as connection:
        payload = json.loads(
            connection.execute("SELECT payload FROM operation WHERE id=?", (start.id,)).fetchone()[
                0
            ]
        )
    local = tmp_path / "local.json"
    local.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "business")}))
    workspace = WorkspaceService.from_local_config(local)
    workspace.initialize(workspace_id=str(access.deployment.workspace_id))
    deployment = tmp_path / "deployment.json"
    deployment.write_text(access.deployment.model_dump_json())
    recovery_path = tmp_path / "recovery-a.json"
    recovery_path.write_text("{}")
    payload["plan"]["recovery_configuration_digest"] = hashlib.sha256(
        recovery_path.read_bytes()
    ).hexdigest()
    secret = tmp_path / "upgrades/passphrase-a"
    secret.parent.mkdir()
    phrase = "private upgrade synthetic passphrase"
    secret.write_text(phrase)
    secret.chmod(0o600)
    archive = tmp_path / "archive.epm-backup"
    directory = tmp_path / "reports"
    directory.mkdir(mode=0o700)
    for name, raw in (
        ("verifier.key", b"k" * 32),
        ("verifier.json", json.dumps({"verifier_digest": "a" * 64}).encode()),
    ):
        path = directory / name
        path.write_bytes(raw)
        path.chmod(0o600)
    reports = VerifiedReports(directory, lambda: "b" * 64)
    objects = {}
    bodies = []

    class Remote:
        bucket = "private-bucket"

        def __init__(self):
            self.client = self

        def upload(self, key, path, size):
            objects[key] = path.read_bytes()
            assert len(objects[key]) == size

        def get_object(self, *, Bucket, Key):
            assert Bucket == self.bucket
            raw = objects[Key]
            if failure == "readback" and Key == "encrypted-point":
                raw = raw[:-1]
            body = io.BytesIO(raw)
            bodies.append(body)
            return {"ContentLength": len(raw), "Body": body}

    remote = Remote()
    platform = Mock()
    platform.h.paths.control = tmp_path
    platform.h.paths.configs = tmp_path
    platform.paths_for.return_value = {"local": local, "deployment": deployment}
    platform.h.inventory.get.return_value = SimpleNamespace(
        key="a",
        workspace_id=str(access.deployment.workspace_id),
        release=payload["plan"]["target"]["release"],
    )
    platform.h.source.prepare.return_value = {
        "deployment": access.deployment.model_dump(mode="json")
    }
    platform.h.source._transport.return_value = commands.administrative_status().model_dump()
    platform.backup.return_value = archive
    config = SimpleNamespace(
        ledger_path=tmp_path / "ledger.json",
        deployment_id=uuid4(),
        workspace_id=str(access.deployment.workspace_id),
    )
    monkeypatch.setattr(module, "load_recovery_configuration", lambda _: config)
    monkeypatch.setattr(module, "recovery_publisher", lambda _: SimpleNamespace(store=remote))
    points = []

    def publish(_deployment, _config, path, archives, passphrase):
        archives.validate_archive(path, passphrase)
        raw = path.read_bytes()
        objects["encrypted-point"] = raw
        points.append(
            SimpleNamespace(
                key="encrypted-point", size=len(raw), sha256=hashlib.sha256(raw).hexdigest()
            )
        )
        return {"key": "encrypted-point"}

    monkeypatch.setattr(module, "publish_archive", publish)
    monkeypatch.setattr(
        module, "FileRecoveryLedger", lambda _: SimpleNamespace(load=lambda: (points, False))
    )
    if failure == "restore":
        monkeypatch.setattr(
            module.BackupService, "restore", Mock(side_effect=RuntimeError("restore failed"))
        )
    verifier = module.UpgradeRecovery(service.store, platform, reports)
    with fast_backup_encryption():
        WorkspaceArchiveService(workspace).create(phrase, "backup", archive)
        if failure:
            with pytest.raises(Exception):
                verifier.produce(payload)
        else:
            proof = verifier.produce(payload)
            assert proof.state == "verified" and proof.restore and proof.approved_binding
            assert verifier.current(payload, "recovery") == proof
    with service.store.transaction() as connection:
        row = connection.execute("SELECT payload FROM upgrade_evidence").fetchone()
        retained = module.UpgradeEvidence.model_validate_json(row[0])
    assert retained.state == ("failed" if failure else "verified")
    assert all(body.closed for body in bodies)
    assert phrase.encode() not in snapshot_control(service.store)
    platform.lock.assert_not_called()
    if failure is None:
        from app.modules.hosted_admin.infrastructure.onboarding import OnboardingRecovery

        bridge_source = SimpleNamespace(
            access_snapshot=lambda _: (
                access.deployment.model_dump(mode="json"),
                commands.administrative_status().model_dump(),
            ),
            prepare=lambda _: {
                "instance": {"release": payload["plan"]["target"]["release"]},
                "deployment_digest": payload["plan"]["configuration_digest"],
            },
        )
        verifier.onboarding = OnboardingRecovery(service.store, bridge_source, reports)
        verifier.resulting(payload, "target")
        status = await_acceptance(service, start)
        accept = request(
            "accept", operation=start.id, expected_revision=status["revision"], restore_access=False
        )
        submit(service, identity, accept)
        verifier.prepare_onboarding(payload | {"acceptance_id": accept.id})
        before = verifier.onboarding.handoff("a", identity)
        assert before["state"] == "verified" and before["completion"] is None
        service.tick()
        after = verifier.onboarding.handoff("a", identity)
        assert after["completion"] == start.id
        snapshot_control(service.store)
        (reports.directory / "verifier.json").write_text(json.dumps({"verifier_digest": "d" * 64}))
        with pytest.raises(ValueError, match="signature_invalid"):
            verifier.current(payload, "recovery")
