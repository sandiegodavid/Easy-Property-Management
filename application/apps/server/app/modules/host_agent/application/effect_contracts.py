"""H02.1 immutable effect inputs; no host authority, persistence or dispatch."""

from typing import Literal
from uuid import UUID, uuid5

from pydantic import model_validator

from app.platform.hosted_contracts.operations import OperationReference
from app.platform.hosted_contracts.semantic import SemanticRequest, semantic_hash
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Reference,
    Revision,
    SafeCode,
    WorkspaceScope,
)

EFFECT_NAMESPACE = UUID("ae334c7e-9085-5c55-aa9b-c2c16c9084bb")


class EffectIdentity(SemanticRequest):
    """Stable effect slot within an immutable original parent operation.

    Fences and consequential parameters belong in the request hash, not this slot.
    Changing them on a retry must conflict instead of allocating another effect.
    """

    version: Literal[1] = 1
    parent: OperationReference
    binding_id: CanonicalId
    resource_generation: Revision
    kind: Literal[
        "prepare_resources",
        "initialize_container",
        "repair_runtime",
        "start_container",
        "stop_container",
        "apply_limits",
        "apply_ingress_policy",
        "stage_restore",
        "switch_binding",
        "retire_resources",
    ]
    slot: SafeCode

    @model_validator(mode="after")
    def workspace_parent(self):
        if not isinstance(self.parent.scope, WorkspaceScope):
            raise ValueError("Operator resource effects require a workspace-scoped parent.")
        return self

    def child_id(self) -> str:
        return str(uuid5(EFFECT_NAMESPACE, semantic_hash(self)))

    def child_key(self) -> str:
        return "host-effect-v1:" + self.child_id()


class ApplyIngressPolicy(SemanticRequest):
    """Admitted IDs only; the inventory resolves exact origin and target.

    Evidence references are not grants. The adapter must verify current authority,
    readiness and fences before effects. H02 cannot enable customer ingress.
    """

    action: Literal["apply_ingress_policy"] = "apply_ingress_policy"
    effect: EffectIdentity
    access_epoch: Revision
    expected_ingress_revision: Revision
    desired_state: Literal["held", "eligible", "blocked"]
    source_identity_proof_ref: Reference | None = None
    resource_readiness_proof_ref: Reference | None = None

    @model_validator(mode="after")
    def matching_ingress(self):
        if self.effect.kind != self.action:
            raise ValueError("Ingress request requires an ingress effect identity.")
        if self.desired_state == "eligible" and (
            self.source_identity_proof_ref is None or self.resource_readiness_proof_ref is None
        ):
            raise ValueError("Eligible ingress requires source identity and resource evidence.")
        return self


class InspectIngress(SemanticRequest):
    """Read-only, bounded single-binding inspection; no effect receipt needed."""

    binding_id: CanonicalId
    resource_generation: Revision


class GuardedLifecycle(SemanticRequest):
    """One restart owner; Docker must never independently restart a runtime."""

    version: Literal[1] = 1
    restart_owner: Literal["restricted_host_supervisor"] = "restricted_host_supervisor"
    docker_restart_policy: Literal["no"] = "no"
    required_checks: tuple[
        Literal["mount"], Literal["quota"], Literal["inventory"], Literal["external_deny"]
    ] = ("mount", "quota", "inventory", "external_deny")
