"""H04.2 Admin-lite control-plane tests: AdminPort, capacity admission, and set-based reads."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.modules.host_agent.application.capacity import (
    CandidateCapacityProfile,
    CapacitySnapshot,
    OperatorBudget,
    Resources,
)
from app.modules.host_agent.application.dispatch import ResourceLimits, TreeLimits
from app.modules.hosted_admin.application.errors import (
    AdminConflictError,
    AdminDeniedError,
    AdminNotFoundError,
    AdminUnavailableError,
)
from app.modules.hosted_admin.application.pilot_contracts import (
    AdminCommand,
    AdmissionCommitment,
    CreateAssignment,
    RefreshSource,
    ReissueInvitation,
    ResourceCeiling,
)
from app.modules.hosted_admin.application.ui_contracts import AdminFilters
from app.modules.hosted_admin.infrastructure.admin_control import (
    AdminControlService,
    SourceObservationReading,
)
from app.modules.hosted_admin.infrastructure.capacity_store import (
    record_capacity_snapshot,
    register_capacity_profile,
)
from app.modules.hosted_admin.infrastructure.policy_bootstrap import bootstrap_free_v1_policy
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment
from app.platform.hosted_contracts.authority import AdminAuthority, ObservationQuery
from app.platform.hosted_contracts.operations import (
    CommandIntent,
    OperationState,
    SemanticConflict,
)
from app.platform.hosted_contracts.reads import FreshnessState
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.ui_states import UIAction
from app.platform.hosted_contracts.values import DeploymentScope, WorkspaceScope
from app.platform.hosted_schema import InitializationResult, initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000101"
PRINCIPAL_ID = "00000000-0000-4000-8000-000000000102"
RELEASE_ID = "00000000-0000-4000-8000-000000000103"
WITHDRAWN_RELEASE_ID = "00000000-0000-4000-8000-000000000104"
ISSUER = "firebase:pilot0"
NOW = 1_000_000
MIB = 1024 * 1024
HOST_SLOTS = 7
TWO_OPERATORS = 2
NEXT_REGISTRY_GEN = 3
SIX_OPERATORS = 6
PAGE_SIZE = 2
OBSERVE_LIMIT = 3
MAX_LIST_QUERIES = 4
NEXT_INVITE_REV = 2
SAMPLE_USAGE_BYTES = 42_000


def free_budget() -> OperatorBudget:
    return OperatorBudget(
        trees=ResourceLimits(
            workspace=TreeLimits(byte_ceiling=128 * MIB, inode_ceiling=4096),
            control=TreeLimits(byte_ceiling=16 * MIB, inode_ceiling=1024),
            scratch=TreeLimits(byte_ceiling=64 * MIB, inode_ceiling=1024),
        ),
        memory_bytes=256 * MIB,
        cpu_millicores=500,
        pids=64,
        shared_memory_bytes=16 * MIB,
        log_bytes=4 * MIB,
        log_files=4,
        boot_metadata_bytes=4 * MIB,
        boot_metadata_inodes=256,
    )


def admission_commitment(budget: OperatorBudget | None = None) -> AdmissionCommitment:
    target = budget or free_budget()
    return AdmissionCommitment(
        warm_memory_bytes=target.memory_bytes,
        cpu_millis=target.cpu_millicores,
        workspace=ResourceCeiling(
            bytes=target.trees.workspace.byte_ceiling,
            inodes=target.trees.workspace.inode_ceiling,
        ),
        control=ResourceCeiling(
            bytes=target.trees.control.byte_ceiling,
            inodes=target.trees.control.inode_ceiling,
        ),
        scratch=ResourceCeiling(
            bytes=target.trees.scratch.byte_ceiling,
            inodes=target.trees.scratch.inode_ceiling,
        ),
    )


def capacity_profile() -> CandidateCapacityProfile:
    return CandidateCapacityProfile(
        reference="pilot0-free-v1",
        revision=1,
        measurement_sha256="a" * 64,
        source_sha256="b" * 64,
        runtime_policy_sha256="c" * 64,
        maximum_observation_age_ms=300_000,
        shared_reserve=Resources(
            memory_bytes=512 * MIB,
            cpu_millicores=500,
            pids=128,
            data_bytes=256 * MIB,
            data_inodes=4096,
            boot_bytes=256 * MIB,
            boot_inodes=2048,
        ),
        recovery_reserve=Resources(
            data_bytes=512 * MIB,
            data_inodes=8192,
            boot_bytes=64 * MIB,
            boot_inodes=512,
        ),
    )


def host_resources(operator_slots: int) -> tuple[Resources, Resources, Resources]:
    budget = free_budget().reservation()
    profile = capacity_profile()
    total = profile.shared_reserve.plus(profile.recovery_reserve)
    for _ in range(operator_slots):
        total = total.plus(budget)
    shared_observed = Resources(
        memory_bytes=128 * MIB,
        cpu_millicores=100,
        pids=32,
        data_bytes=64 * MIB,
        data_inodes=512,
        boot_bytes=64 * MIB,
        boot_inodes=256,
    )
    available = total.remaining(shared_observed)
    return total, available, shared_observed


class Clock:
    def __init__(self, value: int = NOW) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


@pytest.fixture
def env(tmp_path):
    private = tmp_path.resolve() / "private"
    private.mkdir(mode=0o700)
    db_path = private / "admin.sqlite"
    assert (
        initialize_store(HostedStore.ADMIN, db_path, application_directory=APPLICATION)
        == InitializationResult.INITIALIZED
    )
    engine = create_sqlite_engine(db_path)
    clock = Clock()
    with immediate_transaction(engine) as connection:
        bind_deployment(
            connection,
            DeploymentMetadata(
                deployment_id=DEPLOYMENT_ID,
                public_base_domain="epmdemo.invalid",
                login_origin="https://login.epmdemo.invalid",
                registry_generation=1,
                created_at=100,
            ),
            application_directory=APPLICATION,
        )
        policy, _ = bootstrap_free_v1_policy(
            connection, created_at=100, application_directory=APPLICATION
        )
        connection.execute(
            text(
                "INSERT INTO main.admin_principals ("
                "principal_id, issuer, subject, enabled, session_generation, revision, created_at"
                ") VALUES (:id, :issuer, 'admin-uid', 1, 1, 1, 100)"
            ),
            {"id": PRINCIPAL_ID, "issuer": ISSUER},
        )
        for rel_id, state in ((RELEASE_ID, "qualified"), (WITHDRAWN_RELEASE_ID, "withdrawn")):
            connection.execute(
                text(
                    "INSERT INTO main.qualified_releases ("
                    "release_id, component, artifact_kind, artifact_digest, artifact_ref, "
                    "compatibility_manifest_ref, compatibility_manifest_sha256, "
                    "business_schema_revision, access_schema_revision, recovery_schema_revision, "
                    "qualification_ref, state, qualified_at, revision"
                    ") VALUES ("
                    ":id, 'operator', 'oci_image', :digest, 'operator-image:v1', "
                    "'manifest-v1', :mhash, 'biz_1', 'access_0001_initial', 'rec_1', "
                    "'qual-v1', :state, 100, 1"
                    ")"
                ),
                {
                    "id": rel_id,
                    "digest": ("d" if state == "qualified" else "e") * 64,
                    "mhash": "f" * 64,
                    "state": state,
                },
            )
        profile = capacity_profile()
        budget = free_budget()
        register_capacity_profile(connection, profile, budget, created_at=100)
        total, available, shared_observed = host_resources(operator_slots=HOST_SLOTS)
        record_capacity_snapshot(
            connection,
            CapacitySnapshot(
                revision=1,
                observed_at=NOW - 10_000,
                complete=True,
                profile_ref=profile.reference,
                profile_revision=profile.revision,
                total=total,
                available=available,
                shared_observed=shared_observed,
            ),
        )
    service = AdminControlService(
        engine,
        clock=clock,
        issuer=ISSUER,
        application_directory=APPLICATION,
    )
    try:
        yield {
            "engine": engine,
            "service": service,
            "clock": clock,
            "policy_id": policy.policy_id,
        }
    finally:
        engine.dispose()


def actor(
    *, mfa_verified_at: int = NOW - 60_000, principal_id: str = PRINCIPAL_ID
) -> AdminAuthority:
    return AdminAuthority(
        deployment_id=DEPLOYMENT_ID,
        principal_id=principal_id,
        identity_proof_ref="session:admin-1",
        mfa_verified_at=mfa_verified_at,
    )


def make_create_command(policy_id: str, **overrides) -> AdminCommand:
    defaults = {
        "slug": "oak-ridge",
        "email": "owner@oakridge.invalid",
        "display_name": "Oak Ridge",
        "expected_revision": 1,
        "idempotency_key": "create-oak-ridge-1",
        "release_id": RELEASE_ID,
        "initial_data": "empty",
        "seed_bundle": None,
        "commitment": None,
    }
    opts = defaults | overrides
    payload = CreateAssignment(
        operator_id=str(uuid4()),
        workspace_id=str(uuid4()),
        display_name=opts["display_name"],
        email=opts["email"],
        slug=opts["slug"],
        support_contact="support@epmdemo.invalid",
        release_id=opts["release_id"],
        policy_id=policy_id,
        admission_commitment=opts["commitment"] or admission_commitment(),
        initial_data=opts["initial_data"],
        seed_bundle=opts["seed_bundle"],
    )
    intent = CommandIntent[CreateAssignment](
        deployment_id=DEPLOYMENT_ID,
        scope=DeploymentScope(),
        kind="create_assignment",
        expected_revision=opts["expected_revision"],
        access_epoch=1,
        payload=payload,
    )
    return AdminCommand(
        operation_id=str(uuid4()),
        idempotency_key=opts["idempotency_key"],
        intent=intent,
        request_hash=semantic_hash(intent),
    )


def test_create_assignment_empty_and_synthetic_is_atomic_and_idempotent(env):
    service: AdminControlService = env["service"]
    policy_id: str = env["policy_id"]

    cmd = make_create_command(policy_id, slug="maple-grove", email="Maple@Example.invalid")
    outcome = service.execute(actor(), cmd)
    assert outcome.state == OperationState.PENDING
    assert outcome.operation.operation_id == cmd.operation_id
    assert outcome.operation.kind == "create_assignment"

    # Replay with a different proposed operation_id returns the original identity.
    replay_cmd = cmd.model_copy(update={"operation_id": str(uuid4())})
    replayed = service.execute(actor(), replay_cmd)
    assert replayed == outcome
    assert service.original(actor(), cmd.reference()) == outcome

    # Reusing the same idempotency_key with changed semantics conflicts.
    conflicting = make_create_command(
        policy_id,
        slug="maple-grove-2",
        email="other@example.invalid",
        expected_revision=2,
        idempotency_key=cmd.idempotency_key,
    )
    with pytest.raises(SemanticConflict):
        service.execute(actor(), conflicting)

    # Synthetic portfolio assignment succeeds at registry_generation == 2.
    synth_cmd = make_create_command(
        policy_id,
        slug="cedar-demo",
        email="cedar@example.invalid",
        expected_revision=2,
        idempotency_key="create-cedar-1",
        initial_data="synthetic",
        seed_bundle="synthetic-demo-v1:" + "1" * 64,
    )
    synth_outcome = service.execute(actor(), synth_cmd)
    assert synth_outcome.state == OperationState.PENDING

    with env["engine"].connect() as conn:
        for table in (
            "operators",
            "component_deployments",
            "capacity_commitments",
            "operations",
            "operation_events",
            "admin_audit",
        ):
            count = conn.execute(text(f"SELECT count(*) FROM main.{table}")).scalar_one()
            assert count == TWO_OPERATORS
        gen = conn.execute(
            text("SELECT registry_generation FROM main.control_meta WHERE id=1")
        ).scalar_one()
        assert gen == NEXT_REGISTRY_GEN


def test_capacity_admission_has_no_five_operator_cap_and_rejects_when_full(env):
    service: AdminControlService = env["service"]
    policy_id: str = env["policy_id"]

    # Host has 7 operator slots: all 7 succeed (proving no hard-coded 5-operator cap).
    for idx in range(1, HOST_SLOTS + 1):
        cmd = make_create_command(
            policy_id,
            slug=f"pilot-{idx}",
            email=f"pilot{idx}@example.invalid",
            display_name=f"Pilot {idx}",
            expected_revision=idx,
            idempotency_key=f"create-pilot-{idx}",
        )
        outcome = service.execute(actor(), cmd)
        assert outcome.state == OperationState.PENDING

    # 8th operator is rejected by capacity headroom, leaving zero partial rows.
    eighth = make_create_command(
        policy_id,
        slug="pilot-8",
        email="pilot8@example.invalid",
        expected_revision=HOST_SLOTS + 1,
        idempotency_key="create-pilot-8",
    )
    with pytest.raises(AdminConflictError) as exc:
        service.execute(actor(), eighth)
    assert exc.value.code == "capacity_insufficient"
    assert exc.value.limiting_resources

    with env["engine"].connect() as conn:
        for table in ("operators", "capacity_commitments", "operations"):
            count = conn.execute(text(f"SELECT count(*) FROM main.{table}")).scalar_one()
            assert count == HOST_SLOTS


def test_create_assignment_rejects_invalid_combinations_and_rolls_back(env):
    service: AdminControlService = env["service"]
    policy_id: str = env["policy_id"]

    with pytest.raises(AdminDeniedError) as denied:
        service.execute(actor(mfa_verified_at=NOW - 1_000_000), make_create_command(policy_id))
    assert denied.value.code == "admin_recent_mfa_required"

    with pytest.raises(AdminConflictError) as reserved:
        service.execute(actor(), make_create_command(policy_id, slug="admin"))
    assert reserved.value.code == "operator_slug_reserved"

    with pytest.raises(AdminNotFoundError) as withdrawn:
        service.execute(actor(), make_create_command(policy_id, release_id=WITHDRAWN_RELEASE_ID))
    assert withdrawn.value.code == "release_not_found"

    with pytest.raises(AdminConflictError) as stale_rev:
        service.execute(actor(), make_create_command(policy_id, expected_revision=99))
    assert stale_rev.value.code == "registry_revision_conflict"

    smaller = admission_commitment().model_copy(update={"warm_memory_bytes": 1})
    with pytest.raises(AdminConflictError) as mismatch:
        service.execute(actor(), make_create_command(policy_id, commitment=smaller))
    assert mismatch.value.code == "capacity_commitment_mismatch"

    env["clock"].value = NOW + 1_000_000
    with pytest.raises(AdminUnavailableError):
        service.execute(
            actor(mfa_verified_at=env["clock"].value - 1000), make_create_command(policy_id)
        )

    with env["engine"].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM main.operators")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM main.operations")).scalar_one() == 0
        gen = conn.execute(
            text("SELECT registry_generation FROM main.control_meta WHERE id=1")
        ).scalar_one()
        assert gen == 1


def test_set_based_list_pagination_filters_and_constant_query_budget(env):
    service: AdminControlService = env["service"]
    policy_id: str = env["policy_id"]

    for idx in range(1, SIX_OPERATORS + 1):
        env["clock"].value = NOW + idx * 10
        service.execute(
            actor(mfa_verified_at=env["clock"].value - 1000),
            make_create_command(
                policy_id,
                slug=f"site-{idx}",
                email=f"site{idx}@example.invalid",
                display_name=f"Site {idx}",
                expected_revision=idx,
                idempotency_key=f"create-site-{idx}",
            ),
        )

    queries_executed: list[str] = []

    def count_sql(_conn, _cursor, statement, *_args):
        if statement.strip().upper() != "BEGIN":
            queries_executed.append(statement)

    event.listen(env["engine"], "before_cursor_execute", count_sql)
    try:
        current_actor = actor(mfa_verified_at=env["clock"].value - 1000)
        page1 = service.list_operators(
            current_actor,
            ObservationQuery(deployment_id=DEPLOYMENT_ID, scope=DeploymentScope(), limit=PAGE_SIZE),
            AdminFilters(),
        )
        assert len(queries_executed) <= MAX_LIST_QUERIES
        assert page1.directory.data is not None
        assert page1.directory.data.matching_total == SIX_OPERATORS
        assert len(page1.directory.data.items) == PAGE_SIZE
        assert page1.directory.data.continuation is not None
        assert page1.directory.data.items[0].protection.state == "unavailable"
        assert page1.directory.data.items[0].access.state == "unavailable"

        queries_executed.clear()
        page2 = service.list_operators(
            current_actor,
            ObservationQuery(
                deployment_id=DEPLOYMENT_ID,
                scope=DeploymentScope(),
                limit=PAGE_SIZE,
                cursor=page1.directory.data.continuation,
            ),
            AdminFilters(),
        )
        assert len(queries_executed) <= MAX_LIST_QUERIES
        assert page2.directory.data is not None
        assert len(page2.directory.data.items) == PAGE_SIZE
        assert page2.directory.data.items[0].slug == "site-3"

        with pytest.raises(AdminConflictError) as exc:
            service.list_operators(
                current_actor,
                ObservationQuery(
                    deployment_id=DEPLOYMENT_ID,
                    scope=DeploymentScope(),
                    limit=PAGE_SIZE,
                    cursor=page1.directory.data.continuation,
                ),
                AdminFilters(search="site-1"),
            )
        assert exc.value.code == "cursor_context_changed"

        obs_page = service.observe(
            current_actor,
            ObservationQuery(
                deployment_id=DEPLOYMENT_ID, scope=DeploymentScope(), limit=OBSERVE_LIMIT
            ),
        )
        assert obs_page.matching_total == SIX_OPERATORS
        assert len(obs_page.items) == OBSERVE_LIMIT
    finally:
        event.remove(env["engine"], "before_cursor_execute", count_sql)


def test_reissue_invitation_delivery_and_detail_readiness_gates(env):
    service: AdminControlService = env["service"]
    policy_id: str = env["policy_id"]
    create_cmd = make_create_command(policy_id, slug="pine-crest", email="pine@example.invalid")
    service.execute(actor(), create_cmd)
    op_id = create_cmd.intent.payload.operator_id
    ws_id = create_cmd.intent.payload.workspace_id

    with env["engine"].connect() as conn:
        cd_id = conn.execute(
            text(
                "SELECT component_deployment_id FROM main.component_deployments "
                "WHERE operator_id = :id"
            ),
            {"id": op_id},
        ).scalar_one()

    detail_pending = service.detail_operator(actor(), op_id)
    assert detail_pending.readiness.data is not None
    assert detail_pending.readiness.data.state == "pending"
    invite_action = next(
        a for a in detail_pending.actions if a.action == UIAction.REISSUE_INVITATION
    )
    assert invite_action.enabled is False

    reissue_intent = CommandIntent[ReissueInvitation](
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=op_id, workspace_id=ws_id),
        kind="reissue_invitation",
        expected_revision=1,
        access_epoch=1,
        payload=ReissueInvitation(assignment_id=cd_id, verified_identity_ref="admin:mfa"),
    )
    reissue_cmd = AdminCommand(
        operation_id=str(uuid4()),
        idempotency_key="invite-pine-1",
        intent=reissue_intent,
        request_hash=semantic_hash(reissue_intent),
    )
    with pytest.raises(AdminConflictError) as exc:
        service.issue_invitation_with_token(actor(), reissue_cmd)
    assert exc.value.code == "operator_not_ready_for_invitation"

    with immediate_transaction(env["engine"]) as conn:
        conn.execute(
            text(
                "UPDATE main.component_deployments SET state='applied', "
                "observed_release_id=:rel, observation_ref='host-receipt:1', observed_at=:now "
                "WHERE component_deployment_id=:cd"
            ),
            {"rel": RELEASE_ID, "now": NOW, "cd": cd_id},
        )
        conn.execute(
            text("UPDATE main.operators SET setup_state='ready_for_claim' WHERE operator_id=:id"),
            {"id": op_id},
        )

    detail_ready = service.detail_operator(actor(), op_id)
    assert detail_ready.readiness.data is not None
    assert detail_ready.readiness.data.state == "unavailable"
    gates = {g.name: g.state for g in detail_ready.readiness.data.checks}
    assert gates == {
        "isolation": "passed",
        "schema": "passed",
        "routing": "passed",
        "binding": "passed",
        "protection": "unavailable",
    }

    issued = service.issue_invitation_with_token(actor(), reissue_cmd)
    assert issued.outcome.state == OperationState.SUCCEEDED
    assert issued.token is not None and issued.invitation_id is not None
    replayed = service.issue_invitation_with_token(actor(), reissue_cmd)
    assert replayed.outcome == issued.outcome
    assert replayed.token is None

    new_rev = service.mark_invitation_sent(
        actor(), operator_id=op_id, invitation_id=issued.invitation_id, expected_revision=1
    )
    assert new_rev == NEXT_INVITE_REV


def test_refresh_source_updates_projection_or_marks_unavailable(env):
    readings: list[SourceObservationReading | None] = [
        SourceObservationReading(
            effective_enabled=False,
            usage_bytes=SAMPLE_USAGE_BYTES,
            usable_bytes=50_000_000,
            source_revision=5,
            observed_at=NOW - 500,
        ),
        None,
    ]
    service = AdminControlService(
        env["engine"],
        clock=env["clock"],
        issuer=ISSUER,
        application_directory=APPLICATION,
        source_inspector=lambda _op, _ws, _ep: readings.pop(0),
    )
    create_cmd = make_create_command(
        env["policy_id"], slug="birch-way", email="birch@example.invalid"
    )
    service.execute(actor(), create_cmd)
    op_id = create_cmd.intent.payload.operator_id
    ws_id = create_cmd.intent.payload.workspace_id
    with env["engine"].connect() as conn:
        cd_id = conn.execute(
            text(
                "SELECT component_deployment_id FROM main.component_deployments "
                "WHERE operator_id = :id"
            ),
            {"id": op_id},
        ).scalar_one()

    intent = CommandIntent[RefreshSource](
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=op_id, workspace_id=ws_id),
        kind="refresh_source",
        expected_revision=1,
        access_epoch=1,
        payload=RefreshSource(assignment_id=cd_id),
    )
    cmd1 = AdminCommand(
        operation_id=str(uuid4()),
        idempotency_key="refresh-birch-1",
        intent=intent,
        request_hash=semantic_hash(intent),
    )
    res1 = service.execute(actor(), cmd1)
    assert res1.state == OperationState.SUCCEEDED
    detail1 = service.detail_operator(actor(), op_id)
    assert detail1.operator.access.state == "ready"
    assert detail1.operator.access.data is not None
    assert detail1.operator.access.data.effective_enabled is False
    assert detail1.operator.usage.data is not None
    assert detail1.operator.usage.data.used_bytes == SAMPLE_USAGE_BYTES
    assert detail1.refresh_operation == res1

    cmd2 = AdminCommand(
        operation_id=str(uuid4()),
        idempotency_key="refresh-birch-2",
        intent=intent,
        request_hash=semantic_hash(intent),
    )
    res2 = service.execute(actor(), cmd2)
    assert res2.state == OperationState.NEEDS_ATTENTION
    assert res2.error_code == "source_unreachable"
    detail2 = service.detail_operator(actor(), op_id)
    assert detail2.operator.access.state == "unavailable"
    assert detail2.operator.access.data is None
    assert detail2.operator.usage.state == "unavailable"
    assert detail2.operator.usage.data is None
    assert detail2.operator.usage.freshness is not None
    assert detail2.operator.usage.freshness.state == FreshnessState.UNAVAILABLE
