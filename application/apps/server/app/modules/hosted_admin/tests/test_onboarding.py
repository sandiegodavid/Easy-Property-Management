"""Current-binding recovery, private registration and source-receipt completion."""

from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.hosted_access.application.admin_commands import AccessCommand
from app.modules.hosted_access.tests.conftest import deployment_values as deployment_values
from app.modules.hosted_access.tests.test_source_commands import source as source, approved_source
from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest, CommandRequest
from app.modules.hosted_admin.application.recovery import RecoveryCheck, RecoveryReport
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore, SourceEffect
from app.modules.hosted_admin.infrastructure.operations import OperationEngine
from app.modules.hosted_admin.infrastructure.control_recovery import (
    snapshot_control,
    restore_control,
)
from app.modules.hosted_admin.infrastructure.onboarding import OnboardingRecovery
from app.modules.hosted_admin.infrastructure.verified_reports import VerifiedReports


@pytest.fixture
def onboarding(source, tmp_path):
    access, commands, now = approved_source(source)
    authority = AuthorityStore.initialize(tmp_path / "control/authority.sqlite", "owner")
    clock = [now.timestamp() + 10]
    authority.clock = lambda: clock[0]
    directory = tmp_path / "reports"
    directory.mkdir(mode=0o700)
    for name, data in (
        ("verifier.json", b'{"verifier_digest":"' + b"a" * 64 + b'"}'),
        ("verifier.key", b"k" * 32),
    ):
        path = directory / name
        path.write_bytes(data)
        path.chmod(0o600)
    reports = VerifiedReports(directory, lambda: "b" * 64)

    class Source:
        def prepare(self, instance):
            assert instance == "c"
            return {
                "deployment_digest": hashlib.sha256(
                    access.deployment.model_dump_json().encode()
                ).hexdigest(),
                "instance": {"release": "release-20261029-01"},
            }

        def access_snapshot(self, instance):
            assert instance == "c"
            return access.deployment.model_dump(
                mode="json"
            ), commands.administrative_status().model_dump()

        def reconcile(self, payload):
            result = commands.receipt(self.command(payload))
            if result:
                recovery.completed(payload, result.model_dump())
            return result.model_dump() if result else None

        def command(self, payload):
            return AccessCommand.model_validate(
                {
                    k: v
                    for k, v in payload.items()
                    if k not in {"instance", "confirmed", "source_reference"}
                }
            )

        def __call__(self, payload):
            proof = recovery.activation(payload)
            cmd = AccessCommand.model_validate(
                self.command(payload).model_dump() | {"activation": proof}
            )
            result = commands.execute(cmd, datetime.fromtimestamp(clock[0], UTC)).model_dump()
            recovery.completed(payload, result)
            return result

        def contain(self, _payload):
            return not commands.status()["active"]

    dispatch = Source()
    recovery = OnboardingRecovery(authority, dispatch, reports)
    dispatch.recovery = recovery
    with authority.transaction() as connection:
        identity = dict(authority._identity(connection))
    handoff = recovery.handoff("c", identity)
    return SimpleNamespace(
        store=authority,
        clock=clock,
        commands=commands,
        recovery=recovery,
        reports=reports,
        source=dispatch,
        identity=identity,
        handoff=handoff,
    )


def publish(fixture, **changes):
    binding, _ = fixture.recovery.binding("c")
    report = RecoveryReport.model_validate(
        {
            "id": str(uuid4()),
            "handoff_id": fixture.handoff["id"],
            "binding": binding.model_dump(),
            "state": "verified",
            "archive_digest": "c" * 64,
            "binding_digest": "d" * 64,
            "snapshot_marker": "e" * 64,
            "archive_reference": "f" * 64,
            "binding_reference": str(uuid4()),
            "verifier_digest": "a" * 64,
            "completed": dict.fromkeys(
                ("archive", "readback", "restore", "approved_binding", "acceptance"),
                fixture.clock[0],
            ),
            "archive": True,
            "readback": True,
            "restore": True,
            "approved_binding": True,
            "acceptance": True,
            "observed": fixture.clock[0],
            "expires": fixture.clock[0] + 86400,
        }
        | changes
    )
    fixture.reports.publish(report.id, report.model_dump())
    fixture.recovery.register(fixture.handoff["id"], report.id)
    return report


