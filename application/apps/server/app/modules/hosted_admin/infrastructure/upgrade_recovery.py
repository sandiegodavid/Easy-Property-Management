"""Private recovery producer and provenance checker for operation-owned upgrades.

No host lock spans encryption, remote publication, read-back or an isolated drill.
The source maintenance gate and stopped writer protect the captured bytes.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import hashlib
import json

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
from app.modules.hosted_admin.application.operations import canonical, fingerprint
from app.modules.hosted_admin.application.upgrades import UpgradeEvidence
from app.modules.hosted_admin.infrastructure.pre_enrollment import verify_remote
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository


class UpgradeRecovery:
    def __init__(self, store, platform, reports, onboarding=None):
        self.store, self.platform, self.reports = store, platform, reports
        self.onboarding = onboarding

    def binding(self, payload):
        item = self.platform.h.inventory.get(payload["instance"])
        deployment = self.platform.h.source.prepare(item.key)["deployment"]
        if (
            deployment["workspace_id"] != payload["plan"]["instance"]["workspace_id"]
            or deployment["operator_id"] != payload["plan"]["instance"]["operator_id"]
        ):
            raise AdminError("admin_upgrade_binding_changed", 409)
        status = self.platform.h.source._transport(vars(item), {"query": "status"})
        if (
            status["binding_revision"] != payload["plan"]["binding_revision"]
            or not status["binding_matches_configuration"]
        ):
            raise AdminError("admin_upgrade_binding_changed", 409)
        return fingerprint(
            {
                "deployment": deployment,
                "subject": status["approved_subject"],
                "binding": status["binding_revision"],
            }
        )

    def current(self, payload, stage):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM upgrade_evidence WHERE operation_id=? AND stage=? ORDER BY rowid DESC LIMIT 1",
                (payload["operation_id"], stage),
            ).fetchone()
        if row is None:
            return None
        proof = UpgradeEvidence.model_validate_json(row[0])
        if self.reports.report(proof.id) != proof.model_dump():
            raise AdminError("admin_upgrade_evidence_unverified", 409)
        if proof.state != "verified" or not proof.observed <= self.store.clock() < proof.expires:
            return None
        desired = (
            payload["plan"]["original_digest"]
            if stage in {"recovery", "rollback"}
            else payload["plan"]["target"]["digest"]
        )
        if (
            proof.owner != payload["gate_owner"]
            or proof.instance != payload["instance"]
            or proof.workspace_id != payload["plan"]["instance"]["workspace_id"]
            or proof.binding_digest != self.binding(payload)
            or proof.release_digest != desired
        ):
            raise AdminError("admin_upgrade_evidence_stale", 409)
        return proof

    def produce(self, payload):
        platform = self.platform
        paths = platform.paths_for(payload["instance"])
        secret = platform.h.paths.control / "upgrades" / f"passphrase-{payload['instance']}"
        platform.h.protected(secret, platform.h.paths, private=True)
        # Bounded secret is read only by the private worker; never an argv/env,
        # journal field, browser value or exception message.
        with secret.open() as stream:
            phrase = stream.read(1025).rstrip("\n")
        if not 12 <= len(phrase) <= 1024:
            raise AdminError("admin_upgrade_private_recovery_required", 409)
        binding = self.binding(payload)
        now = self.store.clock()
        values = dict(
            id=str(uuid4()),
            operation=payload["operation_id"],
            owner=payload["gate_owner"],
            stage="recovery",
            state="failed",
            instance=payload["instance"],
            workspace_id=payload["plan"]["instance"]["workspace_id"],
            release_digest=payload["plan"]["original_digest"],
            binding_digest=binding,
            observed=now,
            expires=now + 86400,
            completed={},
        )
        try:
            helper_payload = {
                "operation_id": payload["operation_id"],
                "target": payload["instance"],
                "setup": {
                    "plan": {"key": payload["instance"], "workspace_id": values["workspace_id"]},
                    "data": {"release": payload["plan"]["instance"]["release"]},
                },
            }
            archive = platform.backup(helper_payload, phrase)
            values["completed"]["archive"] = self.store.clock()
            configuration = paths["deployment"]
            recovery_path = platform.h.paths.configs / f"recovery-{payload['instance']}.json"
            if (
                hashlib.sha256(recovery_path.read_bytes()).hexdigest()
                != payload["plan"]["recovery_configuration_digest"]
            ):
                raise AdminError("admin_upgrade_recovery_configuration_changed", 409)
            config = load_recovery_configuration(recovery_path)
            with TemporaryDirectory(
                prefix="upgrade-drill-", dir=config.ledger_path.parent
            ) as temporary:
                directory = Path(temporary)
                archives = BackupService(
                    WorkspaceService.from_local_config(paths["local"]),
                    AuditRecorder(SQLiteAuditRepository(directory / "unused.sqlite")),
                    lambda database: AuditRecorder(SQLiteAuditRepository(database)),
                    archive_staging_directory=directory,
                )
                published = publish_archive(configuration, recovery_path, archive, archives, phrase)
                points, _ = FileRecoveryLedger(config).load()
                point = next(item for item in points if item.key == published["key"])
                remote = recovery_publisher(config).store
                downloaded = verify_remote(
                    point, remote, archives, phrase, directory, values["workspace_id"]
                )
                values["completed"]["readback"] = self.store.clock()
                restored = archives.restore(downloaded, phrase, directory / "drill")
                values["completed"]["restore"] = self.store.clock()
                deployment = HostedDeployment.model_validate_json(configuration.read_bytes())
                status = platform.h.source._transport(
                    vars(platform.h.inventory.get(payload["instance"])), {"query": "status"}
                )
                bundle = RecoveryBundle(
                    deployment=deployment, approvedSubjectReference=status["approved_subject"]
                )
                sealed = directory / "binding.epm-recovery"
                seal_bundle(bundle, sealed, phrase)
                key = f"epm/{config.deployment_id}/{config.workspace_id}/upgrade-binding/{values['id']}"
                remote.upload(key, sealed, sealed.stat().st_size)
                body = None
                try:
                    response = remote.client.get_object(Bucket=remote.bucket, Key=key)
                    body = response["Body"]
                    raw = body.read(65537)
                    if raw != sealed.read_bytes():
                        raise AdminError("admin_upgrade_binding_readback_failed", 409)
                    readback = directory / "binding-readback.epm-recovery"
                    readback.write_bytes(raw)
                    readback.chmod(0o600)
                    if open_bundle(readback, phrase) != bundle:
                        raise AdminError("admin_upgrade_binding_readback_failed", 409)
                finally:
                    if body is not None:
                        body.close()
                if self.binding(payload) != binding:
                    raise AdminError("admin_upgrade_binding_changed", 409)
                values["completed"]["approved_binding"] = self.store.clock()
                values["observed"] = self.store.clock()
                values.update(
                    state="verified",
                    archive=True,
                    readback=True,
                    restore=True,
                    approved_binding=True,
                    archive_digest=point.sha256,
                    archive_reference=hashlib.sha256(point.key.encode()).hexdigest(),
                    binding_reference=hashlib.sha256(key.encode()).hexdigest(),
                    encrypted_binding_digest=hashlib.sha256(sealed.read_bytes()).hexdigest(),
                    snapshot_marker=fingerprint(restored.archive_contents.manifest),
                )
        except Exception as original:
            try:
                self.record(UpgradeEvidence(**values))
            except Exception:
                raise AdminError(
                    "admin_upgrade_recovery_and_registration_failed", 503
                ) from original
            raise
        else:
            self.record(UpgradeEvidence(**values))
        return self.current(payload, "recovery")

    def resulting(self, payload, stage):
        source = (
            payload
            if not payload.get("rollback")
            else payload | {"operation_id": payload["parent"]}
        )
        previous = self.current(source, "recovery")
        if previous is None:
            raise AdminError("admin_upgrade_recovery_required", 409)
        values = previous.model_dump() | {
            "id": str(uuid4()),
            "operation": payload["operation_id"],
            "stage": stage,
            "release_digest": payload["plan"]["original_digest"]
            if stage == "rollback"
            else payload["plan"]["target"]["digest"],
            "completed": previous.completed.model_dump() | {"acceptance": self.store.clock()},
            "runtime": True,
            "protected_routing": True,
            "observed": self.store.clock(),
            "expires": min(previous.expires, self.store.clock() + 600),
        }
        proof = UpgradeEvidence.model_validate(values)
        self.record(proof)
        return proof

    def record(self, proof):
        self.reports.publish(proof.id, proof.model_dump())
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO upgrade_evidence VALUES (?,?,?,?,?)",
                (
                    proof.id,
                    proof.operation,
                    proof.stage,
                    canonical(proof.model_dump()),
                    self.store.clock(),
                ),
            )
            self.store._audit(connection, "upgrade_evidence_registered", proof.id)

    def prepare_onboarding(self, payload):
        """Link truthful resulting-release recovery before removing the source gate.

        This records an upgrade acceptance, never a fabricated onboarding source
        receipt. The lifecycle view recognizes it only after the job succeeds.
        """
        if self.onboarding is None:
            return
        command_id = payload["acceptance_id"]
        with self.store.transaction() as connection:
            prior = connection.execute(
                "SELECT 1 FROM upgrade_onboarding WHERE command_id=?", (command_id,)
            ).fetchone()
            identity = dict(self.store._identity(connection))
        if prior:
            return
        item = self.platform.h.inventory.get(payload["instance"])
        status = self.platform.h.source._transport(vars(item), {"query": "status"})
        if not status["identity_approved"]:
            return
        from app.modules.hosted_admin.application.recovery import RecoveryBinding, RecoveryReport

        binding = RecoveryBinding(
            instance=item.key,
            workspace_id=item.workspace_id,
            binding_revision=status["binding_revision"],
            subject=status["approved_subject"],
            configuration_digest=payload["plan"]["configuration_digest"],
            approved_at=status["approved_at"],
            release=item.release,
        )
        handoff = self.onboarding.ensure(binding, identity)
        stage = "rollback" if payload.get("rollback") else "target"
        result = self.current(payload, stage)
        source = (
            payload
            if not payload.get("rollback")
            else payload | {"operation_id": payload["parent"]}
        )
        recovery = self.current(source, "recovery")
        if result is None or recovery is None:
            raise AdminError("admin_upgrade_recovery_required", 409)
        report = RecoveryReport(
            id=str(uuid4()),
            handoff_id=handoff,
            binding=binding,
            state="verified",
            archive_digest=recovery.archive_digest,
            binding_digest=recovery.encrypted_binding_digest,
            snapshot_marker=recovery.snapshot_marker,
            archive_reference=recovery.archive_reference,
            binding_reference=recovery.id,
            verifier_digest=json.loads(
                self.reports._read(self.reports.directory / "verifier.json", 65536)
            )["verifier_digest"],
            archive=True,
            readback=True,
            restore=True,
            approved_binding=True,
            acceptance=True,
            observed=result.observed,
            expires=recovery.expires,
            completed=result.completed,
        )
        self.reports.publish(report.id, report.model_dump())
        self.onboarding.register(handoff, report.id)
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO upgrade_onboarding VALUES (?,?,?,?)",
                (command_id, payload["operation_id"], handoff, report.id),
            )
            self.store._audit(connection, "upgrade_recovery_linked", command_id)
