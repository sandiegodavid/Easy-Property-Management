"""Resource-local IAM candidates; no cloud mutation, secret bytes or Operator identity."""

from typing import Annotated

from pydantic import Field

from app.platform.hosted_contracts.values import Contract, CanonicalId

Project = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]
Segment = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")]


class BootstrapGrants(Contract):
    project: Project
    region: Segment
    repository: Segment
    host_service_account: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]
    tunnel_id: CanonicalId

    def resource_policies(self):
        member = (
            "serviceAccount:"
            + self.host_service_account
            + "@"
            + self.project
            + ".iam.gserviceaccount.com"
        )
        repository = (
            "projects/"
            + self.project
            + "/locations/"
            + self.region
            + "/repositories/"
            + self.repository
        )
        secret = "projects/" + self.project + "/secrets/epm-tunnel-" + self.tunnel_id
        return (
            {
                "resource": repository,
                "policy": {
                    "version": 1,
                    "bindings": [
                        {"role": "roles/artifactregistry.reader", "members": [member]},
                    ],
                },
            },
            {
                "resource": secret,
                "policy": {
                    "version": 1,
                    "bindings": [
                        {"role": "roles/secretmanager.secretAccessor", "members": [member]},
                    ],
                },
            },
        )