def completion(fixture, report):
    status = fixture.commands.administrative_status()
    return CommandRequest(
        operation_id=str(uuid4()),
        instance="c",
        action="complete_onboarding",
        expected_revision=status.admin_revision,
        expected_binding_revision=status.binding_revision,
        fence=status.admin_fence,
        reason="Complete verified isolated onboarding",
        confirmed=True,
        evidence_id=report.id,
        acceptance_id=report.id,
    )


def submit(fixture, command):
    credentials = fixture.store.login(fixture.store.issue())
    fixture.store.reauthenticate(
        BrokerRequest(
            method="reauthenticate",
            command=command,
            credential=fixture.store.issue(command.fingerprint()),
            **credentials,
        )
    )
    return fixture.store.handle(
        BrokerRequest(method="command", command=command, **credentials), fixture.source
    )


def cancel_rejected(fixture, command):
    engine = OperationEngine(fixture.store)
    operation = engine.get(command.operation_id)
    engine.cancel(command.operation_id, operation["revision"], fixture.identity)
    engine.finish_cancel(command.operation_id, SourceEffect(fixture.source))
    assert engine.get(command.operation_id)["state"] == "cancelled"


def test_enable_requires_completion_but_completed_binding_can_be_reenabled(onboarding):
    f = onboarding
    report = publish(f)
    enable = completion(f, report).model_copy(update={"action": "enable"})
    with pytest.raises(AdminError, match="onboarding_completion_required"):
        submit(f, enable)
    assert not f.commands.status()["active"]
    with f.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM onboarding_completion").fetchone()[0] == 0
    cancel_rejected(f, enable)
    completed = submit(f, completion(f, report))
    assert completed["active"]
    status = f.commands.administrative_status()
    f.commands.execute(
        AccessCommand(
            operation_id=str(uuid4()),
            action="disable",
            expected_revision=status.admin_revision,
            expected_binding_revision=status.binding_revision,
            fence=status.admin_fence,
            authority_reference="owner:1",
            reason="Disable the completed binding",
        ),
        datetime.fromtimestamp(f.clock[0], UTC),
    )
    enable = completion(f, report).model_copy(update={"action": "enable"})
    result = submit(f, enable)
    assert result["active"]
    # A committed Enable reconciles even after both proof and verifier change.
    (f.reports.directory / "verifier.json").write_text('{"verifier_digest":"' + "b" * 64 + '"}')
    f.clock[0] += 90000
    assert submit(f, enable) == result
    with f.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM onboarding_completion").fetchone()[0] == 1
    f.commands.validate_retained()


def test_renewed_binding_requires_a_new_completion(onboarding):
    f = onboarding
    submit(f, completion(f, publish(f)))
    status = f.commands.administrative_status()
    renew = AccessCommand(
        operation_id=str(uuid4()),
        action="renew",
        expected_revision=status.admin_revision,
        expected_binding_revision=status.binding_revision,
        fence=status.admin_fence,
        authority_reference="owner:1",
        reason="Renew with a new recovery binding",
        starts=f.clock[0],
        expires=f.clock[0] + 86400,
    )
    f.commands.execute(renew, datetime.fromtimestamp(f.clock[0], UTC))
    f.commands.store.deployment = f.commands.replacement(renew)
    f.handoff = f.recovery.handoff("c", f.identity)
    assert f.handoff["completion"] is None
    report = publish(f)
    enable = completion(f, report).model_copy(update={"action": "enable"})
    with pytest.raises(AdminError, match="onboarding_completion_required"):
        submit(f, enable)
    cancel_rejected(f, enable)
    assert submit(f, completion(f, report))["active"]


