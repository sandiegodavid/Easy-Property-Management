"""Canonical, bounded Ed25519 envelopes for private identity evidence."""

import base64
import binascii
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import SecretStr

from app.modules.hosted_access.application.identity_evidence import (
    HandoffEvidence,
    RecentAuthGrant,
    SessionObservationGrant,
    SourceBindingAssertion,
)
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.platform.hosted_contracts.semantic import canonical_bytes

DOMAIN = b"epm:private-identity:v1\0"
MAX_TOKEN_CHARS = 12000
_TOKEN_PART = re.compile(r"[A-Za-z0-9_-]+")
EVIDENCE_MODELS = (
    SourceBindingAssertion,
    HandoffEvidence,
    SessionObservationGrant,
    RecentAuthGrant,
)


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    if not _TOKEN_PART.fullmatch(value):
        raise ValueError()
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _encode(raw) != value:
        raise ValueError()
    return raw


class IdentitySigner:
    def __init__(self, key_id: str, key: Ed25519PrivateKey):
        self.key_id, self.key = key_id, key

    def sign(self, grant) -> SecretStr:
        if type(grant) not in EVIDENCE_MODELS or grant.key_id != self.key_id:
            raise ProviderDenied()
        raw = canonical_bytes(grant)
        token = _encode(raw) + "." + _encode(self.key.sign(DOMAIN + raw))
        if len(token) > MAX_TOKEN_CHARS:
            raise ProviderDenied()
        return SecretStr(token)


def verify_evidence(token, model, resolve_key, *, now):
    """Resolve the key from protected scope and signer, then verify the exact bytes."""
    if model not in EVIDENCE_MODELS or not isinstance(token, SecretStr):
        raise ProviderDenied()
    try:
        value = token.get_secret_value()
        if len(value) > MAX_TOKEN_CHARS:
            raise ValueError()
        message, signature = value.split(".")
        raw = _decode(message)
        grant = model.model_validate_json(raw)
        if canonical_bytes(grant) != raw or not grant.issued_at <= now < grant.expires_at:
            raise ValueError()
        key = resolve_key(grant.binding, grant.issuer_service, grant.key_id)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError()
        key.verify(_decode(signature), DOMAIN + raw)
        return grant
    except ValueError, binascii.Error, InvalidSignature, RecursionError:
        raise ProviderDenied() from None
