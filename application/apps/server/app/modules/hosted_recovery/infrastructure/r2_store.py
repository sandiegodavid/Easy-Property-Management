"""Host-side Cloudflare R2 object store adapter (used only inside epm-backup-proxy)."""

from __future__ import annotations

from contextlib import closing
import hashlib
from importlib import import_module
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from app.modules.hosted_recovery.domain.models import (
    BackupProxyUnavailable,
    ObjectMetadata,
    RecoveryIntegrityError,
    validate_relative_object_key,
    validate_sha256_hex,
)

_R2_HOST = re.compile(r"^[0-9a-f]{32}\.r2\.cloudflarestorage\.com$")
_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def validate_r2_endpoint(endpoint_url: str) -> str:
    parsed = urlsplit(endpoint_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not _R2_HOST.fullmatch(parsed.hostname)
    ):
        raise ValueError(
            "R2 endpoint must be https://<32-hex-account-id>.r2.cloudflarestorage.com."
        )
    return f"https://{parsed.hostname}"


def validate_bucket_name(bucket: str) -> str:
    if not isinstance(bucket, str) or not _BUCKET_NAME.fullmatch(bucket):
        raise ValueError("Invalid R2 bucket name.")
    return bucket


def _is_not_found_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    err = response.get("Error") or {}
    code = str(err.get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


class R2ObjectStore:
    """S3v4-compatible Cloudflare R2 object store for host-side epm-backup-proxy."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client=None,
    ):
        self.endpoint_url = validate_r2_endpoint(endpoint_url)
        self.bucket = validate_bucket_name(bucket)
        if client is not None:
            self._client = client
        else:
            if not access_key_id or not secret_access_key:
                raise ValueError("R2 access_key_id and secret_access_key are required.")
            try:
                boto3 = import_module("boto3")
                botocore_config = import_module("botocore.config")
            except ImportError as error:
                raise BackupProxyUnavailable(
                    "R2 client requires the optional boto3 package."
                ) from error
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name="auto",
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=botocore_config.Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=10,
                    read_timeout=30,
                ),
            )

    def put_object(self, full_key: str, data: bytes, *, sha256_hex: str) -> ObjectMetadata:
        key = validate_relative_object_key(full_key)
        expected_sha = validate_sha256_hex(sha256_hex)
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            raise RecoveryIntegrityError("Object digest mismatch before upload.")
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType="application/octet-stream",
                Metadata={"epm-sha256": expected_sha},
            )
        except Exception as error:
            raise BackupProxyUnavailable("R2 put_object failed.") from error
        return ObjectMetadata(exists=True, sha256=expected_sha, size=len(data))

    def head_object(self, full_key: str) -> ObjectMetadata:
        key = validate_relative_object_key(full_key)
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if _is_not_found_error(error):
                return ObjectMetadata(exists=False)
            raise BackupProxyUnavailable("R2 head_object failed.") from error
        metadata = response.get("Metadata") or {}
        raw_sha = metadata.get("epm-sha256")
        sha = validate_sha256_hex(raw_sha) if isinstance(raw_sha, str) else None
        size = response.get("ContentLength")
        return ObjectMetadata(exists=True, sha256=sha, size=int(size) if size is not None else None)

    def get_object(
        self, full_key: str, *, max_bytes: int | None = None
    ) -> tuple[bytes, ObjectMetadata]:
        key = validate_relative_object_key(full_key)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            content_length = response.get("ContentLength")
            if (
                max_bytes is not None
                and content_length is not None
                and int(content_length) > max_bytes
            ):
                with closing(response["Body"]):
                    pass
                raise BackupProxyUnavailable("R2 object exceeds maximum allowed frame size.")
            with closing(response["Body"]) as stream:
                if max_bytes is not None:
                    body = stream.read(max_bytes + 1)
                    if len(body) > max_bytes:
                        raise BackupProxyUnavailable(
                            "R2 object stream exceeds maximum allowed frame size."
                        )
                else:
                    body = stream.read()
        except BackupProxyUnavailable:
            raise
        except Exception as error:
            if _is_not_found_error(error):
                raise RecoveryIntegrityError("Requested recovery object does not exist.") from error
            raise BackupProxyUnavailable("R2 get_object failed.") from error
        metadata = response.get("Metadata") or {}
        raw_sha = metadata.get("epm-sha256")
        actual_sha = hashlib.sha256(body).hexdigest()
        if isinstance(raw_sha, str):
            expected_sha = validate_sha256_hex(raw_sha)
            if actual_sha != expected_sha:
                raise RecoveryIntegrityError("Downloaded R2 object failed SHA-256 verification.")
        return body, ObjectMetadata(exists=True, sha256=actual_sha, size=len(body))

    def delete_object(self, full_key: str) -> None:
        key = validate_relative_object_key(full_key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            raise BackupProxyUnavailable("R2 delete_object failed.") from error

    def list_objects_page(
        self,
        prefix: str,
        *,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        if not prefix or not prefix.endswith("/"):
            raise ValueError("Object listing prefix must be non-empty and end with '/'.")
        validate_relative_object_key(prefix[:-1])
        bounded = max(1, min(int(max_keys), 1000))
        params: dict[str, object] = {
            "Bucket": self.bucket,
            "Prefix": prefix,
            "MaxKeys": bounded,
        }
        if continuation_token is not None:
            params["ContinuationToken"] = continuation_token
        try:
            response = self._client.list_objects_v2(**params)
        except Exception as error:
            raise BackupProxyUnavailable("R2 list_objects failed.") from error
        keys: list[str] = []
        for entry in response.get("Contents") or []:
            item_key = entry.get("Key")
            if isinstance(item_key, str):
                keys.append(item_key)
        next_token = (
            response.get("NextContinuationToken")
            if response.get("IsTruncated")
            and isinstance(response.get("NextContinuationToken"), str)
            else None
        )
        return sorted(keys), next_token

    def list_objects(self, prefix: str, *, max_keys: int = 1000) -> list[str]:
        keys, _ = self.list_objects_page(prefix, max_keys=max_keys)
        return keys


class LocalDirectoryObjectStore:
    """Private filesystem ObjectStorePort adapter for component proofs and local tests."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, full_key: str) -> Path:
        key = validate_relative_object_key(full_key)
        target = (self.root / key).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise RecoveryIntegrityError("Object key escapes storage root.") from error
        return target

    def put_object(self, full_key: str, data: bytes, *, sha256_hex: str) -> ObjectMetadata:
        expected_sha = validate_sha256_hex(sha256_hex)
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            raise RecoveryIntegrityError("Object digest mismatch before write.")
        target = self._resolve(full_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".obj-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, target)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
        return ObjectMetadata(exists=True, sha256=actual_sha, size=len(data))

    def head_object(self, full_key: str) -> ObjectMetadata:
        target = self._resolve(full_key)
        if not target.is_file():
            return ObjectMetadata(exists=False)
        data = target.read_bytes()
        return ObjectMetadata(
            exists=True,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
        )

    def get_object(
        self, full_key: str, *, max_bytes: int | None = None
    ) -> tuple[bytes, ObjectMetadata]:
        target = self._resolve(full_key)
        if not target.is_file():
            raise RecoveryIntegrityError("Requested recovery object does not exist.")
        if max_bytes is not None and target.stat().st_size > max_bytes:
            raise BackupProxyUnavailable("Object exceeds maximum allowed frame size.")
        data = target.read_bytes()
        return data, ObjectMetadata(
            exists=True,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
        )

    def delete_object(self, full_key: str) -> None:
        target = self._resolve(full_key)
        target.unlink(missing_ok=True)

    def list_objects_page(
        self,
        prefix: str,
        *,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        if not prefix or not prefix.endswith("/"):
            raise ValueError("Object listing prefix must be non-empty and end with '/'.")
        validate_relative_object_key(prefix[:-1])
        bounded = max(1, min(int(max_keys), 1000))
        base = (self.root / prefix[:-1]).resolve()
        try:
            base.relative_to(self.root)
        except ValueError as error:
            raise RecoveryIntegrityError("Listing prefix escapes storage root.") from error
        if not base.is_dir():
            return [], None
        all_keys = [
            path.relative_to(self.root).as_posix()
            for path in sorted(base.rglob("*"))
            if path.is_file() and not path.name.startswith(".obj-")
        ]
        if continuation_token is not None:
            all_keys = [key for key in all_keys if key > continuation_token]
        page = all_keys[:bounded]
        next_token = page[-1] if len(all_keys) > bounded else None
        return page, next_token

    def list_objects(self, prefix: str, *, max_keys: int = 1000) -> list[str]:
        keys, _ = self.list_objects_page(prefix, max_keys=max_keys)
        return keys
