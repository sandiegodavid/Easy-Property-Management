"""Linux effects with real inventory/access receipts and isolated service/filesystem effects."""

from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
import copy
from datetime import UTC, datetime
import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from scripts import host_admin
from scripts.host_inventory import Instance
from scripts.tests.test_host_inventory import instance, inventory as inventory
from app.modules.hosted_access.tests.conftest import deployment_values as deployment_values
from app.modules.hosted_access.tests.test_source_commands import source as source, approved_source
from app.modules.hosted_access.infrastructure.command_cli import invoke
from app.modules.hosted_admin.application.upgrades import UpgradeInstance, InstalledRelease
from app.modules.hosted_admin.infrastructure.upgrade_deployment import UpgradeDeployment
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.operations import OperationEngine, enqueue
from app.modules.hosted_admin.application.contracts import AdminError


@pytest.fixture
def deployment(source, inventory, tmp_path):
    store, commands, now = approved_source(source)
    store._private_command("enable", now, recovery_override=True)
    root = tmp_path / "host"
    root.mkdir()
    paths = SimpleNamespace(
        control=root / "control",
        systemd=root / "systemd",
        releases=root / "releases",
        configs=root / "configs",
    )
    for path in vars(paths).values():
        path.mkdir()
    original = replace(
        instance("c"),
        workspace_id=str(store.deployment.workspace_id),
        operator_id=str(store.deployment.operator_id),
        email=store.deployment.allowed_email,
    )
    inventory.register(original)
    active = [True]
    starts = []
    target = "release-20261101-01"
    for name in (original.release, target):
        executable = paths.releases / name / "venv/bin/python"
        executable.parent.mkdir(parents=True)
        executable.touch()
    plan = {
        "instance": UpgradeInstance(
            **{name: getattr(original, name) for name in UpgradeInstance.model_fields}
        ).model_dump(),
        "target": {
            "release": target,
            "digest": "a" * 64,
            "installed": 1.0,
            "notes": "",
            "eligible": True,
            "blockers": [],
            "preserve_sessions": True,
            "compatibility_digest": "b" * 64,
        },
        "original_digest": "c" * 64,
        "configuration_digest": "d" * 64,
        "binding_revision": 1,
        "admin_revision": 2,
        "fence": 0,
        "generation": 0,
        "active": True,
        "environment_digest": "e" * 64,
        "recovery_configuration_digest": "f" * 64,
    }
    payload = {
        "operation_id": str(uuid4()),
        "instance": "c",
        "plan": plan,
        "session_handling": "preserve",
        "reason": "Agreed maintenance",
    }
    payload["gate_owner"] = payload["operation_id"]

    def effective():
        path = paths.systemd / "epm-hosted@c.service.d/99-epm-admin-upgrade.conf"
        if not path.exists():
            return original.release
        value = path.read_text().split("ExecStart=")[-1].split()[0]
        return Path(value).parent.parent.parent.name

    def observe(_key):
        return {"fields": asdict(inventory.get("c")) | {"release": effective()}, "digest": "f" * 64}

    def call(argv, **_options):
        if argv[0] == "/usr/sbin/runuser":
            return json.dumps(
                {
                    "workspace_id": original.workspace_id,
                    "compatible": True,
                    "maintenance_owner": store.maintenance.current().owner,
                }
            )
        if argv[1] == "stop":
            active[0] = False
        if argv[1] == "start":
            active[0] = True
            starts.append(argv[-1])
        return ""

    platform = SimpleNamespace(
        h=SimpleNamespace(
            paths=paths,
            inventory=inventory,
            source=SimpleNamespace(
                prepare=lambda _: {"deployment_digest": "d" * 64},
                _transport=lambda _, raw: invoke(store, raw, None),
            ),
            discovery=SimpleNamespace(
                _service=lambda _: (None, None, paths.releases / effective()),
                _release=lambda path: {
                    "manifest_digest": "c" * 64 if path.name == original.release else "a" * 64
                },
                observe=observe,
                source_command_ready=lambda _: None,
            ),
            lock_host=host_admin.lock_host,
            read_json=lambda path, _: json.loads(path.read_bytes()),
            protected=lambda *_args, **_kwargs: None,
            save_baseline=lambda *_: "e" * 64,
            instance_type=Instance,
        ),
        service_state=lambda _: "active" if active[0] else "inactive",
        directory=lambda path: path.mkdir(exist_ok=True),
        publish=lambda path, raw: path.write_bytes(raw),
        sync=lambda _: None,
        call=call,
    )
    proofs = {}
    recovery = SimpleNamespace(
        current=lambda _, stage: proofs.get(stage),
        produce=lambda _: proofs.setdefault("recovery", SimpleNamespace(id=str(uuid4()))),
        resulting=lambda _, stage: proofs.setdefault(stage, SimpleNamespace(id=str(uuid4()))),
    )
    catalog = SimpleNamespace(
        prepare=lambda *_: copy.deepcopy(plan),
        options=lambda _: [InstalledRelease.model_validate(plan["target"])],
        recheck=lambda *_: None,
    )
    acceptance = Mock()
    effects = UpgradeDeployment(platform, catalog, recovery, acceptance, Mock())
    return effects, payload, store, commands, inventory, active, starts, acceptance


