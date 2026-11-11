"""One atomic inet table before Docker filter rules; no global flush or INPUT-only policy."""

import ipaddress
import json
from pathlib import Path
import subprocess

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable

TABLE = "epm_h02"


def match(left, right, op="=="):
    return {"match": {"op": op, "left": left, "right": right}}


def meta(key, value):
    return match({"meta": {"key": key}}, value)


def port(key, value):
    return match({"payload": {"protocol": "tcp", "field": key}}, value)


def address(protocol, field, value):
    if "/" in value:
        network = ipaddress.ip_network(value)
        value = {"prefix": {"addr": str(network.network_address), "len": network.prefixlen}}
    return match({"payload": {"protocol": protocol, "field": field}}, value)


def established():
    return match({"ct": {"key": "state"}}, "established", "in")


def firewall_document(bridges, settings):
    chains = [
        {
            "family": "inet",
            "table": TABLE,
            "name": name,
            "type": "filter",
            "hook": name,
            "prio": -10,
            "policy": "accept",
        }
        for name in ("input", "output", "forward")
    ]
    rules = []

    def rule(chain, *expr, verdict="accept"):
        rules.append(
            {
                "family": "inet",
                "table": TABLE,
                "chain": chain,
                "expr": [*expr, {"counter": None}, {verdict: None}],
            }
        )

    # Restrict the host-side tunnel boundary independently of Caddy host matching.
    rule(
        "output",
        meta("oifname", "lo"),
        meta("l4proto", "tcp"),
        port("dport", settings.gateway_port),
        meta(
            "skuid",
            settings.tunnel_uid,
        ),
    )
    rule(
        "output",
        meta("oifname", "lo"),
        meta("l4proto", "tcp"),
        port("dport", settings.gateway_port),
        verdict="drop",
    )
    for target in bridges:
        for protocol, family, own, gateway in (
            ("ip", "ipv4", target.address4, target.gateway4),
            ("ip6", "ipv6", target.address6, target.gateway6),
        ):
            common = [meta("nfproto", family), meta("l4proto", "tcp")]
            rule(
                "output",
                *common,
                meta("skuid", settings.gateway_uid),
                address(protocol, "daddr", own),
                port("dport", 8000),
            )
            rule(
                "output",
                *common,
                meta("skuid", settings.proxy_uid),
                established(),
                address(protocol, "daddr", own),
                port("sport", settings.proxy_port),
            )
            rule(
                "input",
                *common,
                meta("iifname", target.interface),
                address(protocol, "saddr", own),
                address(protocol, "daddr", gateway),
                port("dport", settings.proxy_port),
            )
            rule(
                "input",
                *common,
                meta("iifname", target.interface),
                established(),
                address(protocol, "saddr", own),
                port("sport", 8000),
            )
        # IPv6 neighbor discovery is link-scoped, not a grant to host services.
        for chain, key in (("input", "iifname"), ("output", "oifname")):
            rule(
                chain,
                meta(key, target.interface),
                meta("l4proto", "ipv6-icmp"),
                match(
                    {"payload": {"protocol": "icmpv6", "field": "type"}},
                    {"set": ["nd-neighbor-solicit", "nd-neighbor-advert"]},
                    "in",
                ),
                match({"payload": {"protocol": "ip6", "field": "hoplimit"}}, 255),
            )
    # Host daemons must not bypass their file isolation by fetching VM credentials
    # from metadata/private control endpoints. Root bootstrap remains a separate role.
    for protocol, ranges in (
        (
            "ip",
            ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10"),
        ),
        ("ip6", ("fc00::/7", "fe80::/10")),
    ):
        for network in ranges:
            rule(
                "output",
                meta("skuid", {"set": list(settings.uids)}),
                address(protocol, "daddr", network),
                verdict="drop",
            )
    # No physical/loopback peer becomes an open outbound proxy. Only the exact
    # operator bridge/address exceptions above can reach this listener.
    rule("input", meta("l4proto", "tcp"), port("dport", settings.proxy_port), verdict="drop")
    # Reserved prefix also covers unexpected/stale bridges. No established shortcut:
    # a sibling/metadata flow established before reload is still dropped.
    for chain, key in (
        ("input", "iifname"),
        ("output", "oifname"),
        ("forward", "iifname"),
        ("forward", "oifname"),
    ):
        rule(chain, meta(key, "epm-*"), verdict="drop")
    for protocol, pool in zip(("ip", "ip6"), settings.pools, strict=True):
        rule(
            "output",
            meta("nfproto", "ipv4" if protocol == "ip" else "ipv6"),
            address(protocol, "daddr", str(pool)),
            verdict="drop",
        )
    commands = [
        {"add": {"table": {"family": "inet", "name": TABLE}}},
        {"flush": {"table": {"family": "inet", "name": TABLE}}},
    ]
    commands += [{"add": {"chain": chain}} for chain in chains]
    commands += [{"add": {"rule": row}} for row in rules]
    return {"nftables": commands}


