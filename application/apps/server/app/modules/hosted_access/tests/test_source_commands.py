"""Atomicity, exact enrollment, original receipt and disable-wins at the owning store."""

from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.admin_commands import AccessCommand
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.hosted_access.infrastructure.source_commands import AccessCommands
from app.platform.sqlite_engine import immediate_transaction


@pytest.fixture
def source(deployment_values):
    deployment = HostedDeployment.model_validate(deployment_values)
    SQLiteHostedSessionStore.initialize(deployment)
    store = SQLiteHostedSessionStore(deployment)
    yield store, AccessCommands(store)
    store.engine.dispose()


def command(**changes):
    return AccessCommand.model_validate(
        {
            "operation_id": str(uuid4()),
            "action": "disable",
            "expected_revision": 0,
            "expected_binding_revision": 0,
            "fence": 0,
            "authority_reference": "deployment-owner:1",
            "reason": "Contain access",
        }
        | changes
    )


def test_disable_replay_and_changed_intent(source):
    store, commands = source
    original = command()
    result = commands.execute(original)
    assert result.generation == 1 and result.fence == 1 and not result.active
    assert commands.execute(original) == result
    with pytest.raises(HostedAccessError, match="current authority"):
        commands.execute(original.model_copy(update={"reason": "changed"}))
    with store.engine.connect() as connection:
        assert len(connection.execute(select(commands.audit)).all()) == 1
        assert len(connection.execute(select(commands.receipts)).all()) == 1
    commands.validate_retained()


def test_audit_failure_rolls_back_mutation_and_receipt(source):
    store, commands = source
    with immediate_transaction(store.engine) as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_audit BEFORE INSERT ON hosted_admin_audit BEGIN SELECT RAISE(ABORT,'audit failed'); END"
        )
    with pytest.raises(IntegrityError, match="audit failed"):
        commands.execute(command())
    assert commands.status()["generation"] == 0
    with store.engine.connect() as connection:
        assert connection.execute(select(commands.receipts)).first() is None


def test_exact_enrollment_and_identity_only_approval_then_recovery_gate(source):
    store, commands = source
    now = datetime.now(UTC)
    with immediate_transaction(store.engine) as connection:
        connection.execute(
            store.enrollment.insert().values(
                subject="verified-subject",
                email=store.deployment.allowed_email,
                received_at=now.timestamp(),
            )
        )
    original = command(
        action="approve", subject="verified-subject", enrollment_received_at=now.timestamp()
    )
    with pytest.raises(HostedAccessError):
        commands.execute(
            original.model_copy(update={"enrollment_received_at": now.timestamp() - 1})
        )
    approved = commands.execute(original)
    assert not approved.active and approved.binding_revision == 1
    with pytest.raises(HostedAccessError) as error:
        commands.execute(command(action="enable", expected_revision=1, expected_binding_revision=1))
    assert error.value.code == "hosted_recovery_required"
    enabled = AccessCommands(store, activation_check=lambda *_: None).execute(
        command(action="enable", expected_revision=1, expected_binding_revision=1)
    )
    assert enabled.active
    commands.validate_retained()


def test_stale_enable_cannot_cross_disable_fence(source):
    store, commands = source
    queued = command(action="enable")
    commands.execute(command())
    with pytest.raises(HostedAccessError):
        AccessCommands(store, activation_check=lambda *_: pytest.fail()).execute(queued)
    assert not commands.status()["active"]


def test_revoke_once_and_expired_containment(source):
    store, commands = source
    store.deployment = store.deployment.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    cmd = command(action="revoke")
    assert commands.execute(cmd) == commands.execute(cmd)
    assert commands.status()["generation"] == 1
    with pytest.raises(HostedAccessError) as error:
        commands.execute(
            command(
                action="approve",
                expected_revision=1,
                fence=1,
                subject="sub",
                enrollment_received_at=1.0,
            )
        )
    assert error.value.code == "hosted_admin_window_invalid"


