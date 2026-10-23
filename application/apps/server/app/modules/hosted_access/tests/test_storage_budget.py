"""Admission counts concurrent staging and fails closed without touching business data."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.configuration import (
    HostedConfigurationError,
    WORKSPACE_BYTES,
)
from app.modules.hosted_access.application.storage_budget import (
    HostedStorageBudget,
    StorageFacts,
    WRITE_HEADROOM,
    MIB,
)
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.storage_budget import (
    build_storage_budget,
    _mount_identity,
)


def facts(**changes):
    return replace(
        StorageFacts(WORKSPACE_BYTES, 220 * MIB, 30 * 1024 * MIB, 20 * 1024 * MIB, 10000), **changes
    )


def test_reserves_all_three_copies_and_serializes_concurrent_capacity():
    budget = HostedStorageBudget(facts)
    with budget.reserve(50 * MIB, write=True):
        assert budget.reserved_bytes == WRITE_HEADROOM + 150 * MIB
        with pytest.raises(HostedAccessError) as caught:
            with budget.reserve(50 * MIB, write=True):
                pytest.fail("Concurrent upload bypassed reservation")
        assert caught.value.code == "hosted_storage_quota_exceeded"
    assert budget.reserved_bytes == 0
    with budget.reserve(50 * MIB, write=True):
        pass


def test_current_journal_growth_counts_in_addition_to_unfinished_reservation():
    state = [facts()]
    budget = HostedStorageBudget(lambda: state[0])
    with budget.reserve(10 * MIB, write=True):
        # Committed/retained bytes and live journals reduce actual free space.
        state[0] = facts(available_bytes=50 * MIB)
        with pytest.raises(HostedAccessError):
            with budget.reserve(0, write=True):
                pytest.fail("Growth was ignored")
    assert budget.reserved_bytes == 0


def test_failed_body_or_domain_transaction_always_releases_reservation():
    budget = HostedStorageBudget(facts)
    with pytest.raises(RuntimeError):
        with budget.reserve(MIB, write=True):
            raise RuntimeError("transaction rollback")
    assert budget.reserved_bytes == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"available_bytes": WRITE_HEADROOM - 1},
        {"available_inodes": 127},
        {"host_available_bytes": WRITE_HEADROOM - 1},
    ],
)
def test_headroom_is_never_admitted(changes):
    with pytest.raises(HostedAccessError):
        with HostedStorageBudget(lambda: facts(**changes)).reserve(0, write=True):
            pytest.fail("Recovery headroom consumed")


def test_host_disk_warns_at_eighty_and_write_maintenance_starts_before_ninety(caplog):
    total = 1000 * MIB
    budget = HostedStorageBudget(
        lambda: facts(host_total_bytes=total, host_available_bytes=200 * MIB)
    )
    with budget.reserve(0, write=True):
        pass
    assert "administrator attention" in caplog.text
    full = HostedStorageBudget(
        lambda: facts(host_total_bytes=total, host_available_bytes=110 * MIB)
    )
    with pytest.raises(HostedAccessError) as caught:
        with full.reserve(0, write=True):
            pytest.fail("Write admitted at 89 percent")
    assert caught.value.code == "hosted_write_maintenance"
    with full.reserve(0, write=False):
        pass


def test_missing_oversized_or_unreadable_accounting_fails_closed():
    invalid = HostedStorageBudget(lambda: facts(capacity_bytes=WORKSPACE_BYTES + 1))
    with pytest.raises(HostedAccessError):
        with invalid.reserve(0, write=True):
            pass
    failed = HostedStorageBudget(Mock(side_effect=OSError("private host path")))
    with pytest.raises(HostedAccessError) as caught:
        with failed.reserve(0, write=True):
            pass
    assert "private host path" not in str(caught.value)


def test_linux_mount_parser_rejects_bind_wrong_filesystem_and_missing_safety_options(monkeypatch):
    volume = Path("/var/lib/epm-a/volume")
    good = "36 25 7:0 / /var/lib/epm-a/volume rw,nodev,nosuid,noexec - ext4 /dev/loop0 rw"
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: good)
    assert _mount_identity(volume) == "7:0"
    for bad in [
        good.replace("7:0 / ", "7:0 /subdir "),
        good.replace("ext4", "tmpfs"),
        good.replace(",noexec", ""),
    ]:
        monkeypatch.setattr(Path, "read_text", lambda *_a, value=bad, **_k: value)
        with pytest.raises(HostedConfigurationError):
            _mount_identity(volume)


def test_real_factory_refuses_unqualified_directory_not_a_mocked_disk(deployment_values, tmp_path):
    from app.modules.hosted_access.application.configuration import HostedDeployment

    deployment = HostedDeployment.model_validate(deployment_values)
    with pytest.raises(HostedConfigurationError):
        build_storage_budget(deployment, tmp_path / "workspace")
