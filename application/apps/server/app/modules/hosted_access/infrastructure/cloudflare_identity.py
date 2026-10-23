"""Offline RS256 verification with fixed, bounded Cloudflare signing-key discovery."""

import base64
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError, VerifiedIdentity

MAX_ASSERTION_BYTES = 16 * 1024
MAX_KEYS_BYTES = 64 * 1024
KEY_CACHE_SECONDS = 15 * 60
REFRESH_COOLDOWN_SECONDS = 30
MIN_RSA_BITS = 2048
MAX_RSA_BITS = 8192


def _decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    result = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("An object is required.")
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Identity-key redirects are not allowed.")


def fetch_keys(issuer: str) -> dict:
    request = Request(issuer + "/cdn-cgi/access/certs", headers={"Accept": "application/json"})
    with build_opener(_NoRedirect()).open(request, timeout=2) as response:
        payload = response.read(MAX_KEYS_BYTES + 1)
    if len(payload) > MAX_KEYS_BYTES:
        raise ValueError("Signing-key response exceeds its bound.")
    return _json(payload)


class CloudflareIdentityVerifier:
    def __init__(
        self,
        deployment: HostedDeployment,
        fetch: Callable[[str], dict] = fetch_keys,
        now: Callable[[], datetime] | None = None,
    ):
        self.deployment = deployment
        self.fetch = fetch
        self.now = now or (lambda: datetime.now(UTC))
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._valid_until = 0.0
        self._last_attempt = -math.inf
        self._lock = threading.Lock()

    def _key(self, kid: str) -> rsa.RSAPublicKey:
        with self._lock:
            tick = time.monotonic()
            if kid in self._keys and tick < self._valid_until:
                return self._keys[kid]
            if tick - self._last_attempt >= REFRESH_COOLDOWN_SECONDS:
                self._last_attempt = tick
                payload = self.fetch(self.deployment.identity_issuer)
                values = payload.get("keys", [])
                if not isinstance(values, list) or not 1 <= len(values) <= 32:
                    raise ValueError("Invalid signing-key collection.")
                keys = {}
                for item in values:
                    if item.get("kty") != "RSA" or item.get("use", "sig") != "sig":
                        continue
                    if item.get("alg", "RS256") != "RS256":
                        continue
                    modulus = int.from_bytes(_decode(item["n"]), "big")
                    if not MIN_RSA_BITS <= modulus.bit_length() <= MAX_RSA_BITS:
                        raise ValueError("Invalid RSA modulus size.")
                    exponent = int.from_bytes(_decode(item["e"]), "big")
                    if item["kid"] in keys:
                        raise ValueError("Ambiguous signing-key identity.")
                    keys[item["kid"]] = rsa.RSAPublicNumbers(exponent, modulus).public_key()
                self._keys = keys
                self._valid_until = tick + KEY_CACHE_SECONDS
            if kid not in self._keys or tick >= self._valid_until:
                raise ValueError("A current signing key is required.")
            return self._keys[kid]

    def verify(self, assertion: str) -> VerifiedIdentity:
        try:
            return self._verify(assertion)
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OverflowError,
            InvalidSignature,
            HTTPError,
            URLError,
            OSError,
        ) as error:
            raise HostedAccessError(
                "hosted_assertion_rejected", "A valid identity assertion is required."
            ) from error

    def _verify(self, assertion: str) -> VerifiedIdentity:
        if len(assertion) > MAX_ASSERTION_BYTES:
            raise ValueError("Oversized assertion.")
        encoded_header, encoded_body, encoded_signature = assertion.split(".")
        header, body = _json(_decode(encoded_header)), _json(_decode(encoded_body))
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("Unqualified signing algorithm or key.")
        self._validate_claims(body)
        self._key(header["kid"]).verify(
            _decode(encoded_signature),
            f"{encoded_header}.{encoded_body}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return VerifiedIdentity(
            body["iss"],
            body["sub"],
            body["email"],
            datetime.fromtimestamp(body["iat"], UTC),
            datetime.fromtimestamp(body["exp"], UTC),
            sha256(assertion.encode("ascii")).hexdigest(),
        )

    def _validate_claims(self, body: dict) -> None:
        audience = body.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if (
            body.get("iss") != self.deployment.identity_issuer
            or not isinstance(audiences, list)
            or self.deployment.identity_audience not in audiences
        ):
            raise ValueError("Foreign issuer or audience.")
        for name in ("sub", "email"):
            if not isinstance(body.get(name), str) or not 1 <= len(body[name]) <= 254:
                raise ValueError("Invalid subject or email.")
        for name in ("iat", "exp"):
            if type(body.get(name)) is not int or body[name] < 0:
                raise ValueError("Invalid identity times.")
        now = self.now().timestamp()
        if body["iat"] > now or body["exp"] <= now or body["exp"] <= body["iat"]:
            raise ValueError("Expired or future identity proof.")
        if "nbf" in body and (type(body["nbf"]) is not int or body["nbf"] > now):
            raise ValueError("Identity proof is not yet valid.")
