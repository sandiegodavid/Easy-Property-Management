"""Versioned encrypted archive format for local backup and export packages."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from app.modules.workspace.domain.models import WORKSPACE_FORMAT_VERSION
from app.platform.product_migrations import current_revision
from app.platform.version import application_version


ARCHIVE_MAGIC = b"EPMB"
ARCHIVE_FORMAT_VERSION = 1
APPLICATION_VERSION = application_version()
AUTH_TAG_LENGTH = 16
MAX_HEADER_BYTES = 64 * 1024
MAX_ARCHIVE_ENTRIES = 100_000
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024 * 1024
MAX_ENCRYPTED_PAYLOAD_BYTES = MAX_UNCOMPRESSED_BYTES
MAX_MANIFEST_BYTES = 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class ArchiveError(RuntimeError):
    """Raised when an archive cannot be created, decrypted, or trusted."""


@dataclass(frozen=True)
class ArchiveContents:
    header: dict[str, Any]
    manifest: dict[str, Any]
    file_count: int
    byte_count: int


def require_passphrase(passphrase: str) -> bytes:
    if len(passphrase) < 12:
        raise ArchiveError("Backup passphrases must contain at least 12 characters.")
    return passphrase.encode("utf-8")


def make_header(*, workspace_id: str, package_type: str) -> dict[str, Any]:
    if package_type not in {"backup", "export"}:
        raise ArchiveError("Package type must be backup or export.")
    return {
        "archiveFormatVersion": ARCHIVE_FORMAT_VERSION,
        "createdAt": datetime.now(UTC).isoformat(),
        "encryption": "AES-256-GCM",
        "kdf": {
            "name": "scrypt",
            "length": 32,
            "n": 32768,
            "p": 1,
            "r": 8,
            "salt": base64.b64encode(os.urandom(16)).decode("ascii"),
        },
        "nonce": base64.b64encode(os.urandom(12)).decode("ascii"),
        "packageType": package_type,
        "sourceWorkspaceId": workspace_id,
    }


def write_encrypted_archive(
    payload_zip: Path,
    output_path: Path,
    header: dict[str, Any],
    passphrase: str,
    *,
    validator: Callable[[Path], None] | None = None,
) -> Path:
    """Encrypt to a temporary file and publish only after the requested validation succeeds."""
    passphrase_bytes = require_passphrase(passphrase)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header_bytes = _serialize_header(header)
    key = _derive_key(passphrase_bytes, header)
    nonce = _decode_nonce(header)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header_bytes)

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    temporary_path = Path(temporary_name)
    try:
        if os.name == "posix":
            os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "wb") as destination, payload_zip.open("rb") as source:
            destination.write(ARCHIVE_MAGIC)
            destination.write(struct.pack(">I", len(header_bytes)))
            destination.write(header_bytes)
            while chunk := source.read(CHUNK_SIZE):
                destination.write(encryptor.update(chunk))
            destination.write(encryptor.finalize())
            destination.write(encryptor.tag)
            destination.flush()
            os.fsync(destination.fileno())
        if validator is not None:
            validator(temporary_path)
        else:
            validate_archive(temporary_path, passphrase)
        _publish_no_replace(temporary_path, output_path)
        temporary_path.unlink()
        return output_path
    except (ArchiveError, OSError, ValueError, InvalidTag) as error:
        temporary_path.unlink(missing_ok=True)
        raise ArchiveError(f"Unable to write encrypted archive: {error}") from error
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _publish_no_replace(temporary_path: Path, output_path: Path) -> None:
    """Publish a completed archive atomically without replacing a final path."""
    try:
        os.link(temporary_path, output_path)
        return
    except FileExistsError as error:
        raise ArchiveError("Refusing to overwrite an existing backup archive.") from error
    except OSError as error:
        raise ArchiveError(
            "Backup destination does not support required atomic no-replace publication. "
            "Choose a filesystem that supports hard links."
        ) from error


def validate_archive(archive_path: Path, passphrase: str) -> ArchiveContents:
    """Authenticate, decrypt, and validate every declared payload file without extraction."""
    with tempfile.TemporaryDirectory(prefix="epm-archive-validation-") as temporary_directory:
        zip_path = Path(temporary_directory) / "payload.zip"
        header = decrypt_archive_to_zip(archive_path, passphrase, zip_path)
        return inspect_payload_zip(zip_path, header)


def decrypt_archive_to_zip(archive_path: Path, passphrase: str, zip_path: Path) -> dict[str, Any]:
    """Decrypt an archive into a caller-owned temporary ZIP path and authenticate its contents."""
    passphrase_bytes = require_passphrase(passphrase)
    header, ciphertext_offset, ciphertext_length, tag = _read_archive_layout(archive_path)
    if ciphertext_length > MAX_ENCRYPTED_PAYLOAD_BYTES:
        raise ArchiveError("Archive encrypted payload exceeds the supported size limit.")
    key = _derive_key(passphrase_bytes, header)
    nonce = _decode_nonce(header)
    header_bytes = _serialize_header(header)
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(header_bytes)

    try:
        with archive_path.open("rb") as source, zip_path.open("wb") as destination:
            source.seek(ciphertext_offset)
            remaining = ciphertext_length
            while remaining:
                chunk = source.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ArchiveError("Archive ended before its encrypted payload was complete.")
                destination.write(decryptor.update(chunk))
                remaining -= len(chunk)
            destination.write(decryptor.finalize())
    except InvalidTag as error:
        zip_path.unlink(missing_ok=True)
        raise ArchiveError("Archive authentication failed: the passphrase is wrong or the archive was modified.") from error
    except OSError as error:
        zip_path.unlink(missing_ok=True)
        raise ArchiveError(f"Unable to decrypt archive: {error}") from error
    return header


def inspect_payload_zip(zip_path: Path, header: dict[str, Any]) -> ArchiveContents:
    """Verify ZIP safety plus the encrypted payload manifest and file hashes."""
    try:
        with zipfile.ZipFile(zip_path) as package:
            infos = package.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ArchiveError("Archive has too many entries.")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ArchiveError("Archive contains duplicate paths.")
            for info in infos:
                _validate_zip_info(info)
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES + MAX_MANIFEST_BYTES:
                raise ArchiveError("Archive expands beyond the supported size limit.")
            if "backup-manifest.json" not in names:
                raise ArchiveError("Archive is missing backup-manifest.json.")
            manifest_info = package.getinfo("backup-manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise ArchiveError("Backup manifest exceeds the supported size limit.")
            manifest = json.loads(package.read(manifest_info))
            declared_files = manifest.get("files")
            if not isinstance(declared_files, list):
                raise ArchiveError("Backup manifest has no valid file inventory.")

            expected = {"backup-manifest.json"}
            byte_count = 0
            for item in declared_files:
                if not isinstance(item, dict) or set(item) != {"path", "sha256", "bytes"}:
                    raise ArchiveError("Backup manifest contains an invalid file entry.")
                path = item.get("path")
                digest = item.get("sha256")
                byte_size = item.get("bytes")
                if not isinstance(path, str) or not isinstance(digest, str) or not _exact_int(byte_size):
                    raise ArchiveError("Backup manifest contains an invalid file entry.")
                _validate_relative_path(path)
                if path in expected:
                    raise ArchiveError("Backup manifest contains duplicate file paths.")
                expected.add(path)
                if path not in names:
                    raise ArchiveError(f"Archive is missing declared file: {path}")
                actual_digest, actual_size = _digest_zip_entry(package, path, MAX_UNCOMPRESSED_BYTES - byte_count)
                if actual_digest != digest or actual_size != byte_size:
                    raise ArchiveError(f"Archive file integrity check failed: {path}")
                byte_count += actual_size
                if byte_count > MAX_UNCOMPRESSED_BYTES:
                    raise ArchiveError("Archive expands beyond the supported size limit.")

            archive_files = {info.filename for info in infos if not info.is_dir()}
            if archive_files != expected:
                raise ArchiveError("Archive contains files that are absent from its manifest.")
            _validate_manifest_consistency(manifest, header)
            return ArchiveContents(header=header, manifest=manifest, file_count=len(declared_files), byte_count=byte_count)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise ArchiveError(f"Archive payload is invalid: {error}") from error


def extract_payload_zip(zip_path: Path, destination_root: Path, contents: ArchiveContents) -> None:
    """Safely extract a previously validated payload, stripping the workspace/ prefix."""
    expected_paths = [item["path"] for item in contents.manifest["files"]]
    try:
        with zipfile.ZipFile(zip_path) as package:
            for archive_path in expected_paths:
                destination_relative = Path(archive_path)
                if destination_relative.parts[0] != "workspace":
                    raise ArchiveError("Backup manifest contains an unsupported top-level path.")
                target = destination_root.joinpath(*destination_relative.parts[1:])
                resolved_target = target.resolve()
                if destination_root.resolve() not in resolved_target.parents and resolved_target != destination_root.resolve():
                    raise ArchiveError("Archive extraction path escapes its destination.")
                target.parent.mkdir(parents=True, exist_ok=True)
                remaining = MAX_UNCOMPRESSED_BYTES
                with package.open(archive_path) as source, target.open("wb") as destination:
                    while chunk := source.read(CHUNK_SIZE):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise ArchiveError("Archive expands beyond the supported size limit.")
                        destination.write(chunk)
                _secure_file(target)
    except (OSError, zipfile.BadZipFile) as error:
        raise ArchiveError(f"Unable to extract archive: {error}") from error


def create_payload_zip(payload_root: Path, zip_path: Path) -> None:
    """Write the staged payload to a deterministic ZIP container."""
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for file_path in sorted(path for path in payload_root.rglob("*") if path.is_file()):
            relative_path = file_path.relative_to(payload_root).as_posix()
            package.write(file_path, relative_path)


def file_inventory(payload_root: Path) -> list[dict[str, Any]]:
    """Return the digest inventory for workspace payload files, excluding the package manifest itself."""
    inventory: list[dict[str, Any]] = []
    for file_path in sorted(path for path in payload_root.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(payload_root).as_posix()
        if relative_path == "backup-manifest.json":
            continue
        digest, byte_size = _digest_file(file_path)
        inventory.append({"path": relative_path, "sha256": digest, "bytes": byte_size})
    return inventory


def _read_archive_layout(archive_path: Path) -> tuple[dict[str, Any], int, int, bytes]:
    try:
        with archive_path.open("rb") as source:
            if source.read(len(ARCHIVE_MAGIC)) != ARCHIVE_MAGIC:
                raise ArchiveError("Archive does not have an Easy Property Management header.")
            header_length_bytes = source.read(4)
            if len(header_length_bytes) != 4:
                raise ArchiveError("Archive header is incomplete.")
            header_length = struct.unpack(">I", header_length_bytes)[0]
            if not 0 < header_length <= MAX_HEADER_BYTES:
                raise ArchiveError("Archive header length is invalid.")
            header_bytes = source.read(header_length)
            if len(header_bytes) != header_length:
                raise ArchiveError("Archive header is incomplete.")
            header = json.loads(header_bytes)
            _validate_header(header)
            file_size = archive_path.stat().st_size
            ciphertext_offset = len(ARCHIVE_MAGIC) + 4 + header_length
            ciphertext_length = file_size - ciphertext_offset - AUTH_TAG_LENGTH
            if ciphertext_length < 1:
                raise ArchiveError("Archive has no encrypted payload.")
            source.seek(file_size - AUTH_TAG_LENGTH)
            tag = source.read(AUTH_TAG_LENGTH)
            return header, ciphertext_offset, ciphertext_length, tag
    except (OSError, json.JSONDecodeError, struct.error) as error:
        raise ArchiveError(f"Unable to read archive header: {error}") from error


def _validate_header(header: object) -> None:
    if not isinstance(header, dict):
        raise ArchiveError("Archive header is not a JSON object.")
    if set(header) != {"archiveFormatVersion", "createdAt", "encryption", "kdf", "nonce", "packageType", "sourceWorkspaceId"}:
        raise ArchiveError("Archive header has unsupported fields.")
    if not _exact_int(header.get("archiveFormatVersion")) or header["archiveFormatVersion"] != ARCHIVE_FORMAT_VERSION:
        raise ArchiveError("Archive format version is unsupported.")
    if header.get("encryption") != "AES-256-GCM" or header.get("packageType") not in {"backup", "export"}:
        raise ArchiveError("Archive header uses unsupported encryption or package type.")
    kdf = header.get("kdf")
    if not isinstance(kdf, dict) or set(kdf) != {"name", "length", "n", "p", "r", "salt"} or kdf.get("name") != "scrypt":
        raise ArchiveError("Archive header uses an unsupported key derivation method.")
    if not isinstance(header.get("sourceWorkspaceId"), str) or not isinstance(header.get("nonce"), str):
        raise ArchiveError("Archive header is missing required fields.")
    if not isinstance(header.get("createdAt"), str):
        raise ArchiveError("Archive header is missing its creation time.")
    try:
        created_at = datetime.fromisoformat(header["createdAt"])
    except ValueError as error:
        raise ArchiveError("Archive header has an invalid creation time.") from error
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ArchiveError("Archive header creation time must include a timezone offset.")
    if not _exact_int(kdf.get("length")) or kdf["length"] != 32:
        raise ArchiveError("Archive header has invalid key derivation parameters.")
    if (not all(_exact_int(kdf.get(key)) for key in ("n", "r", "p"))
            or (kdf.get("n"), kdf.get("r"), kdf.get("p")) != (32768, 8, 1)
            or not isinstance(kdf.get("salt"), str)):
        raise ArchiveError("Archive header has invalid key derivation parameters.")


def _validate_manifest_consistency(manifest: object, header: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ArchiveError("Backup manifest is not a JSON object.")
    if set(manifest) != {"applicationVersion", "credentialsExcluded", "createdAt", "databaseSchemaRevision", "files", "liveJournalFilesExcluded", "packageFormatVersion", "packageType", "sourceWorkspaceId", "workspaceFormatVersion"}:
        raise ArchiveError("Backup manifest has unsupported fields.")
    if not isinstance(manifest.get("applicationVersion"), str) or not manifest["applicationVersion"]:
        raise ArchiveError("Backup manifest is missing producer application metadata.")
    try:
        created_at = datetime.fromisoformat(manifest["createdAt"])
    except (KeyError, TypeError, ValueError) as error:
        raise ArchiveError("Backup manifest has an invalid creation time.") from error
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ArchiveError("Backup manifest creation time must include a timezone offset.")
    if not _exact_int(manifest.get("packageFormatVersion")) or manifest["packageFormatVersion"] != ARCHIVE_FORMAT_VERSION:
        raise ArchiveError("Backup package format is unsupported.")
    if manifest.get("sourceWorkspaceId") != header["sourceWorkspaceId"]:
        raise ArchiveError("Archive header does not match the encrypted backup manifest.")
    if manifest.get("packageType") != header["packageType"]:
        raise ArchiveError("Archive package type does not match its backup manifest.")
    if not _exact_int(manifest.get("workspaceFormatVersion")) or manifest["workspaceFormatVersion"] != WORKSPACE_FORMAT_VERSION:
        raise ArchiveError("Archive workspace format is unsupported.")
    if manifest.get("databaseSchemaRevision") != current_revision():
        raise ArchiveError("Archive database schema revision is unsupported.")
    if manifest.get("credentialsExcluded") is not True or manifest.get("liveJournalFilesExcluded") is not True:
        raise ArchiveError("Backup manifest does not provide required exclusion guarantees.")


def _serialize_header(header: dict[str, Any]) -> bytes:
    return json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _exact_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _derive_key(passphrase: bytes, header: dict[str, Any]) -> bytes:
    kdf = header["kdf"]
    try:
        salt = base64.b64decode(kdf["salt"], validate=True)
        if len(salt) != 16:
            raise ValueError("invalid salt length")
        return Scrypt(
            salt=salt,
            length=kdf["length"],
            n=kdf["n"],
            r=kdf["r"],
            p=kdf["p"],
        ).derive(passphrase)
    except (KeyError, TypeError, ValueError) as error:
        raise ArchiveError("Archive key derivation parameters are invalid.") from error


def _decode_nonce(header: dict[str, Any]) -> bytes:
    try:
        nonce = base64.b64decode(header["nonce"], validate=True)
    except (KeyError, TypeError, ValueError) as error:
        raise ArchiveError("Archive encryption nonce is invalid.") from error
    if len(nonce) != 12:
        raise ArchiveError("Archive encryption nonce is invalid.")
    return nonce


def _validate_zip_info(info: zipfile.ZipInfo) -> None:
    _validate_relative_path(info.filename.rstrip("/") if info.is_dir() else info.filename)
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ArchiveError("Archive contains a symbolic link.")
    if info.file_size > MAX_UNCOMPRESSED_BYTES:
        raise ArchiveError("Archive contains an oversized file.")


def _validate_relative_path(path: str) -> None:
    candidate = Path(path)
    if not path or candidate.is_absolute() or ".." in candidate.parts:
        raise ArchiveError("Archive contains an unsafe path.")


def _digest_file(file_path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with file_path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _digest_zip_entry(package: zipfile.ZipFile, path: str, remaining_limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with package.open(path) as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
            byte_size += len(chunk)
            if byte_size > remaining_limit:
                raise ArchiveError("Archive expands beyond the supported size limit.")
    return digest.hexdigest(), byte_size


def _secure_directory(directory: Path) -> None:
    if os.name == "posix":
        directory.chmod(0o700)


def _secure_file(file_path: Path) -> None:
    if os.name == "posix":
        file_path.chmod(0o600)