def advance(effects, payload, step):
    observation = effects.inspect(payload, step)
    if observation.state == "absent":
        effects.apply(payload, step)
    assert effects.inspect(payload, step).state == "verified"


@pytest.mark.parametrize("restore_access", [True, False])
def test_target_only_upgrade_reconciles_inventory_and_original_receipt(deployment, restore_access):
    effects, payload, store, commands, inventory, active, starts, acceptance = deployment
    other = instance("b")
    inventory.register(other)
    for step in (
        "revalidate",
        "pause",
        "stop",
        "recovery",
        "validate",
        "switch",
        "start",
        "verify",
    ):
        advance(effects, payload, step)
    assert active[0] and store.maintenance.current().owner == payload["gate_owner"]
    assert inventory.get("c").release == payload["plan"]["instance"]["release"]
    accepted = payload | {"restore_access": restore_access}
    advance(effects, accepted, "accept")
    assert store.maintenance.current().owner is None
    assert commands.status()["active"] == restore_access
    assert commands.status()["generation"] == int(not restore_access)
    assert inventory.get("c").release == payload["plan"]["target"]["release"]
    assert inventory.get("c").revision == 2
    assert inventory.get("b") == other
    assert len(starts) == 1 and acceptance.called
    # Expiring/removing proof cannot change the already committed result.
    effects.recovery.current = Mock(side_effect=ValueError("expired"))
    assert effects.inspect(accepted, "accept").state == "verified"
    assert inventory.get("c").revision == 2
    commands.validate_retained()


def test_revocation_after_source_commit_stops_only_target_and_preserves_receipt(
    deployment, tmp_path
):
    effects, payload, store, _commands, inventory, active, _starts, _acceptance = deployment
    other = instance("b")
    inventory.register(other)
    for step in ("revalidate", "pause", "stop", "recovery", "validate", "switch", "start"):
        advance(effects, payload, step)
    payload = payload | {"restore_access": True}
    authority = AuthorityStore.initialize(tmp_path / "authority" / "control.sqlite", "owner")
    engine = OperationEngine(authority)
    with authority.transaction() as connection:
        enqueue(
            connection,
            authority,
            identifier=payload["operation_id"],
            identity=dict(authority._identity(connection)),
            kind="upgrade",
            target=payload["instance"],
            payload=payload,
        )
        connection.execute("UPDATE operation_step SET state='verified' WHERE kind!='accept'")
    effects.require_authority = engine.require_authority
    transport = effects.transport

    def revoke_after_resume(current, request):
        result = transport(current, request)
        if (
            isinstance(request.get("maintenance"), dict)
            and request["maintenance"]["action"] == "resume"
        ):
            authority.revoke_identity()
        return result

    effects.transport = revoke_after_resume
    with pytest.raises(AdminError, match="admin_authority_fenced"):
        engine.run(payload["operation_id"], effects)
    assert not active[0]
    assert store.maintenance.current().owner is None
    assert effects.inspect(payload, "accept").state == "verified"
    assert engine.get(payload["operation_id"])["state"] == "paused"
    assert inventory.get("b") == other


def test_intervening_disable_cannot_be_overridden_by_acceptance(deployment):
    effects, payload, store, commands, inventory, _active, _starts, _acceptance = deployment
    for step in (
        "revalidate",
        "pause",
        "stop",
        "recovery",
        "validate",
        "switch",
        "start",
        "verify",
    ):
        advance(effects, payload, step)
    store.disable(datetime.now(UTC))
    with pytest.raises(ValueError, match="Access changed"):
        effects.apply(payload | {"restore_access": True}, "accept")
    assert not commands.status()["active"]
    assert store.maintenance.current().owner == payload["gate_owner"]
    assert inventory.get("c").release == payload["plan"]["target"]["release"]


