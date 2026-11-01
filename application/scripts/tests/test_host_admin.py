"""Observe/adopt and fence A/B/C only under isolated temporary host roots."""

from dataclasses import asdict
import ast
import hashlib
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts import host_admin as admin
from scripts.host_inventory import HostInventory, InventoryError


def write(path, value):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    path.chmod(0o600)


@pytest.fixture
def host(tmp_path, monkeypatch):
    paths = admin.HostPaths(
        control=tmp_path / "control",
        configs=tmp_path / "configs",
        data=tmp_path / "data",
        backups=tmp_path / "backups",
        releases=tmp_path / "releases",
        systemd=tmp_path / "systemd",
        systemd_runtime=tmp_path / "runtime-systemd",
        systemd_vendor=tmp_path / "vendor-systemd",
        tools=tmp_path / "tools",
        mountinfo=tmp_path / "mountinfo",
        devices=tmp_path / "devices",
        fstab=tmp_path / "fstab",
        security_root=tmp_path,
        owner_uid=os.getuid(),
    )
    for directory in (
        paths.control,
        paths.configs,
        paths.data,
        paths.backups,
        paths.releases,
        paths.systemd,
        paths.systemd_runtime,
        paths.systemd_vendor,
        paths.tools,
    ):
        directory.mkdir(mode=0o700)
    write(paths.fstab, "")
    write(paths.mountinfo, "")
    for name in admin.ADMIN_TOOLS:
        write(paths.tools / name, "#!/bin/bash\n")
    tunnel_config = paths.configs / "tunnel.yml"
    write(tunnel_config, "ingress:\n  - service: http_status:404\n")
    monkeypatch.setattr(admin, "WORKSPACE_BYTES", 4096)
    monkeypatch.setattr(
        admin.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    )
    commands = {}

    def run(argv, **kwargs):
        if "epm-cloudflared.service" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "ExecStart={ path=/usr/bin/cloudflared ; "
                    f"argv[]=/usr/bin/cloudflared --config {tunnel_config} tunnel run ; "
                    "ignore_errors=no ; }\nUnitFileState=disabled\n"
                ),
            )
        if argv[1] in {"list-units", "list-unit-files"}:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="\n".join(
                    f"epm-hosted@{key}.service loaded inactive dead" for key in commands
                ),
            )
        assert argv[1] == "show"
        key = argv[2].removeprefix("epm-hosted@").removesuffix(".service")
        return subprocess.CompletedProcess(argv, 0, stdout=commands[key])

    discovery = admin.HostDiscovery(paths, run=run)
    store = HostInventory(paths.control / "inventory.sqlite", owner_uid=os.getuid())
    store.initialize()
    return paths, commands, discovery, store


def add_instance(host, key, port=8012):
    paths, commands, _, _ = host
    user = f"epm-{key}"
    release = paths.releases / "release-20261027-01"
    release.mkdir(mode=0o700, exist_ok=True)
    write(release / "SOURCE_COMMIT.txt", "a" * 40)
    digest = hashlib.sha256((release / "SOURCE_COMMIT.txt").read_bytes()).hexdigest()
    write(release / "SHA256SUMS", f"{digest}  SOURCE_COMMIT.txt\n")
    base = paths.data / user
    volume = base / "volume"
    workspace = volume / "workspace"
    workspace_id, operator_id = str(uuid4()), str(uuid4())
    write(workspace / "workspace.json", {"workspaceId": workspace_id})
    local = base / "hosted-local.json"
    write(local, {"localWorkspacePath": str(workspace)})
    image = base / "volume.ext4"
    image.write_bytes(b"0" * 4096)
    image.chmod(0o600)
    deployment = paths.configs / f"hosted-{key}.json"
    access = base / "access" / "access.sqlite"
    values = {
        "deployment_mode": "hosted_demo",
        "workspace_id": workspace_id,
        "operator_id": operator_id,
        "allowed_email": f"{key}@example.com",
        "public_origin": f"https://demo-{key}.example.com",
        "identity_issuer": "https://team.cloudflareaccess.com",
        "storage_volume": str(volume),
        "storage_image": str(image),
        "administration_database": str(access),
        "identity_audience": "a" * 64,
        "administrator_contact": "admin@example.com",
        "enabled_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "capabilities": ["records.read", "records.write", "files.read", "files.write"],
    }
    write(deployment, values)
    access.parent.mkdir(mode=0o700)
    with sqlite3.connect(access) as connection:
        connection.execute(
            "CREATE TABLE hosted_operator (id, workspace_id, issuer, email, subject)"
        )
        connection.execute(
            "INSERT INTO hosted_operator VALUES (?, ?, ?, ?, ?)",
            (
                operator_id,
                workspace_id,
                values["identity_issuer"],
                values["allowed_email"],
                "private-subject",
            ),
        )
    access.chmod(0o600)
    index = ord(key) - ord("a") + 1
    with paths.mountinfo.open("a") as stream:
        stream.write(
            f"1 2 7:{index} / {volume} rw,nodev,nosuid,noexec - ext4 /dev/loop{index} rw\n"
        )
    write(paths.devices / f"7:{index}" / "size", "8")
    write(paths.devices / f"7:{index}" / "loop/backing_file", str(image))
    python = release / "venv/bin/python"
    fragment = paths.systemd / "epm-hosted@.service"
    write(fragment, "[Service]\nType=simple\n")
    commands[key] = (
        f"ExecStart={{ path={python} ; argv[]={python} -m app --config {local} "
        f"serve-hosted --deployment {deployment} --port {port} ; ignore_errors=no ; }}\n"
        f"User={user}\nGroup={user}\nMemoryHigh=1073741824\nMemoryMax=1572864000\n"
        f"CPUQuotaPerSecUSec=900ms\nRequiresMountsFor={volume}\n"
        f"FragmentPath={fragment}\nDropInPaths=\n"
    )
    return values


