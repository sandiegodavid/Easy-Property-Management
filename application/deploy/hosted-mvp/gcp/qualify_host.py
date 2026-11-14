"""Opt-in synthetic Docker qualification on the new host's real retained data disk."""

import argparse
import fcntl
import os
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
from qualify_runtime import Qualification, call, command
from app.modules.host_agent.infrastructure.container_policy import container_spec
from app.modules.host_agent.application.dispatch import Allocation
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets
from app.modules.hosted_admin.infrastructure.project_quota_qualification import guard

DATA = Path("/srv/epm/data")


class HostQualification(Qualification):
    def __init__(self):
        guard()
        bootstrap = json.loads(Path("/etc/epm/bootstrap/data.json").read_text())
        if bootstrap["phase"] != "ready":
            raise ValueError("Fresh disk setup is not complete")
        mounted = json.loads(call("findmnt", "-J", "-M", DATA, "-o", "UUID,OPTIONS"))[
            "filesystems"
        ][0]
        if mounted["uuid"] != bootstrap["uuid"] or "prjquota" not in mounted["options"].split(","):
            raise ValueError("The retained data filesystem does not match setup")
        super().__init__()
        # Laboratory.create still reserves private compiler/source/service fixtures.
        # Only the actual target roots change; no mkfs/adoption of the data disk here.
        self.lab.mount = DATA
        self.lab.state["uuid"] = bootstrap["uuid"]
        reservation = DATA / "qualification-projects"
        with reservation.open("a+") as record:
            os.fchmod(record.fileno(), 0o600)
            fcntl.flock(record, fcntl.LOCK_EX)
            record.seek(0)
            self.project_base = int(record.read() or "2000001")
            record.seek(0)
            record.truncate()
            record.write(str(self.project_base + 6))
            record.flush()
            os.fsync(record.fileno())
        self.roots = DATA / "qualification" / self.lab.root.name
        self.roots.mkdir(mode=0o711, parents=True)
        for role in ("workspace", "control", "scratch"):
            (self.roots / role).mkdir(mode=0o711)
        self.targets = QuotaTargets(
            DATA,
            "isolated-native-fixture",
            bootstrap["uuid"],
            *(self.roots / role for role in ("workspace", "control", "scratch")),
        )
        self.storage = PrivateStorage(self.targets)
        self.results.update(
            scope="gcp-amd64-synthetic-direct-data-disk",
            filesystem_uuid=bootstrap["uuid"],
            physical_roots=str(self.roots),
        )


def compatibility(q):
    """Execute native and static 32-bit controls under the exact Docker policy."""
    context = q.lab.root / "compat-input"
    context.mkdir()
    source = context / "control.c"
    source.write_text("int main(void) { return 42; }\n")
    call("gcc", "-static", source, "-o", context / "native")
    call("gcc", "-m32", "-static", source, "-o", context / "compat")
    tag = "epm-h02-native:" + q.lab.root.name
    if json.loads(call("docker", "image", "inspect", tag))[0]["Id"] != "sha256:" + q.image:
        raise ValueError("The fixture base image changed")
    (context / "Dockerfile").write_text(f"FROM {tag}\nCOPY native /native\nCOPY compat /compat\n")
    image_tag = "epm-h02-compat:" + q.lab.root.name
    call("docker", "build", "--network=none", "-t", image_tag, context)
    image = json.loads(call("docker", "image", "inspect", image_tag))[0]["Id"].removeprefix(
        "sha256:"
    )
    owner = q.allocations[0].model_copy(update={"image_digest": image})
    results = {}
    for program in ("native", "compat"):
        cmd = command(owner)
        spec = container_spec(cmd, owner, q.targets, q.profile)
        spec["Cmd"] = ["/" + program]
        identity = q.engine.create(cmd, spec)
        try:
            call("docker", "start", identity)
            call("docker", "wait", identity)
            actual = q.engine.inspect(identity)
            results[program] = actual["State"]["ExitCode"]
        finally:
            q.engine.stop(identity)
            q.engine.remove_stopped(identity)
    if results != {"native": 42, "compat": 159}:
        raise ValueError("Native control or compat architecture rejection was not observed")
    return results


