"""Private configuration, bounded subprocess and shared provider-status regressions."""

from hashlib import sha256
import json
import subprocess
from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
    VerifiedProviderIdentity,
)
from app.modules.hosted_access.infrastructure.firebase_rest import ID_CERTS, ProviderHttp
from app.modules.hosted_access.infrastructure.provider_configuration import (
    build_central_provider,
    load_provider_configuration,
)
from app.modules.hosted_access.infrastructure.provider_status import RevocationCache, UserStatus
from app.modules.hosted_access.tests.test_identity_contracts import setup


@pytest.mark.parametrize(
    "tamper", ["valid", "mode", "symlink", "hardlink", "digest", "realm", "quota"]
)
def test_protected_configuration(tmp_path, tamper):
    tmp_path.chmod(0o700)
    value = setup()
    record = dict(
        version=1,
        realm=value.realm.model_dump(),
        origins=value.origins.model_dump(),
        api_key="synthetic-provider-key",
        google_enabled=True,
        email_link_enabled=True,
        totp_enabled=True,
        provider_email_sends_per_day=value.provider_sends_per_day,
    )
    if tamper == "realm":
        record["realm"]["alias"] = "foreign"
    if tamper == "quota":
        record["provider_email_sends_per_day"] = 1
    raw = json.dumps(record).encode()
    path = tmp_path / "provider.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    sealed = type(value)(
        **(
            value.model_dump()
            | dict(configuration_state="verified", provider_config_sha256=sha256(raw).hexdigest())
        )
    )
    if tamper == "mode":
        path.chmod(0o644)
    if tamper == "digest":
        path.write_text("{}")
    if tamper == "hardlink":
        (tmp_path / "hard.json").hardlink_to(path)
    if tamper == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    if tamper == "valid":
        loaded = load_provider_configuration(path, sealed, component="central_identity")
        assert "synthetic-provider-key" not in repr(loaded)
        rate_admission = Mock()
        adapter = build_central_provider(
            path,
            sealed,
            component="central_identity",
            bearer=lambda: "test",
            rate_admission=rate_admission,
        )
        assert adapter.verifier.realm == sealed.realm
        assert adapter.rate_admission is rate_admission
        rate_admission.reserve_email.assert_not_called()
        for bearer, admission in (
            (None, rate_admission),
            ("credential-instead-of-supplier", rate_admission),
            (lambda: "test", None),
            (lambda: "test", object()),
        ):
            with pytest.raises(ProviderUnavailable):
                build_central_provider(
                    path,
                    sealed,
                    component="central_identity",
                    bearer=bearer,
                    rate_admission=admission,
                )
        with pytest.raises(ProviderUnavailable):
            build_central_provider(
                path,
                sealed,
                component="operator",
                bearer=lambda: "test",
                rate_admission=rate_admission,
            )
    else:
        with pytest.raises(ProviderUnavailable):
            load_provider_configuration(path, sealed, component="central_identity")


def test_process_deadline_has_no_retries(monkeypatch):
    run = Mock(side_effect=subprocess.TimeoutExpired("worker", 5))
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.firebase_rest.subprocess.run", run
    )
    with pytest.raises(ProviderUnavailable):
        ProviderHttp().request(ID_CERTS)
    assert run.call_count == 1
    assert run.call_args.kwargs["timeout"] <= 5


def test_status_cache_compares_each_proof_to_account_fence():
    clock = [100]
    fetch = Mock(return_value=UserStatus("uid", False, 100001))
    cache = RevocationCache(fetch, clock=lambda: clock[0])

    def identity(at):
        return VerifiedProviderIdentity(
            realm="realm",
            subject="uid",
            email="user@example.invalid",
            email_key="realm:user@example.invalid",
            method="google",
            authenticated_at=at,
            issued_at=100000,
            expires_at=1000000,
            mfa_verified_at=None,
        )

    with pytest.raises(ProviderDenied):
        cache.observe(identity(100000))
    assert cache.observe(identity(100002)).checked_at == 100000
    assert fetch.call_count == 1
    clock[0] = 401
    fetch.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        cache.observe(identity(100002))
    assert cache.records[("realm", "uid")].checked_at == 100000
