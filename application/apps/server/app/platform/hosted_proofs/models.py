"""Strict proof specifications/reports; schema validity never authorizes a release."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    EpochMillis,
    Explanation,
    Reference,
    RequestHash,
    SafeCode,
)

GitCommit = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{40}$")]
Sequence = Annotated[StrictInt, Field(ge=1, le=1000)]
Version = Annotated[StrictInt, Field(ge=1, le=1)]


class Proof(StrEnum):
    PACKAGING = "image_schema"
    RUNTIME = "runtime_limits"
    IDENTITY = "identity_handoff"
    USAGE = "usage_accounting"
    RECOVERY = "recovery"
    OPERATIONS = "operations_economics"


class Level(StrEnum):
    COMPONENT = "component"
    NATIVE = "native_linux"
    DOCKER = "docker_linux"
    GCP = "gcp"
    BROWSER = "deployed_browser"
    MANUAL = "manual"


class Result(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"


class PinKind(StrEnum):
    SOURCE = "source"
    TOOL = "tool"
    IMAGE = "image"
    SCHEMA = "schema"
    WORKLOAD = "workload"
    CONFIGURATION = "configuration"


class Specification(Contract):
    version: Version = 1
    proof: Proof
    owner: Literal["H02", "H03", "H04", "H05"]
    contributors: Annotated[
        tuple[Literal["H02", "H03", "H04", "H05", "H06"], ...], Field(max_length=5)
    ]
    revision: Sequence
    levels: Annotated[tuple[Level, ...], Field(min_length=1, max_length=6)]
    required_pins: Annotated[tuple[PinKind, ...], Field(min_length=1, max_length=6)]
    cases: Annotated[tuple[SafeCode, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def unique_requirements(self):
        for values in (self.contributors, self.levels, self.required_pins, self.cases):
            if len(values) != len(set(values)):
                raise ValueError("Specification requirements must be unique.")
        return self


class Pin(Contract):
    reference: Reference
    kind: PinKind
    state: Literal["pinned", "unavailable", "not_applicable"]
    sha256: RequestHash | None
    reason: Explanation | None

    @model_validator(mode="after")
    def exact_pin_or_reason(self):
        if self.state == "pinned":
            if self.sha256 is None or self.reason is not None:
                raise ValueError(
                    "A pinned input needs its exact digest, not an unavailable reason."
                )
        elif self.sha256 is not None or self.reason is None:
            raise ValueError(
                "Unavailable/not-applicable input needs a reason, not a fabricated pin."
            )
        return self


class Environment(Contract):
    level: Level
    os: Literal["linux", "darwin", "windows", "unavailable"]
    architecture: Reference
    machine_ref: Reference
    kernel: Reference | None
    filesystem: Reference | None
    container_runtime: Reference | None
    provider_configuration_ref: Reference | None


class Invocation(Contract):
    driver_ref: Reference
    input_manifest_ref: Reference
    input_manifest_sha256: RequestHash
    phase: Literal["run", "after_reboot", "manual"]
    repetition: Sequence


class Evidence(Contract):
    evidence_id: Reference
    artifact_ref: Reference
    sha256: RequestHash


class Metric(Contract):
    name: SafeCode
    value: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
    unit: Literal["bytes", "inodes", "milliseconds", "count", "usd_micros", "minutes"]


class CaseResult(Contract):
    case_id: SafeCode
    status: Result
    observation: Explanation
    evidence_ids: Annotated[tuple[Reference, ...], Field(max_length=32)]
    metrics: Annotated[tuple[Metric, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def actual_observation(self):
        if self.status in {Result.PASSED, Result.FAILED} and not self.evidence_ids:
            raise ValueError("Executed cases require retained evidence.")
        if self.status in {Result.NOT_RUN, Result.UNAVAILABLE} and self.metrics:
            raise ValueError("Unrun cases cannot contain measured results.")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Case evidence references must be unique.")
        return self


class ProofReport(Contract):
    version: Version = 1
    report_id: CanonicalId
    proof: Proof
    specification_sha256: RequestHash
    specification_revision: Sequence
    owner: Literal["H02", "H03", "H04", "H05"]
    source_commit: GitCommit | None
    source_dirty: StrictBool | None
    recorded_at: EpochMillis
    started_at: EpochMillis | None
    finished_at: EpochMillis | None
    environment: Environment
    invocation: Invocation | None
    pins: Annotated[tuple[Pin, ...], Field(max_length=128)]
    evidence: Annotated[tuple[Evidence, ...], Field(max_length=256)]
    cases: Annotated[tuple[CaseResult, ...], Field(min_length=1, max_length=128)]
    status: Result
    remaining_limits: Annotated[tuple[Explanation, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def truthful_result(self):
        statuses = {item.status for item in self.cases}
        if self.status != combined_status(statuses):
            raise ValueError(
                "Report status must reflect every planned case, including unavailable."
            )
        self._check_evidence()
        ran = bool(statuses & {Result.PASSED, Result.FAILED})
        if ran:
            self._check_execution()
        elif self.started_at is not None or self.finished_at is not None:
            raise ValueError("Unrun reports must not invent execution times.")
        return self

    def _check_evidence(self):
        for values in (
            [item.case_id for item in self.cases],
            [item.evidence_id for item in self.evidence],
            [item.reference for item in self.pins],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Report identifiers must be unique.")
        known = {item.evidence_id for item in self.evidence}
        if any(set(item.evidence_ids) - known for item in self.cases):
            raise ValueError("Case evidence must resolve within the report artifact inventory.")

    def _check_execution(self):
        if self.source_commit is None or self.source_dirty is None or self.invocation is None:
            raise ValueError("Executed cases require source identity and exact invocation inputs.")
        if self.started_at is None or self.finished_at is None:
            raise ValueError("Executed cases require actual start/finish times.")
        if not self.started_at <= self.finished_at <= self.recorded_at:
            raise ValueError("Execution timestamps must be ordered.")
        level = self.environment.level
        if level in {Level.NATIVE, Level.DOCKER, Level.GCP}:
            if (
                self.environment.os != "linux"
                or not self.environment.kernel
                or not self.environment.filesystem
            ):
                raise ValueError(
                    "Native/container/cloud evidence needs actual Linux/kernel/filesystem."
                )
        if level in {Level.DOCKER, Level.GCP} and not self.environment.container_runtime:
            raise ValueError("Container/cloud proof needs the actual container runtime pin.")
        if level in {Level.GCP, Level.BROWSER} and not self.environment.provider_configuration_ref:
            raise ValueError(
                "Cloud/deployed proof needs protected provider configuration identity."
            )


def combined_status(statuses: set[Result]) -> Result:
    for state in (Result.FAILED, Result.UNAVAILABLE, Result.NOT_RUN):
        if state in statuses:
            return state
    return Result.PASSED


def validate_report(specification: Specification, digest: str, report: ProofReport) -> None:
    """Check exact coverage/pins; do not authenticate evidence or promote release gates."""
    if (report.proof, report.owner, report.specification_revision) != (
        specification.proof,
        specification.owner,
        specification.revision,
    ) or report.specification_sha256 != digest:
        raise ValueError("Report does not pin this exact specification and owner.")
    if report.environment.level not in specification.levels:
        raise ValueError("Report level is not one of this specification's declared proof scopes.")
    if {item.case_id for item in report.cases} != set(specification.cases):
        raise ValueError("Every required case must be reported, including unrun/negative controls.")
    required = set(specification.required_pins)
    if {item.kind for item in report.pins} != required:
        raise ValueError(
            "Every required source/tool/image/schema/workload/config pin must be explicit."
        )
    if report.status == Result.PASSED and any(item.state != "pinned" for item in report.pins):
        raise ValueError("A pass cannot depend on unavailable/not-applicable input pins.")
