"""Transient claims serialize stale editors and leave domain revision checks intact."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import secrets
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.hosted_access.application.draft_leases import HostedDraftLeaseService
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.draft_leases import SQLiteDraftLeaseStore
from app.modules.hosted_access.tests.test_sessions import approve, context as session_context

context = session_context


@pytest.fixture
def leases(context):
    service, store, proof, clock = context
    first = approve(context)
    second = service.begin_session(proof)
    actors = [service.authenticate(proof, grant.token) for grant in (first, second)]
    revisions = {}
    adapter = SQLiteDraftLeaseStore(store)
    application = HostedDraftLeaseService(
        adapter, lambda key: revisions.get(key, 0), now=lambda: clock[0]
    )
    return application, adapter, actors, clock, revisions


def claim(application, actor, record_id, token, **values):
    return application.claim(record_id, actor, token=token, expected_revision=0, **values)


def test_explicit_claim_takeover_and_independent_drafts(leases):
    application, adapter, actors, clock, _ = leases
    record = str(uuid4())
    tokens = [secrets.token_urlsafe(32) for _ in actors]
    first = claim(application, actors[0], record, tokens[0])
    assert claim(application, actors[0], record, tokens[0]) == first
    with pytest.raises(HostedAccessError) as error:
        claim(application, actors[1], record, tokens[1])
    assert error.value.code == "hosted_draft_lease_conflict"
    claim(application, actors[1], str(uuid4()), tokens[1])
    claim(application, actors[1], record, tokens[1], takeover=True)
    with pytest.raises(HostedAccessError, match="no longer owns"):
        with adapter.guard(record, actors[0].session_reference, tokens[0], clock[0]):
            pytest.fail("Stale editor entered the mutation boundary")
    with adapter.guard(record, actors[1].session_reference, tokens[1], clock[0]):
        pass
    with adapter.engine.connect() as connection:
        rows = connection.execute(select(adapter.table)).mappings().all()
    assert all(token not in str(rows) for token in tokens)


def test_expiry_renewal_rate_and_revision_checks(leases):
    application, adapter, actors, clock, revisions = leases
    record, token = str(uuid4()), secrets.token_urlsafe(32)
    first = claim(application, actors[0], record, token)
    assert first["expires_at"] - clock[0].timestamp() == 300
    clock[0] += timedelta(seconds=59)
    assert claim(application, actors[0], record, token, renew=True) == first
    clock[0] += timedelta(seconds=2)
    renewed = claim(application, actors[0], record, token, renew=True)
    assert renewed["expires_at"] > first["expires_at"]
    revisions[record] = 1
    with pytest.raises(HostedAccessError) as caught:
        claim(application, actors[1], record, secrets.token_urlsafe(32), takeover=True)
    assert caught.value.code == "hosted_draft_revision_conflict"
    clock[0] += timedelta(seconds=301)
    with pytest.raises(HostedAccessError):
        with adapter.guard(record, actors[0].session_reference, token, clock[0]):
            pytest.fail("Expired authority entered mutation")
    with pytest.raises(HostedAccessError):
        application.claim(record, actors[0], token=token, expected_revision=1, renew=True)
    application.claim(record, actors[1], token=secrets.token_urlsafe(32), expected_revision=1)


def test_takeover_waits_for_whole_owning_transaction_and_guard_rolls_back(leases):
    application, adapter, actors, clock, _ = leases
    record = str(uuid4())
    first, second = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    claim(application, actors[0], record, first)
    entered, release, taken = Event(), Event(), Event()

    def writer():
        with adapter.guard(record, actors[0].session_reference, first, clock[0]):
            entered.set()
            assert release.wait(5)

    def takeover():
        claim(application, actors[1], record, second, takeover=True)
        taken.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(writer)
        assert entered.wait(5)
        taking = pool.submit(takeover)
        assert not taken.wait(0.1)
        release.set()
        writing.result()
        taking.result()
    with pytest.raises(RuntimeError, match="domain rollback"):
        with adapter.guard(record, actors[1].session_reference, second, clock[0]):
            raise RuntimeError("domain rollback")
    with adapter.guard(record, actors[1].session_reference, second, clock[0]):
        pass


def test_revocation_and_restore_remove_effective_authority(leases, context):
    application, adapter, actors, clock, _ = leases
    service, sessions, _proof, _ = context
    record, token = str(uuid4()), secrets.token_urlsafe(32)
    claim(application, actors[0], record, token)
    service.logout(actors[0])
    with pytest.raises(HostedAccessError):
        with adapter.guard(record, actors[0].session_reference, token, clock[0]):
            pytest.fail("Revoked session entered mutation")
    sessions.bind_restore_marker("original", clock[0])
    sessions.bind_restore_marker("restored", clock[0])
    with adapter.engine.connect() as connection:
        assert connection.execute(select(adapter.table)).all() == []
