"""Central-only CONNECT listener with a protected numeric bridge peer."""

import argparse
from ipaddress import IPv4Address
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.host_agent.infrastructure.egress_proxy import ProxyServer
from app.modules.host_agent.infrastructure.endpoint_policy import identity_provider_policy
from app.modules.host_agent.infrastructure.tunnel_credentials import protected_bytes
from app.platform.hosted_contracts.values import Contract


class EgressInputs(Contract):
    version: Literal[1] = 1
    address: IPv4Address
    central_address: IPv4Address
    port: Annotated[int, Field(strict=True, ge=1024, le=65535)]
    firebase_project: str

    @model_validator(mode="after")
    def private_peers(self):
        if self.address == self.central_address or any(
            not address.is_private or address.is_unspecified
            for address in (self.address, self.central_address)
        ):
            raise ValueError("Distinct private identity egress peers are required.")
        identity_provider_policy("central_identity", firebase_project=self.firebase_project)
        return self


class CentralProxy(ProxyServer):
    def __init__(self, inputs):
        self.central_address = str(inputs.central_address)
        super().__init__(
            (str(inputs.address), inputs.port),
            identity_provider_policy("central_identity", firebase_project=inputs.firebase_project),
        )

    def verify_request(self, request, client_address):
        return client_address[0] == self.central_address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    args = parser.parse_args()
    try:
        if os.geteuid() == 0:
            raise ValueError("The central proxy requires a dedicated non-root principal.")
        inputs = EgressInputs.model_validate_json(
            protected_bytes(args.configuration, owner=os.geteuid(), limit=8192)
        )
        with CentralProxy(inputs) as server:
            server.serve_forever()
    except Exception:
        parser.exit(3, "The protected identity egress listener is unavailable.\n")


if __name__ == "__main__":
    main()