def test_explicit_adoption_keeps_three_independent_identities_and_unknown_recovery(host):
    _, _, discovery, store = host
    for index, key in enumerate(("a", "b", "c")):
        add_instance(host, key, 8010 + index)
        observed = discovery.observe(key)
        item = admin.adopt(store, discovery, key, observed["digest"])
        assert admin.adopt(store, discovery, key, observed["digest"]) == item
        baseline = json.loads(
            (store.path.parent / "baselines" / f"{item.baseline_digest}.json").read_text()
        )
        assert baseline["recovery_status"] == "unverified"
        assert baseline["rollback_acceptance"] == "not_recorded"
        assert "private-subject" not in json.dumps(baseline)
    assert len({item.instance_id for item in store.list()}) == len("abc")
    assert len({item.allocation_id for item in store.list()}) == len("abc")
    assert discovery.report(store.list())["discrepancies"] == []


def test_changed_observation_never_adopts_silently(host):
    paths, _, discovery, store = host
    values = add_instance(host, "a")
    before = discovery.observe("a")
    values["allowed_email"] = "changed@example.com"
    write(paths.configs / "hosted-a.json", values)
    with pytest.raises(InventoryError, match="binding differs"):
        admin.adopt(store, discovery, "a", before["digest"])
    assert store.list() == []


def test_stopped_unmanaged_c_is_reported_and_blocks_maintenance(host):
    _, _, discovery, store = host
    add_instance(host, "c")
    report = discovery.report(store.list())
    assert report["discrepancies"] == [{"key": "c", "kind": "unmanaged"}]
    with pytest.raises(InventoryError):
        admin.run_maintenance(store, discovery, "cleanup", "cleanup")


@pytest.mark.parametrize("corrupt", ["config_symlink", "release", "mount", "binding"])
def test_unsafe_host_facts_cannot_be_adopted(host, corrupt):
    paths, _, discovery, store = host
    values = add_instance(host, "a")
    if corrupt == "config_symlink":
        target = paths.configs / "hosted-a.json"
        replacement = paths.configs / "other.json"
        target.rename(replacement)
        target.symlink_to(replacement)
    elif corrupt == "release":
        write(paths.releases / "release-20261027-01/SOURCE_COMMIT.txt", "changed")
    elif corrupt == "mount":
        write(paths.mountinfo, "")
    else:
        with sqlite3.connect(values["administration_database"]) as connection:
            connection.execute("UPDATE hosted_operator SET workspace_id = 'changed'")
    with pytest.raises(InventoryError):
        admin.adopt(store, discovery, "a", "a" * 64)
    assert store.list() == []


def test_host_lock_is_shared_and_released(host):
    _, _, _, store = host
    descriptor = admin.lock_host(store)
    try:
        with pytest.raises(InventoryError, match="Another host maintenance"):
            admin.lock_host(store)
    finally:
        os.close(descriptor)
    os.close(admin.lock_host(store))


