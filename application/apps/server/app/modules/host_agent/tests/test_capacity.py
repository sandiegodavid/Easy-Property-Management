"""Reservation planning is conservative and does not substitute for H04 persistence."""

import pytest
from pydantic import ValidationError

from app.modules.host_agent.application.capacity import (
    CandidateCapacityProfile,
    CapacitySnapshot,
    Commitment,
    OperatorBudget,
    Resources,
    plan_reservation,
)
from app.modules.host_agent.application.dispatch import ResourceLimits, TreeLimits


def profile():
    return CandidateCapacityProfile(
        reference="measured-fixture-v1",
        revision=1,
        measurement_sha256="a" * 64,
        source_sha256="b" * 64,
        runtime_policy_sha256="c" * 64,
        maximum_observation_age_ms=100,
        shared_reserve=Resources(memory_bytes=20, boot_bytes=20),
        recovery_reserve=Resources(data_bytes=20, data_inodes=10),
    )


def snapshot(**changes):
    values = dict(
        revision=1,
        observed_at=1000,
        complete=True,
        profile_ref="measured-fixture-v1",
        profile_revision=1,
        total=Resources(memory_bytes=100, data_bytes=100, data_inodes=100, boot_bytes=100),
        available=Resources(memory_bytes=100, data_bytes=100, data_inodes=100, boot_bytes=100),
        shared_observed=Resources(),
    )
    return CapacitySnapshot(**(values | changes))


def proposal(identity="new", **resources):
    return Commitment(identity=identity, state="pending", reserved=Resources(**resources))


def decide(value, new=None, now=1001, revision=1):
    return plan_reservation(
        profile(), value, new or proposal(data_bytes=30), now=now, expected_revision=revision
    )


def test_candidate_decision_preserves_input_and_does_not_reserve():
    value = snapshot()
    before = value.model_dump_json()
    result = decide(value)
    assert result.status == "within_candidate_envelope"
    assert result.code == "candidate_capacity_only"
    assert value.model_dump_json() == before
    assert not value.commitments


@pytest.mark.parametrize("state", ["pending", "active", "retained", "unknown", "cleanup_pending"])
def test_every_unreleased_commitment_counts_at_full_reserved_size(state):
    row = Commitment(identity="old", state=state, reserved=Resources(data_bytes=60))
    result = decide(snapshot(commitments=(row,)))
    assert result.status == "insufficient"
    assert result.limiting_resources == ("data_bytes",)


def test_materialized_usage_is_not_charged_twice_against_free_space():
    row = Commitment(
        identity="old",
        state="active",
        reserved=Resources(data_bytes=50),
        observed=Resources(data_bytes=40),
    )
    value = snapshot(
        commitments=(row,),
        available=Resources(memory_bytes=100, data_bytes=60, data_inodes=100, boot_bytes=100),
    )
    assert decide(value).status == "within_candidate_envelope"
    assert decide(value, proposal(data_bytes=31)).status == "insufficient"


@pytest.mark.parametrize(
    "change", [{"complete": False}, {"profile_revision": 2}, {"profile_ref": "other"}]
)
def test_incomplete_or_changed_profile_is_unavailable(change):
    assert decide(snapshot(**change)).status == "unavailable"


@pytest.mark.parametrize("now", [999, 1101, True])
def test_future_stale_or_untyped_clock_is_unavailable(now):
    assert decide(snapshot(), now=now).status == "unavailable"


def test_missing_limits_and_changed_snapshot_never_produce_a_plan():
    assert (
        decide(
            snapshot(commitments=(Commitment(identity="lost", state="unknown", reserved=None),))
        ).status
        == "unavailable"
    )
    assert decide(snapshot(), revision=2).status == "unavailable"


def test_existing_identity_requires_owning_original_result_not_double_reservation():
    value = snapshot(commitments=(proposal(identity="same", data_bytes=30),))
    result = decide(value, proposal(identity="same", data_bytes=30))
    assert result.status == "unavailable"
    assert result.code == "capacity_commitment_requires_owning_reconciliation"


def test_free_space_pressure_rejects_even_when_nominal_totals_fit():
    value = snapshot(
        available=Resources(memory_bytes=100, data_bytes=40, data_inodes=100, boot_bytes=100)
    )
    assert decide(value).status == "insufficient"


def test_impossible_usage_or_duplicate_ledger_rejects_before_planning():
    row = proposal(data_bytes=30)
    with pytest.raises(ValidationError):
        snapshot(commitments=(row, row))
    with pytest.raises(ValidationError):
        snapshot(shared_observed=Resources(memory_bytes=1))
    with pytest.raises(ValidationError):
        Commitment(
            identity="bad",
            state="active",
            reserved=Resources(data_bytes=1),
            observed=Resources(data_bytes=2),
        )


def test_kernel_rounding_logs_and_shared_memory_are_explicit():
    tree = TreeLimits(byte_ceiling=1025, inode_ceiling=5)
    budget = OperatorBudget(
        trees=ResourceLimits(workspace=tree, control=tree, scratch=tree),
        memory_bytes=100,
        cpu_millicores=250,
        pids=64,
        shared_memory_bytes=10,
        log_bytes=20,
        log_files=3,
        boot_metadata_bytes=10,
        boot_metadata_inodes=2,
    )
    assert budget.reservation() == Resources(
        memory_bytes=100,
        cpu_millicores=250,
        pids=64,
        data_bytes=6144,
        data_inodes=15,
        boot_bytes=70,
        boot_inodes=5,
    )
    with pytest.raises(ValidationError):
        OperatorBudget(**(budget.model_dump() | {"shared_memory_bytes": 101}))


def test_second_proposal_requires_fresh_revision_and_counts_first_hold():
    original = snapshot(commitments=(proposal(identity="old", data_bytes=30),))
    first = decide(original, proposal(identity="one", data_bytes=30))
    assert first.status == "within_candidate_envelope"
    applied = snapshot(revision=2, commitments=(*original.commitments, first.proposed))
    assert decide(applied, proposal(identity="two", data_bytes=30)).status == "unavailable"
    assert (
        decide(applied, proposal(identity="two", data_bytes=30), revision=2).status
        == "insufficient"
    )


def test_aggregate_integer_overflow_is_unavailable_not_a_partial_plan():
    maximum = 2**63 - 1
    changed = profile().model_copy(
        update={"shared_reserve": Resources(memory_bytes=maximum, boot_bytes=20)}
    )
    value = snapshot(
        total=Resources(memory_bytes=maximum, data_bytes=100, data_inodes=100, boot_bytes=100),
        available=Resources(memory_bytes=maximum, data_bytes=100, data_inodes=100, boot_bytes=100),
    )
    result = plan_reservation(
        changed, value, proposal(memory_bytes=1), now=1001, expected_revision=1
    )
    assert result.status == "unavailable"
    assert result.code == "capacity_arithmetic_unavailable"
