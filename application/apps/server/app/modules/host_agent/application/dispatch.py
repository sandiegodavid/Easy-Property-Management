"""Narrow host effects admitted through a private owning authority, never HTTP."""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from app.modules.host_agent.application.build_inputs import HostPrincipal
from app.modules.host_agent.application.contracts import Action
from app.modules.host_agent.application.effect_contracts import ApplyIngressPolicy, EffectIdentity
from app.platform.hosted_contracts.operations import SemanticConflict
from app.platform.hosted_contracts.semantic import SemanticRequest, semantic_hash
from app.platform.hosted_contracts.values import (
    CanonicalId,
    EpochMillis,
    IdempotencyKey,
    Reference,
    RequestHash,
    Revision,
)

Positive = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]


class HostAgentUnavailable(RuntimeError):
    code = "host_agent_unavailable"

    def __init__(self):
        super().__init__("The protected host operation is unavailable; check its original result.")


class HostAgentDenied(RuntimeError):
    code = "host_agent_denied"

    def __init__(self):
        super().__init__("The protected host request does not match current authority.")


class IngressPolicy(SemanticRequest):
    action: Literal["apply_ingress_policy"] = "apply_ingress_policy"
    desired_state: Literal["held", "blocked", "eligible"]
    expected_ingress_revision: Revision
    source_identity_proof_ref: Reference | None = None
    resource_readiness_proof_ref: Reference | None = None


class HostEffect(SemanticRequest):
    effect: EffectIdentity
    access_epoch: Revision
    expected_revision: Revision
    inputs_hash: RequestHash | None = None
    payload: Annotated[Action | IngressPolicy, Field(discriminator="action")]

    @model_validator(mode="after")
    def matching_target(self):
        if (
            self.payload.action
            in {"prepare_resources", "initialize_container", "repair_runtime", "apply_limits"}
            and self.inputs_hash is None
        ):
            raise ValueError("Resource effects require pinned resolved inputs.")
        if self.effect.kind != self.payload.action:
            raise ValueError("Effect and action must match.")
        if isinstance(self.payload, IngressPolicy):
            ApplyIngressPolicy(
                effect=self.effect,
                access_epoch=self.access_epoch,
                expected_ingress_revision=self.payload.expected_ingress_revision,
                desired_state=self.payload.desired_state,
                source_identity_proof_ref=self.payload.source_identity_proof_ref,
                resource_readiness_proof_ref=self.payload.resource_readiness_proof_ref,
            )
        elif self.payload.action == "retire_resources":
            if self.payload.binding_ids != (self.effect.binding_id,):
                raise ValueError("Retirement requires one child effect per registered binding.")
        elif (
            self.payload.action != "switch_binding"
            and self.payload.binding_id != self.effect.binding_id
        ):
            raise ValueError("Effect target and action binding must match.")
        if (
            self.payload.action == "repair_runtime"
            and self.payload.expected_resource_generation != self.effect.resource_generation
        ):
            raise ValueError("Repair must preserve the registered resource generation.")
        return self


class TreeLimits(SemanticRequest):
    byte_ceiling: Positive
    inode_ceiling: Positive


class ResourceLimits(SemanticRequest):
    workspace: TreeLimits
    control: TreeLimits
    scratch: TreeLimits


class ResourcePlan(ResourceLimits):
    """Authenticated admission output; never inferred from browser input or image tags."""

    image_id: CanonicalId
    release_id: CanonicalId
    image_digest: RequestHash
    capacity_profile_ref: Reference
    limit_profile_id: CanonicalId | None = None


class ResourceInputs(SemanticRequest):
    plan: ResourcePlan
    public_origin: str | None = None


class StoredEffect(SemanticRequest):
    command: HostEffect
    inputs: ResourceInputs | None = None

    @model_validator(mode="after")
    def matching_inputs(self):
        digest = semantic_hash(self.inputs) if self.inputs is not None else None
        if digest != self.command.inputs_hash:
            raise ValueError("Resolved inputs do not match immutable command intent.")
        return self


class AdmittedEffect(SemanticRequest):
    command: HostEffect
    admitted_at: EpochMillis
    expires_at: EpochMillis
    plan: ResourcePlan | None = None
    public_origin: str | None = None

    @model_validator(mode="after")
    def admission_window(self):
        if self.expires_at <= self.admitted_at:
            raise ValueError("Admission expiry must follow verification.")
        if self.command.payload.action == "prepare_resources":
            if self.plan is None or self.public_origin is None:
                raise ValueError("Preparation requires an admitted resource plan and origin.")
        self.retained()
        return self

    def retained(self) -> StoredEffect:
        inputs = (
            ResourceInputs(plan=self.plan, public_origin=self.public_origin) if self.plan else None
        )
        return StoredEffect(command=self.command, inputs=inputs)


