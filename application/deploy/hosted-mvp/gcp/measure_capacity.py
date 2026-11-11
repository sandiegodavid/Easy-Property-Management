"""Bounded synthetic GCP capacity fixture; no inventory admissions or provider mutations."""

import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import platform
import shutil
import subprocess
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lab"))
from qualify_reboot import verify_source
from qualify_runtime import command
from app.modules.host_agent.application.capacity import (
    Resources,
    OperatorBudget,
    CandidateCapacityProfile,
    Commitment,
    plan_reservation,
)
from app.modules.host_agent.application.dispatch import Allocation, ResourceLimits, TreeLimits
from app.modules.host_agent.infrastructure.container_policy import (
    RuntimeProfile,
    container_spec,
    policy_hash,
)
from capacity_observer import shared_services, project_ledger, resource_snapshot
from capacity_profile import candidate_document
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets

MIB = 1024 * 1024
GIB = 1024 * MIB
BASE = (
    "us-west1-docker.pkg.dev/project-47b72bb7-ba90-42c9-910/epm-h02-candidates/"
    "operator@sha256:6c264a90ff2f9a64e1d66b8e5b1405680d517210b4e3d1c586816603c486c995"
)
DATA = Path("/srv/epm/data")
POPULATION = 6
STARTUP_SECONDS = 120


def call(*args):
    return subprocess.run(
        [str(v) for v in args], check=True, capture_output=True, text=True, timeout=180
    ).stdout


def filesystem(path):
    value = os.statvfs(path)
    return dict(
        total_bytes=value.f_blocks * value.f_frsize,
        available_bytes=value.f_bavail * value.f_frsize,
        total_inodes=value.f_files,
        available_inodes=value.f_favail,
    )


def memory():
    values = {
        line.split(":")[0]: int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith(("MemTotal:", "MemAvailable:"))
    }
    return values


def host():
    value = memory()
    if (
        value["MemAvailable"] < GIB
        or filesystem(DATA)["available_bytes"] < 2 * GIB
        or filesystem(Path("/"))["available_bytes"] < 2 * GIB
    ):
        raise RuntimeError("Host abort reserve reached; retain fixture and stop its containers")
    return dict(
        memory=value,
        data=filesystem(DATA),
        boot=filesystem(Path("/")),
        pressure={
            name: Path(f"/proc/pressure/{name}").read_text() for name in ("cpu", "memory", "io")
        },
        cpu_stat=Path("/proc/stat").read_text().splitlines()[0],
        shared_services=shared_services(),
    )


def read_pairs(path):
    return {line.split()[0]: int(line.split()[1]) for line in path.read_text().splitlines()}


def runtime_sample(engine, identity):
    row = engine.inspect(identity)
    if not row or not row["State"]["Running"]:
        raise RuntimeError("A measured container stopped; no capacity pass")
    relative = Path(f"/proc/{row['State']['Pid']}/cgroup").read_text().strip().split("::", 1)[1]
    root = Path("/sys/fs/cgroup") / relative.lstrip("/")
    values = read_pairs(root / "memory.stat")
    return dict(
        memory_current=int((root / "memory.current").read_text()),
        memory_peak=int((root / "memory.peak").read_text()),
        memory_max=(root / "memory.max").read_text().strip(),
        pids_max=(root / "pids.max").read_text().strip(),
        cpu_max=(root / "cpu.max").read_text().strip(),
        memory_anon=values["anon"],
        memory_kernel=values.get("kernel", 0),
        pids=int((root / "pids.current").read_text()),
        cpu=read_pairs(root / "cpu.stat"),
        io=(root / "io.stat").read_text(),
        memory_events=read_pairs(root / "memory.events"),
    )


def trial_reserves():
    # Proposed physical trial bounds only; no fabricated measurement identity or
    # measured/qualified profile exists before the native reports are complete.
    return dict(
        shared=Resources(
            memory_bytes=1536 * MIB,
            cpu_millicores=500,
            pids=512,
            data_bytes=4 * GIB,
            data_inodes=100000,
            boot_bytes=9 * GIB,
            boot_inodes=300000,
        ).model_dump(),
        recovery=Resources(memory_bytes=512 * MIB, data_bytes=GIB, data_inodes=20000).model_dump(),
    )


