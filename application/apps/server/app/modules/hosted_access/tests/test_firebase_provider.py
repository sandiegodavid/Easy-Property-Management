"""Synthetic cryptographic fixtures, not actual provider acceptance."""

import base64
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from unittest.mock import Mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
import pytest

from app.modules.hosted_access.application.identity_setup import IdentitySetup
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
    email_key,
)
from app.modules.hosted_access.infrastructure.firebase_tokens import (
    CertificateCache,
    FirebaseTokenVerifier,
)

NOW = 1794700000


@pytest.fixture
def provider():
    setup = IdentitySetup.model_validate_json(
        (
            Path(__file__).resolve().parents[6] / "deploy/hosted-mvp/identity/selection.json"
        ).read_bytes()
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-provider")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.fromtimestamp(NOW, UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.fromtimestamp(NOW, UTC) + timedelta(hours=1))
        .sign(key, hashes.SHA256())
    )
    fetch = Mock(
        return_value=({"key1": cert.public_bytes(serialization.Encoding.PEM).decode()}, 3600)
    )
    clock = [NOW]
    cache = CertificateCache(fetch, clock=lambda: clock[0])
    verifier = FirebaseTokenVerifier(setup.realm, cache, cache, clock=lambda: clock[0])

    def sign(changes=None, header=None):
        claims = dict(
            iss=setup.realm.issuer,
            aud=setup.realm.audience,
            sub="uid",
            auth_time=NOW - 20,
            iat=NOW - 10,
            exp=NOW + 3500,
            email="A.B+tag@EXAMPLE.invalid",
            email_verified=True,
            firebase={"sign_in_provider": "google.com"},
        ) | (changes or {})

        def encode(value):
            return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

        raw = (
            encode(json.dumps(header or {"alg": "RS256", "kid": "key1"}).encode())
            + "."
            + encode(json.dumps(claims).encode())
        ).encode()
        return raw.decode() + "." + encode(key.sign(raw, padding.PKCS1v15(), hashes.SHA256()))

    return verifier, sign, clock, fetch


def test_google_proof_keeps_auth_time_and_conservative_email(provider):
    verifier, sign, _, _ = provider
    identity = verifier.google(sign())
    assert identity.authenticated_at == (NOW - 20) * 1000
    assert identity.email_key.endswith(":A.B+tag@example.invalid")
    assert identity.method == "google"


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "foreign"},
        {"aud": "foreign"},
        {"sub": ""},
        {"sub": "x" * 129},
        {"email_verified": False},
        {"email_verified": 1},
        {"auth_time": NOW + 1},
        {"auth_time": True},
        {"auth_time": NOW - 1000},
        {"iat": NOW + 1},
        {"exp": NOW},
        {"exp": NOW + 7200},
        {"nbf": NOW + 1},
        {"email": "not-email"},
        {"firebase": {"sign_in_provider": "password"}},
        {"firebase": {"sign_in_provider": "google.com", "tenant": "foreign"}},
    ],
)
def test_invalid_signed_claims_are_not_identity(provider, changes):
    verifier, sign, _, _ = provider
    with pytest.raises(ProviderDenied):
        verifier.google(sign(changes))


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "kid": "key1"},
        {"alg": "HS256", "kid": "key1"},
        {"alg": "RS256"},
        {"alg": "RS256", "kid": "key1", "jku": "https://evil.invalid/keys"},
    ],
)
def test_untrusted_algorithm_and_key_source(provider, header):
    verifier, sign, _, fetch = provider
    with pytest.raises(ProviderDenied):
        verifier.google(sign(header=header))
    fetch.assert_not_called()


def test_admin_and_email_provenance(provider):
    verifier, sign, _, _ = provider
    with pytest.raises(ProviderDenied):
        verifier.google(sign(), admin=True)
    assert (
        verifier.google(
            sign({"firebase": {"sign_in_provider": "google.com", "sign_in_second_factor": "totp"}}),
            admin=True,
        ).method
        == "google_totp"
    )
    token = sign({"firebase": {"sign_in_provider": "password"}})
    with pytest.raises(ProviderDenied):
        verifier.google(token)
    assert (
        verifier.email_completion(
            token, expected_email="A.B+tag@example.invalid", expected_subject="uid"
        ).method
        == "email_link"
    )
    with pytest.raises(ProviderDenied):
        verifier.email_completion(
            token, expected_email="other@example.invalid", expected_subject="uid"
        )


def test_key_cache_deduplicates_unknown_key_and_outage_never_extends_expiry(provider):
    verifier, sign, clock, fetch = provider
    verifier.google(sign())
    for _ in range(10):
        with pytest.raises(ProviderDenied):
            verifier.google(sign(header={"alg": "RS256", "kid": "unknown"}))
    assert fetch.call_count == 1
    expiry = verifier.id_keys.expires
    clock[0] = NOW + 3601
    fetch.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        verifier.id_keys.key("key1")
    assert verifier.id_keys.expires == expiry


