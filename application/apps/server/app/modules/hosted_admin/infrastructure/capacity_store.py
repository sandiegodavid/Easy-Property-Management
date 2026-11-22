"""Serialized host capacity profile, snapshot, and commitment persistence for Admin."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.modules.host_agent.application.capacity import (
    CandidateCapacityProfile,
    CapacityDecision,
    CapacitySnapshot,
    Commitment,
    OperatorBudget,
    Resources,
    plan_reservation,
)
from app.modules.hosted_admin.application.errors import (
    AdminConflictError,
    AdminUnavailableError,
)
from app.modules.hosted_admin.application.pilot_contracts import AdmissionCommitment


@dataclass(frozen=True)
class StoredCapacityState:
    profile: CandidateCapacityProfile
    free_budget: OperatorBudget
    snapshot: CapacitySnapshot


def register_capacity_profile(
    connection: Connection,
    profile: CandidateCapacityProfile,
    free_budget: OperatorBudget,
    *,
    created_at: int,
) -> None:
    """Insert an immutable pinned capacity profile inside a caller-owned write transaction."""
    connection.execute(
        text(
            "INSERT INTO main.capacity_profiles ("
            "profile_ref, profile_revision, measurement_sha256, source_sha256, "
            "runtime_policy_sha256, maximum_observation_age_ms, shared_reserve_json, "
            "recovery_reserve_json, free_budget_json, created_at"
            ") VALUES ("
            ":profile_ref, :profile_revision, :measurement_sha256, :source_sha256, "
            ":runtime_policy_sha256, :maximum_observation_age_ms, :shared_reserve_json, "
            ":recovery_reserve_json, :free_budget_json, :created_at"
            ")"
        ),
        {
            "profile_ref": profile.reference,
            "profile_revision": profile.revision,
            "measurement_sha256": profile.measurement_sha256,
            "source_sha256": profile.source_sha256,
            "runtime_policy_sha256": profile.runtime_policy_sha256,
            "maximum_observation_age_ms": profile.maximum_observation_age_ms,
            "shared_reserve_json": profile.shared_reserve.model_dump_json(),
            "recovery_reserve_json": profile.recovery_reserve.model_dump_json(),
            "free_budget_json": free_budget.model_dump_json(),
            "created_at": created_at,
        },
    )


def record_capacity_snapshot(connection: Connection, snapshot: CapacitySnapshot) -> None:
    """Upsert the singleton host capacity snapshot with monotonic revision enforcement."""
    existing = connection.execute(
        text("SELECT snapshot_revision FROM main.capacity_snapshots WHERE id = 1")
    ).scalar_one_or_none()
    params = {
        "snapshot_revision": snapshot.revision,
        "profile_ref": snapshot.profile_ref,
        "profile_revision": snapshot.profile_revision,
        "observed_at": snapshot.observed_at,
        "complete": 1 if snapshot.complete else 0,
        "total_json": snapshot.total.model_dump_json(),
        "available_json": snapshot.available.model_dump_json(),
        "shared_observed_json": snapshot.shared_observed.model_dump_json(),
    }
    if existing is None:
        connection.execute(
            text(
                "INSERT INTO main.capacity_snapshots ("
                "id, snapshot_revision, profile_ref, profile_revision, observed_at, "
                "complete, total_json, available_json, shared_observed_json"
                ") VALUES ("
                "1, :snapshot_revision, :profile_ref, :profile_revision, :observed_at, "
                ":complete, :total_json, :available_json, :shared_observed_json"
                ")"
            ),
            params,
        )
        return
    if snapshot.revision <= existing:
        raise AdminConflictError(
            "capacity_snapshot_stale",
            "Capacity snapshot revision must strictly advance.",
        )
    connection.execute(
        text(
            "UPDATE main.capacity_snapshots SET "
            "snapshot_revision = :snapshot_revision, "
            "profile_ref = :profile_ref, "
            "profile_revision = :profile_revision, "
            "observed_at = :observed_at, "
            "complete = :complete, "
            "total_json = :total_json, "
            "available_json = :available_json, "
            "shared_observed_json = :shared_observed_json "
            "WHERE id = 1"
        ),
        params,
    )


def load_capacity_state(connection: Connection) -> StoredCapacityState | None:
    """Load the active snapshot, its pinned profile, and all unreleased commitments."""
    snapshot_row = (
        connection.execute(text("SELECT * FROM main.capacity_snapshots WHERE id = 1"))
        .mappings()
        .one_or_none()
    )
    if snapshot_row is None:
        return None
    profile_row = (
        connection.execute(
            text(
                "SELECT * FROM main.capacity_profiles "
                "WHERE profile_ref = :ref AND profile_revision = :rev"
            ),
            {"ref": snapshot_row["profile_ref"], "rev": snapshot_row["profile_revision"]},
        )
        .mappings()
        .one_or_none()
    )
    if profile_row is None:
        return None
    commitment_rows = (
        connection.execute(text("SELECT * FROM main.capacity_commitments ORDER BY operator_id ASC"))
        .mappings()
        .all()
    )
    commitments = tuple(
        Commitment(
            identity=row["operator_id"],
            state=row["state"],
            reserved=Resources.model_validate_json(row["reserved_json"]),
            observed=Resources.model_validate_json(row["observed_json"]),
        )
        for row in commitment_rows
    )
    profile = CandidateCapacityProfile(
        reference=profile_row["profile_ref"],
        revision=profile_row["profile_revision"],
        measurement_sha256=profile_row["measurement_sha256"],
        source_sha256=profile_row["source_sha256"],
        runtime_policy_sha256=profile_row["runtime_policy_sha256"],
        maximum_observation_age_ms=profile_row["maximum_observation_age_ms"],
        shared_reserve=Resources.model_validate_json(profile_row["shared_reserve_json"]),
        recovery_reserve=Resources.model_validate_json(profile_row["recovery_reserve_json"]),
    )
    free_budget = OperatorBudget.model_validate_json(profile_row["free_budget_json"])
    snapshot = CapacitySnapshot(
        revision=snapshot_row["snapshot_revision"],
        observed_at=snapshot_row["observed_at"],
        complete=bool(snapshot_row["complete"]),
        profile_ref=snapshot_row["profile_ref"],
        profile_revision=snapshot_row["profile_revision"],
        total=Resources.model_validate_json(snapshot_row["total_json"]),
        available=Resources.model_validate_json(snapshot_row["available_json"]),
        shared_observed=Resources.model_validate_json(snapshot_row["shared_observed_json"]),
        commitments=commitments,
    )
    return StoredCapacityState(profile=profile, free_budget=free_budget, snapshot=snapshot)


def commitment_matches_budget(requested: AdmissionCommitment, budget: OperatorBudget) -> bool:
    """Ensure the requested AdmissionCommitment matches the pinned Free budget."""
    return (
        requested.warm_memory_bytes == budget.memory_bytes
        and requested.cpu_millis == budget.cpu_millicores
        and requested.workspace.bytes == budget.trees.workspace.byte_ceiling
        and requested.workspace.inodes == budget.trees.workspace.inode_ceiling
        and requested.control.bytes == budget.trees.control.byte_ceiling
        and requested.control.inodes == budget.trees.control.inode_ceiling
        and requested.scratch.bytes == budget.trees.scratch.byte_ceiling
        and requested.scratch.inodes == budget.trees.scratch.inode_ceiling
    )


def evaluate_admission(
    connection: Connection,
    *,
    operator_id: str,
    requested_commitment: AdmissionCommitment,
    now: int,
    expected_snapshot_revision: int | None = None,
) -> tuple[CapacityDecision, Resources]:
    """Evaluate serialized capacity admission against the current snapshot and ledger."""
    state = load_capacity_state(connection)
    if state is None:
        raise AdminUnavailableError(
            "capacity_observation_unavailable",
            "Host capacity profile or snapshot is unavailable.",
        )
    if not commitment_matches_budget(requested_commitment, state.free_budget):
        raise AdminConflictError(
            "capacity_commitment_mismatch",
            "Requested admission commitment does not match the pinned Free budget.",
        )
    reserved = state.free_budget.reservation()
    proposed = Commitment(
        identity=operator_id,
        state="pending",
        reserved=reserved,
        observed=Resources(),
    )
    revision = (
        state.snapshot.revision
        if expected_snapshot_revision is None
        else expected_snapshot_revision
    )
    decision = plan_reservation(
        state.profile,
        state.snapshot,
        proposed,
        now=now,
        expected_revision=revision,
    )
    return decision, reserved
