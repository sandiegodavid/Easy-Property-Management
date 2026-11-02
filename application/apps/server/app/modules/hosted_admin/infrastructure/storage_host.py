"""Private composition of protected inventory, signed evidence and root quotas."""

from dataclasses import asdict
import json
import os
from contextlib import contextmanager
from pathlib import Path

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.storage import (
    BindingCheck,
    BindingReport,
    CleanupReport,
    HostStorageFacts,
    ProfileReport,
    ProjectUsage,
    StorageAuthority,
    StorageHostSettings,
    StorageProof,
    StorageReservation,
    storage_fingerprint,
    canonical_storage,
)
from app.modules.hosted_admin.infrastructure.project_quota import (
    ProjectBinding,
    ProjectQuota,
    DiskQuota,
)


class StorageHost:
    def __init__(self, store, platform, reports):
        self.store, self.platform, self.reports = store, platform, reports

    def settings(self):
        host = self.platform.h
        return StorageHostSettings.model_validate_json(
            canonical_storage(
                host.read_json(host.paths.configs / "storage-control.json", host.paths)
            )
        )

    def evidence(self, profile, prior):
        reference = prior["artifact_id"] if prior else self.settings().profiles.get(profile.id)
        if reference is None:
            raise AdminError("admin_storage_profile_unavailable", 409)
        report = ProfileReport.model_validate_json(
            canonical_storage(self.reports.report(reference))
        )
        if (
            report.artifact_id != reference
            or report.profile != profile
            or report.environment_hash != self.reports.snapshot().environment_hash
            or (prior is not None and report.environment_hash != prior["environment_hash"])
        ):
            raise AdminError("admin_storage_profile_unavailable", 409)
        return report.model_dump(exclude={"kind", "profile"})

    def registered(self, instance):
        item = self.platform.h.inventory.get(instance)
        if item.storage_backend != "project_quota" or item.storage_policy is None:
            raise AdminError("admin_storage_backend_unavailable", 409)
        return item

    def binding(self, command):
        host = self.platform.h
        item = self.registered(command.policy.instance)
        deployment = HostedDeployment.model_validate_json(
            canonical_storage(
                host.read_json(host.paths.configs / f"hosted-{item.key}.json", host.paths)
            )
        )
        policy = command.policy
        if (
            deployment.storage_policy != policy
            or json.loads(item.storage_policy) != policy.model_dump(mode="json")
            or str(deployment.workspace_id) != item.workspace_id
            or str(deployment.operator_id) != item.operator_id
        ):
            raise AdminError("admin_storage_binding_changed", 409)
        status = host.source._transport(asdict(item), {"query": "status"})
        if not status["binding_matches_configuration"]:
            raise AdminError("admin_storage_binding_changed", 409)
        authority = StorageAuthority(
            inventory_revision=item.revision,
            binding_revision=status["binding_revision"],
            admin_revision=status["admin_revision"],
            fence=status["admin_fence"],
        )
        if authority != command.authority:
            raise AdminError("admin_storage_binding_changed", 409)
        profile = self.profile(policy.profile_id)
        reference = self.settings().bindings.get(item.key)
        if reference is None:
            raise AdminError("admin_storage_binding_unverified", 409)
        verified = BindingReport.model_validate_json(
            canonical_storage(self.reports.report(reference))
        )
        expected = BindingCheck(
            policy_digest=storage_fingerprint(policy.model_dump(mode="json")),
            authority=authority,
            release_digest=host.discovery._release(host.paths.releases / item.release)[
                "manifest_digest"
            ],
            sandbox_digest=profile.sandbox_digest,
        )
        if (
            verified.instance != item.key
            or not 0 <= self.store.clock() - verified.observed < 300
            or self.store.clock() >= verified.expires
            or verified.model_dump(include=set(BindingCheck.model_fields)) != expected.model_dump()
        ):
            raise AdminError("admin_storage_binding_unverified", 409)
        return expected

    def profile(self, identifier):
        from app.modules.hosted_access.application.storage_policy import TierProfile

        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT payload,evidence FROM storage_profile WHERE id=?", (identifier,)
            ).fetchone()
        if row is None or row["evidence"] is None:
            raise AdminError("admin_storage_profile_unavailable", 409)
        profile = TierProfile.model_validate_json(row[0])
        proof = self.evidence(profile, json.loads(row[1]))
        if not proof["observed"] <= self.store.clock() < proof["expires"]:
            raise AdminError("admin_storage_profile_unavailable", 409)
        return profile

    def budget(self, filesystem):
        match = next(
            (item for item in self.settings().filesystems if item.filesystem_uuid == filesystem),
            None,
        )
        if match is None:
            raise AdminError("admin_storage_filesystem_unregistered", 409)
        return match

    def probe(self, policy, project):
        budget = self.budget(policy.filesystem_uuid)
        return ProjectQuota(
            ProjectBinding(
                Path(budget.mount),
                Path(project.directory),
                policy.filesystem_uuid,
                project.project_id,
                project.uid,
            )
        )

    def usage(self, policy, project):
        probe = self.probe(policy, project)
        values = probe.observe()
        inode = os.stat(project.directory, follow_symlinks=False).st_ino
        if inode != project.directory_inode:
            raise AdminError("admin_storage_binding_changed", 409)
        return ProjectUsage(**values, directory_inode=inode, enforcement=True)

    def collect(self, filesystem):
        budget = self.budget(filesystem)
        ProjectQuota(
            ProjectBinding(
                Path(budget.mount),
                Path(budget.mount) / "__read_only_probe__",
                budget.filesystem_uuid,
                1,
                1,
            )
        ).filesystem()
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT request FROM storage_allocation WHERE filesystem_uuid=? AND state!='retired' LIMIT 1001",
                (filesystem,),
            ).fetchall()
        if len(rows) > 1000:
            raise AdminError("admin_storage_capacity_bound", 409)
        usage = []
        for row in rows:
            policy = StorageReservation.model_validate_json(row[0]).policy
            for project in policy.projects:
                usage.append(self.usage(policy, project))
        # Read usage before free space: intervening growth is conservatively
        # reserved rather than reusing an optimistic pre-growth free reading.
        self.platform.h.protected(Path(budget.mount), self.platform.h.paths, regular=False)
        stats = os.statvfs(budget.mount)
        return HostStorageFacts(
            **budget.model_dump(exclude={"mount"}),
            observed=self.store.clock(),
            total_bytes=stats.f_blocks * stats.f_frsize,
            free_bytes=stats.f_bavail * stats.f_frsize,
            free_inodes=stats.f_favail,
            enforcement=True,
            environment_hash=self.reports.snapshot().environment_hash,
            projects=tuple(usage),
        )

    def effects(self, command, request):
        reservation = StorageReservation.model_validate_json(canonical_storage(request))
        policy = reservation.policy
        item = self.registered(policy.instance)
        if json.loads(item.storage_policy) != policy.model_dump(mode="json"):
            raise AdminError("admin_storage_binding_changed", 409)
        if command.action == "finish_retirement":
            report = CleanupReport.model_validate_json(
                canonical_storage(self.reports.report(command.id))
            )
            if (
                report.command_fingerprint != command.fingerprint()
                or report.inventory_revision != item.revision
                or not report.observed <= self.store.clock() < report.expires
            ):
                raise AdminError("admin_storage_cleanup_unverified", 409)
            for project in policy.projects:
                probe = self.probe(policy, project)
                quota = probe._control(probe.filesystem(), 0x800007, DiskQuota())
                if (
                    os.path.lexists(project.directory)
                    or quota.allocated_bytes
                    or quota.allocated_inodes
                ):
                    raise AdminError("admin_storage_cleanup_unverified", 409)
            if not report.observed <= self.store.clock() < report.expires:
                raise AdminError("admin_storage_cleanup_unverified", 409)
            return StorageProof.model_validate(
                report.model_dump(include=set(StorageProof.model_fields))
            )
        self.binding(reservation)
        self.profile(policy.profile_id)
        gate = self.platform.h.source._transport(asdict(item), {"maintenance": "status"})
        if gate["owner"] != policy.operation_id:
            raise AdminError("admin_storage_owned_gate_required", 409)
        with self.effect_lock():
            if self.platform.h.inventory.get(item.key) != item:
                raise AdminError("admin_storage_binding_changed", 409)
            for project in policy.projects:
                self.require_attempt(command)
                observed = self.usage(policy, project)
                if command.action == "apply":
                    self.profile(policy.profile_id)
                    if (
                        observed.allocated_bytes > project.hard_bytes
                        or observed.allocated_inodes > project.hard_inodes
                    ):
                        raise AdminError("admin_storage_usage_exceeds_limit", 409)
                    self.probe(policy, project).set_limits(project.hard_bytes, project.hard_inodes)
        self.require_attempt(command)
        self.binding(reservation)
        return StorageProof(
            operation_id=policy.operation_id,
            policy_digest=storage_fingerprint(policy.model_dump(mode="json")),
            observed=self.store.clock(),
            projects=tuple(self.usage(policy, p) for p in policy.projects),
        )

    def require_attempt(self, command):
        with self.store.transaction() as connection:
            identity = self.store._identity(connection)
            attempt = connection.execute(
                "SELECT * FROM storage_attempt WHERE id=?", (command.id,)
            ).fetchone()
            if (
                attempt is None
                or (attempt["identity"], attempt["generation"])
                != (identity["id"], identity["generation"])
                or attempt["request"] != canonical_storage(command.model_dump())
            ):
                raise AdminError("admin_authority_fenced", 409)

    @contextmanager
    def effect_lock(self):
        host = self.platform.h
        descriptor = host.lock_host(host.inventory)
        try:
            with host.inventory.connection() as connection:
                if connection.execute(
                    "SELECT 1 FROM maintenance WHERE state!='reconciled' LIMIT 1"
                ).fetchone():
                    raise AdminError("admin_storage_busy", 409)
            yield
        finally:
            os.close(descriptor)
