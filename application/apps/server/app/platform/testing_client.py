"""Explicit loopback CLI client for domain API tests, not a browser-policy bypass."""

from fastapi.testclient import TestClient

from app.platform.browser_transport import LOCAL_CLIENT_HEADER, LOCAL_CLIENT_VALUE


class LocalApiClient(TestClient):
    def __init__(self, app, *args, **kwargs):
        kwargs.setdefault("base_url", "http://127.0.0.1:8000")
        kwargs.setdefault("headers", {LOCAL_CLIENT_HEADER: LOCAL_CLIENT_VALUE})
        super().__init__(app, *args, **kwargs)
