"""Fixed-endpoint bounded provider transport; no redirects, retries, or credential vault."""

from dataclasses import dataclass
from ipaddress import IPv4Address
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import json
import subprocess
import sys
from threading import BoundedSemaphore

from pydantic import SecretStr

from app.modules.hosted_access.application.identity_setup import require_verified_setup
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
    email_key,
)
from app.modules.hosted_access.infrastructure.firebase_tokens import (
    CLOCK_SKEW_SECONDS,
    MAX_TOKEN,
    unique_json,
)
from app.modules.hosted_access.infrastructure.provider_status import RevocationCache, UserStatus

MAX_RESPONSE = 131072
TIMEOUT_SECONDS = 5
ID_CERTS = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
SESSION_CERTS = "https://www.googleapis.com/identitytoolkit/v3/relyingparty/publicKeys"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class JsonResponse:
    data: dict
    cache_seconds: int


def connect_proxy(value):
    if value is None:
        return {}
    parsed = urllib.parse.urlsplit(value)
    address = IPv4Address(parsed.hostname)
    if (
        parsed.scheme != "http"
        or not address.is_private
        or address.is_unspecified
        or parsed.port is None
        or parsed.netloc != f"{address}:{parsed.port}"
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use the protected private CONNECT endpoint.")
    return {"https": value}


class _SocketHttp:
    def __init__(self, proxy=None):
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.ProxyHandler(connect_proxy(proxy))
        )

    def request(self, url, body=None, *, bearer=None):
        # URLs are built exclusively by this module from protected project/API inputs.
        if not allowed_endpoint(url, body):
            raise ProviderDenied()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if bearer is not None:
            headers["Authorization"] = "Bearer " + bearer
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        request = urllib.request.Request(
            url, data=data, headers=headers, method="GET" if body is None else "POST"
        )
        try:
            with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                content = bytearray()
                while len(content) <= MAX_RESPONSE:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderUnavailable()
                    if response.fp is None:
                        break
                    sock = getattr(getattr(response.fp, "raw", None), "_sock", None)
                    if sock is not None and sock.fileno() >= 0:
                        sock.settimeout(remaining)
                    chunk = response.read1(min(16384, MAX_RESPONSE + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                if len(content) > MAX_RESPONSE or time.monotonic() > deadline:
                    raise ProviderUnavailable()
                match = re.search(
                    r"(?:^|,)\s*max-age=(\d+)", response.headers.get("Cache-Control", "")
                )
                return JsonResponse(unique_json(content), int(match[1]) if match else 0)
        except urllib.error.HTTPError as error:
            # Never expose URL/API key/provider payload or retry an ambiguous mutation.
            if bearer is not None and error.code in {401, 403}:
                raise ProviderUnavailable() from None
            if error.code in {400, 401, 403, 404}:
                raise ProviderDenied() from None
            raise ProviderUnavailable() from None
        except OSError, ValueError, AttributeError:
            raise ProviderUnavailable() from None


ACTIVE_REQUESTS = BoundedSemaphore(16)
MAX_REQUEST = 32768


def allowed_endpoint(url, body):
    if not isinstance(url, str):
        return False
    if url in {ID_CERTS, SESSION_CERTS}:
        return body is None
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "identitytoolkit.googleapis.com"
        or parsed.fragment
        or not isinstance(body, dict)
    ):
        return False
    if parsed.path in {"/v1/accounts:sendOobCode", "/v1/accounts:signInWithEmailLink"}:
        parameters = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        return (
            len(parameters) == 1
            and parameters[0][0] == "key"
            and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,256}", parameters[0][1]))
        )
    return not parsed.query and bool(
        re.fullmatch(
            r"/v1/projects/[a-z][a-z0-9-]{4,28}[a-z0-9]"
            r"(?:/tenants/[A-Za-z0-9_-]{1,128})?"
            r"(?:/accounts:lookup|:createSessionCookie)",
            parsed.path,
        )
    )