def test_rollback_checks_previous_schema_and_never_restores_a_backup(deployment):
    effects, payload, store, _commands, inventory, _active, _starts, _acceptance = deployment
    for step in ("revalidate", "pause", "stop", "recovery", "validate", "switch", "start"):
        advance(effects, payload, step)
    rollback = payload | {
        "operation_id": str(uuid4()),
        "parent": payload["operation_id"],
        "rollback": True,
    }
    for step in (
        "stop",
        "validate_previous",
        "switch_previous",
        "start_previous",
        "verify_previous",
    ):
        advance(effects, rollback, step)
    advance(effects, rollback | {"restore_access": True}, "accept")
    assert inventory.get("c").release == payload["plan"]["instance"]["release"]
    assert store.maintenance.current().owner is None


@pytest.mark.parametrize("lost_reply", [None, "finish", "reconcile"])
def test_rollback_recovers_reconciled_target_after_acceptance_fails(deployment, lost_reply):
    effects, payload, store, commands, inventory, _active, _starts, _acceptance = deployment
    other = instance("b")
    inventory.register(other)
    for step in ("revalidate", "pause", "stop", "recovery", "validate", "switch", "start"):
        advance(effects, payload, step)
    store.disable(datetime.now(UTC))
    with pytest.raises(ValueError, match="Access changed"):
        effects.apply(payload | {"restore_access": True}, "accept")
    target = inventory.get("c")
    assert target.revision == 2 and target.release == payload["plan"]["target"]["release"]
    original_receipt = inventory.maintenance(payload["gate_owner"])
    assert original_receipt["state"] == "reconciled"
    rollback = payload | {
        "operation_id": str(uuid4()),
        "parent": payload["operation_id"],
        "rollback": True,
        "restore_access": False,
    }
    for step in (
        "stop",
        "validate_previous",
        "switch_previous",
        "start_previous",
        "verify_previous",
    ):
        advance(effects, rollback, step)
    reconcile = inventory.reconcile
    finish = inventory.finish_maintenance

    def reconcile_then_lose(*args):
        reconcile(*args)
        raise OSError("lost inventory reply")

    def finish_then_lose(*args):
        finish(*args)
        raise OSError("lost inventory reply")

    if lost_reply:
        if lost_reply == "finish":
            inventory.finish_maintenance = finish_then_lose
        else:
            inventory.reconcile = reconcile_then_lose
        with pytest.raises(OSError, match="lost inventory reply"):
            effects.apply(rollback, "accept")
        assert store.maintenance.current().owner == payload["gate_owner"]
        inventory.reconcile = reconcile
        inventory.finish_maintenance = finish
    advance(effects, rollback, "accept")
    assert inventory.get("c").release == payload["plan"]["instance"]["release"]
    assert inventory.get("c").revision == 3
    assert inventory.maintenance(payload["gate_owner"]) == original_receipt
    assert inventory.maintenance(rollback["operation_id"])["state"] == "reconciled"
    assert inventory.get("b") == other
    assert store.maintenance.current().owner is None
    assert not commands.status()["active"]  # Rollback cannot undo concurrent disablement.
    advance(effects, rollback, "accept")
    assert inventory.get("c").revision == 3
    commands.validate_retained()


@pytest.mark.parametrize("revision", [3, 4])
def test_rollback_rejects_unowned_inventory_revisions(deployment, revision):
    effects, payload, _store, _commands, inventory, _active, _starts, _acceptance = deployment
    original = inventory.get("c")
    with inventory.connection(writable=True) as connection:
        connection.execute("UPDATE instances SET revision=? WHERE key='c'", (revision,))
    rollback = payload | {"operation_id": str(uuid4()), "rollback": True}
    with pytest.raises(AdminError, match="admin_upgrade_inventory_changed"):
        effects.item(rollback)
    assert inventory.get("c").release == original.release


def test_lost_start_response_is_reconciled_without_a_second_start(deployment):
    effects, payload, _store, _commands, _inventory, active, starts, _acceptance = deployment
    for step in ("revalidate", "pause", "stop", "recovery", "validate", "switch"):
        advance(effects, payload, step)
    original = effects.p.call

    def lost(argv, **kwargs):
        result = original(argv, **kwargs)
        if argv[1] == "start":
            raise OSError("response lost")
        return result

    effects.p.call = lost
    with pytest.raises(OSError):
        effects.apply(payload, "start")
    assert active[0]
    advance(effects, payload, "start")
    assert len(starts) == 1


