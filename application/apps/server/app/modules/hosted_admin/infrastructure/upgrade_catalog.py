"""Read-only installed-release readiness, shared by private and broker callers."""

from dataclasses import asdict
import hashlib
import json
import shutil

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.upgrades import (
    ReleaseCatalog,
    ReleaseQualification,
    UpgradePlan,
    UpgradeInstance,
)
from app.modules.hosted_access.infrastructure.recovery_publication import (
    load_recovery_configuration,
)


class InstalledReleaseCatalog:
    def __init__(self, platform, reports, snapshot, clock):
        self.platform, self.reports, self.snapshot, self.clock = platform, reports, snapshot, clock

    def qualifications(self):
        platform = self.platform
        catalog = ReleaseCatalog.model_validate(
            platform.h.read_json(
                platform.h.paths.control / "upgrades/catalog.json", platform.h.paths
            )
        )
        entries = [
            ReleaseQualification.model_validate(self.reports.report(identifier))
            for identifier in catalog.reports
        ]
        if len({entry.target.release for entry in entries}) != len(entries):
            raise AdminError("admin_upgrade_catalog_ambiguous", 409)
        return entries

    def options(self, instance, *, allow_current=False):
        current = self.platform.h.inventory.get(instance)
        capacity = self.snapshot()
        fresh = 0 <= self.clock() - capacity.observed < 300 and capacity.inventory_clear
        count = len(self.platform.h.inventory.list())
        result = []
        for entry in self.qualifications():
            blockers = list(entry.target.blockers)
            if not fresh:
                blockers.append("Current host capacity and inventory need verification.")
            if (
                entry.profile != current.profile
                or entry.environment_digest != capacity.environment_hash
                or entry.operator_ceiling < count
            ):
                blockers.append(
                    "Release qualification does not cover this host and operator profile."
                )
            if not entry.observed <= self.clock() < entry.expires:
                blockers.append("Release qualification needs refreshing.")
            if entry.target.release == current.release and not allow_current:
                blockers.append("This release is already selected.")
            try:
                artifact = self.platform.h.discovery._release(
                    self.platform.h.paths.releases / entry.target.release
                )
                if artifact["manifest_digest"] != entry.target.digest:
                    blockers.append("Installed release changed after qualification.")
            except OSError, ValueError:
                blockers.append("Installed release artifacts could not be verified.")
            result.append(
                entry.target.model_copy(
                    update={
                        "eligible": entry.target.eligible and not blockers,
                        "blockers": blockers,
                    }
                )
            )
        return result

    def recheck(self, instance, target):
        choice = next(
            (
                item
                for item in self.options(instance, allow_current=True)
                if item.release == target["release"]
            ),
            None,
        )
        if choice is None or not choice.eligible or choice.model_dump() != target:
            raise AdminError("admin_upgrade_qualification_changed", 409)

    def prepare(self, instance, release):
        platform = self.platform
        current = platform.h.inventory.get(instance)
        target = next((item for item in self.options(instance) if item.release == release), None)
        if target is None or not target.eligible:
            raise AdminError("admin_upgrade_release_ineligible", 409)
        # No host-wide lock spans compatibility checks. Capture current pinned
        # source facts, then recheck after the target's read-only probe.
        prepared = platform.h.source.prepare(instance)
        platform.h.discovery.source_command_ready(current)
        deployment, status = platform.h.source.access_snapshot(instance)
        original = platform.h.discovery._release(platform.h.paths.releases / current.release)
        recovery_path = platform.h.paths.configs / f"recovery-{instance}.json"
        platform.h.protected(recovery_path, platform.h.paths, private=True)
        recovery = load_recovery_configuration(recovery_path)
        recovery_digest = hashlib.sha256(recovery_path.read_bytes()).hexdigest()
        if shutil.disk_usage(recovery.ledger_path.parent).free < 2 * 250 * 1024 * 1024:
            raise AdminError("admin_upgrade_recovery_space_required", 409)
        executable = platform.h.paths.releases / release / "venv/bin/python"
        platform.h.protected(executable.resolve(strict=True), platform.h.paths)
        probe = json.loads(
            platform.call(
                [
                    "/usr/sbin/runuser",
                    "-u",
                    current.user,
                    "--",
                    str(executable),
                    "-I",
                    "-m",
                    "app.modules.hosted_admin.infrastructure.upgrade_source",
                    "readiness",
                    str(platform.h.paths.configs / f"hosted-{instance}.json"),
                    current.local_config,
                ],
                timeout=60,
            )
        )
        if probe != {
            "workspace_id": current.workspace_id,
            "compatible": True,
            "maintenance_owner": None,
        }:
            raise AdminError("admin_upgrade_schema_unsupported", 409)
        if (
            asdict(platform.h.inventory.get(instance)) != asdict(current)
            or platform.h.source.prepare(instance) != prepared
        ):
            raise AdminError("admin_upgrade_inventory_changed", 409)
        if platform.h.source.status(instance) != status:
            raise AdminError("admin_upgrade_access_changed", 409)
        if (
            platform.h.discovery._release(platform.h.paths.releases / release)["manifest_digest"]
            != target.digest
        ):
            raise AdminError("admin_upgrade_release_changed", 409)
        capacity = self.snapshot()
        if not 0 <= self.clock() - capacity.observed < 300 or not capacity.inventory_clear:
            raise AdminError("admin_upgrade_capacity_unverified", 409)
        with platform.lock():
            # Short final admission check coordinates with private maintenance;
            # the execution step repeats it before creating any access pause.
            if asdict(platform.h.inventory.get(instance)) != asdict(current):
                raise AdminError("admin_upgrade_inventory_changed", 409)
        reference = UpgradeInstance(
            **{name: getattr(current, name) for name in UpgradeInstance.model_fields}
        )
        return UpgradePlan(
            instance=reference,
            target=target,
            original_digest=original["manifest_digest"],
            configuration_digest=prepared["deployment_digest"],
            binding_revision=status["binding_revision"],
            admin_revision=status["admin_revision"],
            fence=status["admin_fence"],
            generation=status["generation"],
            active=status["active"],
            environment_digest=capacity.environment_hash,
            recovery_configuration_digest=recovery_digest,
        ).model_dump()
