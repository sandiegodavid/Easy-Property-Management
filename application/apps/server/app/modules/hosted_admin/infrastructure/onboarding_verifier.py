"""Private passphrase-only recovery producer. Browser inputs cannot assert checks."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.infrastructure.recovery_bundle import (
    RecoveryBundle,
    seal_bundle,
    open_bundle,
)
from app.modules.hosted_access.infrastructure.recovery_publication import (
    FileRecoveryLedger,
    load_recovery_configuration,
    publish_archive,
    recovery_publisher,
)
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import fingerprint
from app.modules.hosted_admin.application.recovery import RecoveryBinding, RecoveryReport
from app.modules.hosted_admin.infrastructure.pre_enrollment import verify_remote
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository


class OnboardingVerifier:
    def __init__(self, recovery, platform, acceptance):
        self.recovery, self.platform, self.acceptance = recovery, platform, acceptance

    def verify(self, identifier, phrase, register):
        with self.recovery.store.transaction() as connection:
            identity = dict(self.recovery.store._identity(connection))
            handoff = self.recovery._get(connection, identifier)
        binding = RecoveryBinding.model_validate_json(handoff["binding"])
        report_id = str(uuid4())
        observed = self.recovery.store.clock()
        values = dict(
            id=report_id,
            handoff_id=identifier,
            binding=binding,
            state="failed",
            observed=observed,
            expires=observed + 86400,
        )
        payload = {
            "operation_id": identifier,
            "target": binding.instance,
            "setup": {
                "plan": {"key": binding.instance, "workspace_id": binding.workspace_id},
                "data": {"release": binding.release},
            },
        }
        failed = False
        failure = None
        completed = {}
        try:
            current, _ = self.recovery.binding(binding.instance)
            if current != binding or handoff["generation"] != identity["generation"]:
                raise AdminError("admin_recovery_binding_changed", 409)
            with self.platform.lock():
                # Capture while still fenced; neither the helper nor successful
                # recovery evidence ever enables a business session.
                status = self.platform.source_status(binding.instance)
                if status["active"]:
                    raise AdminError("admin_recovery_requires_disabled_access", 409)
                if (
                    self.platform.deployment_digest({"key": binding.instance})
                    != binding.configuration_digest
                ):
                    raise AdminError("admin_recovery_binding_changed", 409)
                paths = self.platform.paths_for(binding.instance)
                archive = self.platform.backup(payload, phrase)
                completed["archive"] = self.recovery.store.clock()
                values["archive"] = True
                config = load_recovery_configuration(
                    self.platform.h.paths.configs / f"recovery-{binding.instance}.json"
                )
                with TemporaryDirectory(
                    prefix="onboarding-", dir=config.ledger_path.parent
                ) as temporary:
                    directory = Path(temporary)
                    archives = BackupService(
                        WorkspaceService.from_local_config(paths["local"]),
                        AuditRecorder(SQLiteAuditRepository(directory / "unused.sqlite")),
                        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
                        archive_staging_directory=directory,
                    )
                    published = publish_archive(
                        paths["deployment"],
                        self.platform.h.paths.configs / f"recovery-{binding.instance}.json",
                        archive,
                        archives,
                        phrase,
                    )
                    points, _ = FileRecoveryLedger(config).load()
                    point = next(item for item in points if item.key == published["key"])
                    remote = recovery_publisher(config).store
                    downloaded = verify_remote(
                        point, remote, archives, phrase, directory, binding.workspace_id
                    )
                    completed["readback"] = self.recovery.store.clock()
                    values.update(
                        readback=True,
                        archive_digest=point.sha256,
                        archive_reference=hashlib.sha256(point.key.encode()).hexdigest(),
                    )
                    restored = archives.restore(downloaded, phrase, directory / "drill")
                    marker = fingerprint(restored.archive_contents.manifest)
                    completed["restore"] = self.recovery.store.clock()
                    values.update(restore=True, snapshot_marker=marker)
                    deployment = HostedDeployment.model_validate_json(
                        paths["deployment"].read_bytes()
                    )
                    bundle = RecoveryBundle(
                        deployment=deployment, approvedSubjectReference=binding.subject
                    )
                    sealed = directory / "binding.epm-recovery"
                    seal_bundle(bundle, sealed, phrase)
                    # Separate namespace/ledger: business archive retention cannot
                    # prune or reinterpret an approved-binding reference.
                    reference_key = (
                        f"epm/{config.deployment_id}/{config.workspace_id}/binding/{report_id}"
                    )
                    remote.upload(reference_key, sealed, sealed.stat().st_size)
                    binding_digest = hashlib.sha256(sealed.read_bytes()).hexdigest()
                    reference_path = directory / "readback-binding.epm-recovery"
                    body = None
                    try:
                        response = remote.client.get_object(Bucket=remote.bucket, Key=reference_key)
                        body = response["Body"]
                        raw = body.read(65537)
                        if (
                            len(raw) != sealed.stat().st_size
                            or hashlib.sha256(raw).hexdigest() != binding_digest
                        ):
                            raise AdminError("admin_binding_readback_failed", 409)
                        reference_path.write_bytes(raw)
                        reference_path.chmod(0o600)
                        if open_bundle(reference_path, phrase) != bundle:
                            raise AdminError("admin_binding_readback_failed", 409)
                        completed["approved_binding"] = self.recovery.store.clock()
                        values.update(
                            approved_binding=True,
                            binding_digest=binding_digest,
                            binding_reference=report_id,
                        )
                    finally:
                        if body is not None:
                            body.close()
                    # Trusted private acceptance independently checks release,
                    # isolation, mount/runtime and protected provider ingress.
                    self.platform.restart_pending(payload)
                    self.acceptance(binding.instance)
                    completed["acceptance"] = self.recovery.store.clock()
                    if (
                        self.platform.deployment_digest({"key": binding.instance})
                        != binding.configuration_digest
                    ):
                        raise AdminError("admin_recovery_binding_changed", 409)
                    values.update(
                        state="verified",
                        archive=True,
                        readback=True,
                        restore=True,
                        approved_binding=True,
                        acceptance=True,
                        archive_digest=point.sha256,
                        binding_digest=binding_digest,
                        snapshot_marker=marker,
                    )
            current, _ = self.recovery.binding(binding.instance)
            if current != binding:
                raise AdminError("admin_recovery_binding_changed", 409)
        except Exception as error:
            failed = True
            failure = error
        finally:
            # A failure report is protected and registered as history too. Do
            # not copy shell output, object keys, data or passphrases into it.
            try:
                values.update(
                    state="failed" if failed else "verified",
                    observed=self.recovery.store.clock(),
                    expires=completed.get("archive", observed) + 86400,
                    completed=completed,
                    verifier_digest=json.loads(
                        self.recovery.reports._read(
                            self.recovery.reports.directory / "verifier.json", 65536
                        )
                    )["verifier_digest"],
                )
                report = RecoveryReport.model_validate(values)
                self.recovery.reports.publish(report_id, report.model_dump())
                register(identifier, report_id)
            except Exception as error:
                failed, failure = True, failure or error
            try:
                with self.recovery.store.transaction() as connection:
                    current = self.recovery.store._identity(connection)
                    eligible = (
                        current["id"] == identity["id"]
                        and current["generation"] == identity["generation"]
                    )
                with self.platform.lock():
                    if eligible:
                        self.platform.restart_pending(payload)
                    else:
                        self.platform.call(
                            ["/usr/bin/systemctl", "stop", f"epm-hosted@{binding.instance}.service"]
                        )
            except Exception as error:
                failed, failure = True, failure or error
        if failed:
            raise AdminError("admin_onboarding_verification_failed", 503) from failure
        return {"report_id": report_id, "verified": True}
