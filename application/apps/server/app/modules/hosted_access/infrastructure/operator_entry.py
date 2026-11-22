"""Installed Operator authentication listener with protected workspace and source bindings."""

import argparse
from contextlib import contextmanager
from ipaddress import IPv4Address
from pathlib import Path
from time import time_ns
from typing import Annotated, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field
from sqlalchemy import text
from starlette.responses import Response

from app.bootstrap.api import create_app
from app.hosted_candidates.runtime import inspect
from app.modules.hosted_access.api.managed_business import ManagedBusinessInputs
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.identity_setup import HttpsOrigin
from app.modules.hosted_access.infrastructure.admin_bootstrap import private_file
from app.modules.hosted_access.infrastructure.free_storage_admission import FreeStorageAdmission
from app.modules.hosted_access.infrastructure.handoff_channel import CentralHandoffClient
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner
from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
    OperatorIdentityInputs,
)
from app.modules.hosted_access.infrastructure.usage_accounting import UsageAccountingStore
from app.modules.workspace.application.service import WorkspacePaths
from app.modules.hosted_access.infrastructure.shared_identity_entry import (
    Uid,
    owned_identity_socket,
    read_private,
)
from app.modules.hosted_access.infrastructure.tls_candidate import run_identity_tls
from app.modules.hosted_access.infrastructure.firebase_tokens import unique_json
from app.platform.config import application_root
from app.platform.hosted_contracts.values import Contract, Reference
from app.platform.hosted_schema import validate_schema
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine


class OperatorDeployment(Contract):
    version: Literal[1] = 1
    binding: IdentityBinding
    workspace_configuration: Path
    writer_lock: Path
    access_database: Path
    signing_key: Path
    signing_key_id: Reference
    central_origin: HttpsOrigin
    central_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    central_key_id: Reference
    central_relay: Path
    relay_uid: Uid
    socket_directory: Path
    gateway_address: IPv4Address
    listen_address: IPv4Address
    support_contact: str | None = None

    def check_private_network(self):
        if any(
            address.is_unspecified or not address.is_private
            for address in (self.gateway_address, self.listen_address)
        ):
            raise ValueError("Use the protected private peers.")


class TrustedSourceHTTP:
    def __init__(self, app, gateway):
        self.app = app
        self.gateway = str(gateway)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and (
            scope["scheme"] != "https"
            or (scope.get("client") or ("",))[0] != self.gateway
            or [value for key, value in scope["headers"] if key == b"x-forwarded-proto"]
            != [b"https"]
            or any(
                key in {b"forwarded", b"x-forwarded-host", b"x-forwarded-for"}
                for key, _ in scope["headers"]
            )
        ):
            await Response(status_code=421)(scope, receive, send)
        else:
            await self.app(scope, receive, send)


@contextmanager
def candidate(configuration):
    configuration.check_private_network()
    business = unique_json(read_private(configuration.workspace_configuration))
    if set(business) != {"localWorkspacePath"}:
        raise ValueError("Authentication candidates accept only an owned workspace mount.")
    binding = configuration.binding
    control = configuration.access_database.parent
    workspace = Path(business["localWorkspacePath"])
    if (
        not workspace.is_absolute()
        or workspace.resolve(strict=True) != workspace
        or workspace == control
        or workspace in control.parents
        or control in workspace.parents
    ):
        raise ValueError("Use separate protected access and workspace mounts.")
    signer = IdentitySigner(
        configuration.signing_key_id,
        Ed25519PrivateKey.from_private_bytes(read_private(configuration.signing_key, 32)),
    )
    central_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(configuration.central_key))
    private_file(configuration.access_database)
    engine = create_sqlite_engine(configuration.access_database)
    try:
        with engine.connect() as connection:
            validate_schema(
                connection, HostedStore.HOSTED_ACCESS, application_directory=application_root()
            )
            if connection.execute(
                text(
                    "SELECT deployment_id, operator_id, workspace_id, binding_id, resource_generation FROM access_meta"
                )
            ).all() != [
                (
                    binding.deployment_id,
                    binding.scope.operator_id,
                    binding.scope.workspace_id,
                    binding.binding_id,
                    binding.resource_generation,
                )
            ]:
                raise ValueError("The retained access store does not match the protected binding.")

        def current_binding():
            return binding

        clock = lambda: time_ns() // 1_000_000
        business_engine = create_sqlite_engine(WorkspacePaths(root=workspace).database)
        try:
            usage_store = UsageAccountingStore(engine, business_engine, clock=clock)
            storage_admission = FreeStorageAdmission(usage_store)
            with owned_identity_socket(
                configuration.socket_directory, binding.scope.operator_id
            ) as listener:
                app = create_app(
                    configuration.workspace_configuration,
                    operator_identity_inputs=OperatorIdentityInputs(
                        engine=engine,
                        binding=current_binding,
                        signer=signer,
                        central_key=lambda scope, issuer, kid: (
                            central_key
                            if (scope, issuer, kid)
                            == (binding, "central_identity", configuration.central_key_id)
                            else None
                        ),
                        central=CentralHandoffClient(
                            configuration.central_relay, configuration.relay_uid, current_binding
                        ),
                        clock=clock,
                        listener=listener,
                        relay_uid=configuration.relay_uid,
                        source_origin=binding.target_origin,
                        central_origin=configuration.central_origin,
                        support_contact=configuration.support_contact,
                        business=ManagedBusinessInputs(
                            # Real deployments hold business ingress closed until H05 protection passes.
                            readiness=lambda: False,
                            storage=storage_admission,
                            files=True,
                        ),
                        writer_lock=HostedWriterLock(configuration.writer_lock),
                        usage_reader=usage_store.read_usage,
                    ),
                )
                yield TrustedSourceHTTP(app, configuration.gateway_address)
        finally:
            business_engine.dispose()
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--tls-certificate", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        inspect("operator")
        configuration = OperatorDeployment.model_validate_json(read_private(args.configuration))
        with candidate(configuration) as app:
            run_identity_tls(app, configuration.listen_address, args)
    except Exception:
        parser.exit(3, "The protected Operator authentication candidate is unavailable.\n")


if __name__ == "__main__":
    main()
