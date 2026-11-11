"""Network slots derive from existing exclusive project assignments, not a new ledger."""

from typing import Annotated

from pydantic import Field, model_validator

from app.platform.hosted_contracts.values import CanonicalId, Revision, Contract
from app.modules.host_agent.application.ingress import MAX_ORIGINS


class NetworkRecord(Contract):
    binding_id: CanonicalId
    operator_id: CanonicalId
    workspace_id: CanonicalId
    resource_generation: Revision
    workspace_project: Revision


class NetworkProjection(Contract):
    records: Annotated[tuple[NetworkRecord, ...], Field(max_length=MAX_ORIGINS)]

    @model_validator(mode="after")
    def exclusive(self):
        for name in ("binding_id", "workspace_project"):
            values = [getattr(row, name) for row in self.records]
            if len(values) != len(set(values)):
                raise ValueError("Network ownership and slots must be exclusive.")
        return self
