"""Protected inventory identity binding, separate from native resource verification."""

from pathlib import Path

from sqlalchemy import Connection

from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import CanonicalId, EpochMillis, Reference
from app.platform.hosted_metadata import bind_metadata
from app.platform.schema_resources import HostedStore


class HostMetadata(SemanticRequest):
    host_id: CanonicalId
    deployment_id: CanonicalId
    filesystem_identity: Reference
    agent_contract_version: Reference
    created_at: EpochMillis


def bind_host(
    connection: Connection, metadata: HostMetadata, *, application_directory: Path
) -> bool:
    """Trusted setup only; caller must separately prove device/mount/quota before starts.

    This inserts an identity, not a readiness proof or permission to allocate/start.
    H02.3/H02.5 own authentication and physical verification; no permissive fake verifier.
    """
    return bind_metadata(
        connection,
        metadata,
        store=HostedStore.HOST_INVENTORY,
        application_directory=application_directory,
    )
