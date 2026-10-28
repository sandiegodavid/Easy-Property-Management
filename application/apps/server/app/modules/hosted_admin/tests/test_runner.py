"""Registered instance selections and shared maintenance interlocks, never live host calls."""

from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import admin_console
from scripts.host_admin import HostPaths
from scripts.tests.test_host_inventory import instance
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.tests.test_authority import command


@pytest.fixture
def runner(tmp_path):
    paths = HostPaths(configs=tmp_path / "configs", security_root=tmp_path, owner_uid=os.getuid())
    paths.configs.mkdir(mode=0o700)
    local = paths.configs / "local-c.json"
    local.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    local.chmod(0o600)
    item = replace(instance("c"), local_config=str(local))
    inventory = Mock()
    inventory.get.return_value = item
    config = paths.configs / "hosted-c.json"
    config.write_text(
        json.dumps(
            {
                "operator_id": item.operator_id,
                "workspace_id": item.workspace_id,
                "administration_database": item.access_database,
                "allowed_email": item.email,
                "deployment_mode": "hosted_demo",
            }
        )
    )
    config.chmod(0o600)
    return admin_console.SourceRunner(paths, inventory), inventory, config


def test_prepare_pins_registered_identity_and_config_and_rejects_swap(runner):
    source, inventory, config = runner
    first = source.prepare("c")
    assert first["instance"] == asdict(instance_from := inventory.get.return_value)
    assert "command" not in first
    inventory.get.return_value = replace(instance_from, workspace_id="wrong-workspace")
    with pytest.raises(AdminError, match="binding_changed"):
        source.prepare("c")
    inventory.get.return_value = instance_from
    config.unlink()
    config.symlink_to("/etc/passwd")
    with pytest.raises(ValueError):
        source.prepare("c")


def test_runner_rejects_different_allocation_before_source_call(runner, monkeypatch):
    source, inventory, _ = runner
    original = source.prepare("c")
    inventory.get.return_value = replace(inventory.get.return_value, revision=2)
    read_end, write_end = os.pipe()
    monkeypatch.setattr(admin_console, "lock_host", lambda _: read_end)
    source._transport = Mock(return_value={"found": False, "result": None})
    source._run = Mock(side_effect=AssertionError("Must not dispatch"))
    try:
        with pytest.raises(AdminError, match="binding_changed"):
            source(
                command().model_dump()
                | {"source_reference": original, "authority_reference": "owner:1"}
            )
        source._run.assert_not_called()
    finally:
        os.close(write_end)


def test_unreconciled_private_maintenance_blocks_source_mutation(runner, monkeypatch):
    source, inventory, _ = runner
    original = source.prepare("c")
    database = sqlite3.connect(":memory:")
    database.execute("CREATE TABLE maintenance (state TEXT)")
    database.execute("INSERT INTO maintenance VALUES ('needs_reconciliation')")

    @contextmanager
    def connection():
        yield database

    inventory.connection = connection
    read_end, write_end = os.pipe()
    monkeypatch.setattr(admin_console, "lock_host", lambda _: read_end)
    source._transport = Mock(return_value={"found": False, "result": None})
    source._run = Mock(side_effect=AssertionError("Must not dispatch"))
    try:
        with pytest.raises(AdminError, match="maintenance_pending"):
            source(
                command().model_dump()
                | {"source_reference": original, "authority_reference": "owner:1"}
            )
    finally:
        database.close()
        os.close(write_end)