def before():
    q = HostQualification()
    print(q.lab.root, flush=True)
    q.run()
    q.results["compatibility"] = compatibility(q)
    q.results["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    kernel = Path("/boot") / ("vmlinuz-" + q.results["kernel"])
    q.results["kernel_sha256"] = sha256(kernel.read_bytes()).hexdigest()
    q.results["owners"] = [owner.model_dump() for owner in q.allocations]
    q.results["expected_projects"] = [q.storage.verify(owner) for owner in q.allocations]
    q.results["lock_inodes"] = [
        q.storage.projects(owner)[1].binding.directory.joinpath("writer.lock").stat().st_ino
        for owner in q.allocations
    ]
    q.results["phase"] = "awaiting_reboot"
    (q.lab.root / "h02-gcp-before.json").write_text(json.dumps(q.results, indent=2) + "\n")
    print(q.lab.root / "h02-gcp-before.json")


def verify_writer_lock(lock, owner):
    # The production lock intentionally rejects root opening an operator-owned
    # inode. Prove post-boot acquisition as that exact owner, without NSS lookups.
    code = (
        "import sys\nfrom pathlib import Path\n"
        "from app.platform.hosted_writer_lock import HostedWriterLock\n"
        "with HostedWriterLock(Path(sys.argv[1])): pass\n"
    )
    subprocess.run(
        [sys.executable, "-B", "-c", code, str(lock)],
        user=owner.host_uid,
        group=owner.host_gid,
        extra_groups=[],
        capture_output=True,
        check=True,
        timeout=5,
    )


def after(root):
    guard()

    state = json.loads((root / "h02-gcp-before.json").read_text())
    current_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if state["boot_id"] == current_boot:
        raise ValueError("An actual VM reboot is required")
    running_kernel, running_machine = platform.release(), platform.machine()
    if (running_kernel, running_machine) != (state["kernel"], state["machine"]):
        raise ValueError("Running kernel or architecture changed across reboot")
    kernel = Path("/boot") / ("vmlinuz-" + running_kernel)
    kernel_hash = sha256(kernel.read_bytes()).hexdigest()
    if kernel_hash != state["kernel_sha256"]:
        raise ValueError("Running-kernel image bytes changed")
    uuid = json.loads(call("findmnt", "-J", "-M", DATA, "-o", "UUID"))["filesystems"][0]["uuid"]
    if uuid != state["filesystem_uuid"]:
        raise ValueError("The retained filesystem identity changed")
    physical_roots = Path(state["physical_roots"])
    if not physical_roots.is_relative_to(DATA / "qualification"):
        raise ValueError("Wrong qualification root")
    targets = QuotaTargets(
        DATA,
        "isolated-native-fixture",
        uuid,
        *(physical_roots / role for role in ("workspace", "control", "scratch")),
    )
    storage = PrivateStorage(targets)
    for index, row in enumerate(state["owners"]):
        owner = Allocation(**row)
        if storage.verify(owner) != state["expected_projects"][index]:
            raise ValueError("Kernel project observations changed across reboot")
        lock = storage.projects(owner)[1].binding.directory / "writer.lock"
        if lock.stat().st_ino != state["lock_inodes"][index]:
            raise ValueError("Stable writer lock changed across reboot")
        verify_writer_lock(lock, owner)
    state.update(
        after_boot_id=current_boot,
        after_kernel=running_kernel,
        after_machine=running_machine,
        after_kernel_sha256=kernel_hash,
        phase="passed",
        retained_data_and_six_projects=True,
    )
    (root / "h02-gcp-after.json").write_text(json.dumps(state, indent=2) + "\n")
    print(root / "h02-gcp-after.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.phase == "before" and args.root is None:
        before()
    elif args.phase == "after" and args.root is not None:
        after(args.root)
    else:
        parser.error("Before creates a fresh lab; after requires its exact recorded root")
