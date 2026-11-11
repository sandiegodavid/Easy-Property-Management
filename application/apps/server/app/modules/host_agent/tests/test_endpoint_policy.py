"""Approved HTTPS names do not admit metadata, private DNS or redirect targets."""

import socket

import pytest

from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy
from app.modules.host_agent.application.dispatch import HostAgentDenied


def resolver(address):
    return lambda *args, **kwargs: [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 443),
        )
    ]


def test_default_policy_has_no_unregistered_backup_or_identity_endpoints():
    with pytest.raises(HostAgentDenied):
        EndpointPolicy().resolve("login.example.com:443", resolver=resolver("8.8.8.8"))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.100.100.200",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:8.8.8.8",
        "0.0.0.0",
        "224.0.0.1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::a9fe:a9fe",
        "2002:0a00:0001::1",
        "2001::1",
    ],
)
def test_allowed_hostname_cannot_rebind_to_private_address(address):
    with pytest.raises(HostAgentDenied):
        EndpointPolicy(("login.example.com",)).resolve(
            "login.example.com:443", resolver=resolver(address)
        )


def test_numeric_endpoint_is_pinned_after_resolution_and_rechecked_next_connect():
    policy = EndpointPolicy(("login.example.com",))
    assert policy.resolve("login.example.com:443", resolver=resolver("8.8.8.8")) == (
        (socket.AF_INET, ("8.8.8.8", 443)),
    )
    with pytest.raises(HostAgentDenied):
        policy.resolve("login.example.com:443", resolver=resolver("10.0.0.1"))


@pytest.mark.parametrize(
    "authority",
    [
        "169.254.169.254:443",
        "[::1]:443",
        "login.example.com:80",
        "login.example.com:0443",
        "LOGIN.example.com:443",
        "login.example.com.:443",
        "evil.example.com:443",
        "login.example.com:443/path",
        "login.example.com@evil.example.com:443",
    ],
)
def test_unregistered_or_noncanonical_connect_authority_rejects(authority):
    with pytest.raises(HostAgentDenied):
        EndpointPolicy(("login.example.com",)).resolve(authority, resolver=resolver("8.8.8.8"))


@pytest.mark.parametrize("host", ["a.-bad.com", "a.bad-.com", "a..com", "a." + "x" * 64 + ".com"])
def test_malformed_endpoint_labels_reject(host):
    with pytest.raises(HostAgentDenied):
        EndpointPolicy((host,))


def test_mixed_public_and_private_dns_answer_rejects_entire_result():
    def mixed(*args, **kwargs):
        return resolver("8.8.8.8")() + resolver("169.254.169.254")()

    with pytest.raises(HostAgentDenied):
        EndpointPolicy(("login.example.com",)).resolve("login.example.com:443", resolver=mixed)
