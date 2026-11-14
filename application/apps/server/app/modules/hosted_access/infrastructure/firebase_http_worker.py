"""Private bounded HTTPS subprocess; never register as a route or arbitrary launcher."""

import json
import sys

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.firebase_rest import MAX_REQUEST, _SocketHttp
from app.modules.hosted_access.infrastructure.firebase_tokens import unique_json


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise ProviderDenied()
        payload = unique_json(raw)
        if set(payload) != {"url", "body", "bearer", "proxy"}:
            raise ProviderDenied()
        bearer = payload["bearer"]
        if bearer is not None and (
            not isinstance(bearer, str) or len(bearer) > 16384 or "\r" in bearer or "\n" in bearer
        ):
            raise ProviderDenied()
        response = _SocketHttp(payload["proxy"]).request(
            payload["url"], payload["body"], bearer=bearer
        )
        message = {"state": "ok", "data": response.data, "cache_seconds": response.cache_seconds}
    except ProviderDenied:
        message = {"state": "denied"}
    except ProviderUnavailable, ValueError, TypeError, KeyError, OSError:
        message = {"state": "unavailable"}
    sys.stdout.write(json.dumps(message, separators=(",", ":")))


if __name__ == "__main__":
    main()
