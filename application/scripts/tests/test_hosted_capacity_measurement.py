"""Collector and artifact failures must not become false capacity/admission claims."""

from copy import deepcopy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from app.modules.host_agent.application.capacity import (
    CandidateCapacityProfile,
    OperatorBudget,
    Resources,
)
from app.modules.host_agent.application.dispatch import ResourceLimits, TreeLimits
from app.modules.host_agent.infrastructure.container_policy import RuntimeProfile, policy_hash

ROOT = Path(__file__).resolve().parents[2] / "deploy/hosted-mvp/gcp"
HEADER = "Project,BlockUsed,BlockHardLimit,FileUsed,FileHardLimit\n"
KIB = 1024
LINUX_EDQUOT = 122
LINUX_EAGAIN = 11
LINUX_EMFILE = 24


def test_kernel_retained_limits_and_rounding_are_counted_not_just_live_use():
    parse = runpy.run_path(str(ROOT / "capacity_observer.py"))["quota_commitments"]
    rows = parse(HEADER + "#0,20,0,10,0\n#10,9,8,2,16\n#11,0,100,1,20\n", {11})
    assert len(rows) == 1
    assert rows[0].state == "retained"
    assert rows[0].reserved.data_bytes == 9 * KIB
    assert rows[0].reserved.data_inodes > rows[0].observed.data_inodes


@pytest.mark.parametrize(
    "text,excluded",
    [
        ("#10,0,8,0,16\n#10,0,8,0,16\n", set()),
        ("#10,-1,8,0,16\n", set()),
        ("#4294967296,0,8,0,16\n", set()),
        ("#10,0,8,0,16\n", {11}),
    ],
)
def test_invalid_or_missing_kernel_project_cannot_yield_a_complete_snapshot(text, excluded):
    parse = runpy.run_path(str(ROOT / "capacity_observer.py"))["quota_commitments"]
    with pytest.raises(ValueError):
        parse(HEADER + text, excluded)


def test_unbounded_nonempty_project_remains_unknown():
    parse = runpy.run_path(str(ROOT / "capacity_observer.py"))["quota_commitments"]
    assert parse(HEADER + "#10,1,0,1,0\n", set())[0].reserved is None


def fixture():
    runtime = RuntimeProfile(
        architecture="amd64",
        apparmor_sha256="a" * 64,
        memory_bytes=64 * 1024 * 1024,
        cpu_millicores=100,
        pids=16,
        file_descriptors=64,
        log_bytes=1024 * 1024,
        log_files=2,
    )
    tree = TreeLimits(byte_ceiling=1025, inode_ceiling=10)
    budget = OperatorBudget(
        trees=ResourceLimits(workspace=tree, control=tree, scratch=tree),
        memory_bytes=runtime.memory_bytes,
        cpu_millicores=100,
        pids=16,
        shared_memory_bytes=1024 * 1024,
        log_bytes=runtime.log_bytes,
        log_files=2,
        boot_metadata_bytes=1024,
        boot_metadata_inodes=10,
    )
    profile = CandidateCapacityProfile(
        reference="synthetic-profile",
        revision=1,
        measurement_sha256="b" * 64,
        source_sha256="c" * 64,
        runtime_policy_sha256=policy_hash(runtime),
        maximum_observation_age_ms=100,
        shared_reserve=Resources(memory_bytes=10, boot_bytes=10),
        recovery_reserve=Resources(data_bytes=10, data_inodes=10),
    )
    sample = dict(memory_max=str(runtime.memory_bytes), pids_max="16", cpu_max="10000 100000")
    projects = {
        role: dict(hard_bytes=2048, hard_inodes=10) for role in ("workspace", "control", "scratch")
    }
    stages = [
        dict(
            population=count,
            kind=kind,
            results=[dict(requests=1, p95_ms=1.0, backup_bytes=1)] * count,
            host=[{}],
            runtimes=[[sample] * count],
            projects=[projects] * count,
        )
        for count in (2, 5, 6)
        for kind in ("empty", "loaded")
    ]
    fault = dict(
        workspace=dict(errno=LINUX_EDQUOT, wal_failure_preserved_acknowledged_row=True),
        control_bytes=LINUX_EDQUOT,
        scratch_bytes=LINUX_EDQUOT,
        deleted_open=LINUX_EDQUOT,
        inodes=dict(errno=LINUX_EDQUOT),
        pids=dict(errno=LINUX_EAGAIN),
        descriptors=dict(errno=LINUX_EMFILE),
        shared_memory_readonly=True,
        bounded_memory_child_killed=True,
        application_survived_faults_ms=1.0,
    )
    stages.append(
        dict(
            population=6,
            kind="fault",
            results=[fault] * 6,
            host=[{}],
            runtimes=[[sample] * 6],
            projects=[projects] * 6,
        )
    )
    record = dict(
        status="measured_candidate_pass",
        stop_failures=[],
        source_sha256=profile.source_sha256,
        allocations=[dict(allocation=dict(limits=budget.trees.model_dump()))] * 6,
        runtime_profile=runtime.model_dump(),
        stages=stages,
        unmeasured_trial_reserves=dict(
            shared=profile.shared_reserve.model_dump(),
            recovery=profile.recovery_reserve.model_dump(),
        ),
    )
    return record, profile, budget, runtime


