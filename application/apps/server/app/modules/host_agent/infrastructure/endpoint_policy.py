"""Closed HTTPS CONNECT endpoint policy; names never authorize private resolved IPs."""

from dataclasses import dataclass
import ipaddress
import re
import socket

from app.modules.host_agent.infrastructure.bounded_dns import resolve as bounded_resolve
from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable

DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
TRANSLATION_PREFIXES = tuple(
    ipaddress.ip_network(value)
    for value in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
)


def hostname(value):
    if (
        not isinstance(value, str)
        or len(value) > 253
        or "." not in value
        or any(not DOMAIN.fullmatch(label) for label in value.split("."))
    ):
        raise HostAgentDenied()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise HostAgentDenied()


@dataclass(frozen=True)
class EndpointPolicy:
    hosts: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            type(self.hosts) is not tuple
            or len(self.hosts) > 64
            or len(set(self.hosts)) != len(self.hosts)
        ):
            raise HostAgentDenied()
        for host in self.hosts:
            hostname(host)

    def resolve(self, authority, *, resolver=bounded_resolve):
        if authority.count(":") != 1:
            raise HostAgentDenied()
        host, port = authority.split(":")
        if port != "443" or hostname(host) not in self.hosts:
            raise HostAgentDenied()
        # Re-resolve every CONNECT; reject the whole result if any address is
        # private/link-local/loopback/mapped. Connect to pinned numeric results only.
        rows = resolver(host, 443, type=socket.SOCK_STREAM)
        if not rows or len(rows) > 16:
            raise HostAgentUnavailable()
        endpoints = []
        for family, kind, protocol, canonical, address in rows:
            ip = ipaddress.ip_address(address[0])
            if (
                family not in {socket.AF_INET, socket.AF_INET6}
                or kind != socket.SOCK_STREAM
                or protocol not in {0, socket.IPPROTO_TCP}
                or address[1] != 443
                or (family == socket.AF_INET) != (ip.version == 4)
                or any(ip in prefix for prefix in TRANSLATION_PREFIXES)
                or not ip.is_global
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_reserved
                or getattr(ip, "ipv4_mapped", None) is not None
                or "%" in address[0]
            ):
                raise HostAgentDenied()
            endpoints.append((family, address))
        return tuple(endpoints)
