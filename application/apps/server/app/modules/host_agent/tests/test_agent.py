"""Real inventory resources plus explicit synthetic admission/effects; no native proof."""

from dataclasses import dataclass
from pathlib import Path
import json
import os
import socket
import sqlite3
import struct
from tempfile import TemporaryDirectory
from threading import Thread
from uuid import uuid5, NAMESPACE_URL

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, event

from app.modules.host_agent.application.build_inputs import PrincipalRange
from app.modules.host_agent.application.contracts import (
    PrepareResources,
    StartContainer,
    StopContainer,
)
from app.modules.host_agent.application.dispatch import (
    AdmittedEffect,
    EffectObservation,
    HostAgentDenied,
    HostAgentUnavailable,
    HostEffect,
    IngressPolicy,
    ResourcePlan,
    ResourceInputs,
    TreeLimits,
    UnavailableEffects,
)
from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.modules.host_agent.application.service import HostAgent
from app.modules.host_agent.infrastructure.inventory import Inventory
from app.modules.host_agent.infrastructure.schema_store import HostMetadata, bind_host
from app.modules.host_agent.infrastructure.unix_transport import (
    MAX_FRAME,
    handle_connection,
    peer_uid,
    private_listener,
)
from app.platform.hosted_contracts.operations import OperationReference, SemanticConflict
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore

APPLICATION = Path(__file__).resolve().parents[6]
ID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
BINDING = "00000000-0000-4000-8000-000000000003"


def uid(value):
    return str(uuid5(NAMESPACE_URL, value))


def resource_plan():
    limits = TreeLimits(byte_ceiling=1000000, inode_ceiling=100)
    return ResourcePlan(
        image_id=ID,
        release_id=OTHER,
        image_digest="b" * 64,
        capacity_profile_ref="synthetic-capacity-v1",
        workspace=limits,
        control=limits,
        scratch=limits,
    )


def origin(operator):
    return "https://synthetic-" + operator[-4:] + ".example.invalid"


def prepare(*, operator=ID, binding=BINDING, epoch=1):
    parent = OperationReference(
        deployment_id=ID,
        scope=WorkspaceScope(operator_id=operator, workspace_id=uid(operator)),
        kind="provision",
        operation_id=uid("provision:" + operator),
        idempotency_key="synthetic-parent:" + operator,
        request_hash="a" * 64,
    )
    identity = EffectIdentity(
        parent=parent,
        binding_id=binding,
        resource_generation=1,
        kind="prepare_resources",
        slot="prepare",
    )
    return HostEffect(
        effect=identity,
        access_epoch=epoch,
        expected_revision=1,
        inputs_hash=semantic_hash(
            ResourceInputs(plan=resource_plan(), public_origin=origin(operator))
        ),
        payload=PrepareResources(
            binding_id=binding,
            image_id=ID,
            release_id=OTHER,
            admission_commitment_id=OTHER,
            capacity_profile_ref="synthetic-capacity-v1",
        ),
    )


class Admission:
    def __init__(self):
        self.grants = {}
        self.calls = []

    def add(self, command, **changes):
        fields = dict(command=command, admitted_at=1, expires_at=1000)
        if command.effect.kind == "prepare_resources":
            limits = TreeLimits(byte_ceiling=1000000, inode_ceiling=100)
            fields.update(
                plan=ResourcePlan(
                    image_id=ID,
                    release_id=OTHER,
                    image_digest="b" * 64,
                    capacity_profile_ref="synthetic-capacity-v1",
                    workspace=limits,
                    control=limits,
                    scratch=limits,
                ),
                public_origin="https://synthetic-"
                + command.effect.parent.scope.operator_id[-4:]
                + ".example.invalid",
            )
        self.grants[semantic_hash(command)] = AdmittedEffect(**(fields | changes))
        return command

    def resolve(self, command):
        self.calls.append(command)
        if semantic_hash(command) not in self.grants:
            raise HostAgentDenied()
        return self.grants[semantic_hash(command)]