def test_changed_qualification_cannot_cross_pause_or_acceptance(deployment):
    effects, payload, store, _commands, _inventory, active, _starts, _acceptance = deployment
    advance(effects, payload, "revalidate")
    original = effects.catalog.options
    effects.catalog.options = lambda _: []
    with pytest.raises(ValueError, match="qualification_changed"):
        effects.apply(payload, "pause")
    assert store.maintenance.current().owner is None and active[0]
    effects.catalog.options = original
    for step in ("pause", "stop", "recovery", "validate", "switch", "start", "verify"):
        advance(effects, payload, step)
    effects.catalog.recheck = Mock(side_effect=ValueError("qualification changed"))
    with pytest.raises(ValueError):
        effects.apply(payload | {"restore_access": True}, "accept")
    assert store.maintenance.current().owner == payload["gate_owner"]


def test_pre_pause_cancellation_releases_reservation_without_stopping_operator(deployment):
    effects, payload, store, _commands, inventory, active, _starts, _acceptance = deployment
    advance(effects, payload, "revalidate")
    assert effects.contain(payload)
    assert active[0] and store.maintenance.current().owner is None
    assert inventory.maintenance(payload["gate_owner"])["state"] == "reconciled"


@pytest.mark.parametrize("boundary", ["runtime", "recovery", "onboarding", "source_intent"])
@pytest.mark.parametrize("restore_access", [True, False])
def test_authority_revocation_before_gate_removal_keeps_access_paused(
    deployment, tmp_path, boundary, restore_access
):
    effects, payload, source_store, commands, _inventory, _active, _starts, acceptance = deployment
    for step in ("revalidate", "pause", "stop", "recovery", "validate", "switch", "start"):
        advance(effects, payload, step)
    authority = AuthorityStore.initialize(tmp_path / "authority" / "control.sqlite", "owner")
    engine = OperationEngine(authority)
    with authority.transaction() as connection:
        enqueue(
            connection,
            authority,
            identifier=payload["operation_id"],
            identity=dict(authority._identity(connection)),
            kind="upgrade",
            target=payload["instance"],
            payload=payload,
        )
        connection.execute("UPDATE operation SET state='running'")
    effects.require_authority = engine.require_authority
    if boundary == "runtime":
        acceptance.side_effect = lambda _: authority.revoke_identity()
    elif boundary == "recovery":
        effects.recovery.resulting = lambda *_: authority.revoke_identity()
    elif boundary == "onboarding":
        effects.recovery.prepare_onboarding = lambda _: authority.revoke_identity()
    else:
        original = effects.marker

        def marker(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1] == "accept":
                authority.revoke_identity()
            return result

        effects.marker = marker
    with pytest.raises(AdminError, match="admin_authority_fenced"):
        effects.apply(payload | {"restore_access": restore_access}, "accept")
    assert source_store.maintenance.current().owner == payload["gate_owner"]
    assert effects.inspect(payload, "accept").state == "absent"
    # Restoring Admin identity cannot authorize the old admitted generation.
    authority.restore_identity()
    with pytest.raises(AdminError, match="admin_authority_fenced"):
        engine.require_authority(payload["operation_id"])
    commands.validate_retained()


@pytest.mark.parametrize("stage", ["revalidate", "pause", "switch"])
def test_skipping_reconciles_only_owned_reservation_without_opening_access(deployment, stage):
    effects, payload, store, _commands, inventory, active, _starts, _acceptance = deployment
    other = instance("b")
    inventory.register(other)
    sequence = ["revalidate", "pause", "stop", "recovery", "validate", "switch"]
    for step in sequence[: sequence.index(stage) + 1]:
        advance(effects, payload, step)
    assert effects.contain_for_skip(payload)
    assert effects.contain_for_skip(payload)  # Lost cleanup reply is safe to reconcile.
    assert inventory.maintenance(payload["gate_owner"])["state"] == "reconciled"
    assert inventory.get("b") == other
    if stage == "revalidate":
        assert active[0] and store.maintenance.current().owner is None
    else:
        assert not active[0]
        assert store.maintenance.current().owner == payload["gate_owner"]
        assert inventory.get("c").release == effects.effective_release(payload)
