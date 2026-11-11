"""Pure H02.1 contract tests; no claims about durable receipts or live fences."""

from pathlib import Path
import re

import pytest
from pydantic import ValidationError

from app.modules.host_agent.application.build_inputs import (
    ArtifactPin,
    HostBuildInputs,
    MAIN_ADMIN_TABLES,
    PrincipalRange,
    Toolchain,
)
from app.modules.host_agent.application.effect_contracts import (
    ApplyIngressPolicy,
    EffectIdentity,
    GuardedLifecycle,
    InspectIngress,
)
from app.platform.hosted_contracts.operations import OperationReference
from app.platform.hosted_contracts.semantic import canonical_bytes, semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope

ID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
MAX_KEY_LENGTH = 120


def identity(**changes):
    fields = {
        "parent": OperationReference(
            deployment_id=ID,
            scope=WorkspaceScope(operator_id=ID, workspace_id=ID),
            kind="disable",
            operation_id=ID,
            idempotency_key="original-parent",
            request_hash="a" * 64,
        ),
        "binding_id": ID,
        "resource_generation": 1,
        "kind": "apply_ingress_policy",
        "slot": "external_deny",
    }
    return EffectIdentity(**(fields | changes))


def request(**changes):
    return ApplyIngressPolicy(
        **(
            {
                "effect": identity(),
                "access_epoch": 1,
                "expected_ingress_revision": 1,
                "desired_state": "held",
            }
            | changes
        )
    )


def test_child_identity_is_repeatable_and_bounded():
    first, retry = identity(), identity()
    assert first.child_id() == retry.child_id()
    assert first.child_key() == retry.child_key()
    assert first.child_id() != ID
    assert first.child_id() == "7fab1e52-700d-51df-9081-f2155173561f"
    assert len(first.child_key()) <= MAX_KEY_LENGTH
    assert canonical_bytes(first) == canonical_bytes(retry)


@pytest.mark.parametrize(
    "changes",
    [
        {"binding_id": OTHER},
        {"resource_generation": 2},
        {"kind": "stop_container"},
        {"slot": "source_revoke"},
    ],
)
def test_distinct_effect_slots_have_distinct_identity(changes):
    assert identity(**changes).child_id() != identity().child_id()


@pytest.mark.parametrize("field", ["access_epoch", "expected_ingress_revision"])
def test_changed_fences_change_request_hash_not_effect_identity(field):
    before, after = request(), request(**{field: 2})
    assert before.effect.child_key() == after.effect.child_key()
    assert semantic_hash(before) != semantic_hash(after)


def test_changed_policy_keeps_key_but_conflicts_with_original_semantics():
    held, blocked = request(), request(desired_state="blocked")
    assert held.effect.child_key() == blocked.effect.child_key()
    assert semantic_hash(held) != semantic_hash(blocked)


@pytest.mark.parametrize("state", ["held", "blocked"])
def test_denial_does_not_require_unavailable_source(state):
    assert request(desired_state=state).desired_state == state


@pytest.mark.parametrize(
    "proofs",
    [{}, {"source_identity_proof_ref": "source-v1"}, {"resource_readiness_proof_ref": "ready-v1"}],
)
def test_eligible_requires_both_proof_inputs(proofs):
    with pytest.raises(ValidationError):
        request(desired_state="eligible", **proofs)


def test_eligible_is_typed_input_not_qualification():
    result = request(
        desired_state="eligible",
        source_identity_proof_ref="source-v1",
        resource_readiness_proof_ref="ready-v1",
    )
    assert result.desired_state == "eligible"


def test_wrong_effect_and_raw_targets_rejected():
    with pytest.raises(ValidationError):
        request(effect=identity(kind="start_container"))
    with pytest.raises(ValidationError):
        request(origin="https://unregistered.example.invalid")
    with pytest.raises(ValidationError):
        InspectIngress(binding_id=ID, resource_generation=1, path="/tmp/operator")


@pytest.mark.parametrize(
    "changes",
    [{"restart_owner": "docker"}, {"docker_restart_policy": "always"}, {"required_checks": ()}],
)
def test_no_competing_restart_owner_or_skipped_checks(changes):
    with pytest.raises(ValidationError):
        GuardedLifecycle(**changes)


def test_default_guard_requires_all_prerequisites():
    assert GuardedLifecycle().docker_restart_policy == "no"


def build_inputs(**changes):
    pin = ArtifactPin(version="synthetic-not-a-real-tool", sha256="a" * 64)
    return HostBuildInputs(
        **(
            {
                "deployment_id": ID,
                "protected_setup_ref": "synthetic-private-inputs",
                "protected_setup_sha256": "b" * 64,
                "source_manifest_sha256": "c" * 64,
                "toolchain": Toolchain(**{key: pin for key in Toolchain.model_fields}),
                "image_schema_spec_sha256": "d" * 64,
                "runtime_limits_spec_sha256": "e" * 64,
                "host_uids": PrincipalRange(first=100000, last=100100),
                "host_gids": PrincipalRange(first=100000, last=100100),
                "capacity_profile_revision": 1,
            }
            | changes
        )
    )


def test_pinned_inputs_remain_candidate_with_unmeasured_capacity():
    inputs = build_inputs()
    assert inputs.acceptance == "infrastructure_candidate"
    assert inputs.capacity_state == "unmeasured"
    assert inputs.customer_ingress == "held"


@pytest.mark.parametrize(
    "changes",
    [
        {"acceptance": "qualified"},
        {"customer_ingress": "eligible"},
        {"capacity_state": "passed"},
        {"uid_mapping": "remapped"},
        {"spot": True},
        {"architecture": "arm64"},
        {"protected_setup_sha256": "moving-tag"},
        {"docker_socket": "/var/run/docker.sock"},
    ],
)
def test_candidate_cannot_claim_acceptance_or_change_qualified_target(changes):
    with pytest.raises(ValidationError):
        build_inputs(**changes)


@pytest.mark.parametrize(
    "fields",
    [
        {"first": 0, "last": 5},
        {"first": 5, "last": 4},
        {"first": 5, "last": 5, "reserved": (5,)},
        {"first": 5, "last": 6, "reserved": (5, 5)},
        {"first": 4294967295, "last": 4294967295},
    ],
)
def test_invalid_or_exhausted_principal_ranges_reject(fields):
    with pytest.raises(ValidationError):
        PrincipalRange(**fields)


def test_tool_pin_requires_exact_hash():
    with pytest.raises(ValidationError):
        ArtifactPin(version="latest")


def test_effect_identity_pins_original_parent_and_scope():
    parent = identity().parent
    changed = OperationReference(**(parent.model_dump() | {"operation_id": OTHER}))
    assert identity(parent=changed).child_id() != identity().child_id()
    with pytest.raises(ValidationError):
        identity(
            parent=OperationReference(**(parent.model_dump() | {"scope": {"kind": "deployment"}}))
        )


def test_main_admin_closure_includes_all_three_owning_dictionaries():
    root = next(path for path in Path(__file__).resolve().parents if (path / "AGENTS.md").exists())
    tables = []
    for name in ("admin-registry", "admin-identity", "admin-operations"):
        text = (root / "docs" / "database" / f"{name}.md").read_text()
        tables.extend(re.findall(r"^### `([^`]+)`", text, re.MULTILINE))
    assert sorted(tables) == sorted(MAIN_ADMIN_TABLES)
