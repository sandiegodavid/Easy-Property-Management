"""Operation-owned maintenance retains sessions and cannot override containment."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.maintenance import MaintenanceCommand
from app.modules.hosted_access.application.service import HostedAccessService
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError, VerifiedIdentity
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.hosted_access.infrastructure.source_commands import AccessCommands
from app.platform.sqlite_engine import immediate_transaction


@pytest.fixture
def maintenance(deployment_values):
    deployment = HostedDeployment.model_validate(deployment_values)
    SQLiteHostedSessionStore.initialize(deployment)
    store = SQLiteHostedSessionStore(deployment)
    now = datetime.now(UTC) + timedelta(seconds=2)
    service = HostedAccessService(deployment, store, now=lambda: now)
    identity = VerifiedIdentity(
        deployment.identity_issuer,
        "approved",
        deployment.allowed_email,
        now - timedelta(seconds=1),
        now + timedelta(hours=1),
        sha256(b"proof").hexdigest(),
    )
    with pytest.raises(HostedAccessError):
        service.begin_session(identity)
    store.activate(identity.subject)
    grant = service.begin_session(identity)
    yield store, service, identity, grant, now
    store.engine.dispose()


def pause(store, **changes):
    source = AccessCommands(store).status()
    return MaintenanceCommand(
        **(
            {
                "id": str(uuid4()),
                "owner": str(uuid4()),
                "action": "pause",
                "expected_revision": store.maintenance.current().revision,
                "expected_admin_revision": source["admin_revision"],
                "expected_binding_revision": source["binding_revision"],
                "expected_fence": source["admin_fence"],
                "authority_reference": "admin:1",
                "reason": "Agreed maintenance",
                "release": "a" * 64,
            }
            | changes
        )
    )


def resume(store, original, **changes):
    return pause(
        store,
        **(
            {
                "owner": original.owner,
                "action": "resume",
                "restore_access": True,
                "release": "b" * 64,
            }
            | changes
        ),
    )


def test_pause_blocks_reads_and_sessions_without_revoking_and_survives_restart(maintenance):
    store, service, identity, grant, now = maintenance
    original = pause(store)
    state = store.maintenance.execute(original, now)
    assert state == store.maintenance.execute(original, now + timedelta(days=2))
    for action in (
        lambda: service.authenticate(identity, grant.token),
        lambda: service.begin_session(identity),
    ):
        with pytest.raises(HostedAccessError) as error:
            action()
        assert error.value.code == "hosted_upgrade_in_progress"
    reopened = SQLiteHostedSessionStore(store.deployment)
    try:
        assert reopened.maintenance.current() == state
    finally:
        reopened.engine.dispose()
    store.maintenance.execute(resume(store, original), now)
    assert service.authenticate(identity, grant.token).expires_at == grant.expires_at
    with store.engine.connect() as connection:
        assert (
            connection.execute(select(store.sessions)).mappings().one()["expires_at"]
            == grant.expires_at.timestamp()
        )
    store.maintenance.validate_retained()


@pytest.mark.parametrize("intervention", ["disable", "revoke", "sign_out_all", "expire"])
def test_acceptance_never_overrides_intervening_authority(maintenance, intervention):
    store, service, identity, grant, now = maintenance
    actor = service.authenticate(identity, grant.token)
    original = pause(store)
    store.maintenance.execute(original, now)
    if intervention == "disable":
        store.disable(now)
    elif intervention == "revoke":
        store.revoke_all(now)
    elif intervention == "sign_out_all":
        service.logout(actor, identity, all_devices=True)
    else:
        store.deployment = store.deployment.model_copy(update={"expires_at": now})
    with pytest.raises(HostedAccessError) as error:
        store.maintenance.execute(resume(store, original), now)
    assert error.value.code == "hosted_maintenance_access_changed"
    assert store.maintenance.current().owner == original.owner
    store.disable(now)
    store.maintenance.execute(resume(store, original, restore_access=False), now)
    with pytest.raises(HostedAccessError):
        service.authenticate(identity, grant.token)


def test_mandatory_revocation_does_not_extend_sessions(maintenance):
    store, service, identity, grant, now = maintenance
    original = pause(store, revoke_sessions=True)
    store.maintenance.execute(original, now)
    store.maintenance.execute(resume(store, original), now)
    with pytest.raises(HostedAccessError):
        service.authenticate(identity, grant.token)


def test_wrong_owner_changed_intent_and_failed_audit_leave_gate_closed(maintenance):
    store, _service, _identity, _grant, now = maintenance
    original = pause(store)
    state = store.maintenance.execute(original, now)
    with pytest.raises(HostedAccessError):
        store.maintenance.execute(original.model_copy(update={"reason": "Changed"}), now)
    with pytest.raises(HostedAccessError):
        store.maintenance.execute(resume(store, original, owner=str(uuid4())), now)
    with immediate_transaction(store.engine) as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_maintenance BEFORE INSERT ON hosted_maintenance_receipt BEGIN SELECT RAISE(ABORT,'audit failed'); END"
        )
    with pytest.raises(IntegrityError):
        store.maintenance.execute(resume(store, original), now)
    assert store.maintenance.current() == state


def test_private_source_cli_can_inspect_closed_gate_without_business_access(maintenance):
    from app.modules.hosted_access.infrastructure.command_cli import invoke

    store, _service, _identity, _grant, _now = maintenance
    original = pause(store)
    result = invoke(store, {"maintenance": original.model_dump()}, None)
    assert invoke(store, {"maintenance": "status"}, None) == result
    assert invoke(store, {"maintenance": original.model_dump()}, None) == result