def test_audit_and_receipt_are_immutable_and_safe(source):
    store, commands = source
    cmd = command(reason="Private reason is not a public ledger field")
    commands.execute(cmd)
    with store.engine.connect() as connection:
        audit = dict(connection.execute(select(commands.audit)).mappings().one())
        assert cmd.reason not in json.dumps(audit)
        assert "subject" not in audit["after_json"]
    with pytest.raises(IntegrityError, match="immutable"):
        with immediate_transaction(store.engine) as connection:
            connection.exec_driver_sql("DELETE FROM hosted_admin_receipt")
    with immediate_transaction(store.engine) as connection:
        connection.exec_driver_sql("DROP TRIGGER hosted_admin_audit_no_delete")
    with pytest.raises(ValueError, match="current format"):
        SQLiteHostedSessionStore(store.deployment)


def test_configuration_change_blocks_grants_and_sessions_but_not_containment(source):
    store, commands = source
    store.deployment = store.deployment.model_copy(
        update={"administrator_contact": "new-admin@example.com"}
    )
    assert not commands.administrative_status().binding_matches_configuration
    with pytest.raises(HostedAccessError) as error:
        commands.execute(command(action="approve", subject="pending", enrollment_received_at=1.0))
    assert error.value.code == "hosted_admin_binding_changed"
    assert commands.execute(command()).fence == 1


def test_restore_invalidates_source_command_fence_and_keeps_legal_history(source):
    store, commands = source
    now = datetime.now(UTC)
    store.bind_restore_marker("initial", now)
    original = command()
    store.bind_restore_marker("restored", now)
    assert commands.status()["admin_fence"] == 1
    with pytest.raises(HostedAccessError):
        commands.execute(original)
    commands.validate_retained()
    reopened = SQLiteHostedSessionStore(store.deployment)
    try:
        assert AccessCommands(reopened).status()["binding_revision"] == 1
    finally:
        reopened.engine.dispose()


@pytest.mark.parametrize("corruption", ["fingerprint", "before", "transition", "missing_audit"])
def test_retained_admin_history_rejects_corruption(source, corruption):
    store, commands = source
    commands.execute(command())
    with immediate_transaction(store.engine) as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        for table in ("hosted_admin_audit", "hosted_admin_receipt"):
            for verb in ("update", "delete"):
                connection.exec_driver_sql(f"DROP TRIGGER {table}_no_{verb}")
        if corruption == "fingerprint":
            connection.exec_driver_sql(
                "UPDATE hosted_admin_receipt SET semantic_hash=?", ("x" * 64,)
            )
        elif corruption == "before":
            connection.exec_driver_sql("UPDATE hosted_admin_audit SET before_json='{}'")
        elif corruption == "transition":
            receipt = connection.execute(select(commands.receipts)).mappings().one()
            result = json.loads(receipt["result_json"])
            result["fence"] = 0
            from app.modules.hosted_access.application.admin_commands import AccessResult

            connection.exec_driver_sql(
                "UPDATE hosted_admin_receipt SET result_json=?",
                (AccessResult(**result).model_dump_json(),),
            )
            event = connection.execute(select(commands.audit)).mappings().one()
            after = json.loads(event["after_json"])
            after["admin_fence"] = 0
            connection.exec_driver_sql(
                "UPDATE hosted_admin_audit SET after_json=?", (json.dumps(after),)
            )
        else:
            connection.exec_driver_sql("DELETE FROM hosted_admin_audit")
    with pytest.raises(HostedAccessError) as error:
        commands.validate_retained()
    assert error.value.code == "hosted_admin_history_invalid"


def test_source_status_is_bounded_and_receipt_lookup_requires_exact_intent(source):
    store, commands = source
    with immediate_transaction(store.engine) as connection:
        for index in range(16):
            connection.execute(
                store.enrollment.insert().values(
                    subject=f"pending-{index}",
                    email=store.deployment.allowed_email,
                    received_at=float(index),
                )
            )
    snapshot = commands.administrative_status()
    assert len(snapshot.enrollments) == 16 and snapshot.binding_matches_configuration
    original = command()
    assert commands.receipt(original) is None
    expected = commands.execute(original)
    assert commands.receipt(original) == expected
    with pytest.raises(HostedAccessError):
        commands.receipt(original.model_copy(update={"reason": "Changed"}))


