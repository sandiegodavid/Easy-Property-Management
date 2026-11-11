"""Reserve → commit → effect/inspect → verified receipt; never external work in a write."""

from typing import Protocol

from app.modules.host_agent.application.dispatch import (
    AdmissionPort,
    AdmittedEffect,
    EffectDriver,
    EffectObservation,
    HostAgentDenied,
    HostAgentUnavailable,
    HostEffect,
    require_admission,
)
from app.platform.hosted_contracts.semantic import semantic_hash


class InventoryPort(Protocol):
    def exclusive(self): ...
    def reserve(self, admitted: AdmittedEffect, now: int): ...
    def retained(self, command: HostEffect): ...
    def finish(self, command: HostEffect, observation: EffectObservation, now: int): ...
    def runtime_allocation(self, command: HostEffect): ...
    def supervision_command(self, command: HostEffect, container_id: str | None): ...
    def mark_attention(self, command: HostEffect, observed, now: int): ...


class HostAgent:
    def __init__(
        self, inventory: InventoryPort, admission: AdmissionPort, driver: EffectDriver, *, clock
    ):
        self.inventory, self.admission, self.driver = inventory, admission, driver
        self.clock = clock

    def execute(self, command: HostEffect):
        # H05 restore and H03/H04 enable remain unavailable, even with a typed DTO.
        if command.effect.kind in {"stage_restore", "switch_binding"}:
            raise HostAgentUnavailable()
        if (
            command.effect.kind == "apply_ingress_policy"
            and command.payload.desired_state == "eligible"
        ):
            raise HostAgentUnavailable()
        admitted = self.admission.resolve(command)
        require_admission(command, admitted, self.clock())
        with self.inventory.exclusive():
            require_admission(command, admitted, self.clock())
            _, allocation, fresh = self.inventory.reserve(admitted, self.clock())
            retained, retained_allocation, inspectable = self.inventory.retained(command)
            if retained.state in {"applied", "rejected", "superseded"} or (
                not fresh and not inspectable
            ):
                return retained
            allocation = allocation if fresh else retained_allocation
            try:
                require_admission(command, admitted, self.clock())
                if fresh:
                    observation = self.driver.apply(command, allocation)
                else:
                    observation = self.driver.inspect(command, allocation)
                self._verify(command, observation, allocation)
            except Exception:
                # Provider failure/timeout/invalid observation cannot prove absence or rejection.
                observation = EffectObservation(
                    request_hash=semantic_hash(command),
                    binding_id=command.effect.binding_id,
                    resource_generation=command.effect.resource_generation,
                    status="unknown",
                )
            # Any finish/commit failure propagates. Original pending identity is retained;
            # the next invocation inspects, never blindly re-applies the mutation.
            return self.inventory.finish(command, observation, self.clock())

    def original(self, command: HostEffect):
        admitted = self.admission.resolve(command)
        require_admission(command, admitted, self.clock())
        with self.inventory.exclusive():
            retained, _, _ = self.inventory.retained(command)
            return retained

    def supervise(self, command: HostEffect, *, container_id=None):
        """Private systemd-owner check; never an automatic start/repair command.

        The host composition supplies registered targets, not label-discovered
        containers. Source admission may be down: that must not prevent a safe stop.
        No SQLite write spans Docker, quota or external-deny inspection.
        """
        allocation = None
        try:
            with self.inventory.exclusive():
                allocation = self.inventory.runtime_allocation(command)
                if container_id is not None and allocation.container_ref != container_id:
                    raise HostAgentDenied()
                command = self.inventory.supervision_command(command, allocation.container_ref)
                state = self.driver.supervise(command, allocation)
                if state == "needs_attention":
                    self.inventory.mark_attention(command, allocation, self.clock())
                return state
        except Exception as original:
            failures = [original]
            try:
                self.driver.contain(command, container_id)
            except Exception as containment:
                failures.append(containment)
            if allocation is not None:
                try:
                    with self.inventory.exclusive():
                        self.inventory.mark_attention(command, allocation, self.clock())
                except Exception as persistence:
                    failures.append(persistence)
            if len(failures) > 1:
                raise ExceptionGroup("Runtime guard requires attention.", failures) from original
            raise

    @staticmethod
    def _verify(command, observation, allocation):
        if (
            observation.request_hash != semantic_hash(command)
            or observation.binding_id != command.effect.binding_id
            or observation.resource_generation != command.effect.resource_generation
        ):
            raise HostAgentDenied()
        if observation.status != "applied":
            return
        if command.effect.kind in {"initialize_container", "repair_runtime"}:
            if (
                observation.container_ref is None
                or observation.image_digest != allocation.image_digest
            ):
                raise HostAgentDenied()
        elif observation.container_ref is not None or observation.image_digest is not None:
            raise HostAgentDenied()
        expected = {
            "prepare_resources": "prepared",
            "initialize_container": "stopped",
            "repair_runtime": "stopped",
            "start_container": "running",
            "stop_container": "stopped",
            "retire_resources": "retired",
        }
        if command.effect.kind == "apply_ingress_policy":
            if (
                observation.ingress_state != command.payload.desired_state
                or observation.ingress_revision != allocation.ingress_projection_revision
                or observation.resource_state is not None
            ):
                raise HostAgentDenied()
        elif command.effect.kind in expected:
            if (
                observation.resource_state != expected[command.effect.kind]
                or observation.ingress_state is not None
            ):
                raise HostAgentDenied()
        elif observation.resource_state is not None or observation.ingress_state is not None:
            raise HostAgentDenied()