class Driver:
    def __init__(self, path):
        self.path = path
        self.applied = []
        self.inspected = []
        self.mode = "applied"
        self.callback = None

    def observation(self, command):
        state = {
            "prepare_resources": "prepared",
            "initialize_container": "stopped",
            "repair_runtime": "stopped",
            "start_container": "running",
            "stop_container": "stopped",
            "retire_resources": "retired",
        }
        return EffectObservation(
            request_hash=semantic_hash(command),
            binding_id=command.effect.binding_id,
            resource_generation=command.effect.resource_generation,
            status=self.mode,
            evidence_ref="synthetic-proof" if self.mode != "unknown" else None,
            resource_state=state.get(command.effect.kind),
            ingress_state=command.payload.desired_state
            if command.effect.kind == "apply_ingress_policy"
            else None,
            ingress_revision=command.payload.expected_ingress_revision + 2
            if command.effect.kind == "apply_ingress_policy"
            else None,
            container_ref="synthetic-container:" + command.effect.binding_id
            if command.effect.kind in {"initialize_container", "repair_runtime"}
            else None,
            image_digest="b" * 64
            if command.effect.kind in {"initialize_container", "repair_runtime"}
            else None,
        )

    def apply(self, command, allocation):
        # Another writer can begin: reserve/receipt transaction is already committed.
        with sqlite3.connect(self.path, timeout=0) as connection:
            connection.execute("BEGIN IMMEDIATE")
            assert connection.execute("SELECT count(*) FROM host_receipts").fetchone()[0] > 0
        self.applied.append((command, allocation))
        if self.callback:
            self.callback()
        return self.observation(command)

    def inspect(self, command, allocation):
        self.inspected.append((command, allocation))
        return self.observation(command)


@dataclass
class Setup:
    path: Path
    inventory: Inventory
    admission: Admission
    driver: Driver
    agent: HostAgent


@pytest.fixture
def setup(tmp_path):
    root = tmp_path.resolve() / "protected"
    root.mkdir(mode=0o700)
    path = root / "inventory.sqlite"
    initialize_store(HostedStore.HOST_INVENTORY, path, application_directory=APPLICATION)
    identity = HostMetadata(
        host_id=OTHER,
        deployment_id=ID,
        filesystem_identity="synthetic-ext4",
        agent_contract_version="host-agent-v1",
        created_at=1,
    )
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        bind_host(connection, identity, application_directory=APPLICATION)
        connection.commit()
    engine.dispose()
    inventory = Inventory(
        path,
        application_directory=APPLICATION,
        identity=identity,
        uids=PrincipalRange(first=100000, last=100100, reserved=(100000,)),
        gids=PrincipalRange(first=100000, last=100100, reserved=(100000,)),
        projects=PrincipalRange(first=1, last=100),
        public_domain="example.invalid",
        system_ids=lambda: ({100001}, {100001}),
    )
    admission = Admission()
    driver = Driver(path)
    return Setup(
        path,
        inventory,
        admission,
        driver,
        HostAgent(inventory, admission, driver, clock=lambda: 10),
    )


def rows(setup, table):
    with setup.inventory.transaction(write=False) as connection:
        return list(connection.exec_driver_sql(f"SELECT * FROM {table}").mappings())


def follow(setup, payload, *, epoch=1, slot=None):
    binding = rows(setup, "resource_bindings")[0]
    previous = prepare()
    effect = EffectIdentity(
        parent=previous.effect.parent,
        binding_id=BINDING,
        resource_generation=1,
        kind=payload.action,
        slot=slot or payload.action,
    )
    command = HostEffect(
        effect=effect, access_epoch=epoch, expected_revision=binding["revision"], payload=payload
    )
    return setup.admission.add(command)


def ready(setup):
    command = setup.admission.add(prepare())
    return setup.agent.execute(command)


def test_reservation_precedes_effect_and_exact_retry_retains_identity(setup):
    command = setup.admission.add(prepare())
    first = setup.agent.execute(command)
    retry = setup.agent.execute(command)
    assert first == retry
    assert first.operation_id == command.effect.child_id()
    assert first.parent_operation_id == command.effect.parent.operation_id
    assert first.state == "applied"
    assert len(setup.driver.applied) == 1
    principal = rows(setup, "operator_principals")[0]
    assert principal["host_uid"] == 100002
    assert principal["host_gid"] == 100002
    assert {r["project_id"] for r in rows(setup, "project_assignments")} == {1, 2, 3}
    assert rows(setup, "ingress_bindings")[0]["desired_state"] == "held"
    assert setup.agent.original(command) == first


def test_two_workspaces_receive_distinct_principals_and_projects(setup):
    ready(setup)
    setup.agent.execute(setup.admission.add(prepare(operator=OTHER, binding=uid("other-binding"))))
    assert len({r["host_uid"] for r in rows(setup, "operator_principals")}) == 2
    assert len({r["project_id"] for r in rows(setup, "project_assignments")}) == 6


def test_changed_semantics_under_same_child_key_conflicts(setup):
    ready(setup)
    original = prepare()
    changed = HostEffect(**(original.model_dump() | {"access_epoch": 2}))
    setup.admission.add(changed)
    with pytest.raises(SemanticConflict):
        setup.agent.execute(changed)
    assert len(setup.driver.applied) == 1