def test_maintenance_preserves_failure_and_requires_explicit_reconciliation(host, monkeypatch):
    paths, _, discovery, store = host
    add_instance(host, "a")
    admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    write(paths.tools / "epm-release-vm.sh", "#!/bin/bash\n")
    monkeypatch.setenv("SUDO_USER", "administrator")
    failure_code = 7

    def run(argv, **kwargs):
        identifier = kwargs["env"]["EPM_HOST_MAINTENANCE_ID"]
        admin.require_maintenance(store, identifier)
        return subprocess.CompletedProcess(argv, failure_code)

    monkeypatch.setattr(admin.subprocess, "run", run)
    identifier, code = admin.run_maintenance(
        store,
        discovery,
        "release",
        "deploy",
        request=admin.MaintenanceRequest(key="a", release="release-20261027-02"),
    )
    assert code == failure_code
    assert store.maintenance(identifier)["state"] == "needs_reconciliation"
    with pytest.raises(InventoryError, match="Unfinished maintenance"):
        admin.run_maintenance(
            store,
            discovery,
            "release",
            "deploy",
            request=admin.MaintenanceRequest(key="a", release="release-20261027-02"),
        )
    admin.reconcile(store, discovery, identifier, discovery.report(store.list())["digest"])
    assert store.maintenance(identifier)["state"] == "reconciled"


def test_reconcile_rejects_stale_digest_and_retains_original_allocations(host):
    _, _, discovery, store = host
    add_instance(host, "a")
    item = admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    identifier = store.begin_maintenance(
        "release",
        "deploy",
        "a" * 64,
        admin.MaintenanceRequest(key="a", release="release-20261027-01"),
    )
    store.finish_maintenance(identifier, 0)
    with pytest.raises(InventoryError, match="incomplete or changed"):
        admin.reconcile(store, discovery, identifier, "b" * 64)
    assert asdict(store.get("a")) == asdict(item)


@pytest.mark.parametrize("directory", ["systemd", "systemd_runtime", "systemd_vendor"])
def test_inactive_dropin_only_instance_is_discovered(host, directory):
    paths, _, discovery, _ = host
    (getattr(paths, directory) / "epm-hosted@c.service.d").mkdir()
    assert discovery.keys() == ["c"]


def test_shared_host_directories_are_not_adopted_as_instances(host):
    paths, _, discovery, _ = host
    (paths.data / "epm-volumes").mkdir()
    (paths.data / "epm-recovery").mkdir()
    (paths.data / "epm-admin").mkdir()
    (paths.data / "epm-tunnel").mkdir()
    write(paths.data / "epm-volumes/epm-c.ext4", "retained")
    write(
        paths.fstab,
        f"{paths.data}/epm-volumes/epm-c.ext4 {paths.data}/epm-c/volume ext4 defaults 0 0\n",
    )
    assert discovery.keys() == ["c"]


def test_malformed_instance_does_not_hide_other_observations_or_leak_values(host):
    paths, _, discovery, _ = host
    add_instance(host, "a", 8010)
    values = add_instance(host, "c", 8012)
    values["capabilities"] = {"untrusted": "secret-should-never-appear"}
    write(paths.configs / "hosted-c.json", values)
    report = discovery.report([])
    assert set(report["observed"]) == {"a"}
    assert any(
        problem["key"] == "c" and problem["kind"] == "unverifiable"
        for problem in report["discrepancies"]
    )
    assert "secret-should-never-appear" not in json.dumps(report)


def test_unknown_unverifiable_instance_blocks_even_resumed_maintenance(host):
    paths, _, discovery, store = host
    add_instance(host, "a")
    admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    identifier = store.begin_maintenance(
        "release",
        "deploy",
        "a" * 64,
        admin.MaintenanceRequest(key="a", release="release-20261027-01"),
    )
    store.finish_maintenance(identifier, 1)
    write(paths.configs / "hosted-c.json", "unreadable configuration")
    with pytest.raises(InventoryError, match="discrepancies block"):
        admin.run_maintenance(
            store,
            discovery,
            "release",
            "resume",
            request=admin.MaintenanceRequest(resume=identifier),
        )


def test_completed_scan_cannot_ignore_a_missing_registered_baseline(host):
    _, _, discovery, store = host
    add_instance(host, "a")
    item = admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    (store.path.parent / "baselines" / f"{item.baseline_digest}.json").unlink()
    with pytest.raises(InventoryError, match="baseline evidence is missing"):
        admin.protected_releases(store)


