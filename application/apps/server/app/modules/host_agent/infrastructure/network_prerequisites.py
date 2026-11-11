"""Fail before network creation when reserved pools overlap unrelated host/Docker routes."""

import ipaddress
import json
import subprocess

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable


class HostNetworkPrerequisites:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    @staticmethod
    def routes():
        rows = []
        for family in ("-4", "-6"):
            result = subprocess.run(
                ["/usr/sbin/ip", "-j", family, "route", "show", "table", "all"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            if len(result.stdout) > 2 * 1024 * 1024:
                raise HostAgentUnavailable()
            rows.extend(json.loads(result.stdout))
        return rows

    def verify(self, targets):
        owned = {target.name: target for target in targets}
        interfaces = {target.interface for target in targets}
        pools = self.settings.pools
        for actual in self.engine.networks():
            if actual["Name"] in owned:
                owned[actual["Name"]].verify(actual)
                continue
            for entry in actual.get("IPAM", {}).get("Config") or ():
                network = ipaddress.ip_network(entry["Subnet"])
                if any(network.overlaps(pool) for pool in pools):
                    raise HostAgentDenied()
        for route in self.routes():
            destination = route.get("dst", "default")
            if destination == "default":
                continue
            network = ipaddress.ip_network(destination, strict=False)
            if network.prefixlen and any(network.overlaps(pool) for pool in pools):
                if route.get("dev") not in interfaces:
                    raise HostAgentDenied()
