"""Guarded host effects; current inventory + external deny + qualification are mandatory."""

from typing import Protocol

from app.modules.host_agent.application.dispatch import (
    Allocation,
    EffectObservation,
    HostAgentDenied,
    HostAgentUnavailable,
    HostEffect,
    ResourceLimits,
)
from app.modules.host_agent.infrastructure.container_policy import container_spec, policy_hash
from app.platform.hosted_contracts.semantic import semantic_hash


class RuntimeAuthority(Protocol):
    def verify(self, command: HostEffect, allocation: Allocation, policy_hash: str) -> None:
        """Recheck current inventory, exact image/profile/native proof and external deny.

        Must fail when any prerequisite is unknown/stale. H02.6 owns live external
        denial; H03/H04 own source eligibility. Labels/references are not authority.
        Qualification supplies an explicit private synthetic adapter only in its lab.
        """
        ...

    def verify_runtime(self, command: HostEffect, allocation: Allocation, policy_hash: str) -> None:
        """Check current running-target inventory and current denial, not an old receipt."""
        ...


class EvidencePort(Protocol):
    def record(self, command, allocation, facts) -> str:
        """Durably retain bounded non-secret physical observations; return a safe reference."""
        ...


class NativeEffects:
    def __init__(
        self,
        storage,
        engine,
        profile,
        authority: RuntimeAuthority,
        evidence: EvidencePort,
        *,
        stops=None,
        networks=None,
    ):
        self.storage, self.engine, self.profile = storage, engine, profile
        self.authority, self.evidence = authority, evidence
        self.stops = stops
        self.networks = networks

    def _policy_hash(self):
        value = policy_hash(self.profile)
        return value if self.networks is None else self.networks.qualification_hash(value)

    def guard(self, command, allocation):
        self.authority.verify(command, allocation, self._policy_hash())
        if self.networks is not None:
            self.networks.verify(command, allocation)
        return self.storage.verify(allocation)

    def _spec(self, command, allocation):
        network = None if self.networks is None else self.networks.verify(command, allocation)
        spec = container_spec(
            command, allocation, self.storage.targets, self.profile, network=network
        )
        spec["Labels"]["epm.policy"] = self._policy_hash()
        return spec

    def _current(self, allocation):
        if allocation.container_ref is None:
            raise HostAgentDenied()
        actual = self.engine.inspect(allocation.container_ref)
        self._owned(actual, allocation)
        return actual

    @staticmethod
    def _owned(actual, allocation):
        if actual is None:
            raise HostAgentUnavailable()
        labels = actual["Config"].get("Labels", {})
        if (
            labels.get("epm.binding") != allocation.binding_id
            or labels.get("epm.generation") != str(allocation.resource_generation)
            or actual["Config"]["Image"] != "sha256:" + allocation.image_digest
            or actual["Config"]["User"] != f"{allocation.host_uid}:{allocation.host_gid}"
        ):
            raise HostAgentDenied()

    def _sandbox(self, command, allocation, actual):
        self._owned(actual, allocation)
        expected = self._spec(command, allocation)
        if self.networks is not None:
            self.networks.verify_container(self.networks.verify(command, allocation), actual)
        actual_host = actual["HostConfig"]
        if actual["Config"]["Labels"].get("epm.policy") != self._policy_hash():
            raise HostAgentDenied()
        # Compare every declared security/resource setting, not labels alone. Docker
        # normalizes empty arrays/maps and adds bind defaults; compare those explicitly.
        for key, value in expected["HostConfig"].items():
            got = actual_host.get(key)
            if key == "SecurityOpt":
                if set(got or []) != set(value):
                    raise HostAgentDenied()
            elif key == "Mounts":
                selected = [
                    {k: mount.get(k, False if k == "ReadOnly" else None) for k in value[0]}
                    for mount in (got or [])
                ]
                if selected != value:
                    raise HostAgentDenied()
            elif value in ([], {}):
                if got not in (None, value):
                    raise HostAgentDenied()
            elif got != value:
                raise HostAgentDenied()
        permitted = {
            (m["Source"], m["Target"], not m["ReadOnly"]) for m in expected["HostConfig"]["Mounts"]
        }
        if any(m["Type"] not in {"bind", "tmpfs"} for m in actual["Mounts"]):
            raise HostAgentDenied()
        actual_mounts = {
            (m["Source"], m["Destination"], m["RW"])
            for m in actual["Mounts"]
            if m["Type"] == "bind"
        }
        if actual_mounts != permitted:
            raise HostAgentDenied()

    def apply(self, command, allocation):
        kind = command.effect.kind
        if kind == "prepare_resources":
            self.authority.verify(command, allocation, self._policy_hash())
            if self.networks is not None:
                self.networks.prepare(command, allocation)
            self.storage.prepare(allocation)
        elif kind in {"initialize_container", "repair_runtime"}:
            self.guard(command, allocation)
            if kind == "initialize_container" and allocation.container_ref is not None:
                raise HostAgentDenied()
            if kind == "repair_runtime":
                old = self._current(allocation)
                if old["State"]["Running"]:
                    raise HostAgentDenied()
                self.engine.remove_stopped(old["Id"])
            self.engine.create(command, self._spec(command, allocation))
        elif kind == "start_container":
            self.guard(command, allocation)
            actual = self._current(allocation)
            self._sandbox(command, allocation, actual)
            if self.stops is None:
                raise HostAgentUnavailable()
            try:
                with self.stops.starting(command, allocation, actual):
                    self.guard(command, allocation)
                    self.engine.start(actual["Id"])
                    self.guard(command, allocation)
            except Exception as original:
                try:
                    self.contain(command, actual["Id"])
                except Exception as cleanup:
                    raise ExceptionGroup(
                        "Start and runtime containment failed.", [original, cleanup]
                    ) from original
                raise
        elif kind == "apply_limits":
            self.guard(command, allocation)
            if (
                allocation.container_ref is not None
                and self._current(allocation)["State"]["Running"]
            ):
                raise HostAgentDenied()
            target = self._limit_target(allocation)
            for role, project in zip(
                ("workspace", "control", "scratch"), self.storage.projects(allocation), strict=True
            ):
                limits = getattr(target.limits, role)
                project.set_limits(limits.byte_ceiling, limits.inode_ceiling)
            self.storage.verify(target)
        elif kind == "stop_container":
            actual = self._current(allocation)
            self.engine.stop(actual["Id"])
        else:
            # H02.6 ingress, H05 restore and irreversible retirement need their owners.
            raise HostAgentUnavailable()
        return self.inspect(command, allocation)

    def inspect(self, command, allocation):
        kind = command.effect.kind
        facts = {}
        container = None
        if kind == "prepare_resources":
            facts = self.guard(command, allocation)
            state = "prepared"
        elif kind in {"initialize_container", "repair_runtime"}:
            facts = self.guard(command, allocation)
            container = self.engine.inspect(self.engine.name(command))
            self._sandbox(command, allocation, container)
            if (
                container["Config"]["Labels"].get("epm.effect") != command.effect.child_id()
                or container["State"]["Running"]
            ):
                raise HostAgentDenied()
            state = "stopped"
        elif kind == "apply_limits":
            self.authority.verify(command, allocation, self._policy_hash())
            if (
                allocation.container_ref is not None
                and self._current(allocation)["State"]["Running"]
            ):
                raise HostAgentDenied()
            facts = self.storage.verify(self._limit_target(allocation))
            state = None
        elif kind in {"start_container", "stop_container"}:
            container = self._current(allocation)
            state = "running" if container["State"]["Running"] else "stopped"
            if state != ("running" if kind == "start_container" else "stopped"):
                raise HostAgentUnavailable()
            if state == "running":
                facts = self.guard(command, allocation)
                self._sandbox(command, allocation, container)
        else:
            raise HostAgentUnavailable()
        evidence = self.evidence.record(command, allocation, {"state": state, "projects": facts})
        return EffectObservation(
            request_hash=semantic_hash(command),
            binding_id=allocation.binding_id,
            resource_generation=allocation.resource_generation,
            status="applied",
            evidence_ref=evidence,
            resource_state=state,
            container_ref=container["Id"]
            if kind in {"initialize_container", "repair_runtime"}
            else None,
            image_digest=allocation.image_digest
            if kind in {"initialize_container", "repair_runtime"}
            else None,
        )

    @staticmethod
    def _limit_target(allocation):
        if allocation.inputs is None:
            raise HostAgentDenied()
        plan = allocation.inputs.plan
        limits = ResourceLimits(
            workspace=plan.workspace, control=plan.control, scratch=plan.scratch
        )
        return allocation.model_copy(update={"limits": limits})

    def supervise(self, command, allocation):
        """One bounded check: never restart or recreate, even after health failure/reboot.

        The owning supervisor runs under Inventory.exclusive and obtains targets
        from the validated inventory, not a Docker label scan. Unknown checks stop
        the exact previously-owned runtime and retain operational attention.
        """
        actual = self._current(allocation)
        if not actual["State"]["Running"]:
            return "stopped"
        try:
            self.authority.verify_runtime(command, allocation, self._policy_hash())
            self.storage.verify(allocation)
            self._sandbox(command, allocation, actual)
            if actual["State"].get("Health", {}).get("Status") == "unhealthy":
                raise HostAgentUnavailable()
            return "running"
        except Exception:
            self.engine.stop(actual["Id"])
            stopped = self.engine.inspect(actual["Id"])
            if stopped is None or stopped["State"]["Running"]:
                raise HostAgentUnavailable()
            self.evidence.record(
                command, allocation, {"state": "needs_attention", "runtime_stopped": True}
            )
            return "needs_attention"

    def contain(self, command, container_id=None):
        if self.stops is None:
            raise HostAgentUnavailable()
        found = False
        for name in self.stops.targets():
            target = self.stops.target(name)
            original = target.command
            if (
                original.effect.binding_id == command.effect.binding_id
                and original.effect.resource_generation == command.effect.resource_generation
                and original.effect.parent.scope == command.effect.parent.scope
                and original.effect.parent.deployment_id == command.effect.parent.deployment_id
                and (container_id is None or target.container_id == container_id)
            ):
                self.stops.contain(self.engine, target)
                found = True
        if not found:
            raise HostAgentUnavailable()
