"""H04.6 Host Agent AdmissionPort, manual provisioning, retry, and synthetic-seed tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.modules.host_agent.application.contracts import PrepareResources
from app.modules.host_agent.application.dispatch import (
    HostAgentDenied,
    HostEffect,
    ResourceInputs,
    require_admission,
)
from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.modules.host_agent.infrastructure.manual_provision import (
    ManualProvisionConfig,
    ManualProvisioner,
    ProvisionPaths,
)
from app.modules.hosted_admin.infrastructure.provisioning_admission import AdminEffectAdmission
from app.modules.hosted_admin.infrastructure.synthetic_seed import canonical_seed_bundle_ref
from app.modules.hosted_admin.tests.test_admin_control import (
    DEPLOYMENT_ID,
    RELEASE_ID,
    actor,
    make_create_command,
)
from app.platform.hosted_contracts.operations import OperationReference
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope

pytest_plugins = ("app.modules.hosted_admin.tests.test_admin_control",)

APPLICATION = Path(__file__).resolve().parents[6]
DATASET_PATH = APPLICATION / "demo" / "dataset.json"
BINDING_ID = "00000000-0000-4000-8000-000000000601"


def _paths_factory(base: Path):
    def build(intent) -> ProvisionPaths:
        root = base / intent.operator_id
        return ProvisionPaths(
            workspace_root=root / "workspace",
            control_root=root / "control",
            scratch_root=root / "scratch",
        )

    return build


def test_admission_port_resolves_pinned_plan_and_rejects_tampering(env):
    service = env["service"]
    cmd = make_create_command(env["policy_id"], slug="aspen", email="aspen@example.invalid")
    outcome = service.execute(actor(), cmd)
    op_id = outcome.operation.operation_id
    operator_id = cmd.intent.payload.operator_id
    workspace_id = cmd.intent.payload.workspace_id

    admission = AdminEffectAdmission(env["engine"], clock=env["clock"])
    intent = admission.load_provision_intent(op_id)
    assert intent.public_origin == "https://aspen.epmdemo.invalid"

    parent_ref = OperationReference(
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=operator_id, workspace_id=workspace_id),
        kind="provision",
        operation_id=op_id,
        idempotency_key=cmd.idempotency_key,
        request_hash=cmd.request_hash,
    )
    effect = EffectIdentity(
        parent=parent_ref,
        binding_id=BINDING_ID,
        resource_generation=1,
        kind="prepare_resources",
        slot="prepare_1",
    )
    expected_hash = semantic_hash(
        ResourceInputs(plan=intent.plan, public_origin=intent.public_origin)
    )
    host_cmd = HostEffect(
        effect=effect,
        access_epoch=1,
        expected_revision=1,
        inputs_hash=expected_hash,
        payload=PrepareResources(
            binding_id=BINDING_ID,
            release_id=RELEASE_ID,
            image_id=RELEASE_ID,
            admission_commitment_id=operator_id,
            capacity_profile_ref=intent.plan.capacity_profile_ref,
        ),
    )

    admitted = admission.resolve(host_cmd)
    require_admission(host_cmd, admitted, env["clock"]())
    assert admitted.plan == intent.plan
    assert admitted.public_origin == "https://aspen.epmdemo.invalid"

    # Tampered inputs_hash or wrong access_epoch fails closed.
    bad_hash_cmd = host_cmd.model_copy(update={"inputs_hash": "0" * 64})
    with pytest.raises(HostAgentDenied):
        admission.resolve(bad_hash_cmd)
    bad_epoch_cmd = host_cmd.model_copy(update={"access_epoch": 2})
    with pytest.raises(HostAgentDenied):
        admission.resolve(bad_epoch_cmd)


def test_manual_provision_empty_workspace_and_idempotent_retry(env, tmp_path):
    service = env["service"]
    cmd = make_create_command(env["policy_id"], slug="willow", email="willow@example.invalid")
    outcome = service.execute(actor(), cmd)
    op_id = outcome.operation.operation_id
    operator_id = cmd.intent.payload.operator_id

    admission = AdminEffectAdmission(env["engine"], clock=env["clock"])
    fail_once = {"should_fail": True}
    hook_calls: list[str] = []

    def hook(stage: str, _intent, _paths) -> str:
        hook_calls.append(stage)
        if stage == "start_container" and fail_once["should_fail"]:
            fail_once["should_fail"] = False
            raise RuntimeError("transient docker failure")
        return f"host-receipt:{stage}"

    provisioner = ManualProvisioner(
        admission,
        ManualProvisionConfig(
            paths_for=_paths_factory(tmp_path / "hosts"),
            application_directory=APPLICATION,
            clock=env["clock"],
            dataset_path=DATASET_PATH,
            host_effect_hook=hook,
        ),
    )

    # First run fails during start_container -> needs_attention, commitment retained as pending.
    first = provisioner.provision(op_id)
    assert first.state == "needs_attention"
    assert first.error_code == "provision_failed"
    with env["engine"].connect() as conn:
        assert (
            conn.execute(
                text("SELECT setup_state FROM main.operators WHERE operator_id = :id"),
                {"id": operator_id},
            ).scalar_one()
            == "needs_attention"
        )
        assert (
            conn.execute(
                text("SELECT state FROM main.capacity_commitments WHERE operator_id = :id"),
                {"id": operator_id},
            ).scalar_one()
            == "pending"
        )

    # Retry succeeds idempotently (replaying initialize_binding without error).
    second = provisioner.provision(op_id)
    assert second.state == "succeeded"
    assert second.observation_ref == "host-receipt:start_container"
    assert second.observed_usage_bytes is not None and second.observed_usage_bytes > 0

    # Third call on already-succeeded operation is a no-op success.
    third = provisioner.provision(op_id)
    assert third.state == "succeeded"

    with env["engine"].connect() as conn:
        assert (
            conn.execute(
                text("SELECT setup_state FROM main.operators WHERE operator_id = :id"),
                {"id": operator_id},
            ).scalar_one()
            == "ready_for_claim"
        )
        assert (
            conn.execute(
                text("SELECT state FROM main.component_deployments WHERE operator_id = :id"),
                {"id": operator_id},
            ).scalar_one()
            == "applied"
        )
        assert (
            conn.execute(
                text("SELECT state FROM main.capacity_commitments WHERE operator_id = :id"),
                {"id": operator_id},
            ).scalar_one()
            == "active"
        )
        assert (
            conn.execute(
                text(
                    "SELECT freshness_state FROM main.operator_source_observations "
                    "WHERE operator_id = :id"
                ),
                {"id": operator_id},
            ).scalar_one()
            == "known"
        )


def test_manual_provision_synthetic_seed_pin_and_mismatch_rejection(env, tmp_path):
    service = env["service"]
    admission = AdminEffectAdmission(env["engine"], clock=env["clock"])

    # Mismatched seed_bundle fails closed and keeps workspace closed.
    bad_cmd = make_create_command(
        env["policy_id"],
        slug="bad-seed",
        email="badseed@example.invalid",
        expected_revision=1,
        idempotency_key="create-bad-seed",
        initial_data="synthetic",
        seed_bundle="synthetic-demo-v1:" + "0" * 64,
    )
    bad_op = service.execute(actor(), bad_cmd).operation.operation_id
    provisioner_bad = ManualProvisioner(
        admission,
        ManualProvisionConfig(
            paths_for=_paths_factory(tmp_path / "bad"),
            application_directory=APPLICATION,
            clock=env["clock"],
            dataset_path=DATASET_PATH,
        ),
    )
    bad_res = provisioner_bad.provision(bad_op)
    assert bad_res.state == "needs_attention"
    assert bad_res.error_code == "seed_bundle_mismatch"

    # Matching pinned seed_bundle runs seeder using scratch and succeeds.
    pinned_bundle = canonical_seed_bundle_ref(DATASET_PATH)
    seeded_markers: list[tuple[Path, Path]] = []

    def fake_seeder(workspace_root: Path, config_path: Path, journal_path: Path) -> None:
        assert config_path.parent == journal_path.parent
        assert workspace_root not in config_path.parents
        journal_path.write_text('{"seeded":true}\n', encoding="utf-8")
        seeded_markers.append((workspace_root, journal_path))

    good_cmd = make_create_command(
        env["policy_id"],
        slug="good-seed",
        email="goodseed@example.invalid",
        expected_revision=2,
        idempotency_key="create-good-seed",
        initial_data="synthetic",
        seed_bundle=pinned_bundle,
    )
    good_op = service.execute(actor(), good_cmd).operation.operation_id
    provisioner_good = ManualProvisioner(
        admission,
        ManualProvisionConfig(
            paths_for=_paths_factory(tmp_path / "good"),
            application_directory=APPLICATION,
            clock=env["clock"],
            dataset_path=DATASET_PATH,
            seeder_runner=fake_seeder,
        ),
    )
    good_res = provisioner_good.provision(good_op)
    assert good_res.state == "succeeded"
    assert len(seeded_markers) == 1
    assert good_res.observed_usage_bytes is not None
    assert good_res.observed_usage_bytes > 0
