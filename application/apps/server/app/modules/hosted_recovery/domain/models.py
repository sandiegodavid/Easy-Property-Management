"""Contracts, AAD derivation, and strict validation for hosted recovery (H05.2)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.platform.hosted_contracts.values import Contract

MANIFEST_FORMAT_VERSION = "epm-hosted-recovery-v1"
CHUNK_MAGIC = b"EPMC"
CHUNK_FORMAT_VERSION = 1
AES_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
DEFAULT_CHUNK_SIZE = 256 * 1024

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_KMS_KEY_REF = re.compile(
    r"^projects/[a-z0-9-]+/locations/[a-z0-9-]+/keyRings/[A-Za-z0-9_-]+"
    r"/cryptoKeys/[A-Za-z0-9_-]+(?:/cryptoKeyVersions/[0-9]+)?$"
)


class HostedRecoveryError(RuntimeError):
    """Operator-safe hosted recovery error without secret or path disclosure."""

    code = "hosted_recovery_error"

    def __init__(
        self, message: str = "Hosted recovery operation failed.", *, code: str | None = None
    ):
        super().__init__(message)
        if code is not None:
            self.code = code


class BackupProxyDenied(HostedRecoveryError):
    code = "backup_proxy_denied"


class BackupProxyUnavailable(HostedRecoveryError):
    code = "backup_proxy_unavailable"


class RecoveryCryptoError(HostedRecoveryError):
    code = "recovery_crypto_error"


class RecoveryIntegrityError(HostedRecoveryError):
    code = "recovery_integrity_error"


def validate_sha256_hex(value: str) -> str:
    if not isinstance(value, str) or not _HEX_SHA256.fullmatch(value):
        raise ValueError("Expected a 64-character lowercase SHA-256 hex digest.")
    return value


def validate_kms_key_ref(value: str) -> str:
    if not isinstance(value, str) or not _KMS_KEY_REF.fullmatch(value):
        raise ValueError("Invalid GCP Cloud KMS key reference.")
    return value


def validate_relative_object_key(key: str) -> str:
    """Validate a strict relative object key with no traversal, leading slash, or control chars."""
    if not isinstance(key, str) or not key or len(key) > 512:
        raise ValueError("Relative object key must be 1..512 characters.")
    if key.startswith("/") or key.endswith("/") or "\\" in key or "\x00" in key:
        raise ValueError("Relative object key contains forbidden path characters.")
    parts = key.split("/")
    for part in parts:
        if part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part):
            raise ValueError("Relative object key contains an invalid path segment.")
    return key


def validate_relative_file_path(relative_path: str) -> str:
    """Validate a retained file relative path (no traversal, absolute root, or drive prefix)."""
    if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 512:
        raise ValueError("Retained file path must be 1..512 characters.")
    if relative_path.startswith("/") or "\\" in relative_path or "\x00" in relative_path:
        raise ValueError("Retained file path cannot be absolute or contain backslashes/nulls.")
    parts = relative_path.split("/")
    for part in parts:
        if part in {"", ".", ".."}:
            raise ValueError("Retained file path contains forbidden traversal segments.")
        if ":" in part:
            raise ValueError("Retained file path cannot contain colons.")
    return relative_path


def key_fingerprint(key_ref: str) -> str:
    """Short deterministic namespace fingerprint for key-rotation-safe chunk addressing."""
    return hashlib.sha256(key_ref.encode("utf-8")).hexdigest()[:16]


def canonical_json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


class EnvelopeContext(Contract):
    """Scope and compatibility metadata bound into AES-256-GCM AAD."""

    deployment_id: str = Field(min_length=1, max_length=128)
    scope_kind: Literal["operator", "control"]
    operator_id: str | None = Field(default=None, min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128)
    point_id: str = Field(min_length=1, max_length=128)
    schema_revisions: dict[str, str]
    key_ref: str

    @field_validator("key_ref")
    @classmethod
    def _check_key_ref(cls, value: str) -> str:
        return validate_kms_key_ref(value)

    @field_validator("schema_revisions")
    @classmethod
    def _check_schema_revisions(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("schema_revisions must be non-empty.")
        for name, rev in value.items():
            if not name or not rev:
                raise ValueError("schema_revisions keys and values must be non-empty.")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _check_scope_fields(self) -> EnvelopeContext:
        if self.scope_kind == "operator":
            if not self.operator_id or not self.workspace_id:
                raise ValueError("Operator recovery scope requires operator_id and workspace_id.")
        elif self.operator_id is not None or self.workspace_id is not None:
            raise ValueError("Control recovery scope cannot include operator_id or workspace_id.")
        return self

    def chunk_aad(self, chunk_sha256: str) -> bytes:
        validate_sha256_hex(chunk_sha256)
        return canonical_json_bytes(
            {
                "role": "chunk",
                "deployment_id": self.deployment_id,
                "scope_kind": self.scope_kind,
                "operator_id": self.operator_id,
                "workspace_id": self.workspace_id,
                "key_ref": self.key_ref,
                "chunk_sha256": chunk_sha256,
            }
        )

    def manifest_aad(self) -> bytes:
        return canonical_json_bytes(
            {
                "role": "manifest",
                "deployment_id": self.deployment_id,
                "scope_kind": self.scope_kind,
                "operator_id": self.operator_id,
                "workspace_id": self.workspace_id,
                "point_id": self.point_id,
                "schema_revisions": self.schema_revisions,
                "key_ref": self.key_ref,
            }
        )

    def kms_aad(self) -> bytes:
        return canonical_json_bytes(
            {
                "role": "dek",
                "deployment_id": self.deployment_id,
                "scope_kind": self.scope_kind,
                "operator_id": self.operator_id,
                "workspace_id": self.workspace_id,
                "key_ref": self.key_ref,
            }
        )


class ChunkRef(Contract):
    chunk_sha256: str
    object_key: str
    ciphertext_sha256: str
    plaintext_size: int = Field(ge=0)
    ciphertext_size: int = Field(gt=0)

    @field_validator("chunk_sha256", "ciphertext_sha256")
    @classmethod
    def _check_digests(cls, value: str) -> str:
        return validate_sha256_hex(value)

    @field_validator("object_key")
    @classmethod
    def _check_object_key(cls, value: str) -> str:
        return validate_relative_object_key(value)


class DatabaseSnapshotManifest(Contract):
    filename: str = Field(min_length=1, max_length=128)
    plaintext_sha256: str
    plaintext_size: int = Field(ge=0)
    chunks: list[ChunkRef]

    @field_validator("filename")
    @classmethod
    def _check_filename(cls, value: str) -> str:
        if (
            "/" in value
            or "\\" in value
            or value in {".", ".."}
            or not _SAFE_SEGMENT.fullmatch(value)
        ):
            raise ValueError("Database snapshot filename must be a safe single segment.")
        return value

    @field_validator("plaintext_sha256")
    @classmethod
    def _check_digest(cls, value: str) -> str:
        return validate_sha256_hex(value)


class RetainedFileManifest(Contract):
    relative_path: str
    content_sha256: str
    plaintext_size: int = Field(ge=0)
    chunks: list[ChunkRef]

    @field_validator("relative_path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return validate_relative_file_path(value)

    @field_validator("content_sha256")
    @classmethod
    def _check_digest(cls, value: str) -> str:
        return validate_sha256_hex(value)


class RecoveryPointManifest(Contract):
    format_version: Literal["epm-hosted-recovery-v1"] = MANIFEST_FORMAT_VERSION
    deployment_id: str
    scope_kind: Literal["operator", "control"]
    operator_id: str | None = None
    workspace_id: str | None = None
    point_id: str
    captured_at: int = Field(ge=0)
    business_revision: str = Field(min_length=1, max_length=128)
    files_generation: str = Field(min_length=1, max_length=128)
    source_generation: int = Field(ge=1)
    release_ref: str = Field(min_length=1, max_length=128)
    schema_revisions: dict[str, str]
    key_ref: str
    databases: list[DatabaseSnapshotManifest] = Field(min_length=1)
    files: list[RetainedFileManifest] = Field(default_factory=list)

    @field_validator("key_ref")
    @classmethod
    def _check_key_ref(cls, value: str) -> str:
        return validate_kms_key_ref(value)


class ManifestEnvelope(Contract):
    """AEAD-protected manifest wrapper stored in off-host object storage."""

    format_version: Literal["epm-hosted-recovery-v1"] = MANIFEST_FORMAT_VERSION
    deployment_id: str
    scope_kind: Literal["operator", "control"]
    operator_id: str | None = None
    workspace_id: str | None = None
    point_id: str
    schema_revisions: dict[str, str]
    key_ref: str
    wrapped_dek_b64: str = Field(min_length=1)
    nonce_b64: str = Field(min_length=1)
    ciphertext_b64: str = Field(min_length=1)

    @field_validator("key_ref")
    @classmethod
    def _check_key_ref(cls, value: str) -> str:
        return validate_kms_key_ref(value)

    def to_envelope_context(self) -> EnvelopeContext:
        return EnvelopeContext(
            deployment_id=self.deployment_id,
            scope_kind=self.scope_kind,
            operator_id=self.operator_id,
            workspace_id=self.workspace_id,
            point_id=self.point_id,
            schema_revisions=self.schema_revisions,
            key_ref=self.key_ref,
        )


class ObjectMetadata(Contract):
    exists: bool
    sha256: str | None = None
    size: int | None = Field(default=None, ge=0)

    @field_validator("sha256")
    @classmethod
    def _check_digest(cls, value: str | None) -> str | None:
        return validate_sha256_hex(value) if value is not None else None


class BackupPointResult(Contract):
    point_id: str
    manifest_ref: str
    manifest_sha256: str
    manifest_format: str
    key_ref: str
    wrapped_dek_b64: str
    stored_bytes: int = Field(ge=0)
    uploaded_bytes: int = Field(ge=0)
    deduplicated_chunks: int = Field(ge=0)
    uploaded_chunks: int = Field(ge=0)
    verified_chunks: int = Field(ge=0)


class RestorePointResult(Contract):
    point_id: str
    manifest_sha256: str
    database_files: list[str]
    restored_files: list[str]
    verified_chunks: int = Field(ge=0)


class PruneResult(Contract):
    retained_chunks: int = Field(ge=0)
    deleted_chunks: list[str] = Field(default_factory=list)
