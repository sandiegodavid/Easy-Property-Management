from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from app.modules.files.application.errors import MAX_FILE_BYTES, FileError, PublicationCleanupIncomplete
from app.modules.files.domain.models import StoredFile
from app.platform.locking import WorkspaceOperationInProgressError, WorkspaceOperationLock


@dataclass
class _Lease:
    store: "FilesystemContentStore"
    relative_path: str
    size_bytes: int
    content_sha256: str
    published: bool
    lock: WorkspaceOperationLock | None
    storage_provider: str = "local"
    storage_state: str = "available"
    s3_bucket: str | None = None
    s3_object_key: str | None = None
    s3_version_id: str | None = None
    provider_etag: str | None = None

    @property
    def publication_id(self) -> str:
        # Local managed objects are immutable and digest-addressed.
        return self.content_sha256

    @property
    def local_relative_path(self) -> str:
        return self.relative_path

    def commit(self) -> None:
        self._release()

    def rollback(self) -> None:
        try:
            if self.published:
                (self.store.files_root / self.relative_path).unlink(missing_ok=True)
        finally:
            self._release()

    def _release(self) -> None:
        if self.lock is not None:
            lock, self.lock = self.lock, None
            lock.__exit__(None, None, None)


class FilesystemContentStore:
    storage_provider = "local"

    def __init__(self, files_root: Path) -> None:
        self.files_root = files_root

    def _managed_directory(self) -> Path:
        if self.files_root.exists() and (self.files_root.is_symlink() or not self.files_root.is_dir()):
            raise FileError("Managed file root is unsafe.", "file_integrity_failed")
        self.files_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        managed = self.files_root / "managed"
        if managed.exists() and (managed.is_symlink() or not managed.is_dir()):
            raise FileError("Managed file directory is unsafe.", "file_integrity_failed")
        managed.mkdir(mode=0o700, exist_ok=True)
        return managed

    def store(self, source: Path) -> _Lease:
        managed = self._managed_directory()
        temporary = managed / f".{uuid4().hex}.uploading"
        digest = hashlib.sha256(); size = 0
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output:
                while chunk := input_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise FileError("File exceeds the 50 MiB local upload limit.")
                    digest.update(chunk); output.write(chunk)
            content_hash = digest.hexdigest()
            relative = f"managed/{content_hash}"
            target = self.files_root / relative
            lock = self._acquire_digest_lock(content_hash)
            try:
                if target.exists():
                    if _hash_regular_file(target) != (content_hash, size):
                        raise FileError("Stored file content failed its integrity check.")
                    temporary.unlink()
                    return _Lease(self, relative, size, content_hash, False, lock)
                temporary.chmod(0o600)
                temporary.replace(target)
                return _Lease(self, relative, size, content_hash, True, lock)
            except Exception:
                lock.__exit__(None, None, None)
                raise
        except FileError:
            raise
        except OSError as error:
            raise FileError("Local file storage is unavailable.", "file_provider_unavailable") from error
        finally:
            temporary.unlink(missing_ok=True)

    def _acquire_digest_lock(self, digest: str) -> WorkspaceOperationLock:
        lock = WorkspaceOperationLock(self.files_root.parent / ".file-content-locks" / f"{digest}.lock")
        deadline = time.monotonic() + 10
        while True:
            try:
                return lock.__enter__()
            except WorkspaceOperationInProgressError as error:
                if time.monotonic() >= deadline:
                    raise FileError("Another upload of the same content did not finish in time.") from error
                time.sleep(0.05)

    def path_for(self, item: StoredFile) -> Path:
        if item.storage_provider != "local" or item.local_relative_path is None:
            raise FileError("The file does not have a local content location.", "file_content_unavailable")
        if item.local_relative_path != f"managed/{item.content_sha256}":
            raise FileError("Stored file content has an invalid managed locator.", "file_integrity_failed")
        self._managed_directory()
        path = self.files_root / item.local_relative_path
        try:
            digest, actual = _hash_regular_file(path)
        except FileNotFoundError as error:
            raise FileError("Stored file content is unavailable.", "file_content_unavailable") from error
        if actual != item.size_bytes or digest != item.content_sha256:
            raise FileError("Stored file content failed its integrity check.", "file_integrity_failed")
        return path

    def reconcile(self, retained_locations: set[str]) -> dict[str, tuple[str, ...]]:
        """Read-only comparison of the managed directory and retained locators."""
        managed = self._managed_directory()
        found: set[str] = set()
        unverifiable: set[str] = set()
        try:
            for candidate in managed.iterdir():
                if candidate.is_symlink() or not candidate.is_file():
                    unverifiable.add(candidate.name)
                    continue
                # Only immutable digest object names participate in FILE-001.
                if len(candidate.name) == 64 and all(char in "0123456789abcdef" for char in candidate.name):
                    found.add(f"managed/{candidate.name}")
        except OSError as error:
            raise FileError("Unable to reconcile local file storage.", "file_provider_unavailable") from error
        return {
            "referenced": tuple(sorted(found & retained_locations)),
            "orphaned": tuple(sorted(found - retained_locations)),
            "missing": tuple(sorted(retained_locations - found)),
            "unverifiable": tuple(sorted(unverifiable)),
        }