def test_abandoned_maintenance_can_be_reconciled_without_replaying_commands(host):
    _, _, discovery, store = host
    add_instance(host, "a")
    admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    identifier = store.begin_maintenance(
        "release",
        "deploy",
        "a" * 64,
        admin.MaintenanceRequest(key="a", release="release-20261027-01"),
    )
    admin.reconcile(store, discovery, identifier, discovery.report(store.list())["digest"])
    assert store.maintenance(identifier)["state"] == "reconciled"
    assert store.maintenance(identifier)["exit_code"] == -1


def test_old_operation_cannot_borrow_an_unrelated_host_lock(host):
    _, _, discovery, store = host
    add_instance(host, "a")
    admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    identifier = store.begin_maintenance(
        "release",
        "deploy",
        "a" * 64,
        admin.MaintenanceRequest(key="a", release="release-20261027-01"),
    )
    descriptor = admin.lock_host(store)
    try:
        with pytest.raises(InventoryError, match="different operation"):
            admin.require_maintenance(store, identifier)
    finally:
        os.close(descriptor)


def test_child_keeps_the_host_lock_and_does_not_receive_arbitrary_environment(host, monkeypatch):
    paths, _, discovery, store = host
    add_instance(host, "a")
    admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    write(paths.tools / "epm-release-vm.sh", "#!/bin/bash\n")
    monkeypatch.setenv("SUDO_USER", "administrator")
    monkeypatch.setenv("BASH_ENV", "/untrusted/injected.sh")

    def run(argv, **kwargs):
        assert argv[:3] == ["/usr/sbin/runuser", "-u", "administrator"]
        assert "BASH_ENV" not in kwargs["env"]
        (descriptor,) = kwargs["pass_fds"]
        assert Path(f"/dev/fd/{descriptor}").exists()
        with pytest.raises(InventoryError, match="Another host maintenance"):
            admin.lock_host(store)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(admin.subprocess, "run", run)
    admin.run_maintenance(
        store,
        discovery,
        "release",
        "deploy",
        request=admin.MaintenanceRequest(key="a", release="release-20261027-02"),
    )


def test_journal_failure_does_not_replace_the_original_execution_failure(host, monkeypatch):
    paths, _, discovery, store = host
    add_instance(host, "a")
    admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    write(paths.tools / "epm-release-vm.sh", "#!/bin/bash\n")
    monkeypatch.setenv("SUDO_USER", "administrator")

    def execution_failed(*args, **kwargs):
        raise RuntimeError("original execution failure")

    def journal_failed(*args):
        raise sqlite3.OperationalError("disk is full")

    monkeypatch.setattr(admin.subprocess, "run", execution_failed)
    monkeypatch.setattr(store, "finish_maintenance", journal_failed)
    with pytest.raises(RuntimeError, match="original execution failure") as caught:
        admin.run_maintenance(
            store,
            discovery,
            "release",
            "deploy",
            request=admin.MaintenanceRequest(key="a", release="release-20261027-02"),
        )
    assert "needs journal reconciliation" in caught.value.__notes__[0]


def test_tunnel_observation_records_identity_without_claiming_provider_acceptance(host):
    paths, _, discovery, store = host
    add_instance(host, "a")
    observed = discovery.observe("a")
    admin.adopt(store, discovery, "a", observed["digest"])
    assert observed["facts"]["tunnel"]["provider_verification"] == "not_performed"
    write(paths.configs / "tunnel.yml", "changed routing\n")
    report = discovery.report(store.list())
    assert report["discrepancies"][0]["fields"] == ["config_digest"]


def test_backup_staging_is_derived_from_registered_allocation_and_idempotent(host):
    paths, _, discovery, store = host
    add_instance(host, "c")
    admin.adopt(store, discovery, "c", discovery.observe("c")["digest"])
    descriptor = admin.lock_host(store)
    try:
        identifier = store.begin_maintenance(
            "release", "backup", "a" * 64, request=admin.MaintenanceRequest(key="c")
        )
        admin.mark_lock(descriptor, identifier)
        args = SimpleNamespace(key="c", maintenance_id=identifier)
        admin.prepare_backup(args, store, paths)
        admin.prepare_backup(args, store, paths)
        for path in (paths.backups / "epm-c/staging", paths.data / "epm-recovery/c/staging"):
            assert path.is_dir()
            assert path.stat().st_mode & 0o777 == admin.PRIVATE_DIRECTORY_MODE
    finally:
        os.close(descriptor)


