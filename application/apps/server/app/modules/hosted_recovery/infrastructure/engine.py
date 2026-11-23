"""Content-addressed chunked AEAD backup engine with KMS envelope encryption (H05.2)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.modules.hosted_recovery.application.ports import BackupTransport
from app.modules.hosted_recovery.domain.models import (
    AES_GCM_NONCE_BYTES,
    AES_KEY_BYTES,
    BackupPointResult,
    CHUNK_FORMAT_VERSION,
    CHUNK_MAGIC,
    ChunkRef,
    DEFAULT_CHUNK_SIZE,
    DatabaseSnapshotManifest,
    EnvelopeContext,
    MANIFEST_FORMAT_VERSION,
    ManifestEnvelope,
    PruneResult,
    RecoveryCryptoError,
    RecoveryIntegrityError,
    RecoveryPointManifest,
    RestorePointResult,
    RetainedFileManifest,
    key_fingerprint,
    validate_relative_file_path,
    validate_relative_object_key,
    validate_sha256_hex,
)


@dataclass(frozen=True)
class DatabaseInput:
    """Consistent local database snapshot staged for backup."""

    filename: str
    path: Path


@dataclass(frozen=True)
class RetainedFileInput:
    """Retained workspace file staged for backup."""

    relative_path: str
    path: Path


def _seal_chunk(dek: bytes, plaintext: bytes, *, aad: bytes) -> bytes:
    nonce = os.urandom(AES_GCM_NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
    return CHUNK_MAGIC + bytes([CHUNK_FORMAT_VERSION]) + nonce + ciphertext


def _open_chunk(dek: bytes, framed: bytes, *, aad: bytes) -> bytes:
    header_len = len(CHUNK_MAGIC) + 1 + AES_GCM_NONCE_BYTES
    if len(framed) < header_len + 16:
        raise RecoveryIntegrityError("Encrypted chunk is truncated.")
    if framed[: len(CHUNK_MAGIC)] != CHUNK_MAGIC:
        raise RecoveryIntegrityError("Encrypted chunk magic mismatch.")
    version = framed[len(CHUNK_MAGIC)]
    if version != CHUNK_FORMAT_VERSION:
        raise RecoveryIntegrityError("Unsupported encrypted chunk version.")
    nonce_start = len(CHUNK_MAGIC) + 1
    nonce = framed[nonce_start : nonce_start + AES_GCM_NONCE_BYTES]
    ciphertext = framed[header_len:]
    try:
        return AESGCM(dek).decrypt(nonce, ciphertext, aad)
    except InvalidTag as error:
        raise RecoveryCryptoError("Encrypted chunk authentication failed.") from error


def _require_regular_no_symlink(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RecoveryIntegrityError("Backup input must be a regular non-symlink file.")


def _safe_destination_path(root: Path, relative_path: str) -> Path:
    validated = validate_relative_file_path(relative_path)
    resolved_root = root.resolve()
    target = (resolved_root / validated).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise RecoveryIntegrityError("Restore target escapes destination directory.") from error
    return target


class ChunkedAeadBackupEngine:
    """Pure-Python chunked AES-256-GCM backup engine backed by BackupTransport."""

    def __init__(self, transport: BackupTransport, *, chunk_size: int = DEFAULT_CHUNK_SIZE):
        if chunk_size < 1024 or chunk_size > 1024 * 1024:
            raise ValueError("chunk_size must be between 1 KiB and 1 MiB.")
        self.transport = transport
        self.chunk_size = chunk_size

    def _obtain_dek(
        self,
        context: EnvelopeContext,
        *,
        existing_wrapped_dek_b64: str | None = None,
        existing_key_ref: str | None = None,
    ) -> tuple[bytes, str]:
        kms_aad = context.kms_aad()
        if existing_wrapped_dek_b64 and existing_key_ref == context.key_ref:
            try:
                wrapped = base64.b64decode(existing_wrapped_dek_b64.encode("ascii"), validate=True)
            except ValueError as error:
                raise RecoveryCryptoError("Invalid wrapped DEK encoding.") from error
            dek = self.transport.kms_unwrap(context.key_ref, wrapped, aad=kms_aad)
            if len(dek) != AES_KEY_BYTES:
                raise RecoveryCryptoError("Unwrapped DEK has invalid length.")
            return dek, existing_wrapped_dek_b64
        dek = os.urandom(AES_KEY_BYTES)
        wrapped = self.transport.kms_wrap(context.key_ref, dek, aad=kms_aad)
        wrapped_b64 = base64.b64encode(wrapped).decode("ascii")
        return dek, wrapped_b64

    def _upload_file_chunks(
        self,
        path: Path,
        *,
        context: EnvelopeContext,
        dek: bytes,
        key_fp: str,
        stats: dict[str, int],
        new_chunk_refs: list[ChunkRef],
    ) -> tuple[str, int, list[ChunkRef]]:
        _require_regular_no_symlink(path)
        whole_hasher = hashlib.sha256()
        total_plaintext = 0
        refs: list[ChunkRef] = []
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(self.chunk_size)
                if not chunk:
                    break
                whole_hasher.update(chunk)
                total_plaintext += len(chunk)
                chunk_sha256 = hashlib.sha256(chunk).hexdigest()
                object_key = validate_relative_object_key(f"chunks/{key_fp}/{chunk_sha256}.enc")
                head = self.transport.head_object(object_key)
                if head.exists and head.sha256 is not None and head.size is not None:
                    ref = ChunkRef(
                        chunk_sha256=chunk_sha256,
                        object_key=object_key,
                        ciphertext_sha256=head.sha256,
                        plaintext_size=len(chunk),
                        ciphertext_size=head.size,
                    )
                    stats["deduplicated_chunks"] += 1
                    stats["stored_bytes"] += head.size
                else:
                    framed = _seal_chunk(dek, chunk, aad=context.chunk_aad(chunk_sha256))
                    meta = self.transport.put_object(object_key, framed)
                    actual_sha = hashlib.sha256(framed).hexdigest()
                    if meta.sha256 != actual_sha or meta.size != len(framed):
                        raise RecoveryIntegrityError("Uploaded chunk metadata mismatch.")
                    ref = ChunkRef(
                        chunk_sha256=chunk_sha256,
                        object_key=object_key,
                        ciphertext_sha256=actual_sha,
                        plaintext_size=len(chunk),
                        ciphertext_size=len(framed),
                    )
                    stats["uploaded_chunks"] += 1
                    stats["uploaded_bytes"] += len(framed)
                    stats["stored_bytes"] += len(framed)
                    new_chunk_refs.append(ref)
                refs.append(ref)
        if not refs:
            empty_sha = hashlib.sha256(b"").hexdigest()
            object_key = validate_relative_object_key(f"chunks/{key_fp}/{empty_sha}.enc")
            head = self.transport.head_object(object_key)
            if head.exists and head.sha256 is not None and head.size is not None:
                ref = ChunkRef(
                    chunk_sha256=empty_sha,
                    object_key=object_key,
                    ciphertext_sha256=head.sha256,
                    plaintext_size=0,
                    ciphertext_size=head.size,
                )
                stats["deduplicated_chunks"] += 1
                stats["stored_bytes"] += head.size
            else:
                framed = _seal_chunk(dek, b"", aad=context.chunk_aad(empty_sha))
                meta = self.transport.put_object(object_key, framed)
                actual_sha = hashlib.sha256(framed).hexdigest()
                if meta.sha256 != actual_sha or meta.size != len(framed):
                    raise RecoveryIntegrityError("Uploaded empty chunk metadata mismatch.")
                ref = ChunkRef(
                    chunk_sha256=empty_sha,
                    object_key=object_key,
                    ciphertext_sha256=actual_sha,
                    plaintext_size=0,
                    ciphertext_size=len(framed),
                )
                stats["uploaded_chunks"] += 1
                stats["uploaded_bytes"] += len(framed)
                stats["stored_bytes"] += len(framed)
                new_chunk_refs.append(ref)
            refs.append(ref)
        return whole_hasher.hexdigest(), total_plaintext, refs

    def create_point(
        self,
        *,
        context: EnvelopeContext,
        captured_at: int,
        business_revision: str,
        files_generation: str,
        source_generation: int,
        release_ref: str,
        databases: list[DatabaseInput],
        files: list[RetainedFileInput] | None = None,
        existing_wrapped_dek_b64: str | None = None,
        existing_key_ref: str | None = None,
        full_readback: bool = False,
    ) -> BackupPointResult:
        """Upload deduplicated encrypted chunks, publish manifest last, and verify readback."""
        if not databases:
            raise ValueError("At least one database snapshot is required.")
        dek, wrapped_dek_b64 = self._obtain_dek(
            context,
            existing_wrapped_dek_b64=existing_wrapped_dek_b64,
            existing_key_ref=existing_key_ref,
        )
        key_fp = key_fingerprint(context.key_ref)
        stats = {
            "stored_bytes": 0,
            "uploaded_bytes": 0,
            "deduplicated_chunks": 0,
            "uploaded_chunks": 0,
        }
        new_chunk_refs: list[ChunkRef] = []

        db_manifests: list[DatabaseSnapshotManifest] = []
        seen_db_names: set[str] = set()
        for db_input in databases:
            if db_input.filename in seen_db_names:
                raise RecoveryIntegrityError("Duplicate database snapshot filename.")
            seen_db_names.add(db_input.filename)
            digest, size, chunks = self._upload_file_chunks(
                db_input.path,
                context=context,
                dek=dek,
                key_fp=key_fp,
                stats=stats,
                new_chunk_refs=new_chunk_refs,
            )
            db_manifests.append(
                DatabaseSnapshotManifest(
                    filename=db_input.filename,
                    plaintext_sha256=digest,
                    plaintext_size=size,
                    chunks=chunks,
                )
            )

        file_manifests: list[RetainedFileManifest] = []
        seen_paths: set[str] = set()
        for file_input in sorted(files or [], key=lambda item: item.relative_path):
            rel = validate_relative_file_path(file_input.relative_path)
            if rel in seen_paths:
                raise RecoveryIntegrityError("Duplicate retained file path in manifest.")
            seen_paths.add(rel)
            digest, size, chunks = self._upload_file_chunks(
                file_input.path,
                context=context,
                dek=dek,
                key_fp=key_fp,
                stats=stats,
                new_chunk_refs=new_chunk_refs,
            )
            file_manifests.append(
                RetainedFileManifest(
                    relative_path=rel,
                    content_sha256=digest,
                    plaintext_size=size,
                    chunks=chunks,
                )
            )

        manifest = RecoveryPointManifest(
            deployment_id=context.deployment_id,
            scope_kind=context.scope_kind,
            operator_id=context.operator_id,
            workspace_id=context.workspace_id,
            point_id=context.point_id,
            captured_at=captured_at,
            business_revision=business_revision,
            files_generation=files_generation,
            source_generation=source_generation,
            release_ref=release_ref,
            schema_revisions=context.schema_revisions,
            key_ref=context.key_ref,
            databases=db_manifests,
            files=file_manifests,
        )
        manifest_plaintext = manifest.model_dump_json().encode("utf-8")
        manifest_nonce = os.urandom(AES_GCM_NONCE_BYTES)
        manifest_ciphertext = AESGCM(dek).encrypt(
            manifest_nonce, manifest_plaintext, context.manifest_aad()
        )
        envelope = ManifestEnvelope(
            deployment_id=context.deployment_id,
            scope_kind=context.scope_kind,
            operator_id=context.operator_id,
            workspace_id=context.workspace_id,
            point_id=context.point_id,
            schema_revisions=context.schema_revisions,
            key_ref=context.key_ref,
            wrapped_dek_b64=wrapped_dek_b64,
            nonce_b64=base64.b64encode(manifest_nonce).decode("ascii"),
            ciphertext_b64=base64.b64encode(manifest_ciphertext).decode("ascii"),
        )
        envelope_bytes = envelope.model_dump_json().encode("utf-8")
        manifest_ref = validate_relative_object_key(f"manifests/{context.point_id}.json.enc")
        manifest_meta = self.transport.put_object(manifest_ref, envelope_bytes)
        manifest_sha256 = hashlib.sha256(envelope_bytes).hexdigest()
        if manifest_meta.sha256 != manifest_sha256 or manifest_meta.size != len(envelope_bytes):
            raise RecoveryIntegrityError("Published manifest metadata mismatch.")
        stats["uploaded_bytes"] += len(envelope_bytes)
        stats["stored_bytes"] += len(envelope_bytes)

        verify_keys = None if full_readback else {ref.object_key for ref in new_chunk_refs}
        verified_chunks = self.verify_point(
            manifest_ref=manifest_ref,
            expected_context=context,
            expected_manifest_sha256=manifest_sha256,
            only_object_keys=verify_keys,
        )
        return BackupPointResult(
            point_id=context.point_id,
            manifest_ref=manifest_ref,
            manifest_sha256=manifest_sha256,
            manifest_format=MANIFEST_FORMAT_VERSION,
            key_ref=context.key_ref,
            wrapped_dek_b64=wrapped_dek_b64,
            stored_bytes=stats["stored_bytes"],
            uploaded_bytes=stats["uploaded_bytes"],
            deduplicated_chunks=stats["deduplicated_chunks"],
            uploaded_chunks=stats["uploaded_chunks"],
            verified_chunks=verified_chunks,
        )

    def load_manifest(
        self,
        *,
        manifest_ref: str,
        expected_deployment_id: str,
        expected_scope_kind: str,
        expected_operator_id: str | None = None,
        expected_workspace_id: str | None = None,
        expected_point_id: str | None = None,
        expected_key_ref: str | None = None,
        expected_manifest_sha256: str | None = None,
    ) -> tuple[RecoveryPointManifest, EnvelopeContext, bytes, str]:
        """Download, verify digest/scope/AAD, unwrap DEK, and decrypt a point manifest."""
        validated_ref = validate_relative_object_key(manifest_ref)
        raw_bytes, meta = self.transport.get_object(validated_ref)
        actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if meta.sha256 is not None and meta.sha256 != actual_sha256:
            raise RecoveryIntegrityError(
                "Downloaded manifest digest does not match storage metadata."
            )
        if expected_manifest_sha256 is not None:
            validate_sha256_hex(expected_manifest_sha256)
            if actual_sha256 != expected_manifest_sha256:
                raise RecoveryIntegrityError("Manifest SHA-256 mismatch.")
        try:
            envelope = ManifestEnvelope.model_validate_json(raw_bytes)
        except Exception as error:
            raise RecoveryIntegrityError("Manifest envelope is malformed.") from error

        if (
            envelope.deployment_id != expected_deployment_id
            or envelope.scope_kind != expected_scope_kind
            or envelope.operator_id != expected_operator_id
            or envelope.workspace_id != expected_workspace_id
        ):
            raise RecoveryIntegrityError("Manifest scope does not match caller workspace.")
        if expected_point_id is not None and envelope.point_id != expected_point_id:
            raise RecoveryIntegrityError("Manifest point_id mismatch.")
        if expected_key_ref is not None and envelope.key_ref != expected_key_ref:
            raise RecoveryIntegrityError("Manifest key_ref mismatch.")

        context = envelope.to_envelope_context()
        try:
            wrapped_dek = base64.b64decode(envelope.wrapped_dek_b64.encode("ascii"), validate=True)
            nonce = base64.b64decode(envelope.nonce_b64.encode("ascii"), validate=True)
            ciphertext = base64.b64decode(envelope.ciphertext_b64.encode("ascii"), validate=True)
        except ValueError as error:
            raise RecoveryCryptoError("Manifest envelope contains invalid base64.") from error

        dek = self.transport.kms_unwrap(context.key_ref, wrapped_dek, aad=context.kms_aad())
        if len(dek) != AES_KEY_BYTES:
            raise RecoveryCryptoError("Unwrapped DEK has invalid length.")
        try:
            plaintext = AESGCM(dek).decrypt(nonce, ciphertext, context.manifest_aad())
        except InvalidTag as error:
            raise RecoveryCryptoError("Manifest AEAD verification failed.") from error
        try:
            manifest = RecoveryPointManifest.model_validate_json(plaintext)
        except Exception as error:
            raise RecoveryIntegrityError("Decrypted manifest payload is invalid.") from error

        if (
            manifest.deployment_id != context.deployment_id
            or manifest.scope_kind != context.scope_kind
            or manifest.operator_id != context.operator_id
            or manifest.workspace_id != context.workspace_id
            or manifest.point_id != context.point_id
            or manifest.key_ref != context.key_ref
            or manifest.schema_revisions != context.schema_revisions
        ):
            raise RecoveryIntegrityError(
                "Decrypted manifest contradicts authenticated envelope metadata."
            )
        return manifest, context, dek, actual_sha256

    def _read_and_verify_chunk(
        self,
        ref: ChunkRef,
        *,
        context: EnvelopeContext,
        dek: bytes,
    ) -> bytes:
        framed, meta = self.transport.get_object(ref.object_key)
        actual_ciphertext_sha = hashlib.sha256(framed).hexdigest()
        if actual_ciphertext_sha != ref.ciphertext_sha256 or len(framed) != ref.ciphertext_size:
            raise RecoveryIntegrityError("Downloaded chunk ciphertext digest/size mismatch.")
        if meta.sha256 is not None and meta.sha256 != actual_ciphertext_sha:
            raise RecoveryIntegrityError("Storage metadata digest mismatch for chunk.")
        plaintext = _open_chunk(dek, framed, aad=context.chunk_aad(ref.chunk_sha256))
        if len(plaintext) != ref.plaintext_size:
            raise RecoveryIntegrityError("Decrypted chunk size mismatch.")
        if hashlib.sha256(plaintext).hexdigest() != ref.chunk_sha256:
            raise RecoveryIntegrityError("Decrypted chunk plaintext digest mismatch.")
        return plaintext

    def verify_point(
        self,
        *,
        manifest_ref: str,
        expected_context: EnvelopeContext,
        expected_manifest_sha256: str | None = None,
        only_object_keys: set[str] | None = None,
    ) -> int:
        """Readback-verify manifest and referenced encrypted chunks from off-host storage."""
        manifest, context, dek, _ = self.load_manifest(
            manifest_ref=manifest_ref,
            expected_deployment_id=expected_context.deployment_id,
            expected_scope_kind=expected_context.scope_kind,
            expected_operator_id=expected_context.operator_id,
            expected_workspace_id=expected_context.workspace_id,
            expected_point_id=expected_context.point_id,
            expected_key_ref=expected_context.key_ref,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        if context.schema_revisions != expected_context.schema_revisions:
            raise RecoveryIntegrityError("Manifest schema_revisions mismatch.")
        seen_keys: set[str] = set()
        verified_count = 0
        all_chunks = [
            chunk for group in (*manifest.databases, *manifest.files) for chunk in group.chunks
        ]
        for ref in all_chunks:
            if ref.object_key in seen_keys:
                continue
            seen_keys.add(ref.object_key)
            if only_object_keys is not None and ref.object_key not in only_object_keys:
                head = self.transport.head_object(ref.object_key)
                if (
                    not head.exists
                    or head.sha256 != ref.ciphertext_sha256
                    or head.size != ref.ciphertext_size
                ):
                    raise RecoveryIntegrityError(
                        "Deduplicated chunk missing or altered in storage."
                    )
                continue
            self._read_and_verify_chunk(ref, context=context, dek=dek)
            verified_count += 1
        return verified_count

    def restore_point(
        self,
        *,
        manifest_ref: str,
        expected_deployment_id: str,
        expected_scope_kind: str,
        destination_dir: Path,
        expected_operator_id: str | None = None,
        expected_workspace_id: str | None = None,
        expected_point_id: str | None = None,
        expected_manifest_sha256: str | None = None,
    ) -> RestorePointResult:
        """Download, verify, decrypt, and materialize a verified point into an empty directory."""
        if destination_dir.is_symlink() or not destination_dir.is_dir():
            raise RecoveryIntegrityError(
                "Restore destination must be an existing non-symlink directory."
            )
        if any(destination_dir.iterdir()):
            raise RecoveryIntegrityError("Restore destination directory must be empty.")

        manifest, context, dek, manifest_sha256 = self.load_manifest(
            manifest_ref=manifest_ref,
            expected_deployment_id=expected_deployment_id,
            expected_scope_kind=expected_scope_kind,
            expected_operator_id=expected_operator_id,
            expected_workspace_id=expected_workspace_id,
            expected_point_id=expected_point_id,
            expected_manifest_sha256=expected_manifest_sha256,
        )

        verified_chunks = 0
        database_files: list[str] = []
        for db in manifest.databases:
            target = _safe_destination_path(destination_dir, db.filename)
            verified_chunks += self._restore_chunks_to_file(
                db.chunks,
                target=target,
                expected_sha256=db.plaintext_sha256,
                expected_size=db.plaintext_size,
                context=context,
                dek=dek,
            )
            database_files.append(db.filename)

        restored_files: list[str] = []
        files_root = destination_dir / "files"
        if manifest.files:
            files_root.mkdir(mode=0o700, exist_ok=True)
        for item in manifest.files:
            target = _safe_destination_path(files_root, item.relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            verified_chunks += self._restore_chunks_to_file(
                item.chunks,
                target=target,
                expected_sha256=item.content_sha256,
                expected_size=item.plaintext_size,
                context=context,
                dek=dek,
            )
            restored_files.append(item.relative_path)

        return RestorePointResult(
            point_id=manifest.point_id,
            manifest_sha256=manifest_sha256,
            database_files=database_files,
            restored_files=restored_files,
            verified_chunks=verified_chunks,
        )

    def _restore_chunks_to_file(
        self,
        chunks: list[ChunkRef],
        *,
        target: Path,
        expected_sha256: str,
        expected_size: int,
        context: EnvelopeContext,
        dek: bytes,
    ) -> int:
        hasher = hashlib.sha256()
        written = 0
        count = 0
        with target.open("wb") as stream:
            for ref in chunks:
                plaintext = self._read_and_verify_chunk(ref, context=context, dek=dek)
                stream.write(plaintext)
                hasher.update(plaintext)
                written += len(plaintext)
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(target, 0o600)
        if written != expected_size or hasher.hexdigest() != expected_sha256:
            raise RecoveryIntegrityError("Restored file digest/size mismatch.")
        return count

    def prune_unreferenced_chunks(
        self,
        *,
        retained_manifest_refs: list[str],
        expected_deployment_id: str,
        expected_scope_kind: str,
        expected_operator_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> PruneResult:
        """Delete only chunk objects not referenced by any retained verified manifest."""
        if not retained_manifest_refs:
            raise RecoveryIntegrityError(
                "Refusing to prune without at least one retained manifest."
            )
        referenced: set[str] = set()
        for manifest_ref in retained_manifest_refs:
            manifest, _, _, _ = self.load_manifest(
                manifest_ref=manifest_ref,
                expected_deployment_id=expected_deployment_id,
                expected_scope_kind=expected_scope_kind,
                expected_operator_id=expected_operator_id,
                expected_workspace_id=expected_workspace_id,
            )
            for group in (*manifest.databases, *manifest.files):
                for ref in group.chunks:
                    referenced.add(ref.object_key)
        existing = self.transport.list_objects("chunks/")
        deleted: list[str] = []
        for key in existing:
            if key not in referenced:
                self.transport.delete_object(key)
                deleted.append(key)
        return PruneResult(retained_chunks=len(referenced), deleted_chunks=sorted(deleted))
