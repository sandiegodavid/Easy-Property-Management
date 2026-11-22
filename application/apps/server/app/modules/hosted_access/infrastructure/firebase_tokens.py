"""Bounded RS256 Firebase proof verification; never accepts emulator/custom tokens.

Provider public certificates are fetched only by the fixed-endpoint adapter. These
objects authorize no EPM principal or workspace and never retain a bearer token.
"""

import base64
import json
import re
from threading import Event, Lock
import time

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.modules.hosted_access.application.identity_setup import IdentityRealm
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
    VerifiedProviderIdentity,
    email_key,
)

MAX_TOKEN = 16384
MAX_KEYS = 16
MAX_CERT = 8192
MAX_CACHE_SECONDS = 3600
MIN_REFRESH_SECONDS = 60
MIN_RSA_BITS = 2048


def unique_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProviderDenied()
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ProviderDenied()
        return value
    except ValueError, UnicodeError, RecursionError:
        raise ProviderDenied() from None


def _decode(segment):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ProviderDenied()
    try:
        value = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except ValueError:
        raise ProviderDenied() from None
    if base64.urlsafe_b64encode(value).rstrip(b"=").decode() != segment:
        raise ProviderDenied()
    return value


CLOCK_SKEW_SECONDS = 30
MAX_WAIT_SECONDS = 5


