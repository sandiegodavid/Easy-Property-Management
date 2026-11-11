"""Focused private contracts. Real enforcement is proved by the Linux harness."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.modules.hosted_admin.infrastructure.project_quota import (
    DiskQuota,
    ProjectBinding,
    ProjectQuota,
    QuotaUnavailable,
)
from app.modules.hosted_admin.infrastructure.project_sandbox import service_properties


def test_seed_workload_changes_only_bounded_resources_not_security_filters():
    directories = {
        role: Path("/var/lib/test") / role for role in ("workspace", "scratch", "control")
    }
    primitive = set(service_properties("epm-qtest-example", directories))
    seed = set(service_properties("epm-qtest-example", directories, workload="seed"))
    assert seed - primitive == {"MemoryMax=512M", "RuntimeMaxSec=180"}
    assert primitive - seed == {"MemoryMax=128M", "RuntimeMaxSec=30"}
    with pytest.raises(QuotaUnavailable, match="workload_invalid"):
        service_properties("epm-qtest-example", directories, workload="unbounded")


def test_missing_quota_module_fails_before_laboratory_allocation(monkeypatch):
    from unittest.mock import Mock
    from app.modules.hosted_admin.infrastructure import project_quota_qualification as qualification

    monkeypatch.setattr(qualification, "guard", lambda: None)
    monkeypatch.setattr(qualification, "call", Mock(side_effect=RuntimeError("missing module")))
    allocate = Mock(side_effect=AssertionError("No image or lab allocation"))
    monkeypatch.setattr(qualification.tempfile, "mkdtemp", allocate)
    with pytest.raises(RuntimeError, match="missing module"):
        qualification.Laboratory.create()
    allocate.assert_not_called()


@pytest.fixture
def binding():
    return ProjectBinding(
        Path("/var/lib/data"),
        Path("/var/lib/data/a"),
        "00000000-0000-4000-8000-000000000001",
        101,
        1001,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"project_id": 0},
        {"project_id": True},
        {"project_id": 2**32},
        {"uid": 0},
        {"directory": Path("/var/lib/data")},
        {"directory": Path("/elsewhere")},
        {"directory": Path("/var/lib/data/a/../../escape")},
        {"mount": Path("relative")},
        {"filesystem_uuid": "not-a-uuid"},
    ],
)
def test_private_bindings_reject_ambiguous_or_unbounded_identities(binding, changes):
    with pytest.raises(ValueError):
        replace(binding, **changes)


@pytest.mark.parametrize("limits", [(0, 1), (1, 0), (True, 1), (1, -1), (2**63, 1)])
def test_invalid_limits_never_reach_the_kernel(binding, limits):
    probe = ProjectQuota(binding)
    probe.filesystem = Mock(side_effect=AssertionError("No kernel operation permitted"))
    with pytest.raises(QuotaUnavailable, match="limits_invalid"):
        probe.set_limits(*limits)


def test_limit_rounding_is_exact_and_kernel_usage_is_not_host_free_space(binding, monkeypatch):
    probe = ProjectQuota(binding)
    probe.filesystem = Mock(return_value=Path("/dev/test"))
    probe.observe = Mock(return_value={"hard_bytes": 2048, "hard_inodes": 9})
    calls = []
    probe._control = lambda device, command, value: calls.append((device, command, value))

    @contextmanager
    def directory(*_args):
        yield 123

    monkeypatch.setattr(
        "app.modules.hosted_admin.infrastructure.project_quota.protected_directory", directory
    )
    monkeypatch.setattr(
        "app.modules.hosted_admin.infrastructure.project_quota.attributes",
        lambda _: (0x200, 0, 0, 101, 0, b""),
    )
    assert probe.set_limits(1025, 9) == {"hard_bytes": 2048, "hard_inodes": 9}
    _, _, quota = calls[0]
    assert isinstance(quota, DiskQuota)
    assert quota.block_hard == 2 and quota.inode_hard == 9
    assert quota.block_soft == quota.inode_soft == 0


def test_failed_private_probe_has_only_safe_unavailable_facts(binding):
    probe = ProjectQuota(binding)
    probe.observe = Mock(side_effect=OSError("private /dev/secret and credentials"))
    assert probe.availability() == {
        "state": "unavailable",
        "error": "admin_project_quota_unavailable",
    }


def test_native_sandbox_has_no_unaccounted_temporary_mount_or_capability_escape():
    directories = {
        role: Path("/var/lib/data/a-" + role) for role in ("workspace", "scratch", "control")
    }
    values = service_properties("epm-qtest-a", directories)
    assert "CapabilityBoundingSet=" in values
    assert "SystemCallArchitectures=native" in values
    assert "NoNewPrivileges=yes" in values
    assert "SystemCallFilter=@system-service" in values
    assert "TemporaryFileSystem=/dev/shm:ro /run:ro" in values
    assert not any(item.startswith("PrivateTmp=") for item in values)
    with pytest.raises(QuotaUnavailable):
        service_properties("root", directories)
    with pytest.raises(QuotaUnavailable):
        service_properties("epm-qtest-a", directories | {"scratch": directories["workspace"]})


@pytest.mark.parametrize("bound", [0, -1, True, 100001])
def test_attribution_scan_is_explicitly_bounded(binding, bound):
    with pytest.raises(QuotaUnavailable, match="scan_bound_invalid"):
        ProjectQuota(binding).verify_tree(bound)