def test_unknown_admission_and_changed_grant_do_not_allocate(setup):
    command = prepare()
    with pytest.raises(HostAgentDenied):
        setup.agent.execute(command)
    setup.admission.add(command)
    setup.admission.grants[semantic_hash(command)] = AdmittedEffect(
        command=HostEffect(**(command.model_dump() | {"access_epoch": 2})),
        admitted_at=1,
        expires_at=1000,
        plan=setup.admission.grants[semantic_hash(command)].plan,
        public_origin=origin(ID),
    )
    with pytest.raises(SemanticConflict):
        setup.agent.execute(command)
    assert rows(setup, "resource_bindings") == []


@pytest.mark.parametrize("times", [(11, 100), (1, 10)])
def test_admission_freshness_fails_before_reservation(setup, times):
    command = prepare()
    setup.admission.add(command, admitted_at=times[0], expires_at=times[1])
    with pytest.raises(HostAgentDenied):
        setup.agent.execute(command)
    assert rows(setup, "host_receipts") == []


def test_provider_failure_is_unknown_and_retry_inspects_only(setup):
    command = setup.admission.add(prepare())
    setup.driver.callback = lambda: (_ for _ in ()).throw(
        OSError("provider outage /private/secret")
    )
    first = setup.agent.execute(command)
    assert first.state == "unknown"
    setup.driver.callback = None
    retry = setup.agent.execute(command)
    assert retry.state == "applied"
    assert len(setup.driver.applied) == 1
    assert len(setup.driver.inspected) == 1
    assert "secret" not in rows(setup, "host_receipts")[0]["observed_json"]


def test_crash_after_reservation_never_reapplies_on_restart(setup):
    class Crash(BaseException):
        pass

    command = setup.admission.add(prepare())
    setup.driver.callback = lambda: (_ for _ in ()).throw(Crash())
    with pytest.raises(Crash):
        setup.agent.execute(command)
    assert rows(setup, "host_receipts")[0]["state"] == "pending"
    setup.driver.callback = None
    restarted = HostAgent(setup.inventory, setup.admission, setup.driver, clock=lambda: 20)
    assert restarted.execute(command).state == "applied"
    assert len(setup.driver.applied) == 1
    assert len(setup.driver.inspected) == 1


