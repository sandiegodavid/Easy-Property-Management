"""Fault ordering around fresh tree publication; native enforcement is tested separately."""

from contextlib import contextmanager
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.host_agent.application.dispatch import (
    Allocation,
    ResourceLimits,
    TreeLimits,
    HostAgentDenied,
)
from app.modules.host_agent.infrastructure import private_storage


@pytest.fixture
def storage(tmp_path, monkeypatch):
    events = []
    failure = set()
    limits = TreeLimits(byte_ceiling=8192, inode_ceiling=64)
    allocation = Allocation(
        binding_id="00000000-0000-4000-8000-000000000001",
        resource_generation=1,
        host_uid=os.getuid(),
        host_gid=os.getgid(),
        workspace_project=11,
        control_project=12,
        scratch_project=13,
        filesystem_identity="synthetic-mount",
        image_digest="b" * 64,
        limits=ResourceLimits(workspace=limits, control=limits, scratch=limits),
    )
    roots = []
    for role in private_storage.ROLES:
        parent = tmp_path / role
        parent.mkdir()
        roots.append(SimpleNamespace(directory=parent / allocation.binding_id, uid=os.getuid()))

    mkdir, chmod = Path.mkdir, Path.chmod

    def simulated_root_mkdir(path, mode=0o777, **kwargs):
        # The unit process is not root. Simulate root traversal of mode-000
        # reservations; native Linux separately proves real permissions/UIDs.
        return mkdir(path, mode=0o700 if mode == 0 else mode, **kwargs)

    def record_grant(path, mode, **kwargs):
        events.append((path.parent.name, "grant" if mode == 0o700 else "fence"))
        return chmod(path, mode, **kwargs)

    monkeypatch.setattr(Path, "mkdir", simulated_root_mkdir)
    monkeypatch.setattr(Path, "chmod", record_grant)

    class Quota:
        def __init__(self, binding):
            self.binding = binding
            self.role = binding.directory.parent.name

        def filesystem(self):
            events.append((self.role, "filesystem"))

        def initialize_empty(self):
            assert not any(event[1] == "grant" for event in events)
            events.append((self.role, "initialize"))

        def set_limits(self, *args):
            assert not any(event[1] == "grant" for event in events)
            events.append((self.role, "limits"))
            if self.role in failure:
                raise OSError("synthetic set-quota failure")

        def observe(self):
            return {"hard_bytes": 8192, "hard_inodes": 64}

    @contextmanager
    def protected(path):
        yield None

    monkeypatch.setattr(private_storage, "ProjectQuota", Quota)
    monkeypatch.setattr(private_storage, "protected_directory", protected)
    targets = SimpleNamespace(bindings=lambda a: tuple(roots))
    return private_storage.PrivateStorage(targets), allocation, roots, events, failure


def test_prepare_limits_precede_all_write_grants_and_control_lock_is_separate(storage):
    service, allocation, roots, events, failure = storage
    service.prepare(allocation)
    assert [(r, "limits") for r in private_storage.ROLES] == [e for e in events if e[1] == "limits"]
    assert all(root.directory.stat().st_mode & 0o777 == 0o700 for root in roots)
    control = roots[1].directory
    assert (control / "writer.lock").stat().st_mode & 0o777 == 0o600
    assert (control / "data").is_dir()
    with pytest.raises(HostAgentDenied):
        service.prepare(allocation)


@pytest.mark.parametrize("role", private_storage.ROLES)
def test_partial_prepare_never_grants_writer_access(storage, role):
    service, allocation, roots, events, failure = storage
    failure.add(role)
    with pytest.raises(OSError):
        service.prepare(allocation)
    assert not any(event[1] == "grant" for event in events)


@pytest.mark.parametrize("tamper", ["owner_permissions", "linked_lock", "linked_control_data"])
def test_verify_rejects_control_identity_changes(storage, tamper):
    service, allocation, roots, events, failure = storage
    service.prepare(allocation)
    control = roots[1].directory
    if tamper == "owner_permissions":
        roots[0].directory.chmod(0o777)
    elif tamper == "linked_lock":
        os.link(control / "writer.lock", control / "alias")
    else:
        (control / "data").rmdir()
        (control / "data").symlink_to(roots[0].directory, target_is_directory=True)
    with pytest.raises(HostAgentDenied):
        service.verify(allocation)
