"""Compose current inventory with independent native-profile and external-deny owners."""

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable


class RuntimeAuthority:
    def __init__(self, inventory, qualification, external_deny):
        self.inventory = inventory
        self.qualification = qualification
        self.external_deny = external_deny

    def verify(self, command, allocation, policy_hash):
        receipt, current, inspectable = self.inventory.retained(command)
        if not inspectable or receipt.state not in {"pending", "unknown"} or current != allocation:
            raise HostAgentDenied()
        # Each owner checks current physical/current-fence evidence. A DTO, proof
        # reference or locally verified label cannot substitute for these ports.
        self.qualification.verify(command, allocation, policy_hash)
        self.external_deny.verify(command, allocation)

    def verify_runtime(self, command, allocation, policy_hash):
        current = self.inventory.runtime_allocation(command)
        if current != allocation:
            raise HostAgentDenied()
        self.qualification.verify(command, allocation, policy_hash)
        self.external_deny.verify(command, allocation)


class UnavailableRuntimePrerequisite:
    def verify(self, *args):
        raise HostAgentUnavailable()
