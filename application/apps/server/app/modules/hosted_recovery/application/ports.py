"""Ports for hosted recovery object storage, KMS envelope wrapping, and proxy transport."""

from __future__ import annotations

from typing import Protocol

from app.modules.hosted_recovery.domain.models import ObjectMetadata


class ObjectStorePort(Protocol):
    """Host-side object storage backend (used exclusively inside epm-backup-proxy)."""

    def put_object(self, full_key: str, data: bytes, *, sha256_hex: str) -> ObjectMetadata: ...

    def head_object(self, full_key: str) -> ObjectMetadata: ...

    def get_object(
        self, full_key: str, *, max_bytes: int | None = None
    ) -> tuple[bytes, ObjectMetadata]: ...

    def delete_object(self, full_key: str) -> None: ...

    def list_objects(self, prefix: str, *, max_keys: int = 1000) -> list[str]: ...

    def list_objects_page(
        self,
        prefix: str,
        *,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> tuple[list[str], str | None]: ...


class KmsPort(Protocol):
    """Host-side KMS wrap/unwrap backend (used exclusively inside epm-backup-proxy)."""

    def wrap_dek(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes: ...

    def unwrap_dek(self, key_ref: str, wrapped_dek: bytes, *, aad: bytes) -> bytes: ...


class BackupTransport(Protocol):
    """Container-facing prefix-confined backup & KMS client (implemented by UnixBackupProxyClient)."""

    def put_object(self, relative_key: str, data: bytes) -> ObjectMetadata: ...

    def head_object(self, relative_key: str) -> ObjectMetadata: ...

    def get_object(self, relative_key: str) -> tuple[bytes, ObjectMetadata]: ...

    def delete_object(self, relative_key: str) -> None: ...

    def list_objects(self, subprefix: str = "", *, max_keys: int = 1000) -> list[str]: ...

    def kms_wrap(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes: ...

    def kms_unwrap(self, key_ref: str, wrapped_dek: bytes, *, aad: bytes) -> bytes: ...