class ProviderHttp:
    """One short-lived worker per bounded call; timeout includes DNS/connect/TLS.

    Parent enforces a wall-clock deadline and kills/reaps a blocked worker. Credentials
    use stdin/stdout pipes, never argv, files or a persistent child. No replay on timeout.
    """

    def __init__(self, proxy=None):
        connect_proxy(proxy)
        self.proxy = proxy

    def request(self, url, body=None, *, bearer=None):
        if not allowed_endpoint(url, body):
            raise ProviderDenied()
        payload = json.dumps(
            {"url": url, "body": body, "bearer": bearer, "proxy": self.proxy}, separators=(",", ":")
        ).encode()
        if len(payload) > MAX_REQUEST:
            raise ProviderDenied()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        if not ACTIVE_REQUESTS.acquire(timeout=TIMEOUT_SECONDS):
            raise ProviderUnavailable()
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderUnavailable()
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.modules.hosted_access.infrastructure.firebase_http_worker",
                ],
                input=payload,
                capture_output=True,
                timeout=remaining,
                check=False,
                env={
                    name: value for name, value in os.environ.items() if name.lower() != "no_proxy"
                },
            )
            if result.returncode or len(result.stdout) > MAX_RESPONSE * 2:
                raise ProviderUnavailable()
            try:
                message = unique_json(result.stdout)
            except ProviderDenied, ValueError, TypeError, RecursionError:
                raise ProviderUnavailable() from None
            if message.get("state") == "denied":
                raise ProviderDenied()
            if (
                message.get("state") != "ok"
                or not isinstance(message.get("data"), dict)
                or type(message.get("cache_seconds")) is not int
                or message["cache_seconds"] < 0
            ):
                raise ProviderUnavailable()
            return JsonResponse(message["data"], message["cache_seconds"])
        except OSError, subprocess.TimeoutExpired:
            raise ProviderUnavailable() from None
        finally:
            ACTIVE_REQUESTS.release()