class Measurement:
    def __init__(self):
        if os.geteuid() != 0 or os.environ.get("EPM_RUN_CAPACITY_QUALIFICATION") != "1":
            raise RuntimeError("Explicit disposable root GCP capacity opt-in required")
        bootstrap = json.loads(Path("/etc/epm/bootstrap/data.json").read_text())
        mounted = json.loads(call("findmnt", "-J", "-M", DATA, "-o", "UUID,OPTIONS"))[
            "filesystems"
        ][0]
        if (
            bootstrap["phase"] != "ready"
            or mounted["uuid"] != bootstrap["uuid"]
            or "prjquota" not in mounted["options"].split(",")
        ):
            raise RuntimeError("The protected retained quota filesystem is not ready")
        for unit in ("epm-gateway", "epm-egress", "epm-tunnel", "epm-host-guardian"):
            call("systemctl", "is-active", "--quiet", unit)
        self.root = DATA / "qualification" / ("h02-capacity-" + uuid4().hex)
        self.root.mkdir(mode=0o711)
        print(self.root, flush=True)
        self.rows = []
        self.engine = DockerEngine()
        self.record = dict(
            status="running",
            root=str(self.root),
            baseline=host(),
            stages=[],
            allocations=[],
            scope="synthetic_local_application_in_network_none_no_hosted_admission",
            kernel=platform.release(),
            machine=platform.machine(),
        )
        self.prepare(bootstrap)

    def save(self):
        temporary = self.root / "progress.next"
        with temporary.open("w") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(json.dumps(self.record, indent=2) + "\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(self.root / "progress.json")
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def prepare(self, bootstrap):
        source = Path(__file__).resolve().parents[3]
        self.record["source_sha256"] = verify_source(source)
        policy = source / "deploy/hosted-mvp/sandbox/epm-h02-operator-v1"
        call("apparmor_parser", "-r", policy)
        self.runtime = RuntimeProfile(
            architecture="amd64",
            apparmor_sha256=sha256(policy.read_bytes()).hexdigest(),
            memory_bytes=768 * MIB,
            cpu_millicores=250,
            pids=64,
            file_descriptors=512,
            log_bytes=2 * MIB,
            log_files=3,
        )
        self.reserves = trial_reserves()
        for name in ("workspace", "control", "scratch"):
            (self.root / name).mkdir(mode=0o711)
        targets = QuotaTargets(
            DATA,
            "isolated-capacity-fixture",
            bootstrap["uuid"],
            *(self.root / name for name in ("workspace", "control", "scratch")),
        )
        self.storage = PrivateStorage(targets)
        self.image = self.build_image()
        self.reserve_projects()
        self.record.update(
            runtime_profile=self.runtime.model_dump(),
            unmeasured_trial_reserves=self.reserves,
            image=self.image,
            filesystem_uuid=bootstrap["uuid"],
        )
        self.save()

    def reserve_projects(self):
        with (DATA / "qualification-projects").open("r+") as record:
            fcntl.flock(record, fcntl.LOCK_EX)
            self.project_base = int(record.read())
            record.seek(0)
            record.truncate()
            record.write(str(self.project_base + POPULATION * 3))
            record.flush()
            os.fsync(record.fileno())

    def build_image(self):
        context = self.root / "image"
        context.mkdir()
        shutil.copyfile(Path(__file__).with_name("capacity_actor.py"), context / "actor.py")
        (context / "Dockerfile").write_text(
            f"FROM {BASE}\nCOPY actor.py /capacity_actor.py\nHEALTHCHECK NONE\n"
            'ENTRYPOINT ["/opt/epm/venv/bin/python","-B","/capacity_actor.py"]\nCMD []\n'
        )
        tag = "epm-h02-capacity:" + self.root.name
        call("docker", "build", "--network=none", "-t", tag, context)
        return json.loads(call("docker", "image", "inspect", tag))[0]["Id"].removeprefix("sha256:")

    def add(self):
        index = len(self.rows)
        user = "epm-cap-" + self.root.name[-8:] + str(index)
        call("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user)
        owner = pwd.getpwnam(user)
        limits = ResourceLimits(
            workspace=TreeLimits(byte_ceiling=256 * MIB, inode_ceiling=8192),
            control=TreeLimits(byte_ceiling=64 * MIB, inode_ceiling=4096),
            scratch=TreeLimits(byte_ceiling=128 * MIB, inode_ceiling=4096),
        )
        allocation = Allocation(
            binding_id=str(uuid4()),
            resource_generation=1,
            host_uid=owner.pw_uid,
            host_gid=owner.pw_gid,
            workspace_project=self.project_base + 3 * index,
            control_project=self.project_base + 3 * index + 1,
            scratch_project=self.project_base + 3 * index + 2,
            filesystem_identity="isolated-capacity-fixture",
            image_digest=self.image,
            limits=limits,
        )
        self.record["allocations"].append(dict(user=user, allocation=allocation.model_dump()))
        self.save()
        self.storage.prepare(allocation)
        cmd = command(allocation)
        spec = container_spec(cmd, allocation, self.storage.targets, self.runtime)
        spec["Env"].append("EPM_RUN_CAPACITY_FIXTURE=1")
        self.record["allocations"][-1]["planned_container_name"] = self.engine.name(cmd)
        self.save()
        identity = self.engine.create(cmd, spec)
        self.rows.append((allocation, identity))
        self.record["allocations"][-1]["container"] = identity
        self.save()
        self.engine.start(identity)
        scratch = self.storage.projects(allocation)[2].binding.directory
        deadline = time.monotonic() + STARTUP_SECONDS
        while not (scratch / "ready.json").exists():
            runtime_sample(self.engine, identity)
            host()
            if time.monotonic() > deadline:
                (self.root / f"startup-{index}.log").write_text(call("docker", "logs", identity))
                raise RuntimeError("Measured runtime startup deadline exceeded")
            time.sleep(0.5)
        ready = json.loads((scratch / "ready.json").read_text())
        assert ready == dict(uid=owner.pw_uid, gid=owner.pw_gid)

    def phase(self, kind):
        sequence = len(self.record["stages"]) + 1
        stage = dict(kind=kind, population=len(self.rows), host=[], runtimes=[], results=[])
        for owner, _ in self.rows:
            scratch = self.storage.projects(owner)[2].binding.directory
            temporary = scratch / "next.json"
            temporary.write_text(
                json.dumps(dict(sequence=sequence, kind=kind, duration_seconds=10))
            )
            temporary.chmod(0o644)
            temporary.replace(scratch / "command.json")
        deadline = time.monotonic() + (300 if kind == "fault" else 180)
        while True:
            stage["host"].append(host())
            stage["runtimes"].append(
                [runtime_sample(self.engine, identity) for _, identity in self.rows]
            )
            paths = [
                self.storage.projects(owner)[2].binding.directory / f"result-{sequence}.json"
                for owner, _ in self.rows
            ]
            if all(path.exists() for path in paths):
                stage["results"] = [json.loads(path.read_text()) for path in paths]
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Capacity workload deadline exceeded")
            time.sleep(0.5)
        stage["projects"] = [self.storage.verify(owner) for owner, _ in self.rows]
        self.record["stages"].append(stage)
        self.save()

    def budget(self, owner):
        return OperatorBudget(
            trees=owner.limits,
            memory_bytes=self.runtime.memory_bytes,
            cpu_millicores=self.runtime.cpu_millicores,
            pids=self.runtime.pids,
            shared_memory_bytes=1024 * 1024,
            log_bytes=self.runtime.log_bytes,
            log_files=self.runtime.log_files,
            boot_metadata_bytes=MIB,
            boot_metadata_inodes=1024,
        )

    def establish_profile_basis(self):
        data = json.dumps(self.record, sort_keys=True).encode()
        with (self.root / "two-runtime-basis.json").open("xb") as output:
            output.write(data)
        self.profile = CandidateCapacityProfile(
            reference="gcp-amd64-candidate-v1",
            revision=1,
            measurement_sha256=sha256(data).hexdigest(),
            source_sha256=self.record["source_sha256"],
            runtime_policy_sha256=policy_hash(self.runtime),
            maximum_observation_age_ms=5000,
            shared_reserve=Resources(**self.reserves["shared"]),
            recovery_reserve=Resources(**self.reserves["recovery"]),
        )
        self.record["decisions"] = []

    def headroom_for_next(self):
        known = {identity for _, identity in self.rows}
        if set(call("docker", "ps", "-q", "--no-trunc").split()) != known:
            raise RuntimeError("Unaccounted running Docker runtime; capacity is unknown")
        excluded, commitments = set(), []
        for owner, identity in self.rows:
            sample = runtime_sample(self.engine, identity)
            usage = self.storage.verify(owner)
            excluded.update((owner.workspace_project, owner.control_project, owner.scratch_project))
            commitments.append(
                Commitment(
                    identity=owner.binding_id,
                    state="active",
                    reserved=self.budget(owner).reservation(),
                    observed=Resources(
                        memory_bytes=sample["memory_anon"],
                        pids=sample["pids"],
                        data_bytes=sum(row["allocated_bytes"] for row in usage.values()),
                        data_inodes=sum(row["allocated_inodes"] for row in usage.values()),
                    ),
                )
            )
        commitments.extend(project_ledger(excluded))
        snapshot = resource_snapshot(self.profile, host(), commitments, len(self.rows))
        proposed = Commitment(
            identity="trial-next-" + str(len(self.rows) + 1),
            state="pending",
            reserved=self.budget(self.rows[0][0]).reservation(),
        )
        decision = plan_reservation(
            self.profile,
            snapshot,
            proposed,
            now=time.time_ns() // 1000000,
            expected_revision=snapshot.revision,
        )
        self.record["decisions"].append(
            dict(snapshot=snapshot.model_dump(), decision=decision.model_dump())
        )
        self.save()
        return decision.status == "within_candidate_envelope"

    def verify_logs(self, identity):
        row = self.engine.inspect(identity)
        path = Path(row["LogPath"])
        files = list(path.parent.glob(path.name + "*"))
        if len(files) > self.runtime.log_files or sum(
            p.stat().st_size for p in files
        ) > self.runtime.log_files * (self.runtime.log_bytes + 8192):
            raise RuntimeError("Rotating logs exceed declared physical allowance")
        return dict(
            container=identity, files=len(files), bytes=sum(p.stat().st_size for p in files)
        )

    def publish_profile(self):
        if self.record["status"] != "measured_candidate_pass":
            raise RuntimeError("Incomplete measurements cannot publish a candidate profile")
        evidence = (self.root / "progress.json").read_bytes()
        document = candidate_document(
            evidence, self.profile, self.budget(self.rows[0][0]), self.runtime
        )
        with (self.root / "candidate-profile.json").open("x") as output:
            output.write(json.dumps(document, indent=2) + "\n")

    def workloads(self):
        for _ in range(2):
            self.add()
        self.phase("empty")
        self.phase("loaded")
        self.establish_profile_basis()
        for target in (5, 6):
            while len(self.rows) < target:
                if not self.headroom_for_next():
                    raise RuntimeError("Fresh candidate headroom did not permit the next runtime")
                self.add()
            self.phase("empty")
            self.phase("loaded")
        self.phase("fault")
        self.record["log_bounds"] = [self.verify_logs(identity) for _, identity in self.rows]
        self.record["status"] = "measured_candidate_pass"

    def contain(self):
        failures = []
        for _, identity in self.rows:
            try:
                self.engine.stop(identity)
                if self.engine.inspect(identity)["State"]["Running"]:
                    raise RuntimeError("Fixture stop could not be verified")
            except Exception as error:
                failures.append(type(error).__name__)
            try:
                logs = subprocess.run(
                    ["docker", "logs", "--tail", "80", identity],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                (self.root / (identity + ".log")).write_text(logs.stdout + logs.stderr)
            except Exception as error:
                self.record.setdefault("diagnostic_failures", []).append(type(error).__name__)
        self.record["stop_failures"] = failures
        if failures:
            self.record["status"] = "cleanup_incomplete"
        self.save()
        if failures:
            raise RuntimeError("Fixture stop remains incomplete; preserve recorded identities")

    def run(self):
        try:
            self.workloads()
        except BaseException as original:
            self.record["status"] = "failed"
            self.record["error_type"] = type(original).__name__
            try:
                self.contain()
            except Exception as cleanup:
                raise BaseExceptionGroup(
                    "Capacity workload and containment both failed", [original, cleanup]
                ) from None
            raise
        self.contain()
        self.publish_profile()
        print(self.root / "progress.json")


if __name__ == "__main__":
    Measurement().run()
