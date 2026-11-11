"""Exact Pilot 0 artifact compatibility; evidence availability is never approval."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_validator

from app.platform.hosted_contracts.values import (
    CanonicalId,
    Component,
    Contract,
    Reference,
    RequestHash,
    Scope,
)


class SchemaStore(StrEnum):
    BUSINESS = "business"
    ADMIN = "admin"
    ADMIN_RECOVERY = "admin_recovery"
    INVENTORY = "inventory"
    ACCESS = "access"
    RECOVERY = "recovery"


class SchemaRevision(Contract):
    store: SchemaStore
    revision: Reference


class QualificationEvidence(Contract):
    state: Literal["passed", "failed", "unavailable"]
    artifact_digest: RequestHash
    evidence_ref: Reference | None

    @model_validator(mode="after")
    def proven_reference(self):
        if self.state == "passed" and self.evidence_ref is None:
            raise ValueError("Passed qualification requires its protected evidence reference.")
        return self


class CompatibilityManifest(Contract):
    version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    release_id: CanonicalId
    component: Component
    artifact_kind: Literal["oci_image", "web_bundle"]
    artifact_ref: Reference
    artifact_digest: RequestHash
    oci_manifest_digest: RequestHash | None
    api_contract: Reference
    source_contract: Reference
    agent_contract: Reference
    inventory_revision: Reference
    owned_schemas: Annotated[tuple[SchemaRevision, ...], Field(max_length=6)]
    readable_schemas: Annotated[tuple[SchemaRevision, ...], Field(max_length=6)]
    native_qualification: QualificationEvidence
    provider_qualification: QualificationEvidence

    @model_validator(mode="after")
    def valid_manifest(self):
        owned = _schema_map(self.owned_schemas)
        readable = _schema_map(self.readable_schemas)
        if any(
            store in readable and readable[store] != revision for store, revision in owned.items()
        ):
            raise ValueError("Owned/readable revisions cannot disagree.")
        expected = {
            Component.ADMIN: {SchemaStore.ADMIN, SchemaStore.ADMIN_RECOVERY},
            Component.OPERATOR: {SchemaStore.BUSINESS, SchemaStore.ACCESS, SchemaStore.RECOVERY},
            Component.TENANT: set(),
            Component.OWNER: set(),
        }[self.component]
        if set(owned) != expected:
            raise ValueError("Component schema ownership is incomplete or crosses store authority.")
        portal = self.component in {Component.TENANT, Component.OWNER}
        if portal != (self.artifact_kind == "web_bundle"):
            raise ValueError(
                "Pilot runtime artifacts are OCI; future portal assets own no schemas."
            )
        if (self.artifact_kind == "oci_image") != (self.oci_manifest_digest is not None):
            raise ValueError("OCI requires an immutable registry manifest digest; bundles do not.")
        if portal and set(readable) != {SchemaStore.BUSINESS}:
            raise ValueError("Portal source compatibility must pin the business schema only.")
        if not portal and set(readable) - set(owned):
            raise ValueError("Runtime manifests cannot claim another service's private stores.")
        for evidence in (self.native_qualification, self.provider_qualification):
            if evidence.artifact_digest != self.artifact_digest:
                raise ValueError("Qualification must bind the exact artifact digest.")
        return self


def _schema_map(values: tuple[SchemaRevision, ...]) -> dict[SchemaStore, str]:
    result = {value.store: value.revision for value in values}
    if len(result) != len(values):
        raise ValueError("A schema store must appear only once.")
    return result


class ComponentAssignment(Contract):
    deployment_id: CanonicalId
    component: Component
    scope: Scope
    release_id: CanonicalId

    @model_validator(mode="after")
    def component_scope(self):
        if (self.component == Component.OPERATOR) != (self.scope.kind == "workspace"):
            raise ValueError(
                "Operator assignments are workspace-scoped; other components are shared."
            )
        return self


class RuntimeCompatibility(Contract):
    api_contract: Reference
    source_contract: Reference
    agent_contract: Reference
    inventory_revision: Reference
    schemas: Annotated[tuple[SchemaRevision, ...], Field(max_length=6)]


class CompatibilityUnavailable(ValueError):
    code = "hosted_compatibility_unavailable"


def require_compatible(
    manifest: CompatibilityManifest, assignment: ComponentAssignment, runtime: RuntimeCompatibility
) -> None:
    """Pure pre-dispatch comparison; H02 authenticates manifests/proofs and registry IDs."""
    if manifest.component != assignment.component or manifest.release_id != assignment.release_id:
        raise CompatibilityUnavailable("Release/component assignment mismatch.")
    if any(
        e.state != "passed"
        for e in (manifest.native_qualification, manifest.provider_qualification)
    ):
        raise CompatibilityUnavailable("Native/provider qualification is unavailable or failed.")
    for field in ("api_contract", "source_contract", "agent_contract", "inventory_revision"):
        if getattr(manifest, field) != getattr(runtime, field):
            raise CompatibilityUnavailable(
                "Exact API/source/agent/inventory compatibility required."
            )
    expected = _schema_map(manifest.readable_schemas) | _schema_map(manifest.owned_schemas)
    if expected != _schema_map(runtime.schemas):
        raise CompatibilityUnavailable("Exact declared schema compatibility required.")
