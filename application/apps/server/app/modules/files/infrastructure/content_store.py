from __future__ import annotations

import hashlib
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.modules.files.application.errors import FileError, MAX_FILE_BYTES
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

    def store(self, source: Path) -> _Lease:
        managed = self.files_root / "managed"
        managed.mkdir(mode=0o700, exist_ok=True)
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
                    if target.is_symlink() or _hash_file(target) != (content_hash, size):
                        raise FileError("Stored file content failed its integrity check.")
                    temporary.unlink()
                    return _Lease(self, relative, size, content_hash, False, lock)
                temporary.chmod(0o600)
                temporary.replace(target)
                return _Lease(self, relative, size, content_hash, True, lock)
            except Exception:
                lock.__exit__(None, None, None)
                raise
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
            raise FileError("The file does not have a local content location.")
        path = (self.files_root / item.local_relative_path).resolve()
        if self.files_root.resolve() not in path.parents or not path.is_file():
            raise FileError("Stored file content is unavailable.")
        digest = hashlib.sha256(); actual = 0
        with path.open("rb") as input_file:
            while chunk := input_file.read(1024 * 1024):
                actual += len(chunk); digest.update(chunk)
        if actual != item.size_bytes or digest.hexdigest() != item.content_sha256:
            raise FileError("Stored file content failed its integrity check.")
        return path


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


class S3ContentStore:
    """AWS S3 adapter using an injected boto3-compatible client."""

    storage_provider = "s3"

    def __init__(self, client, bucket: str, prefix: str = "managed", lock_root: Path | None = None) -> None:
        self.client = client
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        self.lock_root = lock_root or Path(tempfile.gettempdir()) / "epm-s3-locks"
        if not self.bucket:
            raise FileError("S3 storage requires a bucket.")

    def store(self, source: Path) -> _S3Lease:
        self._require_bucket_versioning()
        digest, size = _hash_file(source)
        if size > MAX_FILE_BYTES:
            raise FileError("File exceeds the 50 MiB upload limit.")
        # Each publication owns its object, including across independent clients.
        # Local blobs deduplicate; remote objects must not share rollback ownership.
        suffix = f"{digest}/{uuid4().hex}"
        key = f"{self.prefix}/{suffix}" if self.prefix else suffix
        lock = self._acquire_digest_lock(digest)
        lease = None
        try:
            with source.open("rb") as body:
                response = self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=body,
                    Metadata={"sha256": digest}, IfNoneMatch="*",
                )
            version = response.get("VersionId")
            if not version or version == "null":
                self._delete_unidentified_publication(key)
                raise FileError("S3 publication did not return a durable version identity.")
            lease = _S3Lease(self, key, size, digest, True, s3_bucket=self.bucket,
                             s3_version_id=version, provider_etag=response.get("ETag"), lock=lock)
            self._verify_existing(key, version, digest, size)
            return lease
        except Exception as error:
            try:
                if lease is not None:
                    lease.rollback()
                else:
                    lock.__exit__(None, None, None)
            except Exception as cleanup_error:
                raise FileError(
                    "S3 publication failed and its private object could not be cleaned up."
                ) from cleanup_error
            if isinstance(error, FileError):
                raise
            raise FileError(f"Unable to publish S3 content: {error}") from error

    def _require_bucket_versioning(self) -> None:
        try:
            versioning = self.client.get_bucket_versioning(Bucket=self.bucket)
        except Exception as error:
            raise FileError(f"Unable to verify S3 bucket versioning: {error}") from error
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
                raise FileError("Existing S3 content failed its integrity check.")
        finally:
            path.unlink(missing_ok=True)

    def path_for(self, item: StoredFile) -> Path:
        if item.storage_provider != "s3" or not item.s3_bucket or not item.s3_object_key:
            raise FileError("The file does not have an S3 content location.")
        staged = tempfile.NamedTemporaryFile(prefix="epm-s3-", delete=False)
        path = Path(staged.name)
        staged.close()
        try:
            self.client.download_file(item.s3_bucket, item.s3_object_key, str(path),
                                      ExtraArgs={"VersionId": item.s3_version_id} if item.s3_version_id else {})
            digest, actual = _hash_file(path)
            if actual != item.size_bytes or digest != item.content_sha256:
                raise FileError("Stored S3 content failed its integrity check.")
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def materialize(self, bucket: str, object_key: str, version_id: str | None,
                    target: Path, expected_hash: str, expected_size: int) -> None:
        with target.open("xb") as output:
            extra = {"VersionId": version_id} if version_id else None
            if extra:
                self.client.download_fileobj(bucket, object_key, output, ExtraArgs=extra)
            else:
                self.client.download_fileobj(bucket, object_key, output)
        digest, size = _hash_file(target)
        if digest != expected_hash or size != expected_size:
            target.unlink(missing_ok=True)
            raise FileError("S3 content failed portable-backup verification.")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size