class AdmissionPort(Protocol):
    def resolve(self, command: HostEffect) -> AdmittedEffect:
        """Authenticate current original Admin intent; return exact immutable child input.

        A reference/DTO is not authority. Reject unknown, revoked, changed or stale
        parents. Implementations use an authenticated Admin-owned port, never open
        another authority's DB or rebuild intent from mutable assignments. H04 owns
        the live implementation; private synthetic qualification adapters are explicit.
        """
        ...


class EffectObservation(SemanticRequest):
    request_hash: RequestHash
    binding_id: CanonicalId
    resource_generation: Revision
    status: Literal["applied", "rejected", "unknown"]
    evidence_ref: Reference | None = None
    resource_state: Literal["prepared", "running", "stopped", "retired"] | None = None
    ingress_state: Literal["held", "blocked"] | None = None
    ingress_revision: Revision | None = None
    container_ref: Reference | None = None
    image_digest: RequestHash | None = None

    @model_validator(mode="after")
    def confirmed_evidence(self):
        if self.status != "unknown" and self.evidence_ref is None:
            raise ValueError("Confirmed effects require retained verification evidence.")
        if (self.ingress_state is None) != (self.ingress_revision is None):
            raise ValueError("Ingress observations require the exact projected revision.")
        return self


class Allocation(SemanticRequest):
    binding_id: CanonicalId
    resource_generation: Revision
    host_uid: HostPrincipal
    host_gid: HostPrincipal
    workspace_project: HostPrincipal
    control_project: HostPrincipal
    scratch_project: HostPrincipal
    filesystem_identity: Reference
    image_digest: RequestHash
    inputs: ResourceInputs | None = None
    ingress_projection_revision: Revision | None = None
    container_ref: Reference | None = None
    limits: ResourceLimits | None = None
    binding_revision: Revision | None = None
    access_epoch: Revision | None = None

    @model_validator(mode="after")
    def distinct_projects(self):
        if len({self.workspace_project, self.control_project, self.scratch_project}) != 3:
            raise ValueError("Each protected tree requires its own registered project.")
        return self


class EffectDriver(Protocol):
    def apply(self, command: HostEffect, allocation: Allocation) -> EffectObservation:
        """Verify current physical readiness, perform and inspect only this typed effect.

        No shell, raw paths or image tags. H02.5/H02.6 resolve protected mounts/images,
        invoke qualified quota primitives and enforce guarded lifecycle/gateway policy.
        No driver may treat inventory reservation alone as native readiness.
        """
        ...

    def inspect(self, command: HostEffect, allocation: Allocation) -> EffectObservation:
        """Read actual receipt/ownership; never rerun an uncertain historical mutation."""
        ...


class UnavailableEffects:
    def apply(self, command: HostEffect, allocation: Allocation) -> EffectObservation:
        raise HostAgentUnavailable()

    def inspect(self, command: HostEffect, allocation: Allocation) -> EffectObservation:
        raise HostAgentUnavailable()


class EffectReceipt(SemanticRequest):
    operation_id: CanonicalId
    parent_operation_id: CanonicalId
    idempotency_key: IdempotencyKey
    request_hash: RequestHash
    binding_id: CanonicalId
    state: Literal["pending", "unknown", "applied", "rejected", "superseded"]
    revision: Revision
    evidence_ref: Reference | None = None
    superseded_by_operation_id: CanonicalId | None = None
    containment_evidence_ref: Reference | None = None

    @model_validator(mode="after")
    def retained_supersession(self):
        evidence = (self.superseded_by_operation_id, self.containment_evidence_ref)
        if self.state == "superseded":
            if not all(evidence):
                raise ValueError(
                    "Superseded starts require the verified stop identity and evidence."
                )
        elif any(value is not None for value in evidence):
            raise ValueError("Only superseded starts carry containment resolution.")
        return self


def require_admission(command: HostEffect, admitted: AdmittedEffect, now: int) -> None:
    if semantic_hash(command) != semantic_hash(admitted.command):
        raise SemanticConflict()
    if not admitted.admitted_at <= now < admitted.expires_at:
        raise HostAgentDenied()