def test_existing_staging_permissions_are_not_silently_repaired(host):
    paths, _, _, _ = host
    target = paths.backups / "epm-c"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    identity = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    with pytest.raises(InventoryError, match="unexpected ownership or permissions"):
        admin.private_directory(target, paths, identity)
    assert target.stat().st_mode & 0o777 != admin.PRIVATE_DIRECTORY_MODE


def test_staging_symlink_is_rejected_without_touching_its_target(host):
    paths, _, _, _ = host
    target = paths.backups / "preserve"
    target.mkdir(mode=0o700)
    link = paths.backups / "epm-c"
    link.symlink_to(target)
    with pytest.raises(OSError):
        admin.private_directory(
            link, paths, SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        )
    assert target.stat().st_mode & 0o777 == admin.PRIVATE_DIRECTORY_MODE


def test_system_interpreter_helpers_remain_python_312_compatible():
    scripts = Path(__file__).resolve().parents[1]
    for name in ("host_admin.py", "host_inventory.py", "release_cleanup.py"):
        ast.parse((scripts / name).read_text(), feature_version=(3, 12))


def test_private_inventory_cli_denies_unprivileged_callers_before_opening_control_store(
    monkeypatch,
):
    monkeypatch.setattr(sys, "argv", ["host_admin.py", "keys"])
    monkeypatch.setattr(admin.os, "geteuid", lambda: 1001)
    with pytest.raises(InventoryError, match="private root administrator path"):
        admin.main()


def test_private_cli_has_no_arbitrary_exec_or_path_override():
    for arguments in (["exec", "bash"], ["init", "--root", "/tmp/alternate"]):
        with pytest.raises(SystemExit):
            admin.argument_parser().parse_args(arguments)


def test_root_tooling_changes_require_explicit_incident_reconciliation(host):
    paths, _, discovery, store = host
    add_instance(host, "a")
    original = admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    write(paths.tools / "epm-release-vm.sh", "#!/bin/bash\n# reviewed private tooling update\n")
    with pytest.raises(InventoryError, match="discrepancies block"):
        admin.run_maintenance(
            store,
            discovery,
            "release",
            "deploy",
            request=admin.MaintenanceRequest(key="a", release="release-20261027-02"),
        )
    report = discovery.report(store.list())
    args = SimpleNamespace(incident="private-tooling-update", observed_digest=report["digest"])
    admin.record_breakglass(args, store, discovery)
    current = store.get("a")
    assert current.instance_id == original.instance_id
    assert current.allocation_id == original.allocation_id
    assert current.revision == original.revision + 1
    assert store.maintenance_history()[0]["incident_reference"] == args.incident
    assert admin.protected_releases(store) == [original.release]


@pytest.mark.parametrize("phase", ["resume", "reconcile"])
@pytest.mark.parametrize("change", ["release", "configuration"])
def test_a_operation_rejects_changed_b_before_execution_or_reconciliation(
    host, monkeypatch, phase, change
):
    paths, commands, discovery, store = host
    for key, port in (("a", 8001), ("b", 8002)):
        add_instance(host, key, port)
        admin.adopt(store, discovery, key, discovery.observe(key)["digest"])
    identifier = store.begin_maintenance(
        "release",
        "deploy",
        discovery.report(store.list())["digest"],
        request=admin.MaintenanceRequest(key="a", release="release-20261028-01"),
    )
    store.finish_maintenance(identifier, 1)
    if change == "release":
        shutil.copytree(
            paths.releases / "release-20261027-01", paths.releases / "release-20261028-01"
        )
        commands["b"] = commands["b"].replace("release-20261027-01", "release-20261028-01")
    else:
        deployment = paths.configs / "hosted-b.json"
        configuration = json.loads(deployment.read_text())
        configuration["administrator_contact"] = "different-admin@example.com"
        write(deployment, configuration)
    monkeypatch.setenv("SUDO_USER", "administrator")
    with pytest.raises(InventoryError, match="outside the maintenance target"):
        if phase == "resume":
            admin.run_maintenance(
                store,
                discovery,
                "release",
                "resume",
                request=admin.MaintenanceRequest(resume=identifier),
            )
        else:
            admin.reconcile(store, discovery, identifier, discovery.report(store.list())["digest"])
    assert store.maintenance(identifier)["state"] == "needs_reconciliation"
    assert all(item.revision == 1 for item in store.list())


