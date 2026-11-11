"""Opt-in root Linux reboot fixture; no production authority, no reboot command."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
from qualify_runtime import Qualification, call, command
from app.modules.host_agent.application.dispatch import Allocation
from app.modules.host_agent.infrastructure.container_policy import RuntimeProfile, container_spec
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry, StopTarget
from app.modules.hosted_admin.infrastructure.project_quota_qualification import Laboratory, guard


BOOT = Path("/proc/sys/kernel/random/boot_id")


def verify_source(root):
    manifest = json.loads((root / "qualification-source.json").read_text())
    digest = sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    assert digest == manifest["source_sha256"], "Manifest identity changed"
    for name, digest in manifest["files"].items():
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        assert sha256((root / name).read_bytes()).hexdigest() == digest, name
    return manifest["source_sha256"]


def platform_pin():
    kernel = Path("/boot") / ("vmlinuz-" + platform.release())
    return {
        "kernel": platform.release(),
        "machine": platform.machine(),
        "kernel_sha256": sha256(kernel.read_bytes()).hexdigest(),
        "docker": json.loads(call("/usr/bin/docker", "version", "--format", "{{json .Server}}")),
        "cgroup": Path("/sys/fs/cgroup/cgroup.controllers").read_text().strip(),
        "source_sha256": verify_source(Path(__file__).resolve().parents[3]),
    }


def before():
    q = Qualification()
    print(q.lab.root, flush=True)
    owners = [q.allocate(0), q.allocate(1)]
    directory = q.lab.root / "reboot-stops"
    directory.mkdir(mode=0o700)
    registry = StopRegistry(directory)
    identities = []
    for allocation in owners:
        cmd = command(allocation)
        identity = q.engine.create(cmd, container_spec(cmd, allocation, q.targets, q.profile))
        registry.register(
            StopTarget(
                command=cmd,
                container_id=identity,
                image_digest=q.image,
                host_uid=allocation.host_uid,
                host_gid=allocation.host_gid,
            )
        )
        q.engine.start(identity)
        q.wait_writer(identity)
        identities.append(identity)
    expected = [q.storage.verify(owner) for owner in owners]
    locks = [q.storage.projects(owner)[1].binding.directory / "writer.lock" for owner in owners]
    state = {
        "phase": "awaiting_reboot",
        "boot_id": BOOT.read_text().strip(),
        "platform": platform_pin(),
        "owners": [owner.model_dump() for owner in owners],
        "containers": identities,
        "profile": q.profile.model_dump(),
        "expected": expected,
        "lock_inodes": [p.stat().st_ino for p in locks],
    }
    (q.lab.root / "h02-reboot.json").write_text(json.dumps(state, indent=2) + "\n")
    print(q.lab.root / "h02-reboot.json", flush=True)


def after(root):
    guard()
    lab = Laboratory(root)
    saved = lab.root / "h02-reboot-result.json"
    state = json.loads((saved if saved.exists() else lab.root / "h02-reboot.json").read_text())
    assert state["phase"] in {"awaiting_reboot", "passed"}
    assert BOOT.read_text().strip() != state["boot_id"], "An actual guest reboot is required"
    assert platform_pin() == state["platform"], "Changed sources/platform need a fresh proof"
    if state["phase"] == "passed":
        return state
    q = Qualification.__new__(Qualification)
    q.lab, q.engine = lab, DockerEngine()
    q.profile = RuntimeProfile(**state["profile"])
    owners = [Allocation(**row) for row in state["owners"]]
    q.targets = QuotaTargets(
        lab.mount,
        "isolated-native-fixture",
        lab.state["uuid"],
        *(lab.mount / role for role in ("workspace", "control", "scratch")),
    )
    q.storage = PrivateStorage(q.targets)
    q.results = {"cases": {}}
    q.source = lab.root / "qualification"
    q.image = owners[0].image_digest
    # Check Docker's retained actual records BEFORE restoring the fixture mount.
    for identity in state["containers"]:
        actual = q.engine.inspect(identity)
        assert actual and not actual["State"]["Running"]
        assert actual["HostConfig"]["RestartPolicy"]["Name"] == "no"
    call(
        "/usr/bin/mount",
        "-o",
        "loop,prjquota,nodev,nosuid,noexec",
        lab.root / "shared.ext4",
        lab.mount,
    )
    q.security()  # Reload the exact pinned AppArmor profile before any fixture start.
    cases = {"actual_boot_changed": True, "no_automatic_container_restart": True}
    for index, owner in enumerate(owners):
        assert q.storage.verify(owner) == state["expected"][index]
        lock = q.storage.projects(owner)[1].binding.directory / "writer.lock"
        assert lock.stat().st_ino == state["lock_inodes"][index]
    cases["all_six_quota_projects_and_lock_inodes_retained"] = True
    cases["security_and_wal"] = q.actor(owners[0], "security")
    for role in ("workspace", "control", "scratch"):
        target = "/control/data" if role == "control" else "/" + role
        cases[role + "_post_reboot_edquot"] = q.actor(owners[0], "bytes", target)
        q.clear_fill(owners[0], role)
    cases["cross_uid"] = q.cross_uid(*owners)
    registry = StopRegistry(lab.root / "reboot-stops")
    registry.contain_all(q.engine)
    state.update(phase="passed", after_boot_id=BOOT.read_text().strip(), cases=cases)
    (lab.root / "h02-reboot-result.json").write_text(json.dumps(state, indent=2) + "\n")
    print(lab.root / "h02-reboot-result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    guard()
    if args.phase == "before" and args.root is None:
        before()
    elif args.phase == "after" and args.root is not None:
        after(args.root)
    else:
        parser.error("Before allocates a fresh lab; after requires that exact lab root.")
