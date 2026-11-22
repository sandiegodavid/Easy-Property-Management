"""Offline provider transport failures; no live credentials or external requests."""

import io
import json
import subprocess
import urllib.error
import urllib.request
from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure import firebase_rest as transport


def response(content):
    value = Mock()
    value.__enter__ = Mock(return_value=value)
    value.__exit__ = Mock(return_value=False)
    value.headers = {"Cache-Control": "public, max-age=600"}
    # A minimal stream avoids manufacturing a real socket or TLS connection.
    value.fp = Mock(raw=None)
    value.read1.side_effect = io.BytesIO(content).read1
    return value


@pytest.mark.parametrize("status", [301, 302, 307, 308, 429, 500, 503])
def test_http_failure_never_retries_or_follows_redirect(status):
    http = transport._SocketHttp()
    http.opener = Mock()
    http.opener.open.side_effect = urllib.error.HTTPError(
        transport.ID_CERTS, status, "private provider response", {}, None
    )
    with pytest.raises(ProviderUnavailable):
        http.request(transport.ID_CERTS)
    assert http.opener.open.call_count == 1
    request = urllib.request.Request(transport.ID_CERTS)
    assert (
        transport.NoRedirect().redirect_request(
            request, None, status, "redirect", {}, "https://untrusted.invalid/"
        )
        is None
    )


@pytest.mark.parametrize(
    "content,error",
    [
        (b"x" * (transport.MAX_RESPONSE + 1), ProviderUnavailable),
        (b"not-json", ProviderUnavailable),
        (b'{"key":1,"key":2}', ProviderUnavailable),
        (b"[]", ProviderUnavailable),
    ],
)
def test_response_bounds_and_malformed_json(content, error):
    http = transport._SocketHttp()
    http.opener = Mock()
    stream = response(content)
    http.opener.open.return_value = stream
    with pytest.raises(error):
        http.request(transport.ID_CERTS)
    assert http.opener.open.call_count == 1
    assert sum(call.args[0] for call in stream.read1.call_args_list) <= (transport.MAX_RESPONSE + 1)


def test_slow_response_exhausts_absolute_deadline(monkeypatch):
    http = transport._SocketHttp()
    http.opener = Mock()
    http.opener.open.return_value = response(b"{}")
    monkeypatch.setattr(transport.time, "monotonic", Mock(side_effect=[0, 6]))
    with pytest.raises(ProviderUnavailable):
        http.request(transport.ID_CERTS)
    http.opener.open.return_value.read1.assert_not_called()
    assert http.opener.open.call_count == 1


@pytest.mark.parametrize(
    "url,body",
    [
        ("http://www.googleapis.com/", None),
        (transport.ID_CERTS + "?redirect=1", None),
        (transport.ID_CERTS, {}),
        ("https://identitytoolkit.googleapis.com.evil.invalid/v1/accounts:sendOobCode?key=x", {}),
        ("https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key=x&key=y", {}),
        ("https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key=x#fragment", {}),
        ("https://identitytoolkit.googleapis.com/v1/projects/example-project/accounts:delete", {}),
    ],
)
def test_unregistered_endpoint_never_starts_worker(monkeypatch, url, body):
    run = Mock()
    monkeypatch.setattr(transport.subprocess, "run", run)
    with pytest.raises(ProviderDenied):
        transport.ProviderHttp().request(url, body)
    run.assert_not_called()


@pytest.mark.parametrize(
    "stdout,returncode,error",
    [
        (b"{}", 1, ProviderUnavailable),
        (b"x" * (transport.MAX_RESPONSE * 2 + 1), 0, ProviderUnavailable),
        (b"not-json", 0, ProviderUnavailable),
        (b'{"state":"ok","data":[],"cache_seconds":1}', 0, ProviderUnavailable),
        (b'{"state":"ok","data":{},"cache_seconds":true}', 0, ProviderUnavailable),
        (b'{"state":"ok","data":{},"cache_seconds":-1}', 0, ProviderUnavailable),
        (b'{"state":"denied"}', 0, ProviderDenied),
    ],
)
def test_worker_protocol_failure_releases_admission(monkeypatch, stdout, returncode, error):
    run = Mock(return_value=subprocess.CompletedProcess([], returncode, stdout, b""))
    semaphore = Mock()
    semaphore.acquire.return_value = True
    monkeypatch.setattr(transport.subprocess, "run", run)
    monkeypatch.setattr(transport, "ACTIVE_REQUESTS", semaphore)
    with pytest.raises(error):
        transport.ProviderHttp().request(transport.ID_CERTS)
    assert run.call_count == 1
    semaphore.release.assert_called_once_with()


def test_valid_worker_response_keeps_credentials_in_pipe(monkeypatch):
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, b'{"state":"ok","data":{},"cache_seconds":600}', b""
        )
    )
    monkeypatch.setattr(transport.subprocess, "run", run)
    result = transport.ProviderHttp().request(transport.ID_CERTS, bearer="private-proof")
    assert result == transport.JsonResponse({}, 600)
    assert "private-proof" not in repr(run.call_args.args)
    assert json.loads(run.call_args.kwargs["input"])["bearer"] == "private-proof"


@pytest.mark.parametrize("code", [401, 403])
def test_server_bearer_401_403_maps_to_provider_unavailable(code):
    http = transport._SocketHttp()
    http.opener = Mock()
    url = "https://identitytoolkit.googleapis.com/v1/projects/example-project/accounts:lookup"
    http.opener.open.side_effect = urllib.error.HTTPError(
        url, code, "auth", hdrs={}, fp=io.BytesIO(b"{}")
    )
    with pytest.raises(ProviderUnavailable):
        http.request(url, {"localId": ["uid"]}, bearer="expired-token")