def test_resumed_child_reloads_original_selections_and_checkpoint(host, monkeypatch):
    _, _, discovery, store = host
    add_instance(host, "a")
    source = admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    identifier = store.begin_maintenance(
        "release",
        "deploy",
        discovery.report(store.list())["digest"],
        request=admin.MaintenanceRequest(key="a", release="release-20261028-01"),
    )
    store.finish_maintenance(identifier, 1)
    intent = store.maintenance_intent(identifier)
    monkeypatch.setenv("SUDO_USER", "administrator")
    monkeypatch.setenv("EPM_INSTANCE", "b")
    monkeypatch.setenv("EPM_RELEASE", "release-20261029-01")
    monkeypatch.setenv("EPM_DEPLOY_RECORD", "/different/checkpoint")

    def run(argv, **kwargs):
        environment = kwargs["env"]
        assert environment["EPM_INSTANCE"] == source.key
        assert environment["EPM_RELEASE"] == intent["release"]
        assert environment["EPM_DEPLOY_RECORD"] == intent["checkpoint"]
        with pytest.raises(InventoryError, match="original maintenance target"):
            admin.select_command(
                SimpleNamespace(maintenance_id=identifier, key="b", format="json"),
                store,
                discovery.paths,
            )
        with pytest.raises(InventoryError, match="original maintenance intent"):
            admin.assert_intent(
                SimpleNamespace(maintenance_id=identifier, checkpoint="/different/checkpoint"),
                store,
            )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(admin.subprocess, "run", run)
    assert admin.run_maintenance(
        store, discovery, "release", "resume", request=admin.MaintenanceRequest(resume=identifier)
    ) == (
        identifier,
        0,
    )
    assert store.maintenance_intent(identifier) == intent


def test_reconciliation_accepts_only_intended_target_release_and_keeps_b(host):
    paths, commands, discovery, store = host
    for key, port in (("a", 8001), ("b", 8002)):
        add_instance(host, key, port)
        admin.adopt(store, discovery, key, discovery.observe(key)["digest"])
    original_b = store.get("b")
    identifier = store.begin_maintenance(
        "release",
        "deploy",
        discovery.report(store.list())["digest"],
        request=admin.MaintenanceRequest(key="a", release="release-20261028-01"),
    )
    store.finish_maintenance(identifier, 0)
    shutil.copytree(paths.releases / "release-20261027-01", paths.releases / "release-20261028-01")
    commands["a"] = commands["a"].replace("release-20261027-01", "release-20261028-01")
    admin.reconcile(store, discovery, identifier, discovery.report(store.list())["digest"])
    assert store.get("a").release == "release-20261028-01"
    assert store.get("a").revision == original_b.revision + 1
    assert store.get("b") == original_b
    assert store.maintenance(identifier)["state"] == "reconciled"


def test_maintenance_cli_forwards_the_reviewed_selection(host, monkeypatch):
    _, _, discovery, store = host
    arguments = admin.argument_parser().parse_args(
        [
            "maintenance",
            "--kind",
            "release",
            "--action",
            "deploy",
            "--key",
            "a",
            "--release",
            "release-20261028-01",
        ]
    )

    def run(actual_store, actual_discovery, kind, action, request):
        assert actual_store is store
        assert actual_discovery is discovery
        assert (kind, action) == ("release", "deploy")
        assert request == admin.MaintenanceRequest(key="a", release="release-20261028-01")
        return "original-maintenance", 0

    monkeypatch.setattr(admin, "run_maintenance", run)
    with pytest.raises(SystemExit) as caught:
        admin.maintenance_command(arguments, store, discovery)
    assert caught.value.code == 0


def test_upgrade_reservation_protects_target_and_rollback_release_without_holding_host_lock(host):
    _, _, discovery, store = host
    add_instance(host, "a")
    original = admin.adopt(store, discovery, "a", discovery.observe("a")["digest"])
    identifier = str(uuid4())
    target = "release-20261031-01"
    descriptor = admin.lock_host(store)
    try:
        store.reserve_upgrade(identifier, original, target)
    finally:
        os.close(descriptor)
    # A durable reservation does not keep the process-wide flock held through
    # backups or provider calls. Other operators' urgent containment can still
    # acquire it; ordinary maintenance admission remains blocked durably.
    descriptor = admin.lock_host(store)
    os.close(descriptor)
    assert admin.protected_releases(store) == sorted([original.release, target])
    assert store.get("a") == original
