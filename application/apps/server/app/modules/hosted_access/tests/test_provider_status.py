"""Bounded shared account observations under multi-device and multi-user traffic."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
    VerifiedProviderIdentity,
)
from app.modules.hosted_access.infrastructure.provider_status import (
    FRESH_MS,
    MAX_IDENTITIES,
    RevocationCache,
    UserStatus,
)


def identity(subject="uid", realm="realm"):
    return VerifiedProviderIdentity(
        realm=realm,
        subject=subject,
        email="user@example.invalid",
        email_key=realm + ":user@example.invalid",
        method="google",
        authenticated_at=100000,
        issued_at=100000,
        expires_at=1000000,
        mfa_verified_at=None,
    )


def test_100_device_observations_share_one_provider_lookup():
    started, release = Event(), Event()

    def fetch(proof):
        started.set()
        assert release.wait(3)
        return UserStatus(proof.subject, False, 0)

    lookup = Mock(side_effect=fetch)
    cache = RevocationCache(lookup, clock=lambda: 100)
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(cache.observe, identity()) for _ in range(100)]
        assert started.wait(3)
        release.set()
        observations = [future.result(timeout=3) for future in futures]
    assert len(observations) == 100
    assert {item.checked_at for item in observations} == {100000}
    assert lookup.call_count == 1
    assert not cache.pending


def test_100_distinct_accounts_have_independent_observations():
    lookup = Mock(side_effect=lambda proof: UserStatus(proof.subject, False, 0))
    cache = RevocationCache(lookup, clock=lambda: 100)
    with ThreadPoolExecutor(max_workers=16) as executor:
        observations = list(
            executor.map(cache.observe, [identity(f"uid{number}") for number in range(100)])
        )
    assert len({item.status.subject for item in observations}) == 100
    assert lookup.call_count == len(cache.records) == 100
    assert not cache.pending


def test_cache_bound_and_realm_isolation():
    lookup = Mock(side_effect=lambda proof: UserStatus(proof.subject, False, 0))
    cache = RevocationCache(lookup, clock=lambda: 100)
    for number in range(MAX_IDENTITIES + 1):
        cache.observe(identity(f"uid{number}"))
    assert len(cache.records) == MAX_IDENTITIES
    assert ("realm", "uid0") not in cache.records
    cache.observe(identity("uid1", "other-realm"))
    assert ("other-realm", "uid1") in cache.records
    assert ("realm", "uid1") not in cache.records
    assert lookup.call_count == MAX_IDENTITIES + 2


def test_expired_refresh_failure_is_not_a_cache_hit_and_can_recover():
    tick = [100]
    lookup = Mock(return_value=UserStatus("uid", False, 0))
    cache = RevocationCache(lookup, clock=lambda: tick[0])
    original = cache.observe(identity())
    tick[0] += FRESH_MS / 1000
    lookup.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        cache.observe(identity())
    assert cache.records[("realm", "uid")] == original
    assert not cache.pending
    lookup.side_effect = None
    lookup.return_value = UserStatus("uid", True, 0)
    with pytest.raises(ProviderDenied):
        cache.observe(identity())
    assert cache.records[("realm", "uid")].checked_at == tick[0] * 1000
    assert lookup.call_count == 3


def test_expired_device_cannot_inherit_another_devices_freshness():
    lookup = Mock(return_value=UserStatus("uid", False, 0))
    cache = RevocationCache(lookup, clock=lambda: 100)
    cache.observe(identity())
    with pytest.raises(ProviderUnavailable):
        cache.observe(identity().model_copy(update={"expires_at": 100000}))
    assert lookup.call_count == 1