@pytest.mark.parametrize("change", ["pin", "missing", "changed"])
def test_activation_revalidates_protected_report_and_preserves_history(onboarding, change):
    f = onboarding
    report = publish(f)
    if change == "pin":
        (f.reports.directory / "verifier.json").write_text('{"verifier_digest":"' + "b" * 64 + '"}')
    elif change == "missing":
        (f.reports.directory / f"{report.id}.json").unlink()
    else:
        f.reports.publish(report.id, report.model_dump() | {"snapshot_marker": "changed"})
    check = RecoveryCheck(handoff_id=f.handoff["id"], expected_revision=1)
    view = f.recovery.check(check)
    assert view["state"] == "stale" and view["report"] == report.model_dump()
    cmd = completion(f, report)
    with pytest.raises(AdminError, match="verification_required"):
        submit(f, cmd)
    assert not f.commands.status()["active"]
    assert f.recovery.observation("c").policy_state == "stale"
    with f.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM recovery_report").fetchone()[0] == 1
    if change == "pin":
        cancel_rejected(f, cmd)
        fresh = publish(f, verifier_digest="b" * 64)
        assert f.recovery.check(check)["state"] == "verified"
        assert submit(f, completion(f, fresh))["active"]
        with f.store.transaction() as connection:
            assert connection.execute("SELECT count(*) FROM recovery_report").fetchone()[0] == 2


def test_committed_completion_reconciles_after_verifier_changes(onboarding):
    f = onboarding
    cmd = completion(f, publish(f))
    result = submit(f, cmd)
    (f.reports.directory / "verifier.json").write_text('{"verifier_digest":"' + "b" * 64 + '"}')
    assert submit(f, cmd) == result
    with f.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM onboarding_completion").fetchone()[0] == 1


def test_persistent_checklist_exact_report_and_idempotent_source_completion(onboarding):
    f = onboarding
    assert f.handoff["state"] == "unknown" and not f.commands.status()["active"]
    assert f.recovery.handoff("c", f.identity)["id"] == f.handoff["id"]
    report = publish(f)
    check = RecoveryCheck(handoff_id=f.handoff["id"], expected_revision=1)
    assert f.recovery.check(check)["state"] == "verified"
    cmd = completion(f, report)
    credentials = f.store.login(f.store.issue())
    f.store.reauthenticate(
        BrokerRequest(
            method="reauthenticate",
            command=cmd,
            credential=f.store.issue(cmd.fingerprint()),
            **credentials,
        )
    )
    request = BrokerRequest(method="command", command=cmd, **credentials)
    result = f.store.handle(request, f.source)
    assert result["active"]
    f.clock[0] += 90000
    # Fresh private session reconciles the original result despite expired proof.
    replay = request.model_copy(update=f.store.login(f.store.issue()))
    assert f.store.handle(replay, f.source) == result
    with f.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM onboarding_completion").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT count(*) FROM audit WHERE action='onboarding_completed'"
            ).fetchone()[0]
            == 1
        )
    f.commands.validate_retained()
    AuthorityStore(f.store.path)


def test_private_report_registration_rejects_forgery_foreign_identity_and_browser_assertions(
    onboarding,
):
    f = onboarding
    report = publish(f)
    path = f.reports.directory / f"{report.id}.json"
    envelope = json.loads(path.read_bytes())
    envelope["payload"]["acceptance"] = False
    path.write_text(json.dumps(envelope))
    with pytest.raises(AdminError, match="signature_invalid"):
        f.recovery.register(f.handoff["id"], report.id)
    with pytest.raises(ValueError):
        BrokerRequest.model_validate(
            {
                "method": "recovery_check",
                "recovery": {
                    "handoff_id": f.handoff["id"],
                    "expected_revision": 1,
                    "verified": True,
                },
            }
        )
    with pytest.raises(AdminError, match="report_conflict"):
        publish(f, handoff_id=str(uuid4()))