def test_candidate_artifact_binds_evidence_and_remains_non_admitting():
    module = runpy.run_path(str(ROOT / "capacity_profile.py"))
    record, profile, budget, runtime = fixture()
    evidence = json.dumps(record).encode()
    result = module["candidate_document"](evidence, profile, budget, runtime)
    validated = module["validate_document"](
        result,
        evidence,
        expected_source=profile.source_sha256,
        expected_policy=profile.runtime_policy_sha256,
    )
    assert validated.acceptance == "measured_candidate"
    assert result["admission_enabled"] is False
    with pytest.raises(ValueError, match="identity changed"):
        module["validate_document"](
            result,
            evidence + b" ",
            expected_source=profile.source_sha256,
            expected_policy=profile.runtime_policy_sha256,
        )


@pytest.mark.parametrize(
    "change", [{"status": "running"}, {"stop_failures": ["unknown"]}, {"stages": []}]
)
def test_partial_or_cleanup_failed_evidence_never_publishes(change):
    module = runpy.run_path(str(ROOT / "capacity_profile.py"))
    record, profile, budget, runtime = fixture()
    with pytest.raises(ValueError):
        module["candidate_document"](json.dumps(record | change).encode(), profile, budget, runtime)


def test_changed_reserve_and_permissive_document_are_rejected():
    module = runpy.run_path(str(ROOT / "capacity_profile.py"))
    record, profile, budget, runtime = fixture()
    evidence = json.dumps(record).encode()
    with pytest.raises(ValueError, match="Reserves"):
        module["candidate_document"](
            evidence,
            profile.model_copy(update={"recovery_reserve": Resources(data_bytes=1, data_inodes=1)}),
            budget,
            runtime,
        )
    document = module["candidate_document"](evidence, profile, budget, runtime)
    for change in ({"admission_enabled": True}, {"version": True}, {"extra": False}):
        changed = deepcopy(document) | change
        with pytest.raises(ValueError):
            module["validate_document"](
                changed,
                evidence,
                expected_source=profile.source_sha256,
                expected_policy=profile.runtime_policy_sha256,
            )


@pytest.mark.parametrize("change", ["fault", "cgroup", "quota", "workload", "runtime", "budget"])
def test_incomplete_faults_and_mismatched_measured_limits_cannot_publish(change):
    module = runpy.run_path(str(ROOT / "capacity_profile.py"))
    record, profile, budget, runtime = fixture()
    record = deepcopy(record)
    if change == "fault":
        record["stages"][-1]["results"][0]["bounded_memory_child_killed"] = False
    elif change == "cgroup":
        record["stages"][0]["runtimes"][0][0]["memory_max"] = "max"
    elif change == "quota":
        record["stages"][0]["projects"][0]["scratch"]["hard_bytes"] = 1024
    elif change == "workload":
        record["stages"][0]["results"][0]["requests"] = 0
    elif change == "runtime":
        record["runtime_profile"]["pids"] = 32
    else:
        record["allocations"][0]["allocation"]["limits"]["workspace"]["byte_ceiling"] = 2049
    with pytest.raises(ValueError):
        module["candidate_document"](json.dumps(record).encode(), profile, budget, runtime)


def test_failed_workload_preserves_original_error_and_attempts_every_stop(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    module = runpy.run_path(str(ROOT / "measure_capacity.py"))
    measurement = module["Measurement"].__new__(module["Measurement"])
    stopped = []

    def stop(identity):
        stopped.append(identity)
        if identity == "first":
            raise OSError("synthetic stop failure")

    def workload():
        raise ValueError("synthetic original failure")

    measurement.root = tmp_path
    measurement.rows = [(None, "first"), (None, "second")]
    measurement.record = dict(status="running")
    measurement.engine = SimpleNamespace(stop=stop, inspect=lambda _: {"State": {"Running": False}})
    measurement.workloads = workload
    monkeypatch.setattr(
        module["subprocess"], "run", lambda *a, **kw: SimpleNamespace(stdout="", stderr="")
    )
    with pytest.raises(ExceptionGroup) as caught:
        measurement.run()
    assert stopped == ["first", "second"]
    assert isinstance(caught.value.exceptions[0], ValueError)
    saved = json.loads((tmp_path / "progress.json").read_text())
    assert saved["error_type"] == "ValueError"
    assert saved["status"] == "cleanup_incomplete"
    assert not (tmp_path / "candidate-profile.json").exists()
