"""Reset checkpoints/config cutover under temporary roots, never live host services."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from scripts import release_demo as tool
from demo.verify import EXPECTED
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.service import HostedAccessService
from app.modules.hosted_access.domain.models import HostedAccessError, VerifiedIdentity
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def hosted_values(root, instance):
    base = root / "data" / f"epm-{instance}"
    now = datetime.now(UTC)
    return {
        "deployment_mode": "hosted_demo",
        "public_origin": f"https://demo-{instance}.example.com",
        "identity_issuer": "https://example.cloudflareaccess.com",
        "identity_audience": "a" * 64,
        "workspace_id": str(uuid4()),
        "operator_id": str(uuid4()),
        "allowed_email": f"operator-{instance}@example.invalid",
        "administrator_contact": "admin@example.invalid",
        "administration_database": str(base / "access/old.sqlite"),
        "storage_volume": str(base / "volume"),
        "storage_image": str(root / f"{instance}.ext4"),
        "enabled_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "capabilities": ["records.read", "records.write", "files.read", "files.write"],
    }


@pytest.fixture
def reset_host(tmp_path, monkeypatch):
    for name, suffix in (
        ("RELEASES", "releases"),
        ("CONFIGS", "config"),
        ("DATA", "data"),
        ("BACKUPS", "backups"),
        ("SYSTEMD", "systemd"),
    ):
        monkeypatch.setattr(tool, name, tmp_path / suffix)
    monkeypatch.setattr(tool, "ROOT_UID", os.getuid())
    monkeypatch.setattr(tool.os, "fchown", lambda *_args: None)
    monkeypatch.setattr(tool.os, "chown", lambda *_args: None)
    monkeypatch.setattr(tool.pwd, "getpwnam", lambda _: SimpleNamespace(pw_gid=os.getgid()))
    monkeypatch.setattr(
        tool,
        "load_hosted_deployment",
        lambda path: HostedDeployment.model_validate(tool.read_json(path)),
    )
    monkeypatch.setattr(tool, "check_stopped", lambda _plan: None)
    for instance in ("a", "b"):
        values = hosted_values(tmp_path, instance)
        workspace = Path(values["storage_volume"]) / "old"
        write_json(workspace / "workspace.json", {"workspaceId": values["workspace_id"]})
        (workspace / "old-data.txt").write_text("old data must remain untouched")
        base, local, hosted = tool.instance_paths(instance)
        (base / "access").mkdir(mode=0o700)
        write_json(local, {"localWorkspacePath": str(workspace)})
        write_json(hosted, values)
        dropin = tool.SYSTEMD / f"epm-hosted@{instance}.service.d/90-release.conf"
        dropin.parent.mkdir(parents=True)
        dropin.write_text(f"old override {instance}\n")
    return tmp_path


def plan_args(root, instance="a"):
    release = "release-20261026-02"
    release_root = tool.RELEASES / release
    release_root.mkdir(parents=True, exist_ok=True)
    (release_root / "SOURCE_COMMIT.txt").write_text("a" * 40)
    record = release_root / "wizard-state" / f"{instance}.ABCDEFGH"
    record.mkdir(parents=True, mode=0o700)
    archive = root / f"fresh-{instance}.epm-backup"
    archive.write_bytes(b"encrypted archive placeholder")
    descriptor = {
        "format": 1,
        "release": release,
        "instance": instance,
        "source_commit": "a" * 40,
        "workspace_id": str(uuid4()),
        "schema_revision": tool.current_revision(),
        "archive_sha256": tool.file_hash(archive),
        "workspace_bytes": 4096,
    }
    metadata = root / f"fresh-{instance}.json"
    write_json(metadata, descriptor)
    return SimpleNamespace(
        release=release,
        instance=instance,
        record=record,
        archive=archive,
        descriptor=metadata,
        checksum=descriptor["archive_sha256"],
        old_python="/opt/epm/releases/old/venv/bin/python",
    )


def planned(root):
    args = plan_args(root)
    tool.prepare_plan(args)
    return args, tool.load_plan(args.record)


def restored_plan(args, plan):
    Path(plan["backup"]).parent.mkdir(parents=True, exist_ok=True)
    Path(plan["backup"]).write_bytes(b"verified old-schema backup")
    tool.mark(args.record, plan, "backed_up")
    write_json(Path(plan["workspace"]) / "workspace.json", {"workspaceId": plan["workspace_id"]})
    tool.mark(args.record, plan, "restored")
    tool.mark(args.record, plan, "initialized")


def test_preparation_preserves_old_records_authority_and_expiry(reset_host):
    _, old_local, old_hosted = tool.instance_paths("a")
    original = tool.read_json(old_hosted)
    original_local = old_local.read_bytes()
    args, plan = planned(reset_host)
    candidate = tool.read_json(plan["candidate_hosted"])
    assert old_local.read_bytes() == original_local
    assert tool.read_json(old_hosted) == original
    for key in original.keys() - {"workspace_id", "administration_database"}:
        assert candidate[key] == original[key]
    assert candidate["workspace_id"] != original["workspace_id"]
    assert not Path(candidate["administration_database"]).exists()
    assert (
        Path(plan["old_workspace"], "old-data.txt").read_text() == "old data must remain untouched"
    )
    assert tool.load_plan(args.record)["completed"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("instance", "b"),
        ("release", "release-20261026-99"),
        ("source_commit", "b" * 40),
        ("schema_revision", "other"),
        ("workspace_id", "not-a-uuid"),
        ("workspace_bytes", -1),
        ("extra", "undeclared"),
    ],
)
def test_bad_descriptor_is_rejected_before_preparation(reset_host, field, value):
    args = plan_args(reset_host)
    descriptor = tool.read_json(args.descriptor)
    descriptor[field] = value
    write_json(args.descriptor, descriptor)
    with pytest.raises(ValueError):
        tool.prepare_plan(args)
    assert not (args.record / "reset.json").exists()


def test_independent_checksum_mismatch_is_rejected(reset_host):
    args = plan_args(reset_host)
    args.checksum = "0" * 64
    with pytest.raises(tool.ResetError, match="checksum"):
        tool.prepare_plan(args)


@pytest.mark.parametrize("existing", ["a", "b"])
def test_reset_cannot_reuse_old_or_other_instances_identity(reset_host, existing):
    args = plan_args(reset_host)
    descriptor = tool.read_json(args.descriptor)
    descriptor["workspace_id"] = tool.read_json(tool.CONFIGS / f"hosted-{existing}.json")[
        "workspace_id"
    ]
    write_json(args.descriptor, descriptor)
    with pytest.raises(tool.ResetError):
        tool.prepare_plan(args)


def test_checkpoint_order_and_retries(reset_host):
    args, plan = planned(reset_host)
    with pytest.raises(tool.ResetError, match="order"):
        tool.mark(args.record, plan, "initialized")
    restored_plan(args, plan)
    before = deepcopy(plan)
    tool.mark(args.record, plan, "restored")
    assert plan == before
    with pytest.raises(tool.ResetError, match="stopped configuration"):
        tool.mark(args.record, plan, "switched")


def test_switch_and_rollback_preserve_both_datasets(reset_host):
    args, plan = planned(reset_host)
    old = {row["path"]: Path(row["path"]).read_bytes() for row in plan["originals"]}
    restored_plan(args, plan)
    tool.replace_configs(args.record, plan)
    assert tool.read_json(tool.instance_paths("a")[1])["localWorkspacePath"] == plan["workspace"]
    assert plan["completed"][-1] == "switched"
    tool.replace_configs(args.record, plan, rollback=True)
    assert {name: Path(name).read_bytes() for name in old} == old
    assert Path(plan["old_workspace"]).exists()
    assert Path(plan["workspace"]).exists()
    assert Path(plan["backup"]).exists()


def test_running_service_and_external_config_changes_block_switch(reset_host, monkeypatch):
    args, plan = planned(reset_host)
    restored_plan(args, plan)
    original = tool.read_json(tool.instance_paths("a")[1])

    def running(_plan):
        raise tool.ResetError("must remain stopped")

    monkeypatch.setattr(tool, "check_stopped", running)
    with pytest.raises(tool.ResetError, match="stopped"):
        tool.replace_configs(args.record, plan)
    assert tool.read_json(tool.instance_paths("a")[1]) == original
    monkeypatch.setattr(tool, "check_stopped", lambda _: None)
    tool.instance_paths("a")[1].write_text("changed externally")
    with pytest.raises(tool.ResetError, match="outside this reset"):
        tool.replace_configs(args.record, plan)


def test_interrupted_switch_retries_without_recreating_data(reset_host, monkeypatch):
    args, plan = planned(reset_host)
    restored_plan(args, plan)
    actual_write = tool.atomic_write
    target = tool.instance_paths("a")[2]

    def interrupted(path, data, identity):
        if Path(path) == target:
            raise OSError("injected interruption")
        actual_write(path, data, identity)

    monkeypatch.setattr(tool, "atomic_write", interrupted)
    with pytest.raises(OSError):
        tool.replace_configs(args.record, plan)
    assert tool.load_plan(args.record)["phase"] == "switching"
    assert tool.read_json(tool.instance_paths("a")[1])["localWorkspacePath"] == plan["workspace"]
    monkeypatch.setattr(tool, "atomic_write", actual_write)
    tool.replace_configs(args.record, tool.load_plan(args.record))
    result = tool.load_plan(args.record)
    assert result["completed"].count("switched") == 1


def test_capacity_failure_does_not_change_workspace_or_binding(reset_host, monkeypatch):
    args, plan = planned(reset_host)
    before = tool.instance_paths("a")[1].read_bytes()
    monkeypatch.setattr(tool, "validate_storage_volume", lambda dep, _: (dep.storage_volume, None))
    monkeypatch.setattr(tool.os, "statvfs", lambda _: SimpleNamespace(f_bavail=1, f_frsize=4096))
    with pytest.raises(tool.ResetError, match="headroom"):
        tool.storage(
            SimpleNamespace(
                deployment=Path(plan["candidate_hosted"]),
                workspace=Path(plan["old_workspace"]),
                bytes=4096,
            )
        )
    assert tool.instance_paths("a")[1].read_bytes() == before
    assert not Path(plan["workspace"]).exists()


def test_recovery_ledger_is_separate_and_rollback_restores_binding(reset_host, monkeypatch):
    ledger = reset_host / "recovery/ledger.json"
    ledger.parent.mkdir(mode=0o700)
    ledger.write_text("old verified recovery points")
    original = {
        "workspace_id": tool.read_json(tool.instance_paths("a")[2])["workspace_id"],
        "ledger_path": str(ledger),
        "access_key_id": "private-key",
        "secret_access_key": "private-secret",
    }
    path = tool.CONFIGS / "recovery-a.json"
    write_json(path, original)
    monkeypatch.setattr(
        tool,
        "load_recovery_configuration",
        lambda _: SimpleNamespace(workspace_id=UUID(original["workspace_id"]), ledger_path=ledger),
    )
    args, plan = planned(reset_host)
    restored_plan(args, plan)
    tool.replace_configs(args.record, plan)
    fresh = tool.read_json(path)
    assert fresh["workspace_id"] == plan["workspace_id"]
    assert fresh["ledger_path"] != str(ledger)
    assert ledger.read_text() == "old verified recovery points"
    assert not Path(fresh["ledger_path"]).exists()
    tool.replace_configs(args.record, plan, rollback=True)
    assert tool.read_json(path) == original


def old_session(identity, now):
    deployment = HostedDeployment.model_validate(tool.read_json(tool.instance_paths("a")[2]))
    SQLiteHostedSessionStore.initialize(deployment)
    store = SQLiteHostedSessionStore(deployment)
    try:
        service = HostedAccessService(deployment, store, now=lambda: now)
        with pytest.raises(HostedAccessError, match="approval"):
            service.begin_session(identity)
        store.activate(identity.subject)
        grant = service.begin_session(identity)
        store.disable(now)
        with pytest.raises(HostedAccessError):
            service.authenticate(identity, grant.token)
        return grant
    finally:
        store.engine.dispose()


def test_fresh_access_store_rejects_old_session_and_requires_approval_and_fresh_proof(reset_host):
    args, plan = planned(reset_host)
    restored_plan(args, plan)
    deployment = HostedDeployment.model_validate(tool.read_json(plan["candidate_hosted"]))
    SQLiteHostedSessionStore.initialize(deployment)
    store = SQLiteHostedSessionStore(deployment)
    try:
        now = datetime.now(UTC)
        store.disable(now)
        service = HostedAccessService(deployment, store, now=lambda: now + timedelta(seconds=3))
        old_proof = VerifiedIdentity(
            deployment.identity_issuer,
            "verified-operator",
            deployment.allowed_email,
            now - timedelta(minutes=1),
            now + timedelta(hours=1),
            "a" * 64,
        )
        old_grant = old_session(old_proof, now)
        with pytest.raises(HostedAccessError, match="approval"):
            service.begin_session(old_proof)
        with pytest.raises(HostedAccessError):
            service.authenticate(old_proof, old_grant.token)
        store.activate("verified-operator")
        with pytest.raises(HostedAccessError, match="Fresh sign-in"):
            service.begin_session(old_proof)
        fresh = VerifiedIdentity(
            deployment.identity_issuer,
            "verified-operator",
            deployment.allowed_email,
            now + timedelta(seconds=1),
            now + timedelta(hours=1),
            "b" * 64,
        )
        grant = service.begin_session(fresh)
        actor = service.authenticate(fresh, grant.token)
        assert actor.workspace_id == plan["workspace_id"]
    finally:
        store.engine.dispose()


def test_existing_administration_destination_is_never_replaced(reset_host):
    args = plan_args(reset_host)
    identity = tool.read_json(args.descriptor)["workspace_id"]
    target = tool.DATA / "epm-a/access" / f"hosted-access-{identity}.sqlite"
    target.write_bytes(b"existing authority")
    with pytest.raises(tool.ResetError, match="already exists"):
        tool.prepare_plan(args)
    assert target.read_bytes() == b"existing authority"


@pytest.mark.parametrize("target", ["candidate", "snapshot"])
def test_altered_configuration_sources_block_cutover(reset_host, target):
    args, plan = planned(reset_host)
    restored_plan(args, plan)
    old = tool.instance_paths("a")[1].read_bytes()
    path = (
        Path(plan["candidate_hosted"]) if target == "candidate" else args.record / "hosted.before"
    )
    path.write_text("tampered source")
    with pytest.raises(tool.ResetError, match="changed"):
        tool.replace_configs(args.record, plan)
    assert tool.instance_paths("a")[1].read_bytes() == old


def test_an_external_second_file_change_is_detected_before_any_replacement(reset_host):
    args, plan = planned(reset_host)
    restored_plan(args, plan)
    original_local = tool.instance_paths("a")[1].read_bytes()
    tool.instance_paths("a")[2].write_text("external change")
    with pytest.raises(tool.ResetError, match="outside this reset"):
        tool.replace_configs(args.record, plan)
    assert tool.instance_paths("a")[1].read_bytes() == original_local


def test_reset_record_must_remain_private(reset_host):
    args, _ = planned(reset_host)
    args.record.chmod(0o755)
    with pytest.raises(tool.ResetError, match="root-private"):
        tool.load_plan(args.record)


def backups(config):
    service = WorkspaceService.from_local_config(config)
    return BackupService(
        service,
        AuditRecorder(SQLiteAuditRepository(service.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )


def domain_rows(workspace):
    with sqlite3.connect(workspace / "database/property-management.sqlite") as connection:
        return {
            table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
            for table in ("parties", "properties", "leases", "tenant_profiles", "provider_profiles")
        }


def seed_demo(root, instance):
    application = Path(__file__).resolve().parents[2]
    config = root / f"config-{instance}.json"
    workspace = root / f"source-{instance}"
    for script, args in (
        ("seed.py", ["--workspace", str(workspace), "--local-config", str(config)]),
        ("verify.py", ["--config", str(config)]),
    ):
        result = subprocess.run(
            [sys.executable, str(application / "demo" / script), *args],
            cwd=application,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    return config, workspace


def test_seeded_a_and_b_encrypted_archives_restore_with_distinct_identities(tmp_path):
    identities = []
    for instance in ("a", "b"):
        config, workspace = seed_demo(tmp_path, instance)
        before = domain_rows(workspace)
        assert len(before["properties"]) == EXPECTED["properties"]
        assert len(before["leases"]) == EXPECTED["leases"]
        archive = tmp_path / f"demo-{instance}.epm-backup"
        phrase = "synthetic reset test passphrase only"
        backups(config).create_backup(phrase, package_type="export", output_path=archive)
        descriptor_path = tmp_path / f"demo-{instance}.json"
        tool.describe(
            SimpleNamespace(
                config=config,
                archive=archive,
                release="release-20261026-02",
                instance=instance,
                source="a" * 40,
                output=descriptor_path,
            )
        )
        metadata = tool.read_json(descriptor_path)
        identities.append(metadata["workspace_id"])
        bootstrap = tmp_path / f"bootstrap-{instance}.json"
        write_json(bootstrap, {"localWorkspacePath": str(tmp_path / f"unused-{instance}")})
        restored = tmp_path / f"restored-{instance}"
        backups(bootstrap).restore(archive, phrase, restored)
        assert tool.read_json(restored / "workspace.json")["workspaceId"] == identities[-1]
        assert domain_rows(restored) == before
        assert domain_rows(workspace) == before
        assert metadata["archive_sha256"] == tool.file_hash(archive)
        restored_config = tmp_path / f"restored-{instance}.json"
        write_json(restored_config, {"localWorkspacePath": str(restored)})
        WorkspaceService.from_local_config(restored_config).open(integrity_check=True)
    assert identities[0] != identities[1]