def test_warning_overdue_failed_and_binding_change_never_auto_change_access(onboarding):
    f = onboarding
    report = publish(f)
    f.clock[0] = report.observed + 72000
    f.recovery.observe_all()
    assert f.recovery.observation("c").policy_state == "warning"
    f.clock[0] = report.observed + 86400
    f.recovery.observe_all()
    assert f.recovery.observation("c").policy_state == "overdue"
    with pytest.raises(AdminError, match="verification_required"):
        f.recovery.activation(completion(f, report).model_dump())
    assert not f.commands.status()["active"]
    f.clock[0] += 1
    publish(f, state="failed", acceptance=False)
    assert (
        f.recovery.check(RecoveryCheck(handoff_id=f.handoff["id"], expected_revision=1))["state"]
        == "failed"
    )
    f.store.revoke_identity()
    f.store.restore_identity()
    with pytest.raises(AdminError, match="report_conflict"):
        f.recovery.register(f.handoff["id"], report.id)
    with f.store.transaction() as connection:
        identity = dict(f.store._identity(connection))
    assert f.recovery.handoff("c", identity)["id"] != f.handoff["id"]


def test_source_commit_control_crash_retains_receipt_and_restored_control_stays_fenced(
    onboarding, tmp_path
):
    f = onboarding
    report = publish(f)
    cmd = completion(f, report)
    credentials = f.store.login(f.store.issue())
    f.store.reauthenticate(
        BrokerRequest(
            method="reauthenticate",
            command=cmd,
            credential=f.store.issue(cmd.fingerprint()),
            **credentials,
        )
    )
    admission = f.store.admit(
        BrokerRequest(method="command", command=cmd, **credentials), f.source.prepare
    )
    payload = json.loads(admission["payload"])
    proof = f.recovery.activation(payload)
    source_cmd = AccessCommand.model_validate(
        f.source.command(payload).model_dump() | {"activation": proof}
    )
    original = f.commands.execute(source_cmd, datetime.fromtimestamp(f.clock[0], UTC))
    # The source committed before a control crash and a recovery-tool upgrade.
    (f.reports.directory / "verifier.json").write_text('{"verifier_digest":"' + "b" * 64 + '"}')
    assert f.store.execute(admission, f.source) == original.model_dump()
    encoded = snapshot_control(f.store)
    assert b'"csrf"' not in encoded and b'"token"' not in encoded
    restored = AuthorityStore.initialize(tmp_path / "restored/authority.sqlite", "owner")
    restore_control(restored, encoded)
    with restored.transaction() as connection:
        assert not connection.execute("SELECT enabled FROM administrator").fetchone()[0]
        assert connection.execute("SELECT count(*) FROM session").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM recovery_report").fetchone()[0] == 1
    AuthorityStore(restored.path)


def test_worker_reads_each_current_instance_once_and_keeps_attention_without_source(onboarding):
    from unittest.mock import Mock

    f = onboarding
    publish(f)
    f.store.revoke_identity()
    f.store.restore_identity()
    with f.store.transaction() as connection:
        identity = dict(f.store._identity(connection))
    f.handoff = f.recovery.handoff("c", identity)
    publish(f)
    f.recovery.acknowledge(RecoveryCheck(handoff_id=f.handoff["id"], expected_revision=1))
    original = f.source.access_snapshot
    f.source.access_snapshot = Mock(side_effect=OSError("source stopped"))
    f.recovery.observe_all()
    assert f.source.access_snapshot.call_count == 1
    observation = f.recovery.observation("c")
    assert observation.policy_state == "unknown" and not observation.acknowledged
    assert observation.off_host_readback is not None  # history remains readable
    f.source.access_snapshot = original
    f.recovery.observe_all()
    assert f.recovery.observation("c").policy_state == "verified"
    assert not f.commands.status()["active"]


