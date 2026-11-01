"""Fixed noninteractive Linux deployment effects shared with the private CLI.

Only the registered instance is addressed. Long recovery/provider work never
holds the host lock; source receipts and private markers reconcile lost replies.
"""

from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import tempfile
from uuid import NAMESPACE_URL, uuid5

from app.modules.hosted_access.application.admin_commands import AccessCommand
from app.modules.hosted_access.application.maintenance import MaintenanceCommand
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import Observation, canonical
from app.modules.hosted_admin.application.upgrades import UpgradePlan


class UpgradeDeployment:
    def __init__(self, platform, catalog, recovery, acceptance, require_authority):
        self.p, self.catalog, self.recovery, self.acceptance = (
            platform,
            catalog,
            recovery,
            acceptance,
        )
        self.require_authority = require_authority

    def options(self, instance):
        return self.catalog.options(instance)

    def prepare(self, instance, release):
        return self.catalog.prepare(instance, release)

    @contextmanager
    def lock(self):
        descriptor = self.p.h.lock_host(self.p.h.inventory)
        try:
            yield
        finally:
            os.close(descriptor)

    def item(self, payload):
        plan = UpgradePlan.model_validate(payload["plan"])
        item = self.p.h.inventory.get(payload["instance"])
        if any(
            getattr(item, name) != getattr(plan.instance, name)
            for name in (
                "key",
                "instance_id",
                "allocation_id",
                "workspace_id",
                "operator_id",
                "profile",
            )
        ):
            raise AdminError("admin_upgrade_allocation_changed", 409)
        expected = {
            (plan.instance.revision, plan.instance.release),
            (plan.instance.revision + 1, self.release(payload)),
        }
        if payload.get("contained_skip"):
            expected.add((plan.instance.revision + 1, plan.instance.release))
        if payload.get("rollback"):
            # Acceptance can reconcile the target before source resume fails.
            expected.add((plan.instance.revision + 1, plan.target.release))
            if (item.revision, item.release) == (
                plan.instance.revision + 2,
                plan.instance.release,
            ):
                try:
                    reservation = self.p.h.inventory.maintenance(payload["operation_id"])
                    intent = self.p.h.inventory.maintenance_intent(payload["operation_id"])
                    before = intent["sources"][item.key]
                    if (
                        reservation["state"] == "reconciled"
                        and reservation["action"] == "admin-upgrade"
                        and intent["key"] == item.key
                        and intent["release"] == plan.instance.release
                        and before["revision"] == plan.instance.revision + 1
                        and before["release"] == plan.target.release
                    ):
                        expected.add((item.revision, item.release))
                except ValueError:
                    pass
        if (item.revision, item.release) not in expected:
            raise AdminError("admin_upgrade_inventory_changed", 409)
        if self.p.h.source.prepare(item.key)["deployment_digest"] != plan.configuration_digest:
            raise AdminError("admin_upgrade_configuration_changed", 409)
        return item

    def marker(self, payload, name, create=None):
        root = self.p.h.paths.control / "upgrades"
        self.p.directory(root)
        namespace = (
            payload.get("acceptance_id", payload["operation_id"])
            if name in {"accept", "disable"}
            else payload["operation_id"]
        )
        path = root / (namespace + "-" + name + ".json")
        if not path.exists():
            if create is None:
                return None
            self.p.publish(path, canonical(create()).encode())
        return self.p.h.read_json(path, self.p.h.paths)

    def transport(self, payload, request):
        return self.p.h.source._transport(asdict(self.item(payload)), request)

    def gate(self, payload):
        return self.transport(payload, {"maintenance": "status"})

    def owned(self, payload):
        if self.gate(payload)["owner"] != payload["gate_owner"]:
            raise AdminError("admin_upgrade_gate_owner_changed", 409)

    def release(self, payload):
        return (
            payload["plan"]["instance"]["release"]
            if payload.get("rollback")
            else payload["plan"]["target"]["release"]
        )

    def artifact(self, payload, *, previous=False):
        plan = payload["plan"]
        name = plan["instance"]["release"] if previous else plan["target"]["release"]
        digest = plan["original_digest"] if previous else plan["target"]["digest"]
        if self.p.h.discovery._release(self.p.h.paths.releases / name)["manifest_digest"] != digest:
            raise AdminError("admin_upgrade_release_changed", 409)
        return name

    def probe(self, payload, *, previous=False, stopped=True):
        item = self.item(payload)
        release = self.artifact(payload, previous=previous)
        executable = self.p.h.paths.releases / release / "venv/bin/python"
        self.p.h.protected(executable.resolve(strict=True), self.p.h.paths)
        result = json.loads(
            self.p.call(
                [
                    "/usr/sbin/runuser",
                    "-u",
                    item.user,
                    "--",
                    str(executable),
                    "-I",
                    "-m",
                    "app.modules.hosted_admin.infrastructure.upgrade_source",
                    "stopped" if stopped else "readiness",
                    str(self.p.h.paths.configs / f"hosted-{item.key}.json"),
                    item.local_config,
                ],
                timeout=60,
            )
        )
        if result != {
            "workspace_id": item.workspace_id,
            "compatible": True,
            "maintenance_owner": payload["gate_owner"],
        }:
            raise AdminError("admin_upgrade_schema_unsupported", 409)

    def pause_command(self, payload):
        def create():
            gate = self.gate(payload)
            plan = payload["plan"]
            return MaintenanceCommand(
                id=str(uuid5(NAMESPACE_URL, payload["gate_owner"] + ":pause")),
                owner=payload["gate_owner"],
                action="pause",
                expected_revision=gate["revision"],
                expected_admin_revision=plan["admin_revision"],
                expected_binding_revision=plan["binding_revision"],
                expected_fence=plan["fence"],
                authority_reference="admin-upgrade:" + payload["gate_owner"],
                reason=payload["reason"],
                release=plan["original_digest"],
                revoke_sessions=payload["session_handling"] == "revoke",
            ).model_dump()

        return self.marker(payload, "pause", create)

    def effective_release(self, payload):
        return self.p.h.discovery._service(payload["instance"])[2].name

    def inspect(self, payload, step):
        self.item(payload)
        if step == "revalidate":
            with self.p.h.inventory.connection() as connection:
                found = connection.execute(
                    "SELECT id FROM maintenance WHERE id=? AND action='admin-upgrade'",
                    (payload["gate_owner"],),
                ).fetchone()
            return Observation("verified", {"verified": True}) if found else Observation("absent")
        if step == "pause":
            return (
                Observation("verified", {"verified": True})
                if self.gate(payload)["owner"] == payload["gate_owner"]
                else Observation("absent")
            )
        if step == "accept":
            command = self.marker(payload, "accept")
            if command is not None:
                # Receipt lookup/execute returns the original immutable result
                # even after evidence expires; it never issues a new acceptance.
                result = self.transport(payload, {"maintenance_receipt": command})
                if result["found"]:
                    return Observation("verified", {"verified": True})
            return Observation("absent")
        self.owned(payload)
        if step == "stop":
            return (
                Observation("verified", {"verified": True})
                if self.p.service_state(payload["instance"]) in {"inactive", "failed"}
                else Observation("absent")
            )
        if step == "recovery":
            proof = self.recovery.current(payload, "recovery")
            return (
                Observation("verified", {"verified": True}, proof.id)
                if proof
                else Observation("absent")
            )
        if step in {"validate", "validate_previous"}:
            self.probe(payload, previous=step == "validate_previous")
            return Observation("verified", {"verified": True})
        if step in {"switch", "switch_previous"}:
            return (
                Observation("verified", {"verified": True})
                if self.effective_release(payload) == self.release(payload)
                else Observation("absent")
            )
        if step in {"start", "start_previous"}:
            return (
                Observation("verified", {"verified": True})
                if self.p.service_state(payload["instance"]) == "active"
                and self.effective_release(payload) == self.release(payload)
                else Observation("absent")
            )
        if step in {"verify", "verify_previous"}:
            proof = self.recovery.current(
                payload, "rollback" if payload.get("rollback") else "target"
            )
            if proof:
                self.verify_runtime(payload)
            return (
                Observation("verified", {"verified": True}, proof.id)
                if proof
                else Observation("absent")
            )
        raise AdminError("admin_upgrade_step_invalid", 409)

    def apply(self, payload, step):
        item = self.item(payload)
        if step == "revalidate":
            if self.prepare(item.key, payload["plan"]["target"]["release"]) != payload["plan"]:
                raise AdminError("admin_upgrade_readiness_changed", 409)
            with self.lock():
                self.require_authority(payload["operation_id"])
                self.p.h.inventory.reserve_upgrade(
                    payload["gate_owner"], item, payload["plan"]["target"]["release"]
                )
            return
        if step == "pause":
            choices = self.catalog.options(item.key)
            choice = next(
                (
                    entry
                    for entry in choices
                    if entry.release == payload["plan"]["target"]["release"]
                ),
                None,
            )
            if (
                choice is None
                or choice.model_dump() != payload["plan"]["target"]
                or not choice.eligible
                or (payload["session_handling"] == "preserve" and not choice.preserve_sessions)
            ):
                raise AdminError("admin_upgrade_qualification_changed", 409)
            self.artifact(payload)
            with self.lock():
                command = self.pause_command(payload)
                self.require_authority(payload["operation_id"], phase="pause")
                self.transport(payload, {"maintenance": command})
            return
        if step == "accept":
            return self.accept(payload)
        self.owned(payload)
        if step == "stop":
            self.p.call(
                ["/usr/bin/systemctl", "stop", f"epm-hosted@{item.key}.service"], timeout=90
            )
        elif step == "recovery":
            self.recovery.produce(payload)
        elif step in {"switch", "switch_previous"}:
            self.switch(payload)
        elif step in {"start", "start_previous"}:
            self.artifact(payload, previous=bool(payload.get("rollback")))
            self.require_authority(payload["operation_id"])
            self.p.call(
                ["/usr/bin/systemctl", "start", f"epm-hosted@{item.key}.service"], timeout=90
            )
        elif step in {"verify", "verify_previous"}:
            self.verify(payload)
        else:
            raise AdminError("admin_upgrade_step_invalid", 409)

    def switch(self, payload):
        self.probe(payload, previous=bool(payload.get("rollback")))
        item = self.item(payload)
        with self.lock():
            self.owned(payload)
            if self.p.service_state(item.key) not in {"inactive", "failed"}:
                raise AdminError("admin_upgrade_stop_required", 409)
            directory = self.p.h.paths.systemd / f"epm-hosted@{item.key}.service.d"
            self.p.directory(directory)
            path = directory / "99-epm-admin-upgrade.conf"

            def original():
                if path.exists() or path.is_symlink():
                    self.p.h.protected(path, self.p.h.paths)
                    if path.stat().st_size > 16384:
                        raise AdminError("admin_upgrade_unit_unverified", 409)
                return {"before": path.read_text() if path.exists() else None}

            captured = self.marker(payload, "unit", original)
            desired = f"# EPM operation-owned release selection\n[Service]\nExecStart=\nExecStart={self.p.h.paths.releases / self.release(payload)}/venv/bin/python -m app --config {item.local_config} serve-hosted --deployment {self.p.h.paths.configs / ('hosted-' + item.key + '.json')} --port {item.port}\n"
            if path.exists() and path.read_text() not in {captured["before"], desired}:
                # Rollback owns the original operation's target override too.
                if (
                    not payload.get("rollback")
                    or self.effective_release(payload) != payload["plan"]["target"]["release"]
                ):
                    raise AdminError("admin_upgrade_unit_changed", 409)
            descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".upgrade-")
            try:
                with os.fdopen(descriptor, "w") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(desired)
                    stream.flush()
                    os.fsync(stream.fileno())
                self.require_authority(payload["operation_id"])
                os.replace(temporary, path)
                self.p.sync(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
            self.p.call(["/usr/bin/systemctl", "daemon-reload"])
            if self.effective_release(payload) != self.release(payload):
                raise AdminError("admin_upgrade_runtime_mismatch", 409)

    def verify(self, payload):
        self.verify_runtime(payload)
        return self.recovery.resulting(payload, "rollback" if payload.get("rollback") else "target")

    def verify_runtime(self, payload):
        self.owned(payload)
        self.catalog.recheck(payload["instance"], payload["plan"]["target"])
        self.artifact(payload, previous=bool(payload.get("rollback")))
        self.probe(payload, previous=bool(payload.get("rollback")), stopped=False)
        if self.p.service_state(payload["instance"]) != "active" or self.effective_release(
            payload
        ) != self.release(payload):
            raise AdminError("admin_upgrade_runtime_unverified", 409)
        observation = self.p.h.discovery.observe(payload["instance"])
        item = self.item(payload)
        for name in ("operator_id", "workspace_id", "email", "hostname", "port"):
            if observation["fields"][name] != getattr(item, name):
                raise AdminError("admin_upgrade_runtime_binding_changed", 409)
        self.acceptance(item)  # Independently verifies exact Access policy/audience/route.

    def accept(self, payload):
        # A prior receipt is reconciled by inspect, before refreshing any proof.
        self.verify(payload)
        with self.lock():
            self.require_authority(payload["operation_id"])
            self.owned(payload)
            self.reconcile_inventory(payload, self.release(payload))
            self.p.h.discovery.source_command_ready(self.item(payload))
            prepare_onboarding = getattr(self.recovery, "prepare_onboarding", None)
            if prepare_onboarding is not None:
                prepare_onboarding(payload)
            if not payload["restore_access"]:
                self.disable(payload)

            def command():
                gate = self.gate(payload)
                status = self.transport(payload, {"query": "status"})
                return MaintenanceCommand(
                    id=str(
                        uuid5(
                            NAMESPACE_URL,
                            payload.get("acceptance_id", payload["operation_id"]) + ":accept",
                        )
                    ),
                    owner=payload["gate_owner"],
                    action="resume",
                    expected_revision=gate["revision"],
                    expected_admin_revision=status["admin_revision"],
                    expected_binding_revision=status["binding_revision"],
                    expected_fence=status["admin_fence"],
                    authority_reference="admin-upgrade:" + payload["operation_id"],
                    reason=payload["reason"],
                    release=payload["plan"]["original_digest"]
                    if payload.get("rollback")
                    else payload["plan"]["target"]["digest"],
                    restore_access=payload["restore_access"],
                ).model_dump()

            acceptance = self.marker(payload, "accept", command)
            self.require_authority(payload["operation_id"])
            self.transport(payload, {"maintenance": acceptance})

    def reconcile_inventory(self, payload, release):
        """Caller holds the brief host lock; source gate is not altered here."""
        item = self.item(payload)
        identifier = payload["gate_owner"]
        reservation = self.p.h.inventory.maintenance(identifier)
        if reservation["state"] == "reconciled":
            if item.release == release:
                return
            if not payload.get("rollback"):
                raise AdminError("admin_upgrade_inventory_changed", 409)
            # Retain the original acceptance reconciliation. Rollback owns a
            # separate expected-revision transition from that pinned target.
            identifier = payload["operation_id"]
            self.p.h.inventory.reserve_upgrade(identifier, item, release)
            reservation = self.p.h.inventory.maintenance(identifier)
        intent = self.p.h.inventory.maintenance_intent(identifier)
        before = self.p.h.instance_type(
            **{field: intent["sources"][item.key][field] for field in vars(item)}
        )
        observation = self.p.h.discovery.observe(item.key)
        after = replace(
            before,
            release=release,
            baseline_digest=self.p.h.save_baseline(self.p.h.inventory, observation),
            revision=before.revision + 1,
        )
        if reservation["state"] == "running":
            self.p.h.inventory.finish_maintenance(identifier, 0)
        self.p.h.inventory.reconcile(identifier, [(before, after)], observation["digest"])

    def contain_for_skip(self, payload):
        payload = payload | {"contained_skip": True}
        if not self.contain(payload):
            return False
        # Before pause, contain already releases an unchanged reservation and
        # leaves the operator usable. After pause, retain its exact gate/bytes.
        if self.marker(payload, "pause") is None and self.gate(payload)["owner"] is None:
            return True
        with self.lock():
            self.owned(payload)
            if self.p.service_state(payload["instance"]) not in {"inactive", "failed"}:
                return False
            actual = self.effective_release(payload)
            previous = actual == payload["plan"]["instance"]["release"]
            if actual != self.artifact(payload, previous=previous):
                raise AdminError("admin_upgrade_runtime_mismatch", 409)
            self.reconcile_inventory(payload, actual)
        return True

    def disable(self, payload):
        def command():
            status = self.transport(payload, {"query": "status"})
            return AccessCommand(
                operation_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        payload.get("acceptance_id", payload["operation_id"]) + ":keep-disabled",
                    )
                ),
                action="disable",
                expected_revision=status["admin_revision"],
                expected_binding_revision=status["binding_revision"],
                fence=status["admin_fence"],
                authority_reference="admin-upgrade:" + payload["operation_id"],
                reason="Accept release while keeping operator access disabled",
            ).model_dump()

        disable = self.marker(payload, "disable", command)
        self.require_authority(payload["operation_id"])
        self.transport(payload, disable)

    def contain(self, payload):
        # Never remove a gate or revive sessions after cancellation/authority loss.
        item = self.item(payload)
        if self.gate(payload)["owner"] is None and self.marker(payload, "pause") is None:
            with self.lock():
                with self.p.h.inventory.connection() as connection:
                    row = connection.execute(
                        "SELECT state FROM maintenance WHERE id=? AND action='admin-upgrade'",
                        (payload["gate_owner"],),
                    ).fetchone()
                if row and row[0] != "reconciled":
                    if row[0] == "running":
                        self.p.h.inventory.finish_maintenance(payload["gate_owner"], 0)
                    self.p.h.inventory.reconcile(
                        payload["gate_owner"], [], payload["plan"]["configuration_digest"]
                    )
            return True
        self.p.call(["/usr/bin/systemctl", "stop", f"epm-hosted@{item.key}.service"], timeout=90)
        return self.p.service_state(item.key) in {"inactive", "failed"}
