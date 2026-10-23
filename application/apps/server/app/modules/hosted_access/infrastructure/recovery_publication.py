"""Administrator-only R2 archive upload and private, atomic verification ledger."""

from datetime import datetime
from hashlib import sha256
from importlib import import_module
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, AwareDatetime

from app.modules.hosted_access.application.recovery_publication import (
    RecoveryPoint,
    RecoveryPublicationService,
    RecoveryPublicationError,
)
from app.modules.hosted_access.infrastructure.configuration import (
    _secure_file,
    load_hosted_deployment,
)
from app.platform.locking import WorkspaceOperationLock

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_LEDGER_BYTES = 1024 * 1024


class RecoveryConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deployment_id: UUID
    workspace_id: UUID
    endpoint: str = Field(pattern=r"^https://[a-f0-9]{32}\.r2\.cloudflarestorage\.com$")
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    access_key_id: SecretStr
    secret_access_key: SecretStr
    ledger_path: Path


class PointRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=512)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(gt=0, le=MAX_ARCHIVE_BYTES)
    created_at: AwareDatetime
    verified_at: AwareDatetime


class LedgerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deployment_id: UUID
    workspace_id: UUID
    points: list[PointRecord] = Field(max_length=4096)
    retention_pending: bool


class FileRecoveryLedger:
    def __init__(self, config):
        self.config = config
        self.path = config.ledger_path

    def load(self):
        if not self.path.exists():
            return [], False
        if self.path.is_symlink() or self.path.stat().st_size > MAX_LEDGER_BYTES:
            raise RecoveryPublicationError("Recovery ledger is unsafe or exceeds its bound.")
        try:
            value = LedgerRecord.model_validate_json(self.path.read_bytes())
            if (
                value.deployment_id != self.config.deployment_id
                or value.workspace_id != self.config.workspace_id
            ):
                raise ValueError("Foreign ledger")
            return [
                RecoveryPoint(**point.model_dump()) for point in value.points
            ], value.retention_pending
        except (ValueError, OSError) as error:
            raise RecoveryPublicationError("Recovery ledger could not be validated.") from error

    def save(self, points, *, retention_pending):
        value = LedgerRecord(
            deployment_id=self.config.deployment_id,
            workspace_id=self.config.workspace_id,
            points=[PointRecord(**vars(point)) for point in points],
            retention_pending=retention_pending,
        )
        temporary = self.path.with_name(self.path.name + f".{uuid4().hex}.pending")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                temporary.chmod(0o600)
                stream.write(value.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise RecoveryPublicationError(
                "Recovery verification ledger could not be saved; retain the completed archive."
            ) from error
        finally:
            temporary.unlink(missing_ok=True)


class R2RecoveryObjectStore:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def upload(self, key, source, size):
        try:
            with source.open("rb") as stream:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=stream,
                    ContentLength=size,
                    ContentType="application/octet-stream",
                )
        except Exception as error:
            raise RecoveryPublicationError(
                "R2 publication did not complete; keep the local archive and retry explicitly."
            ) from error

    def digest(self, key, size):
        body = None
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            if response["ContentLength"] != size:
                raise ValueError("Length mismatch")
            digest, count = sha256(), 0
            while chunk := body.read(1024 * 1024):
                count += len(chunk)
                if count > size:
                    raise ValueError("Oversized read-back")
                digest.update(chunk)
            if count != size:
                raise ValueError("Truncated read-back")
            return digest.hexdigest()
        except Exception as error:
            raise RecoveryPublicationError(
                "R2 full read-back failed; no old recovery point was pruned."
            ) from error
        finally:
            if body is not None:
                body.close()

    def delete(self, key):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            raise RecoveryPublicationError(
                "R2 retention is incomplete; the new verified point is retained."
            ) from error


def load_recovery_configuration(path):
    try:
        _secure_file(path)
        if path.stat().st_mode & 0o077:
            raise ValueError("Private credential file required")
        config = RecoveryConfiguration.model_validate_json(path.read_bytes())
        directory = config.ledger_path.parent
        if not config.ledger_path.is_absolute() or not directory.is_dir():
            raise ValueError("Existing private ledger folder required")
        if directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
            raise ValueError("Private administrator folder required")
        for parent in (directory, *directory.parents):
            if parent.is_symlink() or parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022:
                raise ValueError("Protected recovery path required")
        return config
    except (OSError, ValueError) as error:
        raise RecoveryPublicationError(
            "Recovery configuration is invalid or not administrator-private."
        ) from error


def recovery_publisher(config):
    try:
        boto3 = import_module("boto3")
        botocore = import_module("botocore.config")
        client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            region_name="auto",
            aws_access_key_id=config.access_key_id.get_secret_value(),
            aws_secret_access_key=config.secret_access_key.get_secret_value(),
            config=botocore.Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}),
        )
    except (ImportError, ValueError) as error:
        raise RecoveryPublicationError(
            "The administrator R2 adapter requires the qualified boto3 dependency."
        ) from error
    prefix = f"epm/{config.deployment_id}/{config.workspace_id}"
    return RecoveryPublicationService(
        R2RecoveryObjectStore(client, config.bucket), FileRecoveryLedger(config), prefix
    )


def publish_archive(deployment_path, recovery_path, archive, backups, passphrase):
    deployment = load_hosted_deployment(deployment_path)
    config = load_recovery_configuration(recovery_path)
    if config.workspace_id != deployment.workspace_id:
        raise RecoveryPublicationError("Recovery configuration has a different workspace identity.")
    if deployment.storage_volume in config.ledger_path.resolve().parents:
        raise RecoveryPublicationError(
            "Administrator recovery state must be outside business storage."
        )
    if (
        archive.is_symlink()
        or not archive.is_file()
        or not 0 < archive.stat().st_size <= MAX_ARCHIVE_BYTES
    ):
        raise RecoveryPublicationError("A bounded completed encrypted archive is required.")
    with WorkspaceOperationLock(config.ledger_path.with_suffix(".lock")):
        # Copy into an administrator-private directory before validation: app-owned
        # staging cannot change a file between validation, hashing and upload.
        with TemporaryDirectory(prefix="epm-publish-", dir=config.ledger_path.parent) as temporary:
            source = Path(temporary) / "validated.epm-backup"
            count = 0
            with archive.open("rb") as incoming, source.open("xb") as outgoing:
                if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
                    raise RecoveryPublicationError(
                        "Publication source must remain a regular archive file."
                    )
                while chunk := incoming.read(1024 * 1024):
                    count += len(chunk)
                    if count > MAX_ARCHIVE_BYTES:
                        raise RecoveryPublicationError(
                            "Publication source exceeds the bounded archive size."
                        )
                    outgoing.write(chunk)
            source.chmod(0o600)
            contents = backups.validate_archive(source, passphrase)
            if contents.header["sourceWorkspaceId"] != str(config.workspace_id):
                raise RecoveryPublicationError(
                    "The validated archive belongs to another workspace."
                )
            digest = sha256()
            with source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            service = recovery_publisher(config)
            point, pending = service.publish(
                source,
                digest=digest.hexdigest(),
                size=source.stat().st_size,
                created_at=datetime.fromisoformat(contents.header["createdAt"]),
            )
            return {"key": point.key, **service.status(), "retentionPending": pending}
