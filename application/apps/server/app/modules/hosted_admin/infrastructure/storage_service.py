"""Closed internal broker boundary. No storage mutation HTTP routes exist yet."""

from app.modules.hosted_admin.application.storage import ProfileReport, canonical_storage
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.storage_allocations import StorageAllocations
from app.modules.hosted_admin.infrastructure.storage_lifecycle import StorageLifecycle
from app.modules.hosted_admin.infrastructure.project_quota import QuotaUnavailable
from subprocess import SubprocessError


def observed(call, *args):
    try:
        return call(*args)
    except AdminError:
        raise
    except (OSError, QuotaUnavailable, SubprocessError) as error:
        raise AdminError("admin_storage_observation_unavailable", 503) from error


class StorageService:
    def __init__(self, store, host):
        self.host = host
        self.allocations = StorageAllocations(store, host.collect, host.binding, host.evidence)
        self.lifecycle = StorageLifecycle(self.allocations, host.effects)

    def register(self, reference):
        report = ProfileReport.model_validate_json(
            canonical_storage(self.host.reports.report(reference))
        )
        if (
            report.artifact_id != reference
            or self.host.settings().profiles.get(report.profile.id) != reference
        ):
            raise AdminError("admin_storage_profile_unavailable", 409)
        return {"profile_digest": self.allocations.register_profile(report.profile)}

    def reserve(self, command, identity, credential):
        return observed(self.allocations.reserve, command, identity, credential)

    def command(self, command, identity, credential):
        return observed(self.lifecycle.command, command, identity, credential)

    def inspect(self, instance, identity):
        self.host.registered(instance)
        return self.allocations.inspect(instance, identity)
