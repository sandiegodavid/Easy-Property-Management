"""Private terminal evidence producer over existing encrypted recovery facilities."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_access.infrastructure.recovery_publication import (
    FileRecoveryLedger,
    load_recovery_configuration,
    publish_archive,
    recovery_publisher,
    MAX_ARCHIVE_BYTES,
)
from app.modules.workspace.application.archive_service import WorkspaceArchiveService
from app.modules.workspace.application.service import WorkspaceService


def verify_remote(point, remote, archives, phrase, directory, workspace_id):
    """Independent full GET/decryption/current-schema validation, not a list or ETag."""
    path = directory / "readback.epm-backup"
    body = None
    try:
        response = remote.client.get_object(Bucket=remote.bucket, Key=point.key)
        body = response["Body"]
        if response["ContentLength"] != point.size or point.size > MAX_ARCHIVE_BYTES:
            raise AdminError("admin_recovery_readback_invalid", 409)
        digest, count = hashlib.sha256(), 0
        with path.open("xb") as stream:
            path.chmod(0o600)
            while chunk := body.read(1024 * 1024):
                count += len(chunk)
                if count > point.size:
                    raise AdminError("admin_recovery_readback_invalid", 409)
                stream.write(chunk)
                digest.update(chunk)
        if count != point.size or digest.hexdigest() != point.sha256:
            raise AdminError("admin_recovery_readback_invalid", 409)
        if archives.validate_archive(path, phrase).header["sourceWorkspaceId"] != workspace_id:
            raise AdminError("admin_recovery_workspace_conflict", 409)
    finally:
        if body is not None:
            body.close()


class PreEnrollmentRecovery:
    def __init__(self, setup, reports, platform):
        self.setup, self.reports, self.platform = setup, reports, platform

    def verify(self, identifier, phrase):
        # A root-only CLI constructs this collaborator; neither RPC nor HTTP
        # accepts a passphrase, archive, report path or success assertion.
        with self.setup.store.transaction() as connection:
            operation = self.setup.engine._get(connection, identifier)
            if (
                operation["kind"] != "provision"
                or operation["state"] != "waiting"
                or not self.setup.engine._eligible(connection, operation)
            ):
                raise AdminError("admin_setup_recovery_not_pending", 409)
        import json

        payload = json.loads(operation["payload"])
        self.setup.host.desired(payload)
        plan = payload["setup"]["plan"]
        report_id = str(uuid5(NAMESPACE_URL, identifier + ":pre-enrollment"))
        with self.platform.lock():
            if not self.platform.owned(payload):
                raise AdminError("admin_allocation_owner_conflict", 409)
            paths = self.platform.paths_for(plan["key"])
            before = self.platform.deployment_digest(plan)
            failed = False
            try:
                status = self.platform.source_status(plan["key"])
                if status["active"] or status.get("identity_approved"):
                    raise AdminError("admin_recovery_stage_conflict", 409)
                archive = self.platform.backup(payload, phrase)
                recovery_path = self.platform.h.paths.configs / f"recovery-{plan['key']}.json"
                config = load_recovery_configuration(recovery_path)
                with TemporaryDirectory(
                    prefix="pre-enrollment-", dir=config.ledger_path.parent
                ) as directory:
                    archives = WorkspaceArchiveService(
                        WorkspaceService.from_local_config(paths["local"]),
                        staging_directory=Path(directory),
                    )
                    published = publish_archive(
                        paths["deployment"], recovery_path, archive, archives, phrase
                    )
                    points, _ = FileRecoveryLedger(config).load()
                    point = next(item for item in points if item.key == published["key"])
                    verify_remote(
                        point,
                        recovery_publisher(config).store,
                        archives,
                        phrase,
                        Path(directory),
                        plan["workspace_id"],
                    )
                if self.platform.deployment_digest(plan) != before:
                    raise AdminError("admin_source_binding_changed", 409)
                with self.setup.store.transaction() as connection:
                    current = self.setup.engine._get(connection, identifier)
                    if not self.setup.engine._eligible(connection, current):
                        raise AdminError("admin_authority_fenced", 409)
                    observed = self.setup.store.clock()
                    report = {
                        "operation_id": identifier,
                        "workspace_id": plan["workspace_id"],
                        "configuration_digest": before,
                        "encrypted_archive": True,
                        "independent_readback": True,
                        "workspace_validated": True,
                        "observed": observed,
                        "expires": observed + 86400,
                    }
                    self.reports.publish(report_id, report)
                    self.setup.store._audit(
                        connection, "pre_enrollment_recovery_verified", identifier
                    )
                return {"report_id": report_id, "verified": True}
            except Exception:
                failed = True
                with self.setup.store.transaction() as connection:
                    self.setup.store._audit(
                        connection, "pre_enrollment_recovery_failed", identifier
                    )
                raise AdminError("admin_pre_enrollment_verification_failed", 503) from None
            finally:
                # Never enable access here. Restarting this fresh, still-fenced
                # service only restores the pending-enrollment page.
                try:
                    with self.setup.store.transaction() as connection:
                        current = self.setup.engine._get(connection, identifier)
                        eligible = self.setup.engine._eligible(connection, current)
                    if eligible:
                        self.platform.restart_pending(payload)
                    else:
                        self.platform.contain(payload)
                except Exception:
                    if not failed:
                        raise AdminError("admin_pending_service_restart_required", 503) from None
