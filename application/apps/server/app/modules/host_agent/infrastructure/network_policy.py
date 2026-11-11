"""Protected deterministic bridges; no caller-selected host paths, IPs or interfaces."""

from dataclasses import dataclass
from hashlib import sha256
import ipaddress

from app.modules.host_agent.application.dispatch import HostAgentDenied


@dataclass(frozen=True)
class NetworkSettings:
    # Protected host setup, never HTTP or an Operator field. Pools must be reserved
    # against host/VPC/Docker routes during qualification before any bridge creation.
    ipv4_pool: str
    ipv6_pool: str
    first_project: int
    gateway_uid: int
    tunnel_uid: int
    proxy_uid: int
    gateway_port: int = 8080
    proxy_port: int = 1080

    def __post_init__(self):
        v4, v6 = self.pools
        if (
            v4.version != 4
            or not v4.subnet_of(ipaddress.ip_network("10.0.0.0/8"))
            or v4.prefixlen > 30
            or v6.version != 6
            or not v6.subnet_of(ipaddress.ip_network("fc00::/7"))
            or v6.prefixlen > 64
            or type(self.first_project) is not int
            or self.first_project <= 0
            or any(type(uid) is not int or uid <= 0 for uid in self.uids)
            or len(set(self.uids)) != 3
            or any(
                type(port) is not int or not 1024 <= port <= 65535
                for port in (self.gateway_port, self.proxy_port)
            )
            or self.gateway_port == self.proxy_port
        ):
            raise HostAgentDenied()

    @property
    def pools(self):
        return ipaddress.ip_network(self.ipv4_pool), ipaddress.ip_network(self.ipv6_pool)

    @property
    def uids(self):
        return self.gateway_uid, self.tunnel_uid, self.proxy_uid


def bridge(row, settings):
    slot = row.workspace_project - settings.first_project
    v4, v6 = settings.pools
    if not 0 <= slot < min(v4.num_addresses // 4, v6.num_addresses // (2**64)):
        raise HostAgentDenied()
    four = ipaddress.ip_network((int(v4.network_address) + slot * 4, 30))
    six = ipaddress.IPv6Network((int(v6.network_address) + slot * 2**64, 64))
    name = "epm-n-" + row.binding_id + "-" + str(row.resource_generation)
    return Bridge(
        name=name,
        interface="epm-" + sha256(name.encode()).hexdigest()[:11],
        ipv4=str(four),
        ipv6=str(six),
        gateway4=str(four[1]),
        gateway6=str(six[1]),
        address4=str(four[2]),
        address6=str(six[2]),
        proxy_port=settings.proxy_port,
    )


@dataclass(frozen=True)
class Bridge:
    name: str
    interface: str
    ipv4: str
    ipv6: str
    gateway4: str
    gateway6: str
    address4: str
    address6: str
    proxy_port: int

    def spec(self):
        return {
            "Name": self.name,
            "Driver": "bridge",
            "Scope": "local",
            "Internal": True,
            "EnableIPv6": True,
            "Attachable": False,
            "Ingress": False,
            "IPAM": {
                "Driver": "default",
                "Options": {},
                "Config": [
                    {"Subnet": self.ipv4, "Gateway": self.gateway4, "IPRange": ""},
                    {"Subnet": self.ipv6, "Gateway": self.gateway6, "IPRange": ""},
                ],
            },
            "Options": {
                "com.docker.network.bridge.name": self.interface,
                "com.docker.network.bridge.enable_icc": "false",
                "com.docker.network.bridge.enable_ip_masquerade": "false",
            },
        }

    def endpoint(self):
        return {
            self.name: {
                "IPAMConfig": {
                    "IPv4Address": self.address4,
                    "IPv6Address": self.address6,
                }
            }
        }

    def verify(self, actual):
        if actual is None:
            raise HostAgentDenied()
        spec = self.spec()
        for key in ("Name", "Driver", "Scope", "Internal", "EnableIPv6", "Attachable", "Ingress"):
            if actual.get(key) != spec[key]:
                raise HostAgentDenied()
        # Docker 29.9 omits an empty IPRange in inspection. Restore only that
        # explicit empty default; nonempty ranges and every other field stay exact.
        ipam = actual.get("IPAM")
        if isinstance(ipam, dict) and isinstance(ipam.get("Config"), list):
            ipam = {**ipam, "Config": [{"IPRange": "", **entry} for entry in ipam["Config"]]}
        if actual.get("Options") != spec["Options"] or ipam != spec["IPAM"]:
            raise HostAgentDenied()
        # The only admitted application endpoint is the fixed dual-stack address.
        for peer in actual.get("Containers", {}).values():
            if (
                peer.get("IPv4Address") != self.address4 + "/30"
                or peer.get("IPv6Address") != self.address6 + "/64"
            ):
                raise HostAgentDenied()
