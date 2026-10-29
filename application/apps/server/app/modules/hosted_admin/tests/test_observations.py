"""Read-only observation adapters use fixed units and safe registered projections."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.admin_observations import HostConsoleInventory
from scripts.tests.test_host_inventory import instance
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_access.tests.conftest import deployment_values as deployment_values


def test_directory_uses_one_inventory_read_without_source_or_provider_calls():
    source, discovery, reports = Mock(), Mock(), Mock()
    source.inventory.list.return_value = [instance("a"), instance("b")]
    adapter = HostConsoleInventory(source, discovery, reports)
    values = [item.model_dump() for item in adapter.records()]
    source.inventory.list.assert_called_once()
    source.prepare.assert_not_called()
    discovery.assert_not_called()
    reports.assert_not_called()
    assert values[0]["name"] == "Operator A"
    assert not {"workspace", "access_database", "image", "local_config"} & values[0].keys()


def test_host_observations_do_not_infer_boot_policy_or_adopt_unknown_resources():
    source, discovery, reports = Mock(), Mock(), Mock()
    source.inventory.list.return_value = [instance("a"), instance("b")]
    discovery.keys.return_value = ["a", "c"]
    discovery.systemctl.side_effect = ["active\n", "disabled\n"]
    adapter = HostConsoleInventory(source, discovery, reports)
    tunnel = adapter.observe("tunnel", None)
    assert tunnel.service == "active" and tunnel.startup == "disabled"
    assert all(
        call.args[1] == "epm-cloudflared.service" for call in discovery.systemctl.call_args_list
    )
    diff = adapter.observe("discrepancies", None)
    assert diff.unregistered == ["c"] and diff.missing == ["b"]
    source.inventory.register.assert_not_called()
    assert adapter.observe("capacity", None) == reports.snapshot.return_value
    with pytest.raises(AdminError, match="recovery_observation_unavailable"):
        adapter.observe("recovery", "a")


def test_access_observation_validates_source_dates_and_excludes_pending_subjects(deployment_values):
    source = Mock()
    source.paths.configs = Path("/registered")
    status = {
        "active": True,
        "binding_matches_configuration": True,
        "enrollments": [{"subject": "private-subject", "received_at": 1000.0}],
    }
    source.access_snapshot.return_value = deployment_values, status
    adapter = HostConsoleInventory(source, Mock(), Mock())
    value = adapter.observe("access", "a")
    assert value.active and value.pending_enrollments == 1
    assert "private-subject" not in value.model_dump_json()
    assert value.starts < value.expires
    source.access_snapshot.assert_called_once_with("a")


def test_runtime_verifies_exact_registered_mount_and_compares_release():
    source, discovery = Mock(), Mock()
    record = instance("a")
    source.inventory.get.return_value = record
    discovery._service.return_value = (
        {},
        [""] * 9 + [str(record.port)],
        Path("/installed") / record.release,
        None,
        Path(record.local_config),
    )
    discovery.systemctl.return_value = "inactive\n"
    adapter = HostConsoleInventory(source, discovery, Mock())
    result = adapter.observe("runtime", "a")
    assert result.service == "inactive" and result.mount_verified and result.release_matches
    discovery._mount.assert_called_once_with(Path(record.mount), Path(record.image))
