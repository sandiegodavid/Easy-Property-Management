"""Protected main-Admin metadata binding; no authentication/population behavior."""

from pathlib import Path
import re
from urllib.parse import urlsplit

from pydantic import model_validator
from sqlalchemy import Connection

from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import CanonicalId, EpochMillis, Revision
from app.platform.hosted_metadata import bind_metadata
from app.platform.schema_resources import HostedStore


class DeploymentMetadata(SemanticRequest):
    deployment_id: CanonicalId
    public_base_domain: str
    login_origin: str
    registry_generation: Revision
    created_at: EpochMillis

    @model_validator(mode="after")
    def canonical_origins(self):
        domain = self.public_base_domain
        labels = domain.split(".")
        if (
            len(domain) > 253
            or len(labels) < 2
            or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        ):
            raise ValueError("A canonical public DNS domain is required.")
        origin = urlsplit(self.login_origin)
        host = origin.hostname or ""
        prefix = host.removesuffix("." + domain)
        if (
            len(self.login_origin) > 253
            or origin.scheme != "https"
            or origin.netloc != host
            or self.login_origin != f"https://{host}"
            or origin.path
            or origin.query
            or origin.fragment
            or not host.endswith("." + domain)
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", prefix)
        ):
            raise ValueError("A canonical flat HTTPS login origin in the deployment is required.")
        return self


def bind_deployment(
    connection: Connection, metadata: DeploymentMetadata, *, application_directory: Path
) -> bool:
    return bind_metadata(
        connection, metadata, store=HostedStore.ADMIN, application_directory=application_directory
    )