def test_same_clock_failed_report_cannot_fall_back_to_previous_success(onboarding):
    f = onboarding
    first = publish(f)
    publish(f, state="failed", acceptance=False)
    with pytest.raises(AdminError, match="verification_required"):
        f.recovery.activation(completion(f, first).model_dump())


def test_acknowledgment_returns_saved_state_and_new_failure_keeps_verified_history(onboarding):
    f = onboarding
    times = {
        key: f.clock[0] + index
        for index, key in enumerate(
            ("archive", "readback", "restore", "approved_binding", "acceptance")
        )
    }
    f.clock[0] += 10
    first = publish(f, completed=times)
    check = RecoveryCheck(handoff_id=f.handoff["id"], expected_revision=1)
    assert f.recovery.acknowledge(check)["acknowledged"]
    assert f.recovery.check(check)["acknowledged"]
    f.clock[0] += 60
    publish(f, state="failed", acceptance=False)
    observation = f.recovery.observation("c")
    assert observation.policy_state == "failed" and not observation.acknowledged
    assert observation.attempted == f.clock[0]
    assert observation.local_archive == times["archive"]
    assert observation.off_host_readback == times["readback"]
    assert observation.restore_drill == times["restore"]
    assert observation.approved_binding == times["approved_binding"]
    assert observation.snapshot_marker == first.snapshot_marker
    with pytest.raises(AdminError, match="verification_required"):
        f.recovery.activation(completion(f, first).model_dump())


def test_acknowledgment_cannot_acknowledge_a_different_attention_state(onboarding, monkeypatch):
    f = onboarding
    publish(f)
    check = f.recovery.check

    def changed(request):
        value = check(request)
        with f.store.transaction() as connection:
            connection.execute("UPDATE recovery_attention SET state='unknown'")
        return value

    monkeypatch.setattr(f.recovery, "check", changed)
    with pytest.raises(AdminError, match="attention_changed"):
        f.recovery.acknowledge(RecoveryCheck(handoff_id=f.handoff["id"], expected_revision=1))
    assert not f.recovery.observation("c").acknowledged


def test_age_uses_readback_completion_rather_than_later_report_registration(onboarding):
    f = onboarding
    stamp = f.clock[0]
    f.clock[0] += 72000
    publish(
        f,
        completed=dict.fromkeys(
            ("archive", "readback", "restore", "approved_binding", "acceptance"), stamp
        ),
    )
    assert f.recovery.observation("c").policy_state == "warning"
    f.clock[0] += 14400
    f.recovery.observe_all()
    assert f.recovery.observation("c").policy_state == "overdue"


def test_private_verifier_preserves_failure_when_report_registration_and_cleanup_fail(onboarding):
    from contextlib import nullcontext
    from unittest.mock import Mock
    from app.modules.hosted_admin.infrastructure.onboarding_verifier import OnboardingVerifier

    f = onboarding
    original = OSError("private backup failed")
    platform = Mock()
    platform.lock.side_effect = nullcontext
    platform.source_status.return_value = {"active": False}
    platform.deployment_digest.return_value = f.handoff["binding"]["configuration_digest"]
    platform.backup.side_effect = original
    platform.restart_pending.side_effect = OSError("restart failed")
    register = Mock(side_effect=OSError("broker unavailable"))
    with pytest.raises(AdminError, match="verification_failed") as caught:
        OnboardingVerifier(f.recovery, platform, Mock()).verify(
            f.handoff["id"], "private", register
        )
    assert caught.value.__cause__ is original
    platform.restart_pending.assert_called_once()
    report_id = register.call_args.args[1]
    assert f.reports.report(report_id)["state"] == "failed"
    assert not f.commands.status()["active"]


