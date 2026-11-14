"""H03.2 explicit disabled source binding; structural initialization grants no access."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from sqlalchemy import Connection

from app.modules.hosted_access.application.source_contracts import AdmittedFreePolicy
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import CanonicalId, EpochMillis, Reference, Revision
from app.platform.hosted_metadata import bind_metadata
from app.platform.schema_resources import HostedStore


class DisabledAccessMetadata(SemanticRequest):
    deployment_id: CanonicalId
    operator_id: CanonicalId
    workspace_id: CanonicalId
    binding_id: CanonicalId
    resource_generation: Revision
    issuer: Reference
    subject: None = None
    email_key: Annotated[str, Field(strict=True, min_length=1, max_length=254)]
    effective_access: Literal["disabled"] = "disabled"
    access_epoch: Revision
    session_generation: Revision
    not_before: EpochMillis
    effective_policy_id: CanonicalId
    usable_bytes: Literal[50_000_000] = 50_000_000
    policy_revision: Revision
    maintenance_operation_id: None = None
    restore_generation: Revision
    revision: Revision


class DisabledAccessBinding(SemanticRequest):
    """Admitted protected inputs, never inferred from a file or browser submission.

    H04's owner authenticates the admission hash/policy/binding before this call.
    This DTO is a consistency check, not an entitlement or a verified grant.
    """

    version: Literal[1] = 1
    deployment_id: CanonicalId
    operator_id: CanonicalId
    workspace_id: CanonicalId
    binding_id: CanonicalId
    resource_generation: Revision
    issuer: Reference
    email_key: Annotated[str, Field(strict=True, min_length=1, max_length=254)]
    access_epoch: Revision
    session_generation: Revision
    not_before: EpochMillis
    policy: AdmittedFreePolicy
    restore_generation: Revision
    revision: Revision

    def metadata(self) -> DisabledAccessMetadata:
        fields = self.model_dump(exclude={"version", "policy"})
        return DisabledAccessMetadata(
            **fields,
            effective_policy_id=self.policy.policy_id,
            usable_bytes=self.policy.usable_bytes,
            policy_revision=self.policy.policy_revision,
        )


def bind_disabled_access(
    connection: Connection, binding: DisabledAccessBinding, *, application_directory: Path
) -> bool:
    """Exact read-only retry, no enabled/claimed overwrite or inferred usage/session seed.

    Caller owns the current protected transaction; failure rolls back with caller.
    Bind only the metadata singleton. Missing policy usage remains unknown.
    """
    return bind_metadata(
        connection,
        binding.metadata(),
        store=HostedStore.HOSTED_ACCESS,
        application_directory=application_directory,
    )
