"""Trusted read-only host adapters; never installed in an operator process."""

from pathlib import Path

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_admin.application.console import (
    AccessObservation,
    DiscrepancyObservation,
    RegisteredOperator,
    RuntimeObservation,
    TunnelObservation,
)


class HostConsoleInventory:
    def __init__(self, source, discovery, reports, recovery=None):
        self.source, self.discovery, self.reports = source, discovery, reports
        self.recovery = recovery

    def records(self):
        return [
            RegisteredOperator(
                key=item.key,
                name=f"Operator {item.key.upper()}",
                email=item.email,
                hostname=item.hostname,
                release=item.release,
                profile=item.profile,
                registered_revision=item.revision,
            )
            for item in self.source.inventory.list()
        ]

    def observe(self, section, instance):
        if section == "capacity":
            return self.reports.snapshot()
        if section == "discrepancies":
            registered = {item.key for item in self.source.inventory.list()}
            found = set(self.discovery.keys())
            return DiscrepancyObservation(
                unregistered=sorted(found - registered), missing=sorted(registered - found)
            )
        if section == "tunnel":
            state = self.discovery.systemctl(
                "show", "epm-cloudflared.service", "--property=ActiveState", "--value"
            ).strip()
            startup = self.discovery.systemctl(
                "show", "epm-cloudflared.service", "--property=UnitFileState", "--value"
            ).strip()
            return TunnelObservation(
                service=state, startup=startup if startup in {"enabled", "disabled"} else "unknown"
            )
        if section == "access":
            return self.access(instance)
        if section == "runtime":
            return self.runtime(instance)
        if section == "recovery" and self.recovery is not None:
            return self.recovery.observation(instance)
        raise AdminError("admin_recovery_observation_unavailable", 503)

    def access(self, key):
        # Configuration and access state share the private maintenance lock.
        deployment, status = self.source.access_snapshot(key)
        deployment = HostedDeployment.model_validate(deployment)
        return AccessObservation(
            active=status["active"],
            binding_matches=status["binding_matches_configuration"],
            pending_enrollments=len(status["enrollments"]),
            starts=deployment.enabled_at.timestamp(),
            expires=deployment.expires_at.timestamp(),
            capabilities=sorted(deployment.capabilities),
        )

    def runtime(self, key):
        item = self.source.inventory.get(key)
        self.source.prepare(key)
        _, argv, release, _, local = self.discovery._service(key)
        state = self.discovery.systemctl(
            "show", f"epm-hosted@{key}.service", "--property=ActiveState", "--value"
        ).strip()
        self.discovery._mount(Path(item.mount), Path(item.image))
        return RuntimeObservation(
            service=state,
            mount_verified=True,
            release_matches=release.name == item.release
            and str(local) == item.local_config
            and int(argv[9]) == item.port,
        )
