"""Real RSA signatures exercise claim/algorithm/key validation and bounded cache refresh."""

import base64
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import Mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.cloudflare_identity import CloudflareIdentityVerifier


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def identity_context(deployment_values, signing_key):
    deployment = HostedDeployment.model_validate(deployment_values)
    now = datetime.now(UTC)
    numbers = signing_key.public_key().public_numbers()
    fetch = Mock(
        return_value={
            "keys": [
                {
                    "kid": "qualified-key",
                    "kty": "RSA",
                    "alg": "RS256",
                    "use": "sig",
                    "n": encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
                    "e": encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
                }
            ]
        }
    )
    verifier = CloudflareIdentityVerifier(deployment, fetch, now=lambda: now)
    body = {
        "iss": deployment.identity_issuer,
        "aud": [deployment.identity_audience],
        "sub": "verified-subject",
        "email": deployment.allowed_email,
        "iat": int((now - timedelta(seconds=1)).timestamp()),
        "exp": int((now + timedelta(hours=2)).timestamp()),
    }

    def sign(changes=None, header=None):
        first = encode(json.dumps(header or {"alg": "RS256", "kid": "qualified-key"}).encode())
        second = encode(json.dumps({**body, **(changes or {})}).encode())
        content = f"{first}.{second}"
        signature = signing_key.sign(content.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{content}.{encode(signature)}"

    return verifier, fetch, sign


def test_verified_identity_reuses_local_cached_key(identity_context):
    verifier, fetch, sign = identity_context
    token = sign()
    first = verifier.verify(token)
    second = verifier.verify(token)
    assert first == second
    assert first.subject == "verified-subject"
    assert first.fingerprint != token
    fetch.assert_called_once_with(verifier.deployment.identity_issuer)


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.example"},
        {"aud": ["foreign"]},
        {"exp": 0},
        {"iat": 999999999999},
        {"exp": True},
        {"sub": ""},
        {"nbf": 999999999999},
        {"email": None},
    ],
)
def test_invalid_claims_fail_before_key_network_call(identity_context, changes):
    verifier, fetch, sign = identity_context
    with pytest.raises(HostedAccessError):
        verifier.verify(sign(changes))
    fetch.assert_not_called()


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "kid": "qualified-key"},
        {"alg": "HS256", "kid": "qualified-key"},
        {"alg": "RS256", "kid": "unknown"},
        {"alg": "RS256"},
    ],
)
def test_algorithm_confusion_and_unknown_keys_are_rejected(identity_context, header):
    verifier, _fetch, sign = identity_context
    with pytest.raises(HostedAccessError):
        verifier.verify(sign(header=header))


def test_invalid_signature_cache_expiry_and_key_outage_fail_closed(identity_context, monkeypatch):
    verifier, fetch, sign = identity_context
    token = sign()
    verifier.verify(token)
    first, second, signature = token.split(".")
    changed = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(HostedAccessError):
        verifier.verify(f"{first}.{second}.{changed}")
    fetch.assert_called_once()
    verifier._valid_until = 0
    verifier._last_attempt = -10000
    fetch.side_effect = OSError("offline")
    with pytest.raises(HostedAccessError):
        verifier.verify(token)
    assert fetch.call_count == 2


def test_repeated_unknown_kids_cannot_trigger_unbounded_fetch(identity_context):
    verifier, fetch, sign = identity_context
    for kid in ("unknown-one", "unknown-two", "unknown-three"):
        with pytest.raises(HostedAccessError):
            verifier.verify(sign(header={"alg": "RS256", "kid": kid}))
    fetch.assert_called_once()