def test_failed_pending_receipt_rolls_back_principal_projects_binding_and_ingress(setup):

    def deny_insert(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO host_receipts"):
            raise RuntimeError("injected receipt failure")

    event.listen(Engine, "before_cursor_execute", deny_insert)
    try:
        with pytest.raises(RuntimeError, match="injected receipt failure"):
            setup.agent.execute(setup.admission.add(prepare()))
    finally:
        event.remove(Engine, "before_cursor_execute", deny_insert)
    for table in (
        "operator_principals",
        "project_assignments",
        "resource_bindings",
        "ingress_bindings",
        "host_receipts",
    ):
        assert rows(setup, table) == []
    assert setup.driver.applied == []


def test_finish_failure_preserves_pending_identity_for_inspection(setup, monkeypatch):
    command = setup.admission.add(prepare())
    original = setup.inventory.finish

    def fail(*args):
        raise RuntimeError("finish commit failed")

    monkeypatch.setattr(setup.inventory, "finish", fail)
    with pytest.raises(RuntimeError):
        setup.agent.execute(command)
    assert rows(setup, "host_receipts")[0]["state"] == "pending"
    monkeypatch.setattr(setup.inventory, "finish", original)
    assert setup.agent.execute(command).state == "applied"
    assert len(setup.driver.applied) == 1


def test_newer_deny_fences_unseen_start_and_historical_unknown(setup):
    ready(setup)
    start = follow(setup, StartContainer(binding_id=BINDING))
    setup.driver.mode = "unknown"
    assert setup.agent.execute(start).state == "unknown"
    block = follow(
        setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    setup.driver.mode = "applied"
    assert setup.agent.execute(block).state == "applied"
    denied = rows(setup, "ingress_bindings")[0]
    assert denied["access_epoch"] == 2
    assert denied["verified_state"] == "blocked"
    assert denied["verified_revision"] == denied["revision"]
    before = len(setup.driver.inspected)
    assert setup.agent.execute(start).state == "unknown"
    assert len(setup.driver.inspected) == before
    unseen = follow(setup, StartContainer(binding_id=BINDING), slot="unseen_start")
    with pytest.raises(HostAgentDenied):
        setup.agent.execute(unseen)
    current = follow(setup, StartContainer(binding_id=BINDING), epoch=2, slot="current_but_blocked")
    with pytest.raises(HostAgentDenied):
        setup.agent.execute(current)
    stop = follow(setup, StopContainer(binding_id=BINDING), epoch=2)
    assert setup.agent.execute(stop).state == "applied"


def test_enable_stays_unavailable_even_with_proof_shaped_input(setup):
    ready(setup)
    command = follow(
        setup,
        IngressPolicy(
            desired_state="eligible",
            expected_ingress_revision=1,
            source_identity_proof_ref="not-live-proof",
            resource_readiness_proof_ref="not-live-proof",
        ),
    )
    with pytest.raises(HostAgentUnavailable):
        setup.agent.execute(command)
    assert len(setup.driver.applied) == 1


def test_exclusive_lock_prevents_competing_effects(setup):
    with setup.inventory.exclusive():
        with pytest.raises(HostAgentUnavailable):
            setup.agent.execute(setup.admission.add(prepare()))
    assert rows(setup, "host_receipts") == []


def test_missing_or_replaced_inventory_is_never_initialized_or_adopted(setup):
    backup = setup.path.with_suffix(".retained")
    setup.path.rename(backup)
    with pytest.raises(FileNotFoundError):
        setup.agent.execute(setup.admission.add(prepare()))
    assert not setup.path.exists()
    setup.path.touch(mode=0o600)
    with pytest.raises(HostAgentDenied):
        setup.agent.execute(prepare())


def test_wrong_host_binding_rejected(setup):
    with pytest.raises(HostAgentDenied):
        Inventory(
            setup.path,
            application_directory=APPLICATION,
            identity=setup.inventory.identity.model_copy(update={"host_id": ID}),
            uids=setup.inventory.uids,
            gids=setup.inventory.gids,
            projects=setup.inventory.projects,
            public_domain="example.invalid",
            system_ids=setup.inventory.system_ids,
        )


def wire(setup, raw, *, allowed_uid=None):
    client, server = socket.socketpair()
    errors = []

    def run():
        try:
            with server:
                handle_connection(
                    server,
                    setup.agent,
                    allowed_uid=os.getuid() if allowed_uid is None else allowed_uid,
                )
        except Exception as error:
            errors.append(error)

    thread = Thread(target=run)
    thread.start()
    with client:
        # Wrong peers are rejected before the server reads ANY body. Sending after
        # that rejection can legitimately EPIPE depending on thread scheduling.
        if allowed_uid is None or allowed_uid == os.getuid():
            client.sendall(struct.pack("!I", len(raw)) + raw)
        with client.makefile("rb") as response:
            size = struct.unpack("!I", response.read(4))[0]
            result = json.loads(response.read(size))
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert errors == []
    return result


def test_unix_kernel_peer_and_authenticated_command_round_trip(setup):
    command = setup.admission.add(prepare())
    raw = json.dumps({"method": "execute", "command": command.model_dump()}).encode()
    result = wire(setup, raw)
    assert result["result"]["operation_id"] == command.effect.child_id()
    assert "host_uid" not in json.dumps(result)


def test_wrong_unix_peer_never_resolves_admission(setup):
    result = wire(setup, b"not json", allowed_uid=os.getuid() + 1)
    assert result == {"error": {"code": "host_agent_denied"}}
    assert setup.admission.calls == []


@pytest.mark.parametrize(
    "raw",
    [
        b'{"method":"execute","method":"original"}',
        b'{"method":"shell","argv":"whoami"}',
        b"[]",
        b"not-json",
    ],
)
def test_malformed_or_generic_command_is_denied_before_admission(setup, raw):
    assert wire(setup, raw) == {"error": {"code": "host_agent_denied"}}
    assert setup.admission.calls == []


def test_private_listener_never_takes_over_existing_path(setup):
    with TemporaryDirectory(dir=Path("/tmp").resolve(), prefix="epm-host-") as directory:
        os.chown(directory, -1, os.getgid())
        path = Path(directory) / "agent.sock"
        with private_listener(path, client_gid=os.getgid()) as listener:
            assert listener.family == socket.AF_UNIX
            with pytest.raises(OSError):
                with private_listener(path, client_gid=os.getgid()):
                    pass
            assert path.exists()
        assert not path.exists()


def test_resource_inputs_are_pinned_and_preserved_not_reconstructed(setup):
    command = setup.admission.add(prepare())
    grant = setup.admission.grants[semantic_hash(command)]
    changed = grant.plan.model_copy(update={"image_digest": "c" * 64})
    with pytest.raises(ValidationError):
        AdmittedEffect(
            command=command,
            admitted_at=1,
            expires_at=1000,
            plan=changed,
            public_origin=grant.public_origin,
        )
    setup.agent.execute(command)
    stored = rows(setup, "host_receipts")[0]
    assert json.loads(stored["request_json"])["inputs"]["plan"]["image_digest"] == "b" * 64
    assert setup.driver.applied[0][1].inputs.plan == grant.plan


def test_uid_project_exhaustion_rolls_back_all_reservations(setup):
    setup.inventory.projects = PrincipalRange(first=1, last=2)
    with pytest.raises(HostAgentUnavailable):
        setup.agent.execute(setup.admission.add(prepare()))
    for name in (
        "operator_principals",
        "resource_bindings",
        "project_assignments",
        "host_receipts",
        "ingress_bindings",
    ):
        assert rows(setup, name) == []
    assert setup.driver.applied == []


def test_collision_probe_runs_outside_sqlite_writer(setup):
    def probe():
        with sqlite3.connect(setup.path, timeout=0) as connection:
            connection.execute("BEGIN IMMEDIATE")
        return {100001}, {100001}

    setup.inventory.system_ids = probe
    ready(setup)


def test_collision_probe_failure_is_closed_but_retained_receipts_remain_readable(setup):
    command = setup.admission.add(prepare())
    first = setup.agent.execute(command)

    def failure():
        raise HostAgentUnavailable()

    setup.inventory.system_ids = failure
    assert setup.agent.execute(command) == first
    with pytest.raises(HostAgentUnavailable):
        setup.agent.execute(
            setup.admission.add(prepare(operator=OTHER, binding=uid("new-binding")))
        )
    assert len(rows(setup, "resource_bindings")) == 1


def test_unavailable_driver_records_unknown_without_fake_success(setup):
    agent = HostAgent(setup.inventory, setup.admission, UnavailableEffects(), clock=lambda: 10)
    command = setup.admission.add(prepare())
    assert agent.execute(command).state == "unknown"
    assert agent.execute(command).state == "unknown"
    assert rows(setup, "resource_bindings")[0]["state"] == "allocated"


def test_mismatched_driver_observation_never_marks_success(setup):
    command = setup.admission.add(prepare())
    setup.driver.observation = lambda requested: EffectObservation(
        request_hash="c" * 64,
        binding_id=BINDING,
        resource_generation=1,
        status="applied",
        evidence_ref="synthetic-wrong-proof",
        resource_state="prepared",
    )
    assert setup.agent.execute(command).state == "unknown"
    assert rows(setup, "resource_bindings")[0]["state"] == "allocated"


def test_resource_reservation_commit_failure_prevents_effects(setup):
    def fail_commit(connection):
        raise RuntimeError("reservation commit fault")

    event.listen(Engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="reservation commit fault"):
            setup.agent.execute(setup.admission.add(prepare()))
    finally:
        event.remove(Engine, "commit", fail_commit)
    assert rows(setup, "host_receipts") == []
    assert rows(setup, "resource_bindings") == []
    assert setup.driver.applied == []


def test_new_deny_commits_before_gateway_effect_even_when_gateway_fails(setup):
    ready(setup)
    command = follow(
        setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )

    def verify_then_fail():
        current = rows(setup, "ingress_bindings")[0]
        assert current["access_epoch"] == 2
        assert current["desired_state"] == "blocked"
        raise OSError("gateway unavailable")

    setup.driver.callback = verify_then_fail
    result = setup.agent.execute(command)
    assert result.state == "unknown"
    assert rows(setup, "ingress_bindings")[0]["verified_state"] == "unknown"
    setup.driver.callback = None
    assert setup.agent.execute(command).state == "applied"


def test_stage_restore_rejects_before_admission(setup):
    from app.modules.host_agent.application.contracts import StageRestore

    previous = prepare()
    effect = EffectIdentity(
        parent=previous.effect.parent,
        binding_id=BINDING,
        resource_generation=1,
        kind="stage_restore",
        slot="restore",
    )
    command = HostEffect(
        effect=effect,
        access_epoch=1,
        expected_revision=1,
        payload=StageRestore(
            binding_id=BINDING, restore_operation_id=OTHER, restore_authorization_ref="synthetic"
        ),
    )
    with pytest.raises(HostAgentUnavailable):
        setup.agent.execute(command)
    assert setup.admission.calls == []
    assert rows(setup, "host_receipts") == []


def test_effect_binding_and_arbitrary_targets_reject_before_dispatch():
    command = prepare()
    fields = command.model_dump()
    with pytest.raises(ValidationError):
        HostEffect(**(fields | {"path": "/private/secret"}))
    with pytest.raises(ValidationError):
        HostEffect(**(fields | {"payload": StopContainer(binding_id=OTHER)}))
    with pytest.raises(ValidationError):
        HostEffect(**(fields | {"inputs_hash": None}))


def test_native_peer_credentials_are_read_from_socket():
    first, second = socket.socketpair()
    with first, second:
        assert peer_uid(first) == os.getuid()


def test_oversized_transport_frame_is_rejected_without_reading_body(setup):
    client, server = socket.socketpair()
    thread = Thread(target=lambda: handle_connection(server, setup.agent, allowed_uid=os.getuid()))
    thread.start()
    try:
        client.sendall(struct.pack("!I", MAX_FRAME + 1))
        header = client.recv(4)
        result = json.loads(client.recv(struct.unpack("!I", header)[0]))
        assert result == {"error": {"code": "host_agent_denied"}}
        assert setup.admission.calls == []
    finally:
        thread.join(timeout=10)
        client.close()
        server.close()


def test_verified_state_commit_failure_rolls_back_receipt_and_projection(setup):
    command = setup.admission.add(prepare())

    def fail_binding_update(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE resource_bindings"):
            raise RuntimeError("observed state transaction fault")

    event.listen(Engine, "before_cursor_execute", fail_binding_update)
    try:
        with pytest.raises(RuntimeError, match="observed state transaction fault"):
            setup.agent.execute(command)
    finally:
        event.remove(Engine, "before_cursor_execute", fail_binding_update)
    assert rows(setup, "host_receipts")[0]["state"] == "pending"
    assert rows(setup, "resource_bindings")[0]["state"] == "allocated"
    assert setup.agent.execute(command).state == "applied"
    assert len(setup.driver.applied) == 1


def test_pending_resource_effect_blocks_new_work_but_allows_containment(setup):
    setup.driver.mode = "unknown"
    ready(setup)
    start = follow(setup, StartContainer(binding_id=BINDING))
    with pytest.raises(HostAgentDenied):
        setup.agent.execute(start)
    stop = follow(setup, StopContainer(binding_id=BINDING))
    setup.driver.mode = "applied"
    assert setup.agent.execute(stop).state == "applied"


def test_foreign_workspace_and_generation_are_denied_even_with_admission(setup):
    ready(setup)
    command = follow(setup, StopContainer(binding_id=BINDING))
    for changes in [
        {"resource_generation": 2},
        {
            "parent": command.effect.parent.model_copy(
                update={"scope": WorkspaceScope(operator_id=OTHER, workspace_id=uid(OTHER))}
            )
        },
    ]:
        changed = HostEffect(
            **(command.model_dump() | {"effect": command.effect.model_copy(update=changes)})
        )
        setup.admission.add(changed)
        with pytest.raises(HostAgentDenied):
            setup.agent.execute(changed)
    assert len(setup.driver.applied) == 1


def test_retired_mapping_and_project_identities_are_retained(setup):
    from app.modules.host_agent.application.contracts import RetireResources

    ready(setup)
    block = follow(
        setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    setup.agent.execute(block)
    setup.agent.execute(follow(setup, StopContainer(binding_id=BINDING), epoch=2))
    retire = follow(
        setup,
        RetireResources(
            binding_ids=(BINDING,), cleanup_proof_ref="synthetic-cleanup", confirmation_id=ID
        ),
        epoch=2,
    )
    assert setup.agent.execute(retire).state == "applied"
    assert rows(setup, "resource_bindings")[0]["state"] == "retired"
    assert len(rows(setup, "project_assignments")) == 3
    assert len(rows(setup, "operator_principals")) == 1
    assert setup.agent.execute(retire).state == "applied"


def test_limits_apply_only_after_verification_and_pin_original_inputs(setup):
    from app.modules.host_agent.application.contracts import ApplyLimits

    ready(setup)
    previous = prepare()
    effect = EffectIdentity(
        parent=previous.effect.parent,
        binding_id=BINDING,
        resource_generation=1,
        kind="apply_limits",
        slot="limits",
    )
    plan = resource_plan().model_copy(
        update={
            "limit_profile_id": ID,
            "workspace": TreeLimits(byte_ceiling=2000000, inode_ceiling=200),
        }
    )
    command = HostEffect(
        effect=effect,
        access_epoch=1,
        expected_revision=rows(setup, "resource_bindings")[0]["revision"],
        inputs_hash=semantic_hash(ResourceInputs(plan=plan)),
        payload=ApplyLimits(binding_id=BINDING, qualified_limit_profile_id=ID),
    )
    setup.admission.add(command, plan=plan)
    setup.driver.mode = "unknown"
    assert setup.agent.execute(command).state == "unknown"
    assert rows(setup, "resource_bindings")[0]["workspace_byte_ceiling"] == 1000000
    setup.driver.mode = "applied"
    assert setup.agent.execute(command).state == "applied"
    assert rows(setup, "resource_bindings")[0]["workspace_byte_ceiling"] == 2000000
    assert len(setup.driver.applied) == 2


def initialized_runtime(setup):
    from app.modules.host_agent.application.contracts import InitializeContainer

    ready(setup)
    previous = prepare()
    effect = EffectIdentity(
        parent=previous.effect.parent,
        binding_id=BINDING,
        resource_generation=1,
        kind="initialize_container",
        slot="initialize",
    )
    plan = resource_plan()
    command = HostEffect(
        effect=effect,
        access_epoch=1,
        expected_revision=rows(setup, "resource_bindings")[0]["revision"],
        inputs_hash=semantic_hash(ResourceInputs(plan=plan)),
        payload=InitializeContainer(binding_id=BINDING, image_id=ID, release_id=OTHER),
    )
    setup.admission.add(command, plan=plan)
    assert setup.agent.execute(command).state == "applied"
    return command


def test_prepared_runtime_initialization_pins_image_without_business_init(setup):
    initialized_runtime(setup)
    assert rows(setup, "resource_bindings")[0]["state"] == "stopped"
    assert rows(setup, "resource_bindings")[0]["container_ref"] == "synthetic-container:" + BINDING
    assert len(rows(setup, "operator_principals")) == 1
    assert len(rows(setup, "project_assignments")) == 3


def test_inventory_snapshot_preserves_original_receipt_and_allocations(setup):
    ready(setup)
    snapshot = setup.path.with_suffix(".snapshot")
    with sqlite3.connect(setup.path) as source, sqlite3.connect(snapshot) as target:
        source.backup(target)
    snapshot.chmod(0o600)
    restored = Inventory(
        snapshot,
        application_directory=APPLICATION,
        identity=setup.inventory.identity,
        uids=setup.inventory.uids,
        gids=setup.inventory.gids,
        projects=setup.inventory.projects,
        public_domain="example.invalid",
        system_ids=setup.inventory.system_ids,
    )
    with restored.transaction(write=False) as connection:
        assert restored.retained(prepare())[0].state == "applied"
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM project_assignments").scalar_one() == 3
        )


def test_original_result_lookup_uses_indexed_bounded_target_queries(setup):
    command = setup.admission.add(prepare())
    first = setup.agent.execute(command)

    def query_count():
        statements = []

        def capture(connection, cursor, statement, *args):
            if str(connection.engine.url) == "sqlite://":
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", capture)
        try:
            assert setup.agent.original(command) == first
        finally:
            event.remove(Engine, "before_cursor_execute", capture)
        return len(statements)

    before = query_count()
    setup.agent.execute(setup.admission.add(prepare(operator=OTHER, binding=uid("another"))))
    assert query_count() == before
    with setup.inventory.transaction(write=False) as connection:
        plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT * FROM host_receipts WHERE kind='prepare_resources' AND idempotency_key='key'"
        ).all()
        assert any("INDEX" in row[3] for row in plan)


def test_quota_targets_use_inventory_ids_and_protected_roots_without_native_effects(setup):
    from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets

    ready(setup)
    allocation = setup.driver.applied[0][1]
    protected = QuotaTargets(
        mount=Path("/var/lib/epm"),
        filesystem_identity="synthetic-ext4",
        filesystem_uuid=ID,
        workspace_root=Path("/var/lib/epm/workspace"),
        control_root=Path("/var/lib/epm/control"),
        scratch_root=Path("/var/lib/epm/scratch"),
    )
    targets = protected.bindings(allocation)
    assert tuple(target.project_id for target in targets) == (1, 2, 3)
    assert all(
        target.uid == allocation.host_uid and target.directory.name == BINDING for target in targets
    )
    with pytest.raises(HostAgentDenied):
        protected.bindings(
            allocation.model_copy(update={"filesystem_identity": "other-filesystem"})
        )


def test_quota_target_roots_cannot_overlap_or_escape():
    from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets

    with pytest.raises(HostAgentDenied):
        QuotaTargets(
            mount=Path("/var/lib/epm"),
            filesystem_identity="synthetic",
            filesystem_uuid=ID,
            workspace_root=Path("/var/lib/epm/workspace"),
            control_root=Path("/var/lib/epm/workspace/control"),
            scratch_root=Path("/tmp"),
        )


def test_inet_peer_cannot_use_unix_control_boundary():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        with pytest.raises(HostAgentDenied):
            peer_uid(connection)


def test_public_process_cannot_supply_authority_in_json(setup):
    command = setup.admission.add(prepare())
    payload = {
        "method": "execute",
        "command": command.model_dump(),
        "allowed_uid": os.getuid(),
        "actor": "admin",
    }
    assert wire(setup, json.dumps(payload).encode()) == {"error": {"code": "host_agent_denied"}}
    assert setup.admission.calls == []


def test_wrong_wire_version_is_rejected_before_admission(setup):
    command = setup.admission.add(prepare())
    payload = {"version": 2, "method": "execute", "command": command.model_dump()}
    assert wire(setup, json.dumps(payload).encode()) == {"error": {"code": "host_agent_denied"}}
    assert setup.admission.calls == []


def test_admission_expiring_during_reservation_cannot_dispatch(setup):
    ticks = iter((10, 10, 10, 1000, 1000))
    agent = HostAgent(setup.inventory, setup.admission, setup.driver, clock=lambda: next(ticks))
    result = agent.execute(setup.admission.add(prepare()))
    assert result.state == "unknown"
    assert setup.driver.applied == []
    assert rows(setup, "host_receipts")[0]["state"] == "unknown"


def test_confirmed_rejection_is_terminal_without_marking_resources_ready(setup):
    command = setup.admission.add(prepare())
    setup.driver.mode = "rejected"
    result = setup.agent.execute(command)
    assert result.state == "rejected"
    setup.driver.mode = "applied"
    assert setup.agent.execute(command) == result
    assert rows(setup, "resource_bindings")[0]["state"] == "allocated"
    assert len(setup.driver.applied) == 1


def test_duplicate_native_project_mapping_cannot_reach_quota_primitive(setup):
    from app.modules.host_agent.application.dispatch import Allocation

    ready(setup)
    allocation = setup.driver.applied[0][1]
    with pytest.raises(ValidationError):
        Allocation(**(allocation.model_dump() | {"control_project": allocation.workspace_project}))


@pytest.mark.parametrize("wrong_agent", [False, True])
def test_restricted_client_authenticates_agent_before_sending_intent(setup, wrong_agent):
    from app.modules.host_agent.infrastructure.unix_transport import Call, invoke

    command = setup.admission.add(prepare())
    with TemporaryDirectory(dir=Path("/tmp").resolve(), prefix="epm-client-") as directory:
        os.chown(directory, -1, os.getgid())
        path = Path(directory) / "agent.sock"
        with private_listener(path, client_gid=os.getgid()) as listener:
            listener.settimeout(5)

            def serve():
                connection, _ = listener.accept()
                with connection:
                    try:
                        handle_connection(connection, setup.agent, allowed_uid=os.getuid())
                    except OSError:
                        pass  # A client that rejects the agent closes before any call bytes.

            thread = Thread(target=serve)
            thread.start()
            try:
                if wrong_agent:
                    with pytest.raises(HostAgentDenied):
                        invoke(
                            path,
                            Call(method="execute", command=command),
                            expected_agent_uid=os.getuid() + 1,
                        )
                    assert setup.admission.calls == []
                else:
                    assert (
                        invoke(
                            path,
                            Call(method="execute", command=command),
                            expected_agent_uid=os.getuid(),
                        ).state
                        == "applied"
                    )
            finally:
                thread.join(timeout=10)
                assert not thread.is_alive()


def test_restricted_client_lost_reply_is_unavailable_not_a_new_attempt(setup):
    from app.modules.host_agent.infrastructure.unix_transport import Call, invoke

    command = setup.admission.add(prepare())
    with TemporaryDirectory(dir=Path("/tmp").resolve(), prefix="epm-lost-") as directory:
        os.chown(directory, -1, os.getgid())
        path = Path(directory) / "agent.sock"
        with private_listener(path, client_gid=os.getgid()) as listener:

            def lose_reply():
                connection, _ = listener.accept()
                with connection:
                    connection.recv(MAX_FRAME)

            thread = Thread(target=lose_reply)
            thread.start()
            try:
                with pytest.raises(HostAgentUnavailable):
                    invoke(
                        path,
                        Call(method="execute", command=command),
                        expected_agent_uid=os.getuid(),
                    )
                assert setup.admission.calls == []
            finally:
                thread.join(timeout=10)
                assert not thread.is_alive()


def test_supervisor_attention_keeps_original_receipt_and_increments_binding_revision(setup):
    initialized_runtime(setup)
    command = follow(setup, StartContainer(binding_id=BINDING))
    assert setup.agent.execute(command).state == "applied"
    before = setup.agent.original(command)
    allocation = setup.inventory.runtime_allocation(command)
    assert allocation.limits.workspace.byte_ceiling == resource_plan().workspace.byte_ceiling
    setup.driver.supervise = lambda command, allocation: "needs_attention"
    assert setup.agent.supervise(command) == "needs_attention"
    assert setup.agent.original(command) == before
    assert rows(setup, "resource_bindings")[0]["state"] == "needs_attention"
    assert rows(setup, "resource_bindings")[0]["revision"] == allocation.binding_revision + 1


def test_failed_supervisor_still_persists_attention(setup):
    initialized_runtime(setup)
    command = follow(setup, StartContainer(binding_id=BINDING))
    assert setup.agent.execute(command).state == "applied"

    def unavailable(*args):
        raise OSError("synthetic stop failure")

    setup.driver.supervise = unavailable
    setup.driver.contain = lambda *args: None
    with pytest.raises(OSError, match="synthetic stop failure"):
        setup.agent.supervise(command)
    assert rows(setup, "resource_bindings")[0]["state"] == "needs_attention"
