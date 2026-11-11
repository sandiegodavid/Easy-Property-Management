"""CONNECT parsing never admits arbitrary HTTP requests or secret-bearing headers."""

from io import BytesIO

import pytest

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.egress_proxy import authority_from_request


def test_connect_accepts_only_named_https_authority():
    assert (
        authority_from_request(
            BytesIO(
                b"CONNECT login.example.com:443 HTTP/1.1\r\nHost: login.example.com:443\r\n\r\n"
            )
        )
        == "login.example.com:443"
    )


@pytest.mark.parametrize(
    "data",
    [
        b"GET http://169.254.169.254/ HTTP/1.1\r\n\r\n",
        b"CONNECT login.example.com:443 HTTP/1.0\r\nHost: login.example.com:443\r\n\r\n",
        b"CONNECT login.example.com:443 HTTP/1.1\r\nHost: evil.example.com:443\r\n\r\n",
        b"CONNECT login.example.com:443 HTTP/1.1\r\nHost: login.example.com:443\r\nContent-Length: 12\r\n\r\n",
        b"CONNECT login.example.com:443 HTTP/1.1\r\nHost: login.example.com:443\r\nProxy-Authorization: private\r\n\r\n",
        b"CONNECT login.example.com:443 HTTP/1.1\r\nHost: login.example.com:443\r\nHost: evil.example.com:443\r\n\r\n",
        b"CONNECT login.example.com:443 HTTP/1.1\r\nHost: login.example.com:443\r\n",
        b"CONNECT " + b"x" * 4096 + b" HTTP/1.1\r\n\r\n",
    ],
)
def test_malformed_or_unbounded_requests_reject(data):
    with pytest.raises(HostAgentDenied):
        authority_from_request(BytesIO(data))


