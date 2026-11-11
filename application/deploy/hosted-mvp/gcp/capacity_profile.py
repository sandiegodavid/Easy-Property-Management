"""Closed measured-candidate artifact validation, never release/admission acceptance."""

from hashlib import sha256
import json
import math

from app.modules.host_agent.application.capacity import (
    CandidateCapacityProfile,
    OperatorBudget,
    Resources,
)
from app.modules.host_agent.infrastructure.container_policy import RuntimeProfile, policy_hash

TRIAL_POPULATION = 6
# Evidence records Linux errno values, even when inspected from a macOS checkout.
LINUX_QUOTA_ERRORS = (122, 28)  # EDQUOT, ENOSPC
LINUX_EAGAIN = 11
LINUX_EMFILE = 24
FIELDS = {
    "version",
    "profile",
    "operator_budget",
    "runtime",
    "measured_populations",
    "logical_free_bytes",
    "restore_readiness",
    "admission_enabled",
}
REQUIRED_STAGES = {(count, kind) for count in (2, 5, 6) for kind in ("empty", "loaded")} | {
    (6, "fault")
}


def validate_workload(stage):
    for result in stage["results"]:
        if stage["kind"] == "fault":
            if (
                result["workspace"]["errno"] not in LINUX_QUOTA_ERRORS
                or result["workspace"]["wal_failure_preserved_acknowledged_row"] is not True
                or result["pids"]["errno"] != LINUX_EAGAIN
                or result["descriptors"]["errno"] != LINUX_EMFILE
                or result["shared_memory_readonly"] is not True
                or result["bounded_memory_child_killed"] is not True
            ):
                raise ValueError("Required runtime fault did not preserve containment/data")
            validate_storage_faults(result)
        elif (
            type(result["requests"]) is not int
            or result["requests"] <= 0
            or not math.isfinite(result["p95_ms"])
            or result["p95_ms"] <= 0
        ):
            raise ValueError("No successful bounded application workload")
        elif stage["kind"] == "loaded" and result["backup_bytes"] <= 0:
            raise ValueError("Loaded stage has no completed SQLite backup")


def validate_storage_faults(result):
    for name in ("control_bytes", "scratch_bytes", "deleted_open"):
        if result[name] not in LINUX_QUOTA_ERRORS:
            raise ValueError("Required physical byte fault was not observed")
    if result["inodes"]["errno"] not in LINUX_QUOTA_ERRORS:
        raise ValueError("Required physical inode fault was not observed")
    if not math.isfinite(result["application_survived_faults_ms"]):
        raise ValueError("Application did not survive resource faults")


def validate_observations(stage, budget, runtime):
    if len(stage["host"]) != len(stage["runtimes"]):
        raise ValueError("Host/runtime observations are not paired")
    for group in stage["runtimes"]:
        if len(group) != stage["population"]:
            raise ValueError("A measured runtime is missing")
        for sample in group:
            quota, period = map(int, sample["cpu_max"].split())
            if (
                int(sample["memory_max"]) != runtime.memory_bytes
                or int(sample["pids_max"]) != runtime.pids
                or quota * 1000 != period * runtime.cpu_millicores
            ):
                raise ValueError("Observed cgroup bounds differ from the candidate")
    if len(stage["projects"]) != stage["population"]:
        raise ValueError("A measured project allocation is missing")
    for projects in stage["projects"]:
        for role in ("workspace", "control", "scratch"):
            limits = getattr(budget.trees, role)
            if (
                projects[role]["hard_bytes"] != ((limits.byte_ceiling + 1023) // 1024) * 1024
                or projects[role]["hard_inodes"] != limits.inode_ceiling
            ):
                raise ValueError("Observed quota bounds differ from the candidate")


def validate_measurement(record, budget, runtime):
    if record["status"] != "measured_candidate_pass" or record["stop_failures"]:
        raise ValueError("Incomplete workload/containment cannot publish capacity")
    stages = {(row["population"], row["kind"]) for row in record["stages"]}
    if not REQUIRED_STAGES <= stages or len(record["allocations"]) != TRIAL_POPULATION:
        raise ValueError("Required measured cohorts and faults are missing")
    for stage in record["stages"]:
        if (
            len(stage["results"]) != stage["population"]
            or not stage["host"]
            or not stage["runtimes"]
        ):
            raise ValueError("Missing workload or independent host/runtime observations")
        validate_workload(stage)
        validate_observations(stage, budget, runtime)
    if RuntimeProfile.model_validate(record["runtime_profile"]) != runtime:
        raise ValueError("Runtime profile differs from the measurement")
    if any(
        row["allocation"]["limits"] != budget.trees.model_dump() for row in record["allocations"]
    ):
        raise ValueError("Operator storage reservation differs from measured allocations")
    return record


def candidate_document(evidence, profile, budget, runtime):
    record = validate_measurement(json.loads(evidence), budget, runtime)
    if profile.source_sha256 != record[
        "source_sha256"
    ] or profile.runtime_policy_sha256 != policy_hash(runtime):
        raise ValueError("Profile does not identify the measured sources and runtime")
    if profile.shared_reserve != Resources(
        **record["unmeasured_trial_reserves"]["shared"]
    ) or profile.recovery_reserve != Resources(**record["unmeasured_trial_reserves"]["recovery"]):
        raise ValueError("Reserves do not match the measured trial inputs")
    if (
        budget.memory_bytes != runtime.memory_bytes
        or budget.cpu_millicores != runtime.cpu_millicores
        or budget.pids != runtime.pids
        or budget.log_bytes != runtime.log_bytes
        or budget.log_files != runtime.log_files
    ):
        raise ValueError("Operator reservation does not match configured runtime bounds")
    final = profile.model_copy(update={"measurement_sha256": sha256(evidence).hexdigest()})
    return dict(
        version=1,
        profile=final.model_dump(),
        operator_budget=budget.model_dump(),
        runtime=runtime.model_dump(),
        measured_populations=sorted({stage["population"] for stage in record["stages"]}),
        logical_free_bytes=50000000,
        restore_readiness="unavailable_pending_H05",
        admission_enabled=False,
    )


def validate_document(document, evidence, *, expected_source, expected_policy):
    if (
        set(document) != FIELDS
        or type(document["version"]) is not int
        or document["version"] != 1
        or document["admission_enabled"] is not False
        or document["restore_readiness"] != "unavailable_pending_H05"
    ):
        raise ValueError("Unknown or permissive capacity artifact")
    profile = CandidateCapacityProfile.model_validate(document["profile"])
    if (
        profile.source_sha256 != expected_source
        or profile.runtime_policy_sha256 != expected_policy
        or profile.measurement_sha256 != sha256(evidence).hexdigest()
    ):
        raise ValueError("Measurement/source/policy identity changed")
    regenerated = candidate_document(
        evidence,
        profile,
        OperatorBudget.model_validate(document["operator_budget"]),
        RuntimeProfile.model_validate(document["runtime"]),
    )
    if regenerated != document:
        raise ValueError("Capacity artifact does not match measured configuration")
    return profile
