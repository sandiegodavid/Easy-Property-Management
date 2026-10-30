"""Real isolated files with simulated fixed Linux tools; never modifies the host."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from scripts.host_admin import HostPaths, protected, read_json
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure import linux_provisioning as linux
from app.modules.workspace.application.service import WorkspaceService


@pytest.fixture
def platform(tmp_path, monkeypatch):
    paths = HostPaths(
        control=tmp_path / "control",
        configs=tmp_path / "configs",
        data=tmp_path / "data",
        backups=tmp_path / "backups",
        releases=tmp_path / "releases",
        systemd=tmp_path / "systemd",
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
    ):
        directory.mkdir(mode=0o700)
    (paths.control / "provisioning").mkdir(mode=0o700)
    paths.fstab.write_text("# preserve existing mounts\n")
    executable = paths.releases / "release-20261029-01/venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_text("qualified test interpreter")
    calls, users, filesystems, mounts = [], {}, {}, set()
    monkeypatch.setattr(linux.os, "chown", lambda *_: None)
    monkeypatch.setattr(linux.os, "fchown", lambda *_: None)
    monkeypatch.setattr(linux, "WORKSPACE_BYTES", 4096)
    monkeypatch.setattr(linux, "validate_root_reserve", lambda _volume: None)

    def allocate(fd, _offset, size):
        os.write(fd, b"\0" * size)

    monkeypatch.setattr(linux.os, "posix_fallocate", allocate, raising=False)
    monkeypatch.setattr(linux.os.path, "ismount", lambda path: path in mounts)

    def user(name):
        if name not in users:
            raise KeyError(name)
        return users[name]

    monkeypatch.setattr(linux.pwd, "getpwnam", user)
    identifier = str(uuid4())
    plan = {"key": "d-test", "workspace_id": str(uuid4())}
    payload = {
        "target": plan["key"],
        "operation_id": identifier,
        "setup": {"plan": plan, "data": {"release": "release-20261029-01", "template": "empty"}},
    }

    def run(argv, **_kwargs):
        calls.append(argv)
        stdout, code = "", 0
        if argv[0].endswith("useradd"):
            users[argv[-1]] = SimpleNamespace(
                pw_uid=os.getuid(),
                pw_gid=os.getgid(),
                pw_name=argv[-1],
                pw_gecos="epm-setup:" + identifier,
                pw_shell="/usr/sbin/nologin",
            )
        elif argv[0].endswith("blkid"):
            stdout, code = (filesystems[argv[-1]], 0) if argv[-1] in filesystems else ("", 2)
        elif argv[0].endswith("mkfs.ext4"):
            filesystems[argv[-1]] = argv[-2]
        elif argv[0].endswith("mount"):
            mounts.add(Path(argv[-1]))
        elif argv[0].endswith("runuser"):
            stdout = json.dumps({"workspace_id": plan["workspace_id"], "verified": True})
        return SimpleNamespace(returncode=code, stdout=stdout)

    discovery = Mock()
    discovery._mount.side_effect = lambda volume, _image: (
        None if volume in mounts else (_ for _ in ()).throw(ValueError("not mounted"))
    )
    host = SimpleNamespace(
        paths=paths,
        read_json=read_json,
        protected=protected,
        discovery=discovery,
        inventory=Mock(),
        source=Mock(),
    )
    return linux.LinuxProvisioning(host, run), payload, calls, users


def test_allocate_workspace_and_retries_reuse_owned_resources_without_reformat(platform):
    adapter, payload, calls, _ = platform
    config = SimpleNamespace(release="release-20261029-01")
    adapter.apply(payload, "allocate", config)
    assert adapter.inspect(payload, "allocate", config).state == "verified"
    adapter.apply(payload, "allocate", config)
    adapter.apply(payload, "workspace", config)
    assert adapter.inspect(payload, "workspace", config).state == "verified"
    assert sum(argv[0].endswith("useradd") for argv in calls) == 1
    assert sum(argv[0].endswith("mkfs.ext4") for argv in calls) == 1
    formatter = next(argv for argv in calls if argv[0].endswith("mkfs.ext4"))
    assert formatter[formatter.index("-m") + 1] == "10"
    assert (
        formatter[formatter.index("-E") + 1] == "nodiscard,lazy_itable_init=0,lazy_journal_init=0"
    )
    assert adapter.h.paths.fstab.read_text().startswith("# preserve existing mounts\n")
    assert all("epm-a" not in " ".join(argv) and "epm-b" not in " ".join(argv) for argv in calls)


def test_interrupted_allocation_and_wrong_owner_never_take_over_or_reformat(platform):
    adapter, payload, calls, users = platform
    adapter.owned(payload, create=True)
    # Crash immediately after durable ownership intent; resume creates only its resources.
    adapter.apply(payload, "allocate", SimpleNamespace(release="release-20261029-01"))
    users["epm-d-test"].pw_gecos = "someone else"
    before = len(calls)
    with pytest.raises(AdminError, match="owner_conflict"):
        adapter.apply(payload, "allocate", None)
    assert len(calls) == before
    wrong = payload | {"operation_id": str(uuid4())}
    with pytest.raises(AdminError, match="owner_conflict"):
        adapter.owned(wrong, create=True)


def test_containment_uses_owning_disable_before_a_later_restart(platform):
    adapter, payload, calls, _ = platform
    config = SimpleNamespace(release="release-20261029-01")
    adapter.apply(payload, "allocate", config)
    paths = adapter.paths_for(payload["target"])
    paths["unit"].write_text("owned unit")
    paths["access"].write_text("source authority")
    paths["access"].chmod(0o600)
    adapter.h.discovery.systemctl.return_value = "inactive"
    status = {
        "admin_revision": 4,
        "binding_revision": 2,
        "admin_fence": 3,
        "generation": 1,
        "active": True,
        "binding_matches_configuration": True,
        "enrollments": [],
    }

    def transport(instance, request):
        assert instance["key"] == "d-test"
        if request.get("query") == "status":
            return status
        assert request["action"] == "disable" and request["expected_revision"] == 4
        return {
            "operation_id": request["operation_id"],
            "action": "disable",
            "revision": 5,
            "binding_revision": 2,
            "fence": 4,
            "generation": 2,
            "active": False,
        }

    adapter.h.source._transport.side_effect = transport
    assert adapter.contain(payload)
    assert ["/usr/bin/systemctl", "stop", "epm-hosted@d-test.service"] in calls


def test_post_format_sparse_image_and_insufficient_mounted_reserve_fail_closed(
    platform, monkeypatch
):
    adapter, payload, calls, _ = platform
    original = adapter.run

    def sparse_formatter(argv, **kwargs):
        result = original(argv, **kwargs)
        if argv[0].endswith("mkfs.ext4"):
            with Path(argv[-1]).open("wb") as stream:
                stream.truncate(linux.WORKSPACE_BYTES)
        return result

    adapter.run = sparse_formatter
    with pytest.raises(AdminError, match="allocation_incomplete"):
        adapter.apply(payload, "allocate", None)
    # Resume must allocate the missing physical bytes without formatting again.
    adapter.run = original

    def no_reserve(_volume):
        raise linux.HostedConfigurationError("insufficient root reserve")

    monkeypatch.setattr(linux, "validate_root_reserve", no_reserve)
    with pytest.raises(AdminError, match="reserve_incomplete"):
        adapter.apply(payload, "allocate", None)
    assert sum(argv[0].endswith("mkfs.ext4") for argv in calls) == 1


def test_offline_backup_child_initializes_tempfile_in_pinned_volume(platform):
    adapter, payload, _, _ = platform
    adapter.apply(payload, "allocate", None)
    paths = adapter.paths_for(payload["target"])
    WorkspaceService.from_local_config(paths["local"]).initialize(
        workspace_id=payload["setup"]["plan"]["workspace_id"]
    )
    original = adapter.run

    def child(argv, **kwargs):
        if "app.modules.hosted_admin.infrastructure.pre_enrollment_source" not in argv:
            return original(argv, **kwargs)
        # Execute the real source entry point in a fresh interpreter with the
        # adapter's exact environment. Only archive production is replaced;
        # workspace opening, helper arguments and tempfile initialization are real.
        program = """
import os, sys, tempfile
from pathlib import Path
from app.modules.hosted_admin.infrastructure import pre_enrollment_source as source
assert Path(tempfile.gettempdir()) == Path(os.environ['TMPDIR'])
assert Path(os.environ['TMPDIR']) == Path(sys.argv[2]).parent / 'volume/tmp'
def backup(deployment, backups, output, phrase):
    assert phrase == 'synthetic backup phrase'
    output.write_text('simulated encrypted archive')
source.create_hosted_backup = backup
source.main()
"""
        return subprocess.run(
            [sys.executable, "-I", "-c", program, *argv[argv.index("-m") + 2 :]], **kwargs
        )

    adapter.run = child
    assert adapter.backup(payload, "synthetic backup phrase").is_file()