@dataclass
class _S3Lease:
    store: "S3ContentStore"
    s3_object_key: str
    size_bytes: int
    content_sha256: str
    published: bool
    storage_provider: str = "s3"
    storage_state: str = "available"
    local_relative_path: str | None = None
    s3_bucket: str | None = None
    s3_version_id: str | None = None
    provider_etag: str | None = None
    lock: WorkspaceOperationLock | None = None
    publication_id: str | None = None

    def commit(self) -> None:
        self._release()

    def rollback(self) -> None:
        try:
            if self.published:
                arguments = {"Bucket": self.s3_bucket, "Key": self.s3_object_key}
                if self.s3_version_id:
                    arguments["VersionId"] = self.s3_version_id
                self.store.client.delete_object(**arguments)
        finally:
            self._release()

    def _release(self) -> None:
        if self.lock is not None:
            lock, self.lock = self.lock, None
            lock.__exit__(None, None, None)


@dataclass(frozen=True)
class S3ReconciliationPage:
    referenced: tuple[tuple[str, str, str], ...]
    orphaned: tuple[tuple[str, str, str], ...]
    missing: tuple[tuple[str, str, str], ...]
    unverifiable: tuple[tuple[str, str, str], ...]
    continuation: str | None
    incomplete: bool


class S3ContentStore:
    """AWS S3 adapter using an injected boto3-compatible client."""

    storage_provider = "s3"

    def __init__(self, client, bucket: str, prefix: str = "managed", lock_root: Path | None = None,
                 workspace_id: str | Callable[[], str] = "workspace") -> None:
        self.client = client
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        self.lock_root = lock_root or Path(tempfile.gettempdir()) / "epm-s3-locks"
        self.workspace_id = workspace_id
        if not self.bucket:
            raise FileError("S3 storage requires a bucket.")

    def store(self, source: Path) -> _S3Lease:
        self._require_bucket_versioning()
        digest, size = _hash_bounded(source)
        # Each publication owns its object, including across independent clients.
        # Local blobs deduplicate; remote objects must not share rollback ownership.
        workspace_id = self.workspace_id() if callable(self.workspace_id) else self.workspace_id
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise FileError("S3 storage requires a ready workspace identity.")
        publication_id = str(uuid4())
        suffix = f"{workspace_id.strip()}/{digest}/{publication_id}"
        key = f"{self.prefix}/{suffix}" if self.prefix else suffix
        lock = self._acquire_digest_lock(digest)
        lease = None
        try:
            with source.open("rb") as body:
                response = self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=body,
                    Metadata={"sha256": digest, "workspace-id": workspace_id.strip(), "publication-id": publication_id}, IfNoneMatch="*",
                )
            version = response.get("VersionId")
            if not version or version == "null":
                self._delete_unidentified_publication(key)
                raise FileError("S3 publication did not return a durable version identity.", "file_provider_unavailable")
            lease = _S3Lease(self, key, size, digest, True, s3_bucket=self.bucket,
                             s3_version_id=version, provider_etag=response.get("ETag"), lock=lock,
                             publication_id=publication_id)
            self._verify_existing(key, version, digest, size)
            return lease
        except Exception as error:
            try:
                if lease is not None:
                    lease.rollback()
                else:
                    lock.__exit__(None, None, None)
            except Exception as cleanup_error:
                raise PublicationCleanupIncomplete(
                    publication_id, "s3", error, cleanup_error,
                ) from error
            if isinstance(error, FileError):
                raise
            raise FileError("Unable to publish S3 content.", "file_provider_unavailable") from error

    def _require_bucket_versioning(self) -> None:
        try:
            versioning = self.client.get_bucket_versioning(Bucket=self.bucket)
        except Exception as error:
            raise FileError("Unable to verify S3 bucket versioning.", "file_provider_unavailable") from error
        if versioning.get("Status") != "Enabled":
            raise FileError("S3 file storage requires bucket versioning for safe rollback.")

    def _delete_unidentified_publication(self, key: str) -> None:
        """Resolve and delete the exact version when a broken client omits it."""
        try:
            response = self.client.list_object_versions(Bucket=self.bucket, Prefix=key)
            matches = [
                item for item in response.get("Versions", [])
                if item.get("Key") == key and item.get("IsLatest") and item.get("VersionId")
            ]
            if len(matches) != 1:
                raise FileError("could not identify the exact published S3 version")
            self.client.delete_object(
                Bucket=self.bucket,
                Key=key,
                VersionId=matches[0]["VersionId"],
            )
        except Exception as error:
            raise FileError(
                "S3 publication did not return a version ID; manual cleanup may be required."
            ) from error

    def _acquire_digest_lock(self, digest: str) -> WorkspaceOperationLock:
        lock = WorkspaceOperationLock(self.lock_root / f"{self.bucket}-{digest}.lock")
        deadline = time.monotonic() + 10
        while True:
            try:
                return lock.__enter__()
            except WorkspaceOperationInProgressError as error:
                if time.monotonic() >= deadline:
                    raise FileError("Another upload of the same S3 content did not finish in time.") from error
                time.sleep(0.05)

    def _verify_existing(self, key: str, version: str, expected_hash: str, expected_size: int) -> None:
        staged = tempfile.NamedTemporaryFile(prefix="epm-s3-verify-", delete=False)
        path = Path(staged.name)
        staged.close()
        try:
            self.client.download_file(self.bucket, key, str(path), ExtraArgs={"VersionId": version})
            digest, size = _hash_file(path)
            if digest != expected_hash or size != expected_size:
                raise FileError("Existing S3 content failed its integrity check.", "file_integrity_failed")
        except FileError:
            raise
        except Exception as error:
            raise FileError("Unable to verify published S3 content.", "file_provider_unavailable") from error
        finally:
            path.unlink(missing_ok=True)

    def path_for(self, item: StoredFile) -> Path:
        if item.storage_provider != "s3" or not item.s3_bucket or not item.s3_object_key or not item.s3_version_id:
            raise FileError("The file does not have an exact S3 content location.", "file_content_unavailable")
        staged = tempfile.NamedTemporaryFile(prefix="epm-s3-", delete=False)
        path = Path(staged.name)
        staged.close()
        try:
            self.client.download_file(item.s3_bucket, item.s3_object_key, str(path),
                                      ExtraArgs={"VersionId": item.s3_version_id})
            digest, actual = _hash_file(path)
            if actual != item.size_bytes or digest != item.content_sha256:
                raise FileError("Stored S3 content failed its integrity check.", "file_integrity_failed")
            return path
        except FileError:
            path.unlink(missing_ok=True)
            raise
        except Exception as error:
            path.unlink(missing_ok=True)
            if _s3_not_found(error):
                raise FileError("Stored S3 content is unavailable.", "file_content_unavailable") from error
            raise FileError("S3 content is temporarily unavailable.", "file_provider_unavailable") from error

    def materialize(self, bucket: str, object_key: str, version_id: str | None,
                    target: Path, expected_hash: str, expected_size: int) -> None:
        if not version_id:
            raise FileError("S3 content is missing its durable version identity.", "file_content_unavailable")
        with target.open("xb") as output:
            self.client.download_fileobj(bucket, object_key, output, ExtraArgs={"VersionId": version_id})
        digest, size = _hash_file(target)
        if digest != expected_hash or size != expected_size:
            target.unlink(missing_ok=True)
            raise FileError("S3 content failed portable-backup verification.")

    def reconcile(self, retained_locations: set[tuple[str, str, str]], continuation: str | None = None) -> S3ReconciliationPage:
        """Compare one bounded workspace namespace page without deleting anything."""
        workspace_id = self.workspace_id() if callable(self.workspace_id) else self.workspace_id
        prefix = "/".join(part for part in (self.prefix, workspace_id) if part) + "/"
        arguments = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": 1000}
        if continuation:
            arguments["KeyMarker"], _, arguments["VersionIdMarker"] = continuation.partition("|")
        try:
            response = self.client.list_object_versions(**arguments)
        except Exception as error:
            raise FileError("Unable to reconcile S3 file storage.", "file_provider_unavailable") from error
        versions = response.get("Versions", [])
        referenced: list[tuple[str, str, str]] = []
        orphaned: list[tuple[str, str, str]] = []
        unverifiable: list[tuple[str, str, str]] = []
        for value in versions:
            key, version = value.get("Key"), value.get("VersionId")
            if not isinstance(key, str) or not isinstance(version, str) or not version:
                continue
            identity = (self.bucket, key, version)
            (referenced if identity in retained_locations else orphaned).append(identity)
        next_key = response.get("NextKeyMarker")
        next_version = response.get("NextVersionIdMarker")
        next_cursor = f"{next_key}|{next_version}" if next_key and next_version else None
        # Missing versions can only be determined after *all* pages have been
        # accumulated.  The verification coordinator owns that aggregation.
        return S3ReconciliationPage(tuple(referenced), tuple(orphaned), (), tuple(unverifiable), next_cursor, next_cursor is not None)


def _s3_not_found(error: Exception) -> bool:
    """Recognise only definitive object/version absence, never outages."""
    response = getattr(error, "response", None)
    code = (response or {}).get("Error", {}).get("Code") if isinstance(response, dict) else None
    return str(code) in {"404", "NoSuchKey", "NoSuchVersion", "NotFound"}


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _hash_bounded(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise FileError("File exceeds the 50 MiB upload limit.", "file_too_large")
                digest.update(chunk)
    except OSError as error:
        raise FileError("Unable to read S3 upload content.", "file_provider_unavailable") from error
    return digest.hexdigest(), size


def _hash_regular_file(path: Path) -> tuple[str, int]:
    """Read a managed object through one no-follow descriptor."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise FileError("Stored file content is unsafe or unavailable.", "file_integrity_failed") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise FileError("Stored file content is not a regular file.", "file_integrity_failed")
        digest = hashlib.sha256(); size = 0
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk); digest.update(chunk)
        return digest.hexdigest(), size
    finally:
        os.close(descriptor)
