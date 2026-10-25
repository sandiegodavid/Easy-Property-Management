"""Real administrative SQLite sessions: enrollment, fencing, persistence and one-query reads."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import secrets
from unittest.mock import patch

import pytest
from sqlalchemy import event, select

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.service import HostedAccessService
from app.modules.hosted_access.domain.models import HostedAccessError, VerifiedIdentity
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore


@pytest.fixture
def context(deployment_values):
    deployment = HostedDeployment.model_validate(deployment_values)
    now = datetime.now(UTC) + timedelta(seconds=1)
    clock = [now]
    SQLiteHostedSessionStore.initialize(deployment)
    store = SQLiteHostedSessionStore(deployment)
    service = HostedAccessService(deployment, store, now=lambda: clock[0])
    proof = VerifiedIdentity(
        deployment.identity_issuer,
        "verified-subject",
        deployment.allowed_email,
        now - timedelta(seconds=1),
        now + timedelta(hours=2),
        sha256(b"assertion").hexdigest(),
    )
    yield service, store, proof, clock
    store.engine.dispose()


def approve(context):
    service, store, proof, _clock = context
    with pytest.raises(HostedAccessError, match="approval"):
        service.begin_session(proof)
    store.activate(proof.subject)
    return service.begin_session(proof)


def test_pending_enrollment_has_no_session_or_business_authority(context):
    service, store, proof, _clock = context
    with pytest.raises(HostedAccessError) as caught:
        service.begin_session(proof)
    assert caught.value.code == "hosted_enrollment_pending"
    assert len(store.enrollments()) == 1
    with store.engine.connect() as connection:
        assert connection.execute(select(store.sessions)).all() == []
    with pytest.raises(HostedAccessError):
        store.activate("not-the-verified-subject")
    with pytest.raises(HostedAccessError):
        service.begin_session(replace(proof, email="outsider@example.com"))
    assert len(store.enrollments()) == 1


def test_authorized_read_is_one_select_without_writes_and_secrets_are_hashed(context):
    service, store, proof, _clock = context
    grant = approve(context)
    statements = []

    def listener(_c, _cursor, sql, _p, _ctx, _many):
        statements.append(sql)

    event.listen(store.engine, "before_cursor_execute", listener)
    try:
        actor = service.authenticate(proof, grant.token, csrf=grant.csrf)
    finally:
        event.remove(store.engine, "before_cursor_execute", listener)
    assert actor.workspace_id == str(service.deployment.workspace_id)
    assert len([sql for sql in statements if sql.startswith("SELECT")]) == 1
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    with store.engine.connect() as connection:
        row = connection.execute(select(store.sessions)).mappings().one()
    assert row["token_hash"] != grant.token
    assert row["csrf_hash"] != grant.csrf
    assert grant.token not in str(row)
    assert grant.csrf not in str(row)


def test_current_logout_preserves_other_device_but_blocks_old_assertion_bootstrap(context):
    service, _store, proof, _clock = context
    first = approve(context)
    second = service.begin_session(proof)
    service.logout(service.authenticate(proof, first.token), proof)
    with pytest.raises(HostedAccessError):
        service.authenticate(proof, first.token)
    service.authenticate(proof, second.token)
    with pytest.raises(HostedAccessError, match="Fresh sign-in"):
        service.begin_session(proof)


def test_all_device_logout_survives_restart_and_needs_new_identity_proof(context):
    service, store, proof, clock = context
    first = approve(context)
    second = service.begin_session(proof)
    service.logout(service.authenticate(proof, first.token), proof, all_devices=True)
    restarted = SQLiteHostedSessionStore(service.deployment)
    try:
        service = HostedAccessService(service.deployment, restarted, now=lambda: clock[0])
        with pytest.raises(HostedAccessError):
            service.authenticate(proof, second.token)
        with pytest.raises(HostedAccessError):
            service.begin_session(proof)
        clock[0] += timedelta(seconds=2)
        fresh = replace(proof, issued_at=clock[0], fingerprint=sha256(b"fresh").hexdigest())
        grant = service.begin_session(fresh)
        service.authenticate(fresh, grant.token)
    finally:
        restarted.engine.dispose()
    assert store.deployment.workspace_id == service.deployment.workspace_id


def test_logout_blocks_both_bootstrap_and_refreshed_assertions_atomically(context):
    service, store, proof, _clock = context
    first = approve(context)
    other = service.begin_session(proof)
    refreshed = replace(proof, fingerprint=sha256(b"refreshed").hexdigest())
    actor = service.authenticate(refreshed, first.token)

    def fail_current_block(_c, _cursor, sql, parameters, _ctx, _many):
        if (
            sql.startswith("INSERT INTO hosted_blocked_assertion")
            and refreshed.fingerprint in parameters
        ):
            raise RuntimeError("block failed")

    event.listen(store.engine, "before_cursor_execute", fail_current_block)
    try:
        with pytest.raises(RuntimeError, match="block failed"):
            service.logout(actor, refreshed)
    finally:
        event.remove(store.engine, "before_cursor_execute", fail_current_block)
    service.authenticate(refreshed, first.token)
    with store.engine.connect() as connection:
        assert connection.execute(select(store.blocked)).all() == []
    service.logout(actor, refreshed)
    service.authenticate(refreshed, other.token)
    for identity in (proof, refreshed):
        with pytest.raises(HostedAccessError, match="Fresh sign-in"):
            service.begin_session(identity)


def test_session_expiry_csrf_identity_disable_and_no_implicit_rebinding(context):
    service, store, proof, clock = context
    grant = approve(context)
    with pytest.raises(HostedAccessError, match="verification"):
        service.authenticate(proof, grant.token, csrf="wrong")
    with pytest.raises(HostedAccessError):
        service.authenticate(replace(proof, subject="another-subject"), grant.token)
    store.disable(clock[0])
    with pytest.raises(HostedAccessError):
        service.authenticate(proof, grant.token)
    with pytest.raises(HostedAccessError):
        service.begin_session(proof)
    clock[0] = grant.expires_at
    with pytest.raises(HostedAccessError):
        service.authenticate(proof, grant.token)


def test_failed_session_insert_rolls_back_without_partial_session(context):
    service, store, proof, _clock = context
    approve(context)
    with store.engine.connect() as connection:
        before = connection.execute(select(store.sessions)).all()
    with patch.object(secrets, "token_urlsafe", return_value="A" * 43):
        grant = service.begin_session(proof)
        with pytest.raises(Exception):
            service.begin_session(proof)
    with store.engine.connect() as connection:
        after = connection.execute(select(store.sessions)).all()
    assert len(after) == len(before) + 1
    service.authenticate(proof, grant.token)


def test_initialization_is_exclusive_and_schema_tampering_is_rejected(context):
    service, store, _proof, _clock = context
    with pytest.raises(FileExistsError):
        SQLiteHostedSessionStore.initialize(service.deployment)
    with store.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num='foreign'")
    with pytest.raises(HostedAccessError, match="binding"):
        SQLiteHostedSessionStore(service.deployment)


def test_rebinding_requires_disabled_operator_pending_subject_and_fresh_sign_in(context):
    service, store, proof, clock = context
    original = approve(context)
    replacement = replace(proof, subject="replacement-subject")
    with pytest.raises(HostedAccessError):
        store.rebind(replacement.subject, clock[0])
    store.disable(clock[0])
    with pytest.raises(HostedAccessError, match="approval"):
        service.begin_session(replacement)
    with pytest.raises(HostedAccessError):
        store.activate(replacement.subject)
    store.rebind(replacement.subject, clock[0])
    store.activate(replacement.subject)
    with pytest.raises(HostedAccessError):
        service.authenticate(proof, original.token)
    with pytest.raises(HostedAccessError):
        service.begin_session(replacement)
    clock[0] += timedelta(seconds=2)
    replacement = replace(
        replacement, issued_at=clock[0], fingerprint=sha256(b"new-id").hexdigest()
    )
    grant = service.begin_session(replacement)
    service.authenticate(replacement, grant.token)
