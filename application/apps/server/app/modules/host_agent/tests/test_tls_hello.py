"""Real OpenSSL ClientHello fixtures for strict HTTPS endpoint/SNI admission."""

import ssl
from types import SimpleNamespace

import pytest

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.tls_hello import read_client_hello


def hello(host):
    output = ssl.MemoryBIO()
    connection = ssl.create_default_context().wrap_bio(
        ssl.MemoryBIO(), output, server_side=False, server_hostname=host
    )
    try:
        connection.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return output.read()


def source(value, split=1000):
    chunks = bytearray(value)

    def recv(size):
        size = min(size, split)
        result = bytes(chunks[:size])
        del chunks[:size]
        return result

    return SimpleNamespace(recv=recv, settimeout=lambda value: None)


def test_real_tls_hello_is_preserved_with_fragmented_reads():
    data = hello("approved.example.com")
    assert read_client_hello(source(data, split=1), "approved.example.com") == data


def test_tls_name_cannot_front_a_different_connect_authority():
    with pytest.raises(HostAgentDenied):
        read_client_hello(source(hello("other.example.com")), "approved.example.com")


@pytest.mark.parametrize(
    "data", [b"GET / HTTP/1.1\r\n\r\n", b"SSH-2.0-probe", b"\x16\x03\x01\xff\xff", b""]
)
def test_non_tls_or_unbounded_input_is_not_relayed(data):
    with pytest.raises(HostAgentDenied):
        read_client_hello(source(data), "approved.example.com")
