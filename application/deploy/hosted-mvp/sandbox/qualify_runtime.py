"""Explicit disposable root-Linux H02.5 Docker proof; no production composition."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

from app.modules.host_agent.application.contracts import StartContainer
from app.modules.host_agent.application.dispatch import (
    Allocation,
    HostEffect,
    ResourceLimits,
    TreeLimits,
)
from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.modules.host_agent.infrastructure.container_policy import RuntimeProfile, container_spec
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets
from app.modules.host_agent.infrastructure.runtime_effects import NativeEffects
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry
from app.modules.hosted_admin.infrastructure.project_quota_qualification import Laboratory, guard
from app.platform.hosted_contracts.operations import OperationReference
from app.platform.hosted_contracts.values import WorkspaceScope

BASE = "python@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b"
MiB = 1024 * 1024


def call(*args):
    return subprocess.run(
        [str(a) for a in args], check=True, capture_output=True, text=True, timeout=120
    ).stdout


def command(allocation):
    parent = OperationReference(
        deployment_id=str(uuid4()),
        scope=WorkspaceScope(operator_id=str(uuid4()), workspace_id=str(uuid4())),
        kind="provision",
        operation_id=str(uuid4()),
        idempotency_key="isolated-native-proof",
        request_hash="a" * 64,
    )
    effect = EffectIdentity(
        parent=parent,
        binding_id=allocation.binding_id,
        resource_generation=1,
        kind="start_container",
        slot="native_proof",
    )
    return HostEffect(
        effect=effect,
        access_epoch=1,
        expected_revision=1,
        payload=StartContainer(binding_id=allocation.binding_id),
    )


class Qualification:
    project_base = 2001

    def __init__(self):
        guard()
        inputs = Path(__file__).resolve().parent
        self.lab = Laboratory.create()
        self.source = self.lab.root / "qualification"
        shutil.copytree(inputs, self.source, ignore=shutil.ignore_patterns("__pycache__"))
        self.runtime_source = self.lab.root / "source"
        shutil.copytree(
            inputs.parents[2] / "apps/server",
            self.runtime_source,
            ignore=shutil.ignore_patterns("tests", "__pycache__", "web_build"),
        )
        self.engine = DockerEngine()
        self.profile = self.security()
        self.image = self.build()
        roots = tuple(self.lab.mount / role for role in ("workspace", "control", "scratch"))
        for root in roots:
            root.mkdir(mode=0o711)
        self.targets = QuotaTargets(
            self.lab.mount, "isolated-native-fixture", self.lab.state["uuid"], *roots
        )
        self.storage = PrivateStorage(self.targets)
        self.allocations = []
        self.results = {
            "root": str(self.lab.root),
            "kernel": platform.release(),
            "machine": platform.machine(),
            "image": self.image,
            "scope": "native-" + self.profile.architecture + "-lab-not-gcp-acceptance",
            "cases": {},
        }
        (self.lab.root / "h02-runtime-start.json").write_text(json.dumps(self.results, indent=2))

    def security(self):
        path = self.source / "epm-h02-operator-v1"
        call("/usr/sbin/apparmor_parser", "-r", path)
        return RuntimeProfile(
            architecture="arm64" if platform.machine() == "aarch64" else "amd64",
            apparmor_sha256=sha256(path.read_bytes()).hexdigest(),
            memory_bytes=128 * MiB,
            cpu_millicores=500,
            pids=32,
            file_descriptors=128,
            log_bytes=MiB,
            log_files=2,
        )

    def build(self):
        context = self.lab.root / "docker-input"
        context.mkdir()
        platform_root = self.runtime_source / "app/platform"
        shutil.copyfile(self.source / "runtime_actor.py", context / "actor.py")
        app = context / "app/platform"
        app.mkdir(parents=True)
        for name in ("locking.py", "hosted_writer_lock.py"):
            shutil.copyfile(platform_root / name, app / name)
        (context / "Dockerfile").write_text(
            f"FROM {BASE}\nCOPY app /app\nCOPY actor.py /actor.py\n"
            "ENV PYTHONPATH=/ PYTHONDONTWRITEBYTECODE=1\n"
            'CMD ["python","-B","/actor.py","hold"]\n'
        )
        tag = "epm-h02-native:" + self.lab.root.name
        call("/usr/bin/docker", "build", "--network=none", "-t", tag, context)
        return json.loads(call("/usr/bin/docker", "image", "inspect", tag))[0]["Id"].removeprefix(
            "sha256:"
        )

    def allocate(self, owner):
        user = self.lab.state["users"][owner]
        info = pwd.getpwnam(user)
        limits = TreeLimits(byte_ceiling=8 * MiB, inode_ceiling=256)
        value = Allocation(
            binding_id=str(uuid4()),
            resource_generation=1,
            host_uid=info.pw_uid,
            host_gid=info.pw_gid,
            workspace_project=self.project_base + owner * 3,
            control_project=self.project_base + 1 + owner * 3,
            scratch_project=self.project_base + 2 + owner * 3,
            filesystem_identity="isolated-native-fixture",
            image_digest=self.image,
            limits=ResourceLimits(workspace=limits, control=limits, scratch=limits),
        )
        self.storage.prepare(value)
        self.allocations.append(value)
        return value

    def actor(self, allocation, mode, tree="/workspace"):
        cmd = command(allocation)
        spec = container_spec(cmd, allocation, self.targets, self.profile)
        spec["Cmd"] = ["python", "-B", "/actor.py", mode, tree]
        identity = self.engine.create(cmd, spec)
        # Direct test execution is intentionally limited to this disposable fixture.
        # It is not an admission or qualification bypass in the production driver.
        result = subprocess.run(
            ["/usr/bin/docker", "start", "-a", identity],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        inspected = self.engine.inspect(identity)
        if mode == "logs":
            log_path = Path(inspected["LogPath"])
            logs = list(log_path.parent.glob(log_path.name + "*"))
            total = sum(path.stat().st_size for path in logs)
            assert len(logs) <= self.profile.log_files
            assert total <= self.profile.log_bytes * self.profile.log_files + 16384
            self.results["cases"]["log_rotation"] = {"files": len(logs), "bytes": total}
        self.engine.remove_stopped(identity)
        if result.returncode or inspected["State"]["ExitCode"]:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def clear_fill(self, allocation, role):
        project = self.storage.projects(allocation)[("workspace", "control", "scratch").index(role)]
        project.verify_tree()
        root = project.binding.directory
        target = root / "data" if role == "control" else root
        for path in target.glob("fill-*"):
            path.unlink()
        project.observe()

    def guarded_lifecycle(self, allocation):
        directory = self.lab.root / "lifecycle-stop-targets"
        directory.mkdir(mode=0o700)
        self.registry = StopRegistry(directory)
        with self.registry.owner_lease() as ready:
            self.registry.contain_all(self.engine)
            ready()
            try:
                return self._guarded_lifecycle(allocation)
            finally:
                self.registry.contain_all(self.engine)

    def _guarded_lifecycle(self, allocation):
        cmd = command(allocation)
        identity = self.engine.create(
            cmd, container_spec(cmd, allocation, self.targets, self.profile)
        )
        allocation = allocation.model_copy(update={"container_ref": identity})
        attention = []
        driver = NativeEffects(
            self.storage,
            self.engine,
            self.profile,
            SimpleNamespace(verify=lambda *args: None, verify_runtime=lambda *args: None),
            SimpleNamespace(
                record=lambda *args: attention.append(args[-1]) or "isolated-native-proof"
            ),
            stops=self.registry,
        )
        # Explicit synthetic lab composition. No production authority adapter is installed.
        driver.apply(cmd, allocation)
        self.wait_writer(identity)
        denied = self.actor(allocation, "try_lock")
        before = (
            self.storage.projects(allocation)[1].binding.directory.joinpath("writer.lock").stat()
        )
        call("/usr/sbin/quotaoff", "-P", self.lab.mount)
        try:
            assert driver.supervise(cmd, allocation) == "needs_attention"
            assert not self.engine.inspect(identity)["State"]["Running"]
            result = self.negative_actor(allocation)
        finally:
            call("/usr/sbin/quotaon", "-P", self.lab.mount)
        self.clear_fill(allocation, "workspace")
        assert self.engine.inspect(identity)["HostConfig"]["RestartPolicy"]["Name"] == "no"
        self.engine.remove_stopped(identity)
        replacement = command(allocation)
        identity = self.engine.create(
            replacement, container_spec(replacement, allocation, self.targets, self.profile)
        )
        self.engine.start(identity)
        self.wait_writer(identity)
        self.engine.stop(identity)
        self.engine.remove_stopped(identity)
        after = (
            self.storage.projects(allocation)[1].binding.directory.joinpath("writer.lock").stat()
        )
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
        self.storage.verify(allocation)
        return {
            "second_writer": denied,
            "quota_off_stopped": True,
            "negative_control": result,
            "replacement_preserved_lock_inode": True,
            "attention": attention,
        }

    @staticmethod
    def wait_writer(identity):
        for _ in range(40):
            if "writer-ready" in call("/usr/bin/docker", "logs", identity):
                return
            time.sleep(0.05)
        raise AssertionError("Native writer did not become ready")

    def negative_actor(self, allocation):
        cmd = command(allocation)
        spec = container_spec(cmd, allocation, self.targets, self.profile)
        program = (
            "from pathlib import Path; p=Path('/workspace/negative-control'); "
            "p.write_bytes(b'x'*(16*1024*1024)); print(p.stat().st_size)"
        )
        spec["Cmd"] = ["python", "-B", "-c", program]
        identity = self.engine.create(cmd, spec)
        call("/usr/bin/docker", "start", "-a", identity)
        assert self.engine.inspect(identity)["State"]["ExitCode"] == 0
        self.engine.remove_stopped(identity)
        path = self.storage.projects(allocation)[0].binding.directory / "negative-control"
        assert path.stat().st_size == 16 * MiB
        path.unlink()
        return {"bytes_above_registered_ceiling": 16 * MiB}

    def service_supervision(self, allocation):
        cmd = command(allocation)
        identity = self.engine.create(
            cmd, container_spec(cmd, allocation, self.targets, self.profile)
        )
        allocation = allocation.model_copy(update={"container_ref": identity})
        directory = self.lab.root / "service-stop-targets"
        directory.mkdir(mode=0o700)
        registry = StopRegistry(directory)
        config = {
            "command": cmd.model_dump(),
            "allocation": allocation.model_dump(),
            "profile": self.profile.model_dump(),
        }
        configuration = self.lab.root / "guardian-fixture.json"
        configuration.write_text(json.dumps(config))
        configuration.chmod(0o600)
        source = self.runtime_source
        unit = "epm-h02-guardian-" + self.lab.root.name.rsplit("-", 1)[-1]
        python = Path(sys.executable)
        module = "app.modules.host_agent.infrastructure.supervisor"
        stop_command = f"{python} -B -m {module} --registry {directory} --contain-all"
        call(
            "/usr/bin/systemd-run",
            "--unit",
            unit,
            "--property=Restart=on-failure",
            "--property=RestartSec=1",
            "--property=UMask=0077",
            "--property=NoNewPrivileges=yes",
            "--property=ProtectHome=yes",
            "--property=ProtectSystem=strict",
            "--property=ReadWritePaths=" + str(directory),
            "--property=PrivateTmp=yes",
            "--property=LimitCORE=0",
            "--property=LimitNOFILE=1024",
            "--property=TasksMax=32",
            "--property=MemoryMax=256M",
            "--property=TimeoutStopSec=120",
            "--property=ExecStopPost=" + stop_command,
            "--setenv=EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1",
            "--setenv=PYTHONPATH=" + str(source),
            python,
            "-B",
            self.source / "qualification_guard.py",
            "--root",
            self.lab.root,
        )
        try:
            self.wait((directory / "ready").exists)
            driver = NativeEffects(
                self.storage,
                self.engine,
                self.profile,
                SimpleNamespace(verify=lambda *args: None, verify_runtime=lambda *args: None),
                SimpleNamespace(record=lambda *args: "native-service-proof"),
                stops=registry,
            )
            driver.apply(cmd, allocation)
            self.wait_writer(identity)
            marker = self.lab.root / "inventory-unavailable"
            marker.touch()
            self.wait(lambda: not self.engine.inspect(identity)["State"]["Running"])
            marker.unlink()
            driver.apply(cmd, allocation)
            self.wait_writer(identity)
            call("/usr/bin/systemctl", "kill", "--kill-whom=main", "--signal=SIGKILL", unit)
            self.wait(lambda: not self.engine.inspect(identity)["State"]["Running"])
            self.wait(
                lambda: (
                    int(call("/usr/bin/systemctl", "show", unit, "-p", "NRestarts", "--value")) >= 1
                )
            )
            self.wait((directory / "ready").exists)
            assert not self.engine.inspect(identity)["State"]["Running"]
            return {
                "unknown_inventory_stopped": True,
                "sigkill_stop_post_stopped": True,
                "service_restart_never_restarted_container": True,
                "restarts": int(
                    call("/usr/bin/systemctl", "show", unit, "-p", "NRestarts", "--value")
                ),
            }
        finally:
            call("/usr/bin/systemctl", "stop", unit)
            registry.contain_all(self.engine)
            self.engine.remove_stopped(identity)

    @staticmethod
    def wait(condition):
        for _ in range(120):
            if condition():
                return
            time.sleep(0.1)
        raise AssertionError("Bounded native condition was not observed")

    def cross_uid(self, first, second):
        other = self.storage.projects(second)[0].binding.directory
        path = other / "private-owner-data"
        path.write_text("synthetic second owner")
        os.chown(path, second.host_uid, second.host_gid)
        path.chmod(0o600)
        probe = subprocess.run(
            [
                "/usr/bin/setpriv",
                f"--reuid={first.host_uid}",
                f"--regid={first.host_gid}",
                "--clear-groups",
                "/usr/bin/cat",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert probe.returncode != 0 and "Permission denied" in probe.stderr
        return {"private_sibling_read_denied": True}

    def run(self):
        first, second = self.allocate(0), self.allocate(1)
        cases = self.results["cases"]
        cases["security_and_wal"] = self.actor(first, "security")
        for role in ("workspace", "control", "scratch"):
            target = "/control/data" if role == "control" else "/" + role
            for mode in ("bytes", "inodes", "deleted"):
                cases[role + "_" + mode] = self.actor(first, mode, target)
                self.clear_fill(first, role)
        cases["wal_full"] = self.actor(second, "wal")
        cases["log_workload"] = self.actor(first, "logs")
        cases["cross_uid_denial"] = self.cross_uid(first, second)
        cases["guarded_lifecycle"] = self.guarded_lifecycle(first)
        cases["systemd_supervision"] = self.service_supervision(first)
        self.results["status"] = "scoped-native-cases-passed"
        output = self.lab.root / "h02-runtime-result.json"
        output.write_text(json.dumps(self.results, indent=2) + "\n")
        print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.parse_args()
    qualification = Qualification()
    print(qualification.lab.root, flush=True)
    try:
        qualification.run()
    except Exception:
        qualification.results["status"] = "failed"
        (qualification.lab.root / "h02-runtime-result.json").write_text(
            json.dumps(qualification.results, indent=2) + "\n"
        )
        raise
