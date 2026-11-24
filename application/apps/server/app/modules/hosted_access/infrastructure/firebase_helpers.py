"""Serve the fixed Firebase browser helpers through the protected CONNECT peer."""

from http.client import HTTPSConnection, HTTPException
from time import monotonic
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from app.modules.host_agent.application.auth_routes import CENTRAL_IDENTITY_ROUTES
from app.modules.hosted_access.application.managed_provider import ProviderUnavailable
from app.modules.hosted_access.infrastructure.firebase_rest import TIMEOUT_SECONDS, connect_proxy

HELPER_PATHS = frozenset(path for _, path in CENTRAL_IDENTITY_ROUTES if path.startswith("/__/"))
INIT_PATH = "/__/firebase/init.json"
MAX_HELPER_BYTES = 2 * 1024 * 1024
MAX_QUERY_BYTES = 8192


class FirebaseHelpers:
    def __init__(self, setup, proxy, *, public_config=None):
        self.host = setup.realm.project_id + ".firebaseapp.com"
        self.proxy = urlsplit(connect_proxy(proxy)["https"])
        self.public_config = public_config

    def fetch(self, path, query):
        if path not in HELPER_PATHS or path == INIT_PATH or len(query) > MAX_QUERY_BYTES:
            raise ProviderUnavailable()
        connection = HTTPSConnection(self.proxy.hostname, self.proxy.port, timeout=TIMEOUT_SECONDS)
        connection.set_tunnel(self.host, 443)
        end = monotonic() + TIMEOUT_SECONDS
        try:
            target = path + ("?" + query.decode("ascii") if query else "")
            # The browser's cookies, authentication and forwarding headers stay local.
            connection.request("GET", target, headers={"Host": self.host})
            result = connection.getresponse()
            expected = (
                {"application/javascript", "text/javascript"}
                if path.endswith(".js")
                else {"text/html"}
            )
            if result.status != 200 or result.headers.get_content_type() not in expected:
                raise ProviderUnavailable()
            body = bytearray()
            while len(body) <= MAX_HELPER_BYTES:
                remaining = end - monotonic()
                if remaining <= 0:
                    raise ProviderUnavailable()
                remote = getattr(getattr(result.fp, "raw", None), "_sock", None)
                if remote is not None:
                    remote.settimeout(remaining)
                chunk = result.read1(min(65536, MAX_HELPER_BYTES + 1 - len(body)))
                if not chunk:
                    return bytes(body), result.headers["Content-Type"]
                body.extend(chunk)
            raise ProviderUnavailable()
        except OSError, ValueError, HTTPException:
            raise ProviderUnavailable() from None
        finally:
            connection.close()

    async def __call__(self, scope, receive, send):
        from app.platform.hosted_security_headers import API_SECURITY_HEADERS

        path, query = scope["path"], scope["query_string"]
        headers = dict(API_SECURITY_HEADERS)
        if scope["method"] != "GET" or scope.get("raw_path") != path.encode("ascii"):
            response = Response(status_code=404, headers=headers)
        elif path == INIT_PATH:
            response = (
                JSONResponse(self.public_config, headers=headers)
                if self.public_config
                else Response(status_code=503, headers=headers)
            )
        else:
            try:
                body, mime = await run_in_threadpool(self.fetch, path, query)
                response_headers = {**headers, "Content-Type": mime}
                if path in {"/__/auth/handler", "/__/auth/iframe"}:
                    # Firebase-owned auth helper HTML dynamically loads gapi/gstatic scripts
                    # and cross-origin OAuth frames; retain HSTS/Permissions-Policy/nosniff
                    # while letting Firebase's helper execute unmodified.
                    response_headers.pop("Content-Security-Policy", None)
                response = Response(body, headers=response_headers)
            except ProviderUnavailable:
                response = Response(status_code=503, headers=headers)
        await response(scope, receive, send)