def test_established_tunnel_never_injects_http_on_relay_failure(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import app.modules.host_agent.infrastructure.egress_proxy as module

    writes = []
    client = SimpleNamespace(sendall=writes.append)
    monkeypatch.setattr(module, "connect_numeric", lambda endpoints: nullcontext(object()))

    def failed(*args):
        raise ConnectionResetError()

    monkeypatch.setattr(module, "read_client_hello", lambda *args: b"hello")
    monkeypatch.setattr(
        module,
        "connect_numeric",
        lambda endpoints: nullcontext(SimpleNamespace(sendall=lambda data: None)),
    )
    monkeypatch.setattr(module, "relay", failed)
    module.ProxyApplication(SimpleNamespace(resolve=lambda value: ())).serve(
        client,
        BytesIO(b"CONNECT login.example.com:443 HTTP/1.1\r\nHost: login.example.com:443\r\n\r\n"),
    )
    assert writes == [b"HTTP/1.1 200 Connection Established\r\n\r\n"]


def test_numeric_connect_uses_only_checked_address_and_closes_failed_socket(monkeypatch):
    from types import SimpleNamespace
    import socket
    import app.modules.host_agent.infrastructure.egress_proxy as module

    calls = []

    def connect(address):
        calls.append(address)
        raise OSError()

    sock = SimpleNamespace(
        settimeout=lambda seconds: None, connect=connect, close=lambda: calls.append("closed")
    )
    monkeypatch.setattr(module.socket, "socket", lambda *args: sock)
    with pytest.raises(HostAgentDenied):
        module.connect_numeric(((socket.AF_INET, ("8.8.8.8", 443)),))
    assert calls == [("8.8.8.8", 443), "closed"]


def test_connect_preserves_early_tunnel_bytes_without_forwarding_proxy_headers():
    import socket
    from threading import Thread
    from types import SimpleNamespace
    from app.modules.host_agent.infrastructure.egress_proxy import ProxyServer

    received = []
    from app.modules.host_agent.tests.test_tls_hello import hello

    payload = hello("login.example.com")
    with socket.socket() as upstream:
        upstream.bind(("127.0.0.1", 0))
        upstream.listen(1)
        upstream.settimeout(3)
        target = upstream.getsockname()

        def respond():
            with upstream.accept()[0] as peer:
                peer.settimeout(3)
                received.append(peer.recv(4096))
                peer.sendall(b"synthetic-tls-response")

        # Explicit synthetic policy admits this local echo only; production EndpointPolicy
        # rejects loopback. This proves relay framing, not network isolation or real TLS.
        def resolve(authority):
            assert authority == "login.example.com:443"
            return ((socket.AF_INET, target),)

        with ProxyServer(("127.0.0.1", 0), SimpleNamespace(resolve=resolve)) as proxy:
            echo = Thread(target=respond)
            worker = Thread(target=lambda: proxy.serve_forever(poll_interval=0.01))
            echo.start()
            worker.start()
            try:
                with socket.create_connection(proxy.server_address, timeout=3) as client:
                    client.sendall(
                        b"CONNECT login.example.com:443 HTTP/1.1\r\n"
                        b"Host: login.example.com:443\r\n\r\n" + payload
                    )
                    response = b""
                    while chunk := client.recv(4096):
                        response += chunk
                assert response == (
                    b"HTTP/1.1 200 Connection Established\r\n\r\nsynthetic-tls-response"
                )
                assert received == [payload]
            finally:
                proxy.shutdown()
                worker.join(timeout=3)
                echo.join(timeout=3)
            assert not worker.is_alive() and not echo.is_alive()


def test_running_proxy_denies_metadata_and_plain_http_without_network_lookup():
    import socket
    from threading import Thread
    from app.modules.host_agent.infrastructure.egress_proxy import ProxyServer
    from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy

    with ProxyServer(("127.0.0.1", 0), EndpointPolicy()) as proxy:
        worker = Thread(target=lambda: proxy.serve_forever(poll_interval=0.01))
        worker.start()
        try:
            for request in (
                b"GET http://169.254.169.254/ HTTP/1.1\r\n\r\n",
                b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: 169.254.169.254:443\r\n\r\n",
                b"CONNECT unregistered.example.com:443 HTTP/1.1\r\nHost: unregistered.example.com:443\r\n\r\n",
            ):
                with socket.create_connection(proxy.server_address, timeout=3) as client:
                    client.sendall(request)
                    assert client.recv(4096).startswith(b"HTTP/1.1 403 Forbidden\r\n")
        finally:
            proxy.shutdown()
            worker.join(timeout=3)
        assert not worker.is_alive()


def test_proxy_restart_reuse_does_not_allow_two_live_listeners():
    from app.modules.host_agent.infrastructure.egress_proxy import ProxyServer
    from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy

    with ProxyServer(("127.0.0.1", 0), EndpointPolicy()) as first:
        address = first.server_address
        with pytest.raises(OSError):
            ProxyServer(address, EndpointPolicy())
    with ProxyServer(address, EndpointPolicy()) as restarted:
        assert restarted.server_address == address


def test_server_close_terminates_idle_client_and_waits_for_workers():
    import socket
    from threading import Thread
    from app.modules.host_agent.infrastructure.egress_proxy import ProxyServer
    from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy

    server = ProxyServer(("127.0.0.1", 0), EndpointPolicy())
    worker = Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    worker.start()
    client = socket.create_connection(server.server_address, timeout=2)
    try:
        client.sendall(b"CONNECT incomplete")
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive() and not server.clients
        try:
            remaining = client.recv(4096)
        except ConnectionResetError:
            remaining = b""  # Closing a peer with unread bytes may reset on macOS.
        assert remaining == b""
    finally:
        client.close()
        server.server_close()


def test_header_deadline_is_overall_not_reset_for_each_byte(monkeypatch):
    from types import SimpleNamespace
    import app.modules.host_agent.infrastructure.egress_proxy as module

    times = iter((0, 1, 5, 11))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    client = SimpleNamespace(recv=lambda size: b"x", settimeout=lambda value: None)
    with pytest.raises(HostAgentDenied):
        module.DeadlineLines(client).readline(20)