@pytest.mark.parametrize("failed_acceptance", [False, True])
def test_private_verifier_reads_remote_encrypted_bytes_restores_and_registers_failure_too(
    onboarding, tmp_path, monkeypatch, failed_acceptance
):
    from contextlib import nullcontext
    import io
    from unittest.mock import Mock
    from app.modules.hosted_admin.infrastructure import onboarding_verifier as module
    from app.modules.workspace.application.service import WorkspaceService
    from app.modules.workspace.application.archive_service import WorkspaceArchiveService
    from app.modules.workspace.tests.fast_encryption import fast_backup_encryption

    f = onboarding
    local = tmp_path / "local.json"
    local.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "business")}))
    workspace = WorkspaceService.from_local_config(local)
    binding, _ = f.recovery.binding("c")
    workspace.initialize(workspace_id=binding.workspace_id)
    deployment = tmp_path / "deployment.json"
    deployment.write_text(f.commands.store.deployment.model_dump_json())
    archive = tmp_path / "archive.epm-backup"
    phrase = "private synthetic recovery phrase"
    objects = {}

    class Remote:
        bucket = "private-bucket"

        def __init__(self):
            self.client = self

        def upload(self, key, path, size):
            raw = path.read_bytes()
            assert len(raw) == size
            objects[key] = raw

        def get_object(self, *, Bucket, Key):
            assert Bucket == self.bucket
            return {"ContentLength": len(objects[Key]), "Body": io.BytesIO(objects[Key])}

    remote = Remote()
    platform = Mock()
    platform.lock.side_effect = nullcontext
    platform.source_status.return_value = {"active": False}
    platform.paths_for.return_value = {"local": local, "deployment": deployment}
    platform.deployment_digest.return_value = binding.configuration_digest
    platform.backup.return_value = archive
    platform.h.paths.configs = tmp_path
    config = SimpleNamespace(
        ledger_path=tmp_path / "ledger.json",
        deployment_id=uuid4(),
        workspace_id=binding.workspace_id,
    )
    monkeypatch.setattr(module, "load_recovery_configuration", lambda _: config)
    monkeypatch.setattr(module, "recovery_publisher", lambda _: SimpleNamespace(store=remote))
    points = []

    def publish_archive(_deployment, _config, path, archives, passphrase):
        assert (
            archives.validate_archive(path, passphrase).header["sourceWorkspaceId"]
            == binding.workspace_id
        )
        raw = path.read_bytes()
        objects["encrypted-point"] = raw
        points.append(
            SimpleNamespace(
                key="encrypted-point", size=len(raw), sha256=hashlib.sha256(raw).hexdigest()
            )
        )
        return {"key": "encrypted-point"}

    monkeypatch.setattr(module, "publish_archive", publish_archive)
    monkeypatch.setattr(
        module, "FileRecoveryLedger", lambda _: SimpleNamespace(load=lambda: (points, False))
    )
    acceptance = Mock(
        side_effect=AdminError("admin_acceptance_failed", 409) if failed_acceptance else None
    )
    with fast_backup_encryption():
        WorkspaceArchiveService(workspace).create(phrase, "backup", archive)
        verifier = module.OnboardingVerifier(f.recovery, platform, acceptance)
        if failed_acceptance:
            with pytest.raises(AdminError, match="verification_failed"):
                verifier.verify(f.handoff["id"], phrase, f.recovery.register)
        else:
            assert verifier.verify(f.handoff["id"], phrase, f.recovery.register)["verified"]
    view = f.recovery.check(RecoveryCheck(handoff_id=f.handoff["id"], expected_revision=1))
    assert view["state"] == ("failed" if failed_acceptance else "verified")
    assert not f.commands.status()["active"]
    acceptance.assert_called_once_with("c")
    assert all(not (tmp_path / part).exists() for part in ("drill", "readback.epm-backup"))
    assert phrase.encode() not in f.store.path.read_bytes()