class CertificateCache:
    """One bounded cache per token kind; unknown-key refresh is globally throttled.

    Fetch returns (kid->PEM, Cache-Control max-age). Failure cannot slide the retained
    deadline. A single-flight event deduplicates concurrent misses without blocking
    cached lookups; refresh never invokes a DB.
    """

    def __init__(self, fetch, *, clock=time.time):
        self.fetch, self.clock = fetch, clock
        self.keys, self.expires, self.retry_at = {}, 0, 0
        self.lock = Lock()
        self.refreshing: Event | None = None

    def key(self, kid):
        if not isinstance(kid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", kid):
            raise ProviderDenied()
        with self.lock:
            now = self.clock()
            if now < self.expires and kid in self.keys:
                return self.keys[kid][0]
            waiting = self.refreshing
            leader = waiting is None
            if leader:
                if now < self.retry_at:
                    if now >= self.expires:
                        raise ProviderUnavailable()
                    raise ProviderDenied()
                self.retry_at = now + MIN_REFRESH_SECONDS
                waiting = Event()
                self.refreshing = waiting
        if not leader:
            if not waiting.wait(MAX_WAIT_SECONDS):
                raise ProviderUnavailable()
            with self.lock:
                now = self.clock()
                if now < self.expires and kid in self.keys:
                    return self.keys[kid][0]
                if now >= self.expires:
                    raise ProviderUnavailable()
                raise ProviderDenied()
        try:
            documents, max_age = self.fetch()
            keys = self._certificates(documents, now)
            if type(max_age) is not int or max_age <= 0:
                raise ValueError()
            expires = min(
                min(self.clock(), now) + min(max_age, MAX_CACHE_SECONDS),
                *(expiry for _key, expiry in keys.values()),
            )
            with self.lock:
                self.keys = keys
                self.expires = expires
        except ValueError, TypeError, OSError, ProviderUnavailable:
            raise ProviderUnavailable() from None
        finally:
            with self.lock:
                self.refreshing = None
            waiting.set()
        if kid not in keys:
            raise ProviderDenied()
        return keys[kid][0]

    @staticmethod
    def _certificates(documents, now):
        if not isinstance(documents, dict) or not 1 <= len(documents) <= MAX_KEYS:
            raise ValueError()
        keys = {}
        for kid, pem in documents.items():
            if (
                not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", kid)
                or not isinstance(pem, str)
                or len(pem) > MAX_CERT
            ):
                raise ValueError()
            cert = x509.load_pem_x509_certificate(pem.encode("ascii"))
            key = cert.public_key()
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size < MIN_RSA_BITS:
                raise ValueError()
            if (
                not cert.not_valid_before_utc.timestamp()
                <= now
                < cert.not_valid_after_utc.timestamp()
            ):
                continue
            keys[kid] = (key, cert.not_valid_after_utc.timestamp())
        if not keys:
            raise ValueError()
        return keys


class FirebaseTokenVerifier:
    def __init__(
        self,
        realm: IdentityRealm,
        id_keys: CertificateCache,
        session_keys: CertificateCache,
        *,
        clock=time.time,
    ):
        self.realm, self.id_keys, self.session_keys, self.clock = (
            realm,
            id_keys,
            session_keys,
            clock,
        )

    def google(self, token, *, admin=False):
        return self._verify(token, method="google_totp" if admin else "google")

    def email_completion(self, token, *, expected_email, expected_subject):
        """Private adapter entry: only called on signInWithEmailLink's own response.

        Do not route this method as an arbitrary browser-token endpoint.
        """
        result = self._verify(token, method="email_link")
        if result.subject != expected_subject or result.email_key != email_key(
            self.realm.alias, expected_email
        ):
            raise ProviderDenied()
        return result

    def session_cookie(self, cookie, *, method):
        return self._verify(cookie, method=method, session=True)

    def _verify(self, token, *, method, session=False):
        try:
            if not isinstance(token, str) or len(token) > MAX_TOKEN:
                raise ProviderDenied()
            parts = token.split(".")
            if len(parts) != 3:
                raise ProviderDenied()
            header, claims = unique_json(_decode(parts[0])), unique_json(_decode(parts[1]))
            if (
                header.get("alg") != "RS256"
                or header.get("typ", "JWT") != "JWT"
                or set(header) - {"alg", "kid", "typ"}
            ):
                raise ProviderDenied()
            prefix = (
                "https://session.firebase.google.com/"
                if session
                else "https://securetoken.google.com/"
            )
            if (
                claims.get("iss") != prefix + self.realm.project_id
                or claims.get("aud") != self.realm.audience
            ):
                raise ProviderDenied()
            now = self.clock()
            self._claim_checks(claims, now, method, session)
            cache = self.session_keys if session else self.id_keys
            key = cache.key(header.get("kid"))
            key.verify(
                _decode(parts[2]),
                (parts[0] + "." + parts[1]).encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return VerifiedProviderIdentity(
                realm=self.realm.alias,
                subject=claims["sub"],
                email=claims["email"],
                email_key=email_key(self.realm.alias, claims["email"]),
                method=method,
                authenticated_at=claims["auth_time"] * 1000,
                issued_at=claims["iat"] * 1000,
                expires_at=claims["exp"] * 1000,
                mfa_verified_at=claims["auth_time"] * 1000 if method == "google_totp" else None,
            )
        except ValueError, TypeError, KeyError, InvalidSignature, UnicodeError, RecursionError:
            raise ProviderDenied() from None

    def _claim_checks(self, claims, now, method, session):
        if method not in {"google", "email_link", "google_totp"}:
            raise ProviderDenied()
        times = [claims.get(name) for name in ("auth_time", "iat", "exp")]
        if any(type(value) is not int or value < 0 for value in times):
            raise ProviderDenied()
        authenticated, issued, expires = times
        maximum = 14 * 86400 if session else 3600
        if (
            not authenticated <= issued <= now + CLOCK_SKEW_SECONDS
            or now >= expires
            or expires - issued > maximum
        ):
            raise ProviderDenied()
        if "nbf" in claims and (
            type(claims["nbf"]) is not int or claims["nbf"] > now + CLOCK_SKEW_SECONDS
        ):
            raise ProviderDenied()
        if not session and now - authenticated > 15 * 60:
            raise ProviderDenied()
        subject = claims.get("sub")
        if (
            not isinstance(subject, str)
            or not 1 <= len(subject) <= 128
            or any(ord(char) < 33 for char in subject)
            or claims.get("email_verified") is not True
        ):
            raise ProviderDenied()
        firebase = claims.get("firebase")
        if not isinstance(firebase, dict) or firebase.get("tenant") != self.realm.tenant_id:
            raise ProviderDenied()
        provider = "password" if method == "email_link" else "google.com"
        if firebase.get("sign_in_provider") != provider:
            raise ProviderDenied()
        if method == "google_totp" and firebase.get("sign_in_second_factor") != "totp":
            raise ProviderDenied()
        email_key(self.realm.alias, claims.get("email"))
