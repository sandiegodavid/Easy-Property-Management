"""Disposable HTTPS acceptance harness, NEVER a production launcher.

Only configuration-file ownership and remote key discovery are substituted. Real
RS256 proofs, cookies, CSRF, enrollment, SQLite sessions and domain handlers run
with the packaged frontend. Test controls live outside the product application.
"""

import argparse
import base64
from dataclasses import replace
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from sqlalchemy import update
import uvicorn

from app.bootstrap.api import create_app
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.storage_budget import HostedStorageBudget, StorageFacts
from app.modules.hosted_access.application.service import HostedAccessService
from app.modules.hosted_access.infrastructure.cloudflare_identity import CloudflareIdentityVerifier
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.workspace.application.service import WorkspaceService
from app.platform.sqlite_engine import immediate_transaction
from web_smoke_server import packaged_web

ORIGIN = "https://demo.epm.test"


def encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class SyntheticIdentity:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.offset = timedelta(0)

    def now(self):
        return datetime.now(UTC) + self.offset

    def keys(self, _issuer):
        public = self.key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kid": "acceptance",
                    "kty": "RSA",
                    "alg": "RS256",
                    "n": encoded(public.n.to_bytes(256, "big")),
                    "e": encoded(public.e.to_bytes(3, "big")),
                }
            ]
        }

    def assertion(self, deployment, email):
        # Fresh proof after logout/rebinding without wall-clock sleeps.
        self.offset += timedelta(seconds=2)
        claims = {
            "iss": deployment.identity_issuer,
            "aud": deployment.identity_audience,
            "sub": "synthetic-operator",
            "email": email,
            "iat": int(self.now().timestamp()),
            "exp": int((self.now() + timedelta(hours=12)).timestamp()),
            "nonce": str(uuid4()),
        }
        payload = ".".join(
            encoded(json.dumps(value).encode())
            for value in (
                {"alg": "RS256", "kid": "acceptance"},
                claims,
            )
        )
        signature = self.key.sign(payload.encode(), padding.PKCS1v15(), hashes.SHA256())
        return payload + "." + encoded(signature)

    def certificate(self, root):
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "demo.epm.test")])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(self.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(days=1))
            .not_valid_after(datetime.now(UTC) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("demo.epm.test")]), False)
            .sign(self.key, hashes.SHA256())
        )
        cert, key = root / "certificate.pem", root / "key.pem"
        cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(
            self.key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key.chmod(0o600)
        return cert, key


def deployment_for(root, workspace_id, read_only):
    now = datetime.now(UTC)
    return HostedDeployment.model_validate(
        {
            "deployment_mode": "hosted_demo",
            "public_origin": "https://demo-b.epm.test" if read_only else ORIGIN,
            "identity_issuer": "https://synthetic.cloudflareaccess.com",
            "identity_audience": "a" * 64,
            "workspace_id": workspace_id,
            "operator_id": str(uuid4()),
            "allowed_email": "operator-b@example.com" if read_only else "operator@example.com",
            "administrator_contact": "admin@example.com",
            "administration_database": root / "administration.sqlite",
            "storage_volume": root / "volume",
            "storage_image": root / "image.ext4",
            "enabled_at": now,
            "expires_at": now + timedelta(days=14),
            "capabilities": ["records.read", "files.read"]
            if read_only
            else [
                "records.read",
                "records.write",
                "files.read",
                "files.write",
            ],
        }
    )


def synthetic_storage_facts(original, mode):
    facts = original()
    if mode == "full":
        return replace(facts, available_bytes=0)
    if mode == "maintenance":
        return replace(facts, host_available_bytes=facts.host_total_bytes // 10)
    if mode != "ready":
        raise ValueError("Unknown synthetic storage mode")
    return facts


def controls(product, store, identity, deployment):
    @asynccontextmanager
    async def lifespan(_app):
        async with product.router.lifespan_context(product):
            yield

    harness = FastAPI(lifespan=lifespan)

    @harness.post("/__test__/identity")
    def proof(email: str | None = None):
        return {"assertion": identity.assertion(deployment, email or deployment.allowed_email)}

    @harness.post("/__test__/approve")
    def approve():
        store.activate("synthetic-operator")
        return {"approved": True}

    @harness.post("/__test__/expire")
    def expire():
        with immediate_transaction(store.engine) as connection:
            connection.execute(update(store.sessions).values(expires_at=0))
        return {"expired": True}

    @harness.post("/__test__/availability")
    def availability(ready: bool):
        runtime = product.state.workspace_runtime
        runtime.workspace_id = str(deployment.workspace_id) if ready else str(uuid4())
        return {"ready": ready}

    @harness.post("/__test__/runtime")
    def runtime_epoch():
        product.state.workspace_runtime.read_epoch = str(uuid4())
        return {"changed": True}

    original_storage = product.state.hosted_storage_budget.facts

    @harness.post("/__test__/storage")
    def storage_mode(mode: str):
        facts = synthetic_storage_facts(original_storage, mode)
        product.state.hosted_storage_budget.facts = lambda: facts
        return {"mode": mode}

    harness.mount("/", product)
    return harness


def run(root, args):
    config = root / "config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}))
    manifest = WorkspaceService.from_local_config(config).initialize()
    deployment = deployment_for(root, manifest.workspace_id, args.read_only)
    SQLiteHostedSessionStore.initialize(deployment)
    store = SQLiteHostedSessionStore(deployment)
    identity = SyntheticIdentity()
    cert, key = identity.certificate(root)
    with (
        patch(
            "app.bootstrap.hosted_access.build_storage_budget",
            side_effect=lambda *_args: HostedStorageBudget(
                lambda: StorageFacts(
                    250 * 1024**2, 220 * 1024**2, 30 * 1024**3, 20 * 1024**3, 10000
                )
            ),
        ),
        patch("app.bootstrap.api.load_hosted_deployment", return_value=deployment),
        patch(
            "app.bootstrap.hosted_access.CloudflareIdentityVerifier",
            side_effect=lambda value: CloudflareIdentityVerifier(
                value, fetch=identity.keys, now=identity.now
            ),
        ),
        patch(
            "app.bootstrap.hosted_access.HostedAccessService",
            side_effect=lambda value, source: HostedAccessService(value, source, now=identity.now),
        ),
    ):
        product = create_app(
            config,
            hosted_deployment_path=root / "protected.json",
            web_build_path=packaged_web(root),
        )
        uvicorn.run(
            controls(product, store, identity, deployment),
            host="127.0.0.1",
            port=args.port,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            proxy_headers=False,
        )
    store.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="epm-hosted-browser-") as directory:
        run(Path(directory).resolve(), args)


if __name__ == "__main__":
    main()
