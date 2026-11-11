"""Inventory allocation → imported quota binding seam; no filesystem mutations.

H02.5 must verify actual roots/device/enforcement with ProjectQuota and qualify the
combined sandbox before applying limits or granting the owning UID write access.
"""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.modules.host_agent.application.dispatch import Allocation, HostAgentDenied
from app.modules.hosted_admin.infrastructure.project_quota import ProjectBinding


@dataclass(frozen=True)
class QuotaTargets:
    mount: Path
    filesystem_identity: str
    filesystem_uuid: str
    workspace_root: Path
    control_root: Path
    scratch_root: Path

    def __post_init__(self):
        roots = (self.workspace_root, self.control_root, self.scratch_root)
        if (
            str(UUID(self.filesystem_uuid)) != self.filesystem_uuid
            or not self.mount.is_absolute()
            or ".." in self.mount.parts
            or len(set(roots)) != 3
        ):
            raise HostAgentDenied()
        for root in roots:
            if (
                not root.is_absolute()
                or ".." in root.parts
                or root == self.mount
                or not root.is_relative_to(self.mount)
                or any(root != other and root.is_relative_to(other) for other in roots)
            ):
                raise HostAgentDenied()

    def bindings(self, allocation: Allocation) -> tuple[ProjectBinding, ...]:
        """Return unverified native targets only from registered inventory identities."""
        if allocation.filesystem_identity != self.filesystem_identity:
            raise HostAgentDenied()
        return tuple(
            ProjectBinding(
                mount=self.mount,
                directory=root / allocation.binding_id,
                filesystem_uuid=self.filesystem_uuid,
                project_id=project,
                uid=allocation.host_uid,
            )
            for root, project in (
                (self.workspace_root, allocation.workspace_project),
                (self.control_root, allocation.control_project),
                (self.scratch_root, allocation.scratch_project),
            )
        )