def normalized_expr(expressions):
    # nft removes redundant dependencies inferred from payload expressions and uses
    # equality for anonymous sets. Preserve every nonredundant predicate/verdict.
    protocols = {
        entry["match"]["left"]["payload"]["protocol"]
        for entry in expressions
        if "payload" in entry.get("match", {}).get("left", {})
    }
    redundant = []
    if "ip" in protocols:
        redundant.append(meta("nfproto", "ipv4"))
    if "ip6" in protocols:
        redundant.append(meta("nfproto", "ipv6"))
    for protocol in ("tcp", "icmpv6"):
        if protocol in protocols:
            redundant.append(meta("l4proto", "ipv6-icmp" if protocol == "icmpv6" else protocol))
    result = []
    for entry in expressions:
        if "counter" in entry:
            result.append({"counter": None})
            continue
        if entry in redundant:
            continue
        condition = entry.get("match")
        if condition and isinstance(condition.get("right"), dict) and "set" in condition["right"]:
            right = {
                "set": sorted(
                    condition["right"]["set"], key=lambda value: json.dumps(value, sort_keys=True)
                )
            }
            condition = condition | {"right": right}
            entry = {"match": condition}
        if (
            condition
            and condition["op"] == "in"
            and isinstance(condition["right"], dict)
            and "set" in condition["right"]
        ):
            entry = {"match": condition | {"op": "=="}}
        result.append(entry)
    return result


def normalized(document):
    output = []
    for entry in document.get("nftables", []):
        if "metainfo" in entry:
            continue
        kind, value = next(iter(entry.items()))
        if kind not in {"table", "chain", "rule"}:
            raise HostAgentDenied()
        value = {key: item for key, item in value.items() if key not in {"handle"}}
        if kind == "rule":
            value["expr"] = normalized_expr(value["expr"])
        output.append({kind: value})
    # nft lists rules grouped by chain; order *within* each chain is authoritative.
    fixed = [entry for entry in output if "rule" not in entry]
    chains = [entry["chain"]["name"] for entry in fixed if "chain" in entry]
    return fixed + [
        entry
        for chain in chains
        for entry in output
        if "rule" in entry and entry["rule"]["chain"] == chain
    ]


def expected(document):
    return normalized(
        {"nftables": [entry["add"] for entry in document["nftables"] if "add" in entry]}
    )


class NetworkFirewall:
    def __init__(self, settings):
        self.settings = settings

    @staticmethod
    def _run(arguments, data=None):
        try:
            result = subprocess.run(
                ["/usr/sbin/nft", "-j", *arguments],
                input=data,
                capture_output=True,
                timeout=10,
                check=True,
            )
            if len(result.stdout) > 8 * 1024 * 1024:
                raise HostAgentUnavailable()
            return json.loads(result.stdout) if result.stdout else None
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise HostAgentUnavailable() from error

    @staticmethod
    def prerequisites():
        # Host setup loads br_netfilter; never silently alter the host's sysctls here.
        for name in ("bridge-nf-call-iptables", "bridge-nf-call-ip6tables"):
            if Path("/proc/sys/net/bridge", name).read_text().strip() != "1":
                raise HostAgentUnavailable()

    def apply(self, bridges):
        self.prerequisites()
        document = firewall_document(bridges, self.settings)
        self._run(["-f", "-"], json.dumps(document).encode())
        self.verify(bridges)

    def verify(self, bridges):
        self.prerequisites()
        actual = self._run(["list", "table", "inet", TABLE])
        if normalized(actual) != expected(firewall_document(bridges, self.settings)):
            raise HostAgentUnavailable()
