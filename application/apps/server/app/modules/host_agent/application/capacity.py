"""Measured candidate envelopes, never customer admission or a mutable quota ledger.

H04 owns persistence and serialized reservation commits. Callers must recheck the
snapshot revision while committing; this pure planner cannot reserve host resources.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.platform.hosted_contracts.values import (
    Contract,
    Count,
    EpochMillis,
    Reference,
    RequestHash,
    Revision,
)
from app.modules.host_agent.application.dispatch import ResourceLimits


class Resources(Contract):
    memory_bytes: Count = 0
    cpu_millicores: Count = 0
    pids: Count = 0
    data_bytes: Count = 0
    data_inodes: Count = 0
    boot_bytes: Count = 0
    boot_inodes: Count = 0

    def plus(self, other: Resources) -> Resources:
        return Resources(
            **{name: getattr(self, name) + getattr(other, name) for name in type(self).model_fields}
        )

    def remaining(self, other: Resources) -> Resources:
        return Resources(
            **{
                name: max(0, getattr(self, name) - getattr(other, name))
                for name in type(self).model_fields
            }
        )

    def fits(self, ceiling: Resources) -> bool:
        return all(
            getattr(self, name) <= getattr(ceiling, name) for name in type(self).model_fields
        )


class Commitment(Contract):
    identity: Reference
    state: Literal["pending", "active", "retained", "unknown", "cleanup_pending"]
    reserved: Resources | None
    observed: Resources = Resources()

    @model_validator(mode="after")
    def bounded_observation(self):
        if self.reserved is not None and not self.observed.fits(self.reserved):
            raise ValueError(
                "Observed use exceeds the recorded commitment; investigate before planning"
            )
        return self


class OperatorBudget(Contract):
    """Physical trial inputs, separate from advertised logical storage."""

    trees: ResourceLimits
    memory_bytes: Count
    cpu_millicores: Count
    pids: Count
    shared_memory_bytes: Count
    log_bytes: Count
    log_files: Count
    boot_metadata_bytes: Count
    boot_metadata_inodes: Count

    @model_validator(mode="after")
    def bounded(self):
        if (
            not self.memory_bytes
            or not self.cpu_millicores
            or not self.pids
            or not self.log_bytes
            or not self.log_files
            or self.shared_memory_bytes > self.memory_bytes
        ):
            raise ValueError("Explicit runtime, shared-memory and rotating-log bounds required")
        return self

    def reservation(self) -> Resources:
        roles = (self.trees.workspace, self.trees.control, self.trees.scratch)
        return Resources(
            memory_bytes=self.memory_bytes,
            cpu_millicores=self.cpu_millicores,
            pids=self.pids,
            data_bytes=sum(((row.byte_ceiling + 1023) // 1024) * 1024 for row in roles),
            data_inodes=sum(row.inode_ceiling for row in roles),
            boot_bytes=self.log_bytes * self.log_files + self.boot_metadata_bytes,
            boot_inodes=self.log_files + self.boot_metadata_inodes,
        )


class CandidateCapacityProfile(Contract):
    version: Literal[1] = 1
    reference: Reference
    revision: Revision
    acceptance: Literal["measured_candidate"] = "measured_candidate"
    measurement_sha256: RequestHash
    source_sha256: RequestHash
    runtime_policy_sha256: RequestHash
    maximum_observation_age_ms: Count
    shared_reserve: Resources
    # Dedicated physical headroom, distinct from Free logical storage accounting.
    # Reserving it does not implement/qualify H05 backup or workspace restore.
    recovery_reserve: Resources

    @model_validator(mode="after")
    def requires_reserves(self):
        if (
            not self.maximum_observation_age_ms
            or not self.shared_reserve.memory_bytes
            or not self.shared_reserve.boot_bytes
            or not self.recovery_reserve.data_bytes
            or not self.recovery_reserve.data_inodes
        ):
            raise ValueError(
                "Explicit freshness, shared and future-recovery reservations are required"
            )
        return self


class CapacitySnapshot(Contract):
    revision: Revision
    observed_at: EpochMillis
    complete: bool
    profile_ref: Reference
    profile_revision: Revision
    total: Resources
    available: Resources
    shared_observed: Resources
    commitments: tuple[Commitment, ...] = Field(default=(), max_length=4096)

    @model_validator(mode="after")
    def exact_ledger(self):
        if len({row.identity for row in self.commitments}) != len(self.commitments):
            raise ValueError("Every retained resource commitment needs one distinct identity")
        if not self.available.fits(self.total) or not self.shared_observed.fits(self.total):
            raise ValueError("Host observations exceed physical capacity")
        materialized = self.shared_observed
        for row in self.commitments:
            materialized = materialized.plus(row.observed)
        if not materialized.fits(self.total.remaining(self.available)):
            raise ValueError("Attributable usage exceeds total observed physical consumption")
        return self


class CapacityDecision(Contract):
    status: Literal["within_candidate_envelope", "insufficient", "unavailable"]
    code: Reference
    expected_snapshot_revision: Revision
    limiting_resources: tuple[str, ...] = ()
    proposed: Commitment | None = None


def plan_reservation(
    profile: CandidateCapacityProfile,
    snapshot: CapacitySnapshot,
    proposed: Commitment,
    *,
    now: int,
    expected_revision: int,
) -> CapacityDecision:
    """Count full retained/pending/unknown commitments; do not mutate any ledger.

    Enforce both total reservations and observed free resources. Subtract already
    materialized usage only in the free-space check, avoiding double counting it.
    Unknown limits, stale/incomplete observations and changed profiles fail closed.
    """
    result = dict(expected_snapshot_revision=snapshot.revision)
    if (
        type(now) is not int
        or type(expected_revision) is not int
        or not snapshot.complete
        or snapshot.revision != expected_revision
        or snapshot.profile_ref != profile.reference
        or snapshot.profile_revision != profile.revision
        or now < snapshot.observed_at
        or now - snapshot.observed_at > profile.maximum_observation_age_ms
        or not snapshot.shared_observed.fits(profile.shared_reserve)
        or any(row.reserved is None for row in (*snapshot.commitments, proposed))
    ):
        return CapacityDecision(
            status="unavailable", code="capacity_observation_unavailable", **result
        )
    if (
        proposed.state != "pending"
        or proposed.observed != Resources()
        or any(row.identity == proposed.identity for row in snapshot.commitments)
    ):
        return CapacityDecision(
            status="unavailable",
            code="capacity_commitment_requires_owning_reconciliation",
            **result,
        )
    try:
        reserved = profile.shared_reserve.plus(profile.recovery_reserve)
        unmaterialized = profile.shared_reserve.remaining(snapshot.shared_observed).plus(
            profile.recovery_reserve
        )
        for row in (*snapshot.commitments, proposed):
            reserved = reserved.plus(row.reserved)
            unmaterialized = unmaterialized.plus(row.reserved.remaining(row.observed))
    except ValueError:
        return CapacityDecision(
            status="unavailable", code="capacity_arithmetic_unavailable", **result
        )
    limiting = tuple(
        name
        for name in Resources.model_fields
        if getattr(reserved, name) > getattr(snapshot.total, name)
        or getattr(unmaterialized, name) > getattr(snapshot.available, name)
    )
    if limiting:
        return CapacityDecision(
            status="insufficient",
            code="capacity_reservation_exceeds_headroom",
            limiting_resources=limiting,
            **result,
        )
    return CapacityDecision(
        status="within_candidate_envelope",
        code="candidate_capacity_only",
        proposed=proposed,
        **result,
    )