class FirebaseRest:
    def __init__(
        self, setup, api_key: SecretStr, bearer, verifier, *, http=None, rate_admission=None
    ):
        require_verified_setup(setup)
        self.setup, self.api_key, self.bearer, self.verifier = setup, api_key, bearer, verifier
        self.http = http or ProviderHttp()
        self.rate_admission = rate_admission
        self.status_cache = RevocationCache(self._lookup_status, clock=verifier.clock)

    def _public(self, action, body):
        url = (
            "https://identitytoolkit.googleapis.com/v1/accounts:"
            + action
            + "?key="
            + urllib.parse.quote(self.api_key.get_secret_value(), safe="")
        )
        if self.setup.realm.tenant_id is not None:
            body = {**body, "tenantId": self.setup.realm.tenant_id}
        return self.http.request(url, body).data

    def complete_google(self, token: SecretStr, *, remembered, admin=False):
        identity = self.verifier.google(token.get_secret_value(), admin=admin)
        self.lookup_status(identity)
        return self.create_session_cookie(
            token, identity, remembered=False if admin else remembered
        )

    def complete_email_link(self, email, code: SecretStr, *, remembered):
        # H03.5 must reserve the realm-qualified code/browser attempt before this call.
        email_key(self.setup.realm.alias, email)
        if not 1 <= len(code.get_secret_value()) <= 2048:
            raise ProviderDenied()
        result = self._public(
            "signInWithEmailLink", {"email": email, "oobCode": code.get_secret_value()}
        )
        token = result.get("idToken")
        if (
            not isinstance(token, str)
            or len(token) > MAX_TOKEN
            or not isinstance(result.get("localId"), str)
        ):
            raise ProviderDenied()
        # Returned refreshToken is discarded; never store/return the provider response.
        identity = self.verifier.email_completion(
            token, expected_email=email, expected_subject=result["localId"]
        )
        self.lookup_status(identity)
        return self.create_session_cookie(SecretStr(token), identity, remembered=remembered)

    def send_email_link(self, email, *, network=None, operation=None, attempt_id=None):
        normalized = email_key(self.setup.realm.alias, email)
        continuation = self.setup.origins.email_callback
        if attempt_id is not None:
            from uuid import UUID

            try:
                if str(UUID(attempt_id)) != attempt_id:
                    raise ValueError()
            except ValueError, TypeError, AttributeError:
                raise ProviderDenied() from None
            continuation += "?attempt=" + attempt_id
        if self.rate_admission is None or network is None or operation is None:
            raise ProviderUnavailable()
        if self.rate_admission.reserve_email(email, network, operation) != "reserved":
            raise ProviderUnavailable()
        # Caller must reserve its durable per-attempt/network/deployment rate admission.
        # No ID token: this must not implicitly link an existing provider account.
        result = self._public(
            "sendOobCode",
            {
                "requestType": "EMAIL_SIGNIN",
                "email": email,
                "continueUrl": continuation,
                "canHandleCodeInApp": True,
            },
        )
        if (
            not isinstance(result.get("email"), str)
            or email_key(self.setup.realm.alias, result["email"]) != normalized
        ):
            raise ProviderDenied()
        return "sent"

    def lookup_status(self, identity):
        if identity.realm != self.setup.realm.alias:
            raise ProviderDenied()
        return self.status_cache.observe(identity).status.valid_since

    def _lookup_status(self, identity):
        if identity.realm != self.setup.realm.alias:
            raise ProviderDenied()
        project = self.setup.realm.project_id
        body = {"localId": [identity.subject]}
        if self.setup.realm.tenant_id is not None:
            body["tenantId"] = self.setup.realm.tenant_id
        result = self.http.request(
            f"https://identitytoolkit.googleapis.com/v1/projects/{project}/accounts:lookup",
            body,
            bearer=self.bearer(),
        ).data
        users = result.get("users")
        if not isinstance(users, list) or len(users) != 1:
            raise ProviderDenied()
        user = users[0]
        if not isinstance(user, dict):
            raise ProviderDenied()
        valid_since = user.get("validSince", "0")
        if (
            user.get("localId") != identity.subject
            or type(user.get("disabled", False)) is not bool
            or not isinstance(valid_since, str)
            or not re.fullmatch(r"\d{1,16}", valid_since)
        ):
            raise ProviderDenied()
        return UserStatus(identity.subject, user.get("disabled", False), int(valid_since) * 1000)

    def create_session_cookie(self, token: SecretStr, identity, *, remembered):
        duration = 14 * 86400 if remembered else 8 * 3600
        project = self.setup.realm.project_id
        tenant = self.setup.realm.tenant_id
        path = (
            f"/v1/projects/{project}/tenants/{tenant}:createSessionCookie"
            if tenant is not None
            else f"/v1/projects/{project}:createSessionCookie"
        )
        body = {"idToken": token.get_secret_value(), "validDuration": str(duration)}
        if tenant is not None:
            body["tenantId"] = tenant
        result = self.http.request(
            "https://identitytoolkit.googleapis.com" + path,
            body,
            bearer=self.bearer(),
        ).data
        cookie = result.get("sessionCookie")
        if not isinstance(cookie, str) or len(cookie) > MAX_TOKEN:
            raise ProviderDenied()
        proof = self.verifier.session_cookie(cookie, method=identity.method)
        if (proof.subject, proof.realm, proof.email_key, proof.authenticated_at) != (
            identity.subject,
            identity.realm,
            identity.email_key,
            identity.authenticated_at,
        ):
            raise ProviderDenied()
        if (
            proof.expires_at
            > int(self.verifier.clock() * 1000) + (duration + CLOCK_SKEW_SECONDS) * 1000
        ):
            raise ProviderDenied()
        return SecretStr(cookie), proof