def test_source_cli_validates_business_only_for_new_grant_actions(source, monkeypatch):
    from app.modules.hosted_access.infrastructure import command_cli

    store, commands = source
    validate = Mock(side_effect=RuntimeError("not ready"))
    monkeypatch.setattr(command_cli, "validate_workspace_binding", validate)
    monkeypatch.setattr(command_cli.WorkspaceService, "from_local_config", lambda _: object())
    request = command()
    result = command_cli.invoke(store, request.model_dump(), None)
    assert result["action"] == "disable"
    assert command_cli.invoke(store, {"query": "receipt", "command": request.model_dump()}, None)[
        "found"
    ]
    validate.assert_not_called()
    grant = command(
        action="approve",
        subject="pending",
        enrollment_received_at=1.0,
        expected_revision=1,
        fence=1,
    )
    with pytest.raises(RuntimeError, match="not ready"):
        command_cli.invoke(store, grant.model_dump(), None)
    validate.assert_called_once()
    assert commands.status()["admin_revision"] == 1


def test_lost_control_result_replays_actual_source_receipt_without_second_mutation(
    source, tmp_path
):
    import sqlite3
    from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
    from app.modules.hosted_admin.application.contracts import BrokerRequest, CommandRequest

    store, commands = source
    authority = AuthorityStore.initialize(tmp_path / "control" / "authority.sqlite", "owner")
    clock = [authority.clock()]
    authority.clock = lambda: clock[0]
    credentials = authority.login(authority.issue())
    request = BrokerRequest(
        method="command",
        command=CommandRequest(
            **command().model_dump(exclude={"authority_reference", "activation"}),
            instance="c",
            confirmed=True,
        ),
        **credentials,
    )
    reference = {"allocation_id": "original-target"}
    admission = authority.admit(request, lambda _: reference.copy())
    reference["allocation_id"] = "later-target"
    assert authority.admit(request, lambda _: reference.copy()) == admission

    def dispatch(payload):
        assert payload["source_reference"] == {"allocation_id": "original-target"}
        return commands.execute(
            AccessCommand.model_validate(
                {
                    key: value
                    for key, value in payload.items()
                    if key not in {"source_reference", "instance", "confirmed"}
                }
            )
        ).model_dump()

    with authority.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER lost_control_result BEFORE UPDATE ON admission BEGIN SELECT RAISE(ABORT,'lost'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        authority.execute(admission, dispatch)
    assert commands.status()["generation"] == 1
    with authority.transaction() as connection:
        connection.execute("DROP TRIGGER lost_control_result")
    # The abandoned worker claim must expire before its original effect is reconciled.
    clock[0] += 61
    assert authority.execute(authority.admit(request), dispatch)["generation"] == 1
    assert commands.status()["generation"] == 1


def test_administrative_status_has_a_fixed_query_budget(source):
    from sqlalchemy import event

    store, commands = source
    observed = []

    def statement(_connection, _cursor, sql, *_args):
        observed.append(sql)

    event.listen(store.engine, "before_cursor_execute", statement)
    try:
        commands.administrative_status()
        empty_count = len(observed)
        with immediate_transaction(store.engine) as connection:
            connection.execute(
                store.enrollment.insert(),
                [
                    {
                        "subject": f"pending-{index}",
                        "email": store.deployment.allowed_email,
                        "received_at": float(index),
                    }
                    for index in range(16)
                ],
            )
        observed.clear()
        assert len(commands.administrative_status().enrollments) == 16
        # One BEGIN and two set-based SELECTs, independent of enrollment count.
        assert len(observed) == empty_count == 3
        assert sum(sql.lstrip().upper().startswith("SELECT") for sql in observed) == 2
    finally:
        event.remove(store.engine, "before_cursor_execute", statement)


def approved_source(source):
    store, commands = source
    now = datetime.now(UTC)
    with immediate_transaction(store.engine) as connection:
        connection.execute(
            store.enrollment.insert().values(
                subject="verified-current",
                email=store.deployment.allowed_email,
                received_at=now.timestamp(),
            )
        )
    commands.execute(
        command(
            action="approve", subject="verified-current", enrollment_received_at=now.timestamp()
        ),
        now,
    )
    return store, commands, now


def activation(source, **changes):
    from app.modules.hosted_access.application.admin_commands import deployment_fingerprint

    store, commands, now = approved_source(source)
    identifier = str(uuid4())
    proof = {
        "evidence_id": identifier,
        "acceptance_id": identifier,
        "workspace_id": str(store.deployment.workspace_id),
        "binding_revision": 1,
        "subject": "verified-current",
        "deployment_digest": deployment_fingerprint(store.deployment),
        "verified_at": now.timestamp(),
        "expires": now.timestamp() + 86400,
    } | changes
    return (
        commands,
        now,
        command(
            action="complete_onboarding",
            expected_revision=1,
            expected_binding_revision=1,
            evidence_id=identifier,
            acceptance_id=identifier,
            activation=proof,
        ),
    )


def test_completion_atomically_audits_and_reconciles_original_after_evidence_expires(source):
    commands, now, cmd = activation(source)
    result = commands.execute(cmd, now)
    assert result.active and result.action == "complete_onboarding"
    assert (
        commands.execute(cmd.model_copy(update={"activation": None}), now + timedelta(days=2))
        == result
    )
    commands.validate_retained()


@pytest.mark.parametrize(
    "changes",
    [
        {"subject": "old-subject"},
        {"binding_revision": 2},
        {"workspace_id": "00000000-0000-4000-8000-000000000001"},
        {"deployment_digest": "0" * 64},
        {"verified_at": 0.0},
        {"expires": 0.0},
        {"acceptance_id": "00000000-0000-4000-8000-000000000002"},
    ],
)
def test_completion_rejects_stale_or_foreign_proof_without_mutation(source, changes):
    commands, now, cmd = activation(source, **changes)
    with pytest.raises(HostedAccessError):
        commands.execute(cmd, now)
    assert not commands.status()["active"] and commands.status()["admin_revision"] == 1


def test_disable_wins_before_atomic_completion(source):
    commands, now, cmd = activation(source)
    commands.execute(command(expected_revision=1, expected_binding_revision=1), now)
    with pytest.raises(HostedAccessError):
        commands.execute(cmd, now)
    assert not commands.status()["active"]


@pytest.mark.parametrize("action", ["renew", "replace_email"])
def test_configuration_cutover_fences_preserves_history_and_requires_new_recovery(source, action):
    from app.modules.hosted_access.application.admin_commands import deployment_fingerprint

    store, commands, now = approved_source(source)
    values = (
        {"starts": now.timestamp() + 86400, "expires": now.timestamp() + 15 * 86400}
        if action == "renew"
        else {"replacement_email": "replacement@example.test"}
    )
    cmd = command(action=action, expected_revision=1, expected_binding_revision=1, **values)
    result = commands.execute(cmd, now)
    assert not result.active and result.binding_revision == 2 and result.fence == 1
    assert result.generation == 1
    assert commands.execute(cmd, now) == result
    replacement = commands.replacement(cmd)
    with store.engine.connect() as connection:
        row = connection.execute(select(store.operator)).mappings().one()
    assert row["binding_digest"] == deployment_fingerprint(replacement)
    assert row["subject"] == ("verified-current" if action == "renew" else None)
    store.deployment = replacement
    with pytest.raises(HostedAccessError):
        commands.execute(
            command(action="enable", expected_revision=2, expected_binding_revision=2, fence=1),
            now + timedelta(days=1),
        )
    commands.validate_retained()