def test_source_runner_has_fixed_argv_and_environment(runner, monkeypatch):
    source, inventory, _ = runner
    item = asdict(inventory.get.return_value)
    monkeypatch.setattr(admin_console, "protected", lambda *_args, **_kwargs: None)
    # Test only the executable adapter. Production resolves and verifies the installed binary.
    monkeypatch.setattr(admin_console.Path, "resolve", lambda value, **_: value)
    cmd = command()
    expected = {
        "operation_id": cmd.operation_id,
        "action": "disable",
        "revision": 1,
        "binding_revision": 0,
        "fence": 1,
        "generation": 1,
        "active": False,
    }
    source.run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(expected)))
    payload = cmd.model_dump() | {"authority_reference": "owner:1"}
    assert source._run(payload, item) == expected
    argv = source.run.call_args.args[0]
    assert argv[:4] == ["/usr/sbin/runuser", "-u", "epm-c", "--"]
    assert argv[-2] == str(source.paths.configs / "hosted-c.json")
    assert argv[-1] == item["local_config"]
    assert source.run.call_args.kwargs["env"] == {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert "shell" not in source.run.call_args.kwargs


def test_original_source_receipt_reconciles_after_configuration_revision_advances(
    runner, monkeypatch
):
    source, inventory, _ = runner
    reference = source.prepare("c")
    cmd = command()
    payload = cmd.model_dump() | {"source_reference": reference, "authority_reference": "owner:1"}
    expected = {
        "operation_id": cmd.operation_id,
        "action": "disable",
        "revision": 1,
        "binding_revision": 0,
        "fence": 1,
        "generation": 1,
        "active": False,
    }
    inventory.get.return_value = replace(inventory.get.return_value, revision=2)
    source._transport = Mock(return_value={"found": True, "result": expected})
    read_end, write_end = os.pipe()
    monkeypatch.setattr(admin_console, "lock_host", lambda _: read_end)
    try:
        assert source(payload) == expected
        assert source._transport.call_args.args[1]["command"]["operation_id"] == cmd.operation_id
    finally:
        os.close(write_end)


def test_source_receipt_never_reconciles_through_another_allocation(runner, monkeypatch):
    source, inventory, _ = runner
    reference = source.prepare("c")
    inventory.get.return_value = replace(inventory.get.return_value, allocation_id="different")
    source._transport = Mock(side_effect=AssertionError("Wrong allocation must not run"))
    read_end, write_end = os.pipe()
    monkeypatch.setattr(admin_console, "lock_host", lambda _: read_end)
    try:
        with pytest.raises(AdminError, match="binding_changed"):
            source(
                command().model_dump()
                | {"source_reference": reference, "authority_reference": "owner:1"}
            )
        source._transport.assert_not_called()
    finally:
        os.close(write_end)


def test_runtime_readiness_requires_matching_registered_source_and_active_service(
    runner, monkeypatch
):
    from scripts.host_admin import HostDiscovery, InventoryError, RESOURCE_FIELDS, digest_json

    source, inventory, _ = runner
    item = inventory.get.return_value
    facts = dict.fromkeys(RESOURCE_FIELDS, "qualified")
    item = replace(item, profile="observed-" + digest_json(facts)[:16])
    discovery = HostDiscovery(source.paths)
    discovery._service = Mock(
        return_value=(
            facts,
            [""] * 9 + [str(item.port)],
            source.paths.releases / item.release,
            None,
            admin_console.Path(item.local_config),
        )
    )
    discovery._release = Mock()
    discovery.systemctl = Mock(return_value="active")
    discovery.source_command_ready(item)
    discovery._release.assert_called_once()
    discovery.systemctl.return_value = "inactive"
    with pytest.raises(InventoryError):
        discovery.source_command_ready(item)
    discovery.systemctl.return_value = "active"
    with pytest.raises(InventoryError):
        discovery.source_command_ready(replace(item, profile="different-profile"))


def test_private_console_parser_and_listener_identity_fail_closed(monkeypatch):
    assert admin_console.parser().parse_args(["restore-identity"]).action == "restore-identity"
    monkeypatch.setattr(admin_console.sys, "argv", ["console", "serve", "--port", "8765"])
    monkeypatch.setattr(admin_console.os, "geteuid", lambda: 0)
    with pytest.raises(AdminError, match="http_identity_invalid"):
        admin_console.main()


def test_source_timeout_kills_its_group_before_locks_can_be_released(monkeypatch):
    import signal
    import subprocess

    process = Mock(pid=54321)
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("fixed-source-command", 20),
        ("", ""),
    ]
    context = Mock()
    context.__enter__ = Mock(return_value=process)
    context.__exit__ = Mock(return_value=False)
    popen = Mock(return_value=context)
    kill = Mock()
    monkeypatch.setattr(admin_console.subprocess, "Popen", popen)
    monkeypatch.setattr(admin_console.os, "killpg", kill)
    with pytest.raises(AdminError, match="source_command_unavailable"):
        admin_console.source_process(
            ["fixed-source-command"],
            input="{}",
            timeout=20,
            text=True,
            capture_output=True,
            check=False,
        )
    assert popen.call_args.kwargs["start_new_session"] is True
    kill.assert_called_once_with(54321, signal.SIGKILL)
    assert process.communicate.call_count == 2


@pytest.mark.parametrize("active", [False, True])
def test_fenced_source_containment_uses_exact_registered_target_and_owning_disable(
    runner, monkeypatch, active
):
    source, _, _ = runner
    cmd = command()
    payload = cmd.model_dump() | {
        "source_reference": source.prepare("c"),
        "authority_reference": "owner:1",
    }
    status = {
        "admin_revision": 2,
        "binding_revision": 1,
        "admin_fence": 3,
        "generation": 4,
        "active": active,
        "binding_matches_configuration": True,
        "enrollments": [],
    }
    read_end, write_end = os.pipe()
    monkeypatch.setattr(admin_console, "lock_host", lambda _: read_end)

    def transport(_instance, request):
        if request.get("query") == "status":
            return status
        assert request["action"] == "disable"
        assert request["expected_revision"] == 2
        assert request["expected_binding_revision"] == 1
        assert request["fence"] == 3
        assert request["operation_id"] != cmd.operation_id
        return {
            "operation_id": request["operation_id"],
            "action": "disable",
            "revision": 3,
            "binding_revision": 1,
            "fence": 4,
            "generation": 5,
            "active": False,
        }

    source._transport = Mock(side_effect=transport)
    try:
        assert source.contain(payload)
        assert source._transport.call_count == 1 + int(active)
    finally:
        os.close(write_end)


def test_source_reconciliation_never_reads_another_operator_allocation(runner, monkeypatch):
    source, inventory, _ = runner
    payload = command().model_dump() | {
        "source_reference": source.prepare("c"),
        "authority_reference": "owner:1",
    }
    inventory.get.return_value = replace(inventory.get.return_value, operator_id="wrong-operator")
    source._transport = Mock(side_effect=AssertionError("Wrong source must not be queried"))
    read_end, write_end = os.pipe()
    monkeypatch.setattr(admin_console, "lock_host", lambda _: read_end)
    try:
        with pytest.raises(AdminError, match="binding_changed"):
            source.reconcile(payload)
    finally:
        os.close(write_end)