def test_email_normalization_does_not_merge_dot_plus_or_case():
    assert email_key("realm", "A.B+tag@EXAMPLE.invalid") == "realm:A.B+tag@example.invalid"
    assert email_key("realm", "A.B+tag@example.invalid") != email_key("realm", "ab@example.invalid")


def rest(provider):
    from pydantic import SecretStr
    from app.modules.hosted_access.infrastructure.firebase_rest import FirebaseRest

    value = IdentitySetup.model_validate_json(
        (
            Path(__file__).resolve().parents[6] / "deploy/hosted-mvp/identity/selection.json"
        ).read_bytes()
    )
    configured = IdentitySetup(
        **(
            value.model_dump()
            | dict(configuration_state="verified", provider_config_sha256="a" * 64)
        )
    )
    http = Mock()
    client = FirebaseRest(
        configured, SecretStr("private-key"), lambda: "private-bearer", provider[0], http=http
    )
    return client, http


def test_email_endpoint_only_accepts_provider_response_and_discards_refresh(provider):
    from pydantic import SecretStr
    from app.modules.hosted_access.infrastructure.firebase_rest import JsonResponse

    client, http = rest(provider)
    jwt = provider[1]({"firebase": {"sign_in_provider": "password"}})
    http.request.return_value = JsonResponse(
        {"idToken": jwt, "localId": "uid", "refreshToken": "discard-me"}, 0
    )
    client.lookup_status = Mock(return_value=0)
    client.create_session_cookie = Mock(return_value=(SecretStr("central-cookie"), "safe-proof"))
    result = client.complete_email_link(
        "A.B+tag@example.invalid", SecretStr("code"), remembered=True
    )
    assert "discard-me" not in repr(result)
    url, body = http.request.call_args.args
    assert "signInWithEmailLink" in url
    assert set(body) == {"email", "oobCode"}
    assert client.create_session_cookie.call_args.args[1].method == "email_link"


@pytest.mark.parametrize(
    "user",
    [
        {"localId": "uid", "disabled": True},
        {"localId": "uid", "validSince": str(NOW)},
        {"localId": "foreign"},
        None,
    ],
)
def test_current_provider_status_rejects_revocation_or_foreign_user(provider, user):
    from app.modules.hosted_access.infrastructure.firebase_rest import JsonResponse

    client, http = rest(provider)
    http.request.return_value = JsonResponse({"users": [user]}, 0)
    with pytest.raises(ProviderDenied):
        client.lookup_status(provider[0].google(provider[1]()))


def test_provider_timeout_is_not_retried_or_called_invalid_identity(provider):
    client, http = rest(provider)
    http.request.side_effect = ProviderUnavailable()
    client.rate_admission = Mock()
    client.rate_admission.reserve_email.return_value = "reserved"
    with pytest.raises(ProviderUnavailable):
        client.send_email_link(
            "A.B+tag@example.invalid",
            network="server-observed-network",
            operation=Mock(),
        )
    assert http.request.call_count == 1


def test_mail_without_durable_admission_does_not_contact_provider(provider):
    client, http = rest(provider)
    with pytest.raises(ProviderUnavailable):
        client.send_email_link("A.B+tag@example.invalid")
    http.request.assert_not_called()


def test_unverified_configuration_and_operator_role_cannot_load_credentials(tmp_path):
    from app.modules.hosted_access.infrastructure.provider_configuration import (
        load_provider_configuration,
    )

    value = IdentitySetup.model_validate_json(
        (
            Path(__file__).resolve().parents[6] / "deploy/hosted-mvp/identity/selection.json"
        ).read_bytes()
    )
    path = tmp_path / "must-not-create.json"
    for component in ("operator", "central_identity"):
        with pytest.raises(ProviderUnavailable):
            load_provider_configuration(path, value, component=component)
    assert not path.exists()


def test_mail_link_retains_only_public_attempt_correlation(provider):
    from app.modules.hosted_access.infrastructure.firebase_rest import JsonResponse

    client, http = rest(provider)
    client.rate_admission = Mock()
    client.rate_admission.reserve_email.return_value = "reserved"
    http.request.return_value = JsonResponse({"email": "A.B+tag@example.invalid"}, 0)
    attempt = "00000000-0000-4000-8000-000000000099"
    assert (
        client.send_email_link(
            "A.B+tag@example.invalid",
            network="server-network",
            operation=Mock(),
            attempt_id=attempt,
        )
        == "sent"
    )
    assert (
        http.request.call_args.args[1]["continueUrl"]
        == client.setup.origins.email_callback + "?attempt=" + attempt
    )
