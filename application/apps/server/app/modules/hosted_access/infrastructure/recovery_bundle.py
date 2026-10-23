"""Encrypted administrator configuration, deliberately incapable of restoring sessions."""

import json
import os
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from pydantic import BaseModel, ConfigDict, Field

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.recovery_publication import RecoveryPublicationError
from app.modules.hosted_access.infrastructure.configuration import load_hosted_deployment
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.platform.config import repository_root

MAGIC = b"EPM-HOSTED-RECOVERY-1\0"
MAX_BUNDLE_BYTES = 64 * 1024
SALT_BYTES, NONCE_BYTES = 16, 12


class RecoveryBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deployment: HostedDeployment
    approvedSubjectReference: str | None = Field(None, max_length=254)
    pendingSubjectReferences: list[str] = Field(default_factory=list, max_length=16)
    restorationPolicy: Literal["fresh_enrollment_required"] = "fresh_enrollment_required"


def _key(passphrase, salt):
    if len(passphrase) < 12:
        raise RecoveryPublicationError(
            "Recovery bundle passphrase must contain at least twelve characters."
        )
    return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(passphrase.encode())


def _write_new(path, data):
    with path.open("xb") as stream:
        path.chmod(0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def seal_bundle(bundle: RecoveryBundle, output: Path, passphrase):
    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    header = MAGIC + salt + nonce
    payload = bundle.model_dump_json().encode()
    if len(payload) + len(header) + 16 > MAX_BUNDLE_BYTES:
        raise RecoveryPublicationError("Recovery configuration exceeds the bundle bound.")
    encrypted = AESGCM(_key(passphrase, salt)).encrypt(nonce, payload, header)
    _write_new(output, header + encrypted)


def open_bundle(source: Path, passphrase) -> RecoveryBundle:
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_BUNDLE_BYTES:
        raise RecoveryPublicationError("Recovery bundle is missing, unsafe or oversized.")
    with source.open("rb") as stream:
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    prefix = len(MAGIC)
    length = prefix + SALT_BYTES + NONCE_BYTES
    if not raw.startswith(MAGIC) or not length + 16 <= len(raw) <= MAX_BUNDLE_BYTES:
        raise RecoveryPublicationError("Recovery bundle format is invalid.")
    salt, nonce = raw[prefix : prefix + SALT_BYTES], raw[prefix + SALT_BYTES : length]
    try:
        payload = AESGCM(_key(passphrase, salt)).decrypt(nonce, raw[length:], raw[:length])
        return RecoveryBundle.model_validate_json(payload)
    except (InvalidTag, ValueError) as error:
        raise RecoveryPublicationError(
            "Recovery bundle could not be authenticated or validated."
        ) from error


def _external_output(output, deployment):
    root = repository_root().resolve()
    target = output.resolve()
    if root in target.parents or deployment.storage_volume in target.parents:
        raise RecoveryPublicationError(
            "Recovery bundle/output must be outside the checkout and portable business storage."
        )
    if (
        not output.is_absolute()
        or output.parent.is_symlink()
        or output.parent.stat().st_mode & 0o077
    ):
        raise RecoveryPublicationError(
            "Recovery output requires an existing private external folder."
        )


def create_configuration_bundle(deployment_path, output, passphrase):
    deployment = load_hosted_deployment(deployment_path)
    _external_output(output, deployment)
    store = SQLiteHostedSessionStore(deployment)
    try:
        bundle = RecoveryBundle(deployment=deployment, **store.recovery_reference())
    finally:
        store.engine.dispose()
    seal_bundle(bundle, output, passphrase)


def unpack_configuration_bundle(source, output, passphrase):
    bundle = open_bundle(source, passphrase)
    _external_output(output, bundle.deployment)
    # Reference for manual re-provisioning only. No DB/session/enrollment mutation.
    _write_new(output, json.dumps(bundle.model_dump(mode="json"), indent=2).encode())
