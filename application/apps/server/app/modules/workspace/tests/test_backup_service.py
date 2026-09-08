from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore, S3ContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.infrastructure.encrypted_archive import APPLICATION_VERSION, ArchiveError, _validate_header, _validate_manifest_consistency, decrypt_archive_to_zip, make_header, write_encrypted_archive
from app.modules.workspace.application.backup_state import BackupOperationRecord, BackupStateStore, RetentionExecutionError, RetentionRecovery, RetentionResult
from app.platform.config import LocalConfig
from app.platform.locking import WorkspaceOperationLock
from app.platform.secrets import BackupSecretStore, SecretStoreError
from app.platform.product_migrations import current_revision


PASSPHRASE = "a long test backup passphrase"


class MemorySecretStore(BackupSecretStore):
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_passphrase(self, workspace_id: str) -> str | None:
        return self.values.get(workspace_id)

    def set_passphrase(self, workspace_id: str, passphrase: str) -> None:
        self.values[workspace_id] = passphrase

    def delete_passphrase(self, workspace_id: str) -> None:
        self.values.pop(workspace_id, None)


class _BackupFakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def get_bucket_versioning(self, *, Bucket):
        return {"Status": "Enabled"}

    def put_object(self, *, Bucket, Key, Body, Metadata, IfNoneMatch):
        self.objects[(Bucket, Key)] = Body.read()
        return {"VersionId": "version-1", "ETag": "etag-1"}

    def download_file(self, bucket, key, filename, ExtraArgs=None):
        Path(filename).write_bytes(self.objects[(bucket, key)])

    def download_fileobj(self, bucket, key, output, ExtraArgs=None):
        output.write(self.objects[(bucket, key)])

    def delete_object(self, *, Bucket, Key, VersionId=None):
        self.objects.pop((Bucket, Key), None)


class _FailingAuditRecorder:
    def record_change(self, *args, **kwargs) -> None:
        raise sqlite3.DatabaseError("audit unavailable")


class _CompensationFailingSecretStore(MemorySecretStore):
    def delete_passphrase(self, workspace_id: str) -> None:
        raise SecretStoreError("credential cleanup failed")


class BackupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.workspace_path = self.root / "workspace"
        self.backup_path = self.root / "encrypted-backups"
        self.config_path = self.root / "config.local.json"
        self.config_path.write_text(json.dumps({"localWorkspacePath": str(self.workspace_path)}), encoding="utf-8")
        config = LocalConfig(
            config_path=self.config_path,
            workspace_path=self.workspace_path,
            backup_destination_path=self.backup_path,
        )
        self.workspace = WorkspaceService(config)
        self.manifest = self.workspace.initialize()
        self.secrets = MemorySecretStore()
        recorder = AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database))
        self.backups = BackupService(self.workspace, recorder,
                                     lambda database: AuditRecorder(SQLiteAuditRepository(database)), self.secrets)

    def test_encrypted_backup_validates_and_restores_to_a_new_workspace(self) -> None:
        source = self.root / "january.txt"; source.write_text("rent receipt", encoding="utf-8")
        files = FileService(self.workspace, FilesystemContentStore(self.workspace.paths.files), SQLiteFileUnitOfWork(self.workspace.paths.database, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database))))
        attachment = files.add(source, "january.txt", "text/plain")

        result = self.backups.create_backup(PASSPHRASE)

        self.assertTrue(result.archive_path.is_file())
        self.assertEqual(result.archive_contents.manifest["sourceWorkspaceId"], self.manifest.workspace_id)
        self.assertEqual(result.archive_contents.manifest["workspaceFormatVersion"], self.manifest.format_version)
        self.assertEqual(result.archive_contents.manifest["databaseSchemaRevision"], current_revision())
        self.assertNotEqual(result.archive_path.read_bytes()[:2], b"PK")
        self.assertEqual(self.backups.validate_archive(result.archive_path, PASSPHRASE).file_count, 3)

        restored_path = self.root / "restored-workspace"
        restored = self.backups.restore(result.archive_path, PASSPHRASE, restored_path)
        self.assertEqual(restored.workspace_path, restored_path.resolve())
        self.assertEqual((restored_path / "files" / attachment.local_relative_path).read_text(encoding="utf-8"), "rent receipt")
        restored_service = WorkspaceService(LocalConfig(self.config_path, restored_path))
        self.assertEqual(restored_service.open().workspace_id, self.manifest.workspace_id)

    def test_s3_content_is_embedded_and_restored_as_portable_local_content(self) -> None:
        source = self.root / "remote.txt"
        source.write_text("remote evidence", encoding="utf-8")
        client = _BackupFakeS3Client()
        s3 = S3ContentStore(client, "evidence-bucket", "documents")
        recorder = AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database))
        files = FileService(
            self.workspace,
            s3,
            SQLiteFileUnitOfWork(self.workspace.paths.database, recorder),
        )
        attachment = files.add(source, "remote.txt", "text/plain")
        backups = BackupService(
            self.workspace,
            recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
            self.secrets,
            remote_materializer=s3.materialize,
        )

        result = backups.create_backup(PASSPHRASE)
        restored_path = self.root / "restored-s3-workspace"
        backups.restore(result.archive_path, PASSPHRASE, restored_path)

        with sqlite3.connect(restored_path / "database" / "property-management.sqlite") as connection:
            location = connection.execute(
                "SELECT storage_provider, local_relative_path, s3_bucket, s3_object_key "
                "FROM file_content_locations WHERE file_id=?",
                (attachment.id,),
            ).fetchone()
        self.assertEqual(location, ("local", f"managed/{attachment.content_sha256}", None, None))
        self.assertEqual(
            (restored_path / "files" / "managed" / attachment.content_sha256).read_text(encoding="utf-8"),
            "remote evidence",
        )

    def test_backup_rejects_file_content_not_marked_available(self) -> None:
        source = self.root / "quarantined.txt"
        source.write_text("quarantined", encoding="utf-8")
        files = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(
                self.workspace.paths.database,
                AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
            ),
        )
        item = files.add(source, "quarantined.txt", "text/plain")
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute(
                "UPDATE file_content_locations SET storage_state='quarantined' WHERE file_id=?",
                (item.id,),
            )
            connection.commit()
        with self.assertRaisesRegex(BackupError, "Only available"):
            self.backups.create_backup(PASSPHRASE)

    def test_wrong_passphrase_or_tampered_archive_is_rejected(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        with self.assertRaises(BackupError):
            self.backups.validate_archive(result.archive_path, "wrong passphrase")

        contents = bytearray(result.archive_path.read_bytes())
        contents[-1] ^= 1
        result.archive_path.write_bytes(contents)
        with self.assertRaises(BackupError):
            self.backups.validate_archive(result.archive_path, PASSPHRASE)

    def test_archive_manifest_rejects_noncurrent_workspace_or_database_schema(self) -> None:
        header = make_header(workspace_id=self.manifest.workspace_id, package_type="backup")
        manifest = {"applicationVersion": APPLICATION_VERSION, "createdAt": header["createdAt"], "files": [], "packageFormatVersion": 1, "sourceWorkspaceId": self.manifest.workspace_id, "packageType": "backup", "credentialsExcluded": True, "liveJournalFilesExcluded": True, "workspaceFormatVersion": self.manifest.format_version, "databaseSchemaRevision": current_revision()}
        _validate_manifest_consistency(manifest, header)
        manifest["databaseSchemaRevision"] = "not-current"
        with self.assertRaises(ArchiveError): _validate_manifest_consistency(manifest, header)

    def test_archive_application_version_is_producer_metadata_not_a_compatibility_gate(self) -> None:
        header = make_header(workspace_id=self.manifest.workspace_id, package_type="backup")
        manifest = {"applicationVersion": "99.0.0", "createdAt": header["createdAt"], "files": [], "packageFormatVersion": 1, "sourceWorkspaceId": self.manifest.workspace_id, "packageType": "backup", "credentialsExcluded": True, "liveJournalFilesExcluded": True, "workspaceFormatVersion": self.manifest.format_version, "databaseSchemaRevision": current_revision()}
        _validate_manifest_consistency(manifest, header)

    def test_archive_header_rejects_boolean_numeric_kdf_values(self) -> None:
        header = make_header(workspace_id=self.manifest.workspace_id, package_type="backup")
        header["kdf"]["p"] = True
        with self.assertRaises(ArchiveError):
            _validate_header(header)

    def test_validation_rejects_an_authenticated_archive_with_a_corrupt_database(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        corrupted_archive = self.backup_path / "corrupt-database.epm-backup"
        with tempfile.TemporaryDirectory() as temporary_directory:
            zip_path = Path(temporary_directory) / "payload.zip"
            decrypt_archive_to_zip(result.archive_path, PASSPHRASE, zip_path)
            with zipfile.ZipFile(zip_path) as package:
                files = {
                    info.filename: package.read(info.filename)
                    for info in package.infolist()
                    if not info.is_dir()
                }
            database_path = "workspace/database/property-management.sqlite"
            files[database_path] = b"not a SQLite database"
            manifest = json.loads(files["backup-manifest.json"])
            for item in manifest["files"]:
                if item["path"] == database_path:
                    item["bytes"] = len(files[database_path])
                    item["sha256"] = hashlib.sha256(files[database_path]).hexdigest()
            files["backup-manifest.json"] = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as package:
                for path, contents in files.items():
                    package.writestr(path, contents)
            write_encrypted_archive(
                zip_path,
                corrupted_archive,
                make_header(workspace_id=self.manifest.workspace_id, package_type="backup"),
                PASSPHRASE,
            )

        with self.assertRaisesRegex(BackupError, "SQLite"):
            self.backups.validate_archive(corrupted_archive, PASSPHRASE)

    def test_backup_destination_cannot_be_inside_the_live_workspace(self) -> None:
        with self.assertRaises(BackupError):
            self.backups.create_backup(PASSPHRASE, output_path=self.workspace.paths.backups / "unsafe")

    def test_automatic_backup_is_opt_in_and_uses_the_secret_store(self) -> None:
        self.backups.enable_automatic_backups(PASSPHRASE)
        self.assertEqual(self.secrets.get_passphrase(self.manifest.workspace_id), PASSPHRASE)

        result = self.backups.run_due_automatic_backup()
        self.assertIsNotNone(result)
        self.assertIsNone(self.backups.run_due_automatic_backup())
        self.assertTrue(self.backups.backup_status()["automaticEnabled"])

        self.backups.disable_automatic_backups()
        self.assertIsNone(self.secrets.get_passphrase(self.manifest.workspace_id))
        self.assertFalse(self.backups.backup_status()["automaticEnabled"])

    def test_automatic_backup_failure_is_not_reported_as_not_due(self) -> None:
        self.backups.enable_automatic_backups(PASSPHRASE)
        self.secrets.delete_passphrase(self.manifest.workspace_id)

        with self.assertRaisesRegex(BackupError, "Automatic backup failed"):
            self.backups.run_due_automatic_backup()

        self.assertEqual(self.backups.backup_status()["lastFailure"]["reason"], "Automatic backup credential is unavailable.")

    def test_automatic_backup_compensation_failure_is_controlled(self) -> None:
        secrets = _CompensationFailingSecretStore()
        backups = BackupService(self.workspace, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
                                lambda database: AuditRecorder(SQLiteAuditRepository(database)), secrets)
        with patch.object(backups.state, "configure_automatic", side_effect=BackupError("state unavailable")):
            with self.assertRaisesRegex(BackupError, "may be inconsistent"):
                backups.enable_automatic_backups(PASSPHRASE)

    def test_failure_is_retained_as_a_typed_operation_history_record(self) -> None:
        with self.assertRaises(BackupError):
            self.backups.create_backup("too short")
        record = self.backups.backup_status()["history"][0]
        self.assertEqual(record["validationResult"], "failed")
        self.assertFalse(record["validated"])
        self.assertIsNone(record["archiveSha256"])
        self.assertIsNotNone(record["failureReason"])

    def test_retention_failure_does_not_reverse_a_published_backup_success(self) -> None:
        with patch.object(self.backups.state, "apply_retention", side_effect=BackupError("retention unavailable")):
            result = self.backups.create_backup(PASSPHRASE)
        status = self.backups.backup_status()
        self.assertTrue(result.archive_path.exists())
        self.assertEqual(status["history"][0]["validationResult"], "succeeded")
        self.assertIsNone(status["lastFailure"])
        self.assertEqual(status["lastRetentionFailure"]["reason"], "retention unavailable")

    def test_retention_audit_records_the_bounded_deletion_outcome(self) -> None:
        outcome = RetentionResult(considered_count=3, retained_count=1, deleted_count=2,
                                  deleted_archives=("old-a.epm-backup", "old-b.epm-backup"))
        pending = RetentionRecovery(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "11111111-1111-4111-8111-111111111111", datetime.now(UTC),
            "deleted", {"destination": str(self.backup_path), "archiveName": None, **outcome.to_dict()}, outcome,
        )
        with (patch.object(self.backups.state, "apply_retention", return_value=outcome),
              patch.object(self.backups.state, "recover_pending_retention", side_effect=(None, pending))):
            self.backups.create_backup(PASSPHRASE)
        event = self.backups.audit_recorder.repository.history("backup_retention")[0]
        self.assertEqual(event.action, "deleted")
        self.assertEqual(event.after_snapshot["deletedArchiveCount"], 2)
        self.assertEqual(event.after_snapshot["deletedArchives"], ["old-a.epm-backup", "old-b.epm-backup"])

    def test_retention_audit_preserves_considered_and_retained_counts(self) -> None:
        first = self.backups.create_backup(PASSPHRASE)
        duplicate = first.archive_path.with_name("count-duplicate.epm-backup")
        duplicate.write_bytes(first.archive_path.read_bytes())
        state = self.backups.state.load()
        original = state.retention_inventory[0]
        self.backups.state.save(replace(state, retention_inventory=(original, replace(original, archive_name=duplicate.name))))

        self.backups.create_backup(PASSPHRASE)

        event = self.backups.audit_recorder.repository.history("backup_retention", action="deleted")[0]
        self.assertEqual(event.after_snapshot["consideredArchiveCount"], 3)
        self.assertEqual(event.after_snapshot["retainedArchiveCount"], 1)

    def test_recovery_bounds_deleted_names_while_preserving_the_full_count(self) -> None:
        names = [f"expired-{index}.epm-backup" for index in range(101)]
        operation_at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
        self.backups.state._save_retention_journal({
            "auditEventId": "12121212-1212-4121-8121-121212121212",
            "archiveName": "new.epm-backup",
            "destination": str(self.backup_path),
            "archiveNames": names,
            "consideredArchiveCount": 101,
            "correlationId": "13131313-1313-4131-8131-131313131313",
            "deletedArchiveCount": 0,
            "deletedArchiveNames": [],
            "operationAt": operation_at.isoformat(),
            "retainedArchiveCount": 0,
            "state": "deletion_pending",
        })
        recovered = self.backups.state.recover_pending_retention()
        assert recovered is not None
        self.assertEqual(recovered.result.deleted_count, 101)
        self.assertEqual(len(recovered.audit_after["deletedArchives"]), 100)
        self.assertTrue(recovered.audit_after["deletedArchivesTruncated"])
        self.assertEqual(recovered.occurred_at, operation_at)

    def test_audit_pending_journal_requires_the_exact_bounded_deletion_names(self) -> None:
        journal = {
            "auditEventId": "10101010-1010-4010-8010-101010101010",
            "archiveName": "new.epm-backup",
            "destination": str(self.backup_path),
            "archiveNames": ["expired.epm-backup"],
            "consideredArchiveCount": 1,
            "correlationId": "20202020-2020-4020-8020-202020202020",
            "deletedArchiveCount": 1,
            "deletedArchiveNames": [],
            "operationAt": datetime.now(UTC).isoformat(),
            "retainedArchiveCount": 0,
            "state": "audit_pending",
        }
        self.backups.state.retention_journal_path.write_text(json.dumps(journal), encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "Retention recovery journal"):
            self.backups.state.recover_pending_retention()

    def test_recovery_audit_uses_the_journal_destination(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        outcome = RetentionResult(considered_count=1, retained_count=0, deleted_count=1,
                                  deleted_archives=("old.epm-backup",))
        original_destination = self.root / "prior-destination"
        recovered = RetentionRecovery(
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "44444444-4444-4444-8444-444444444444",
            datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC),
            "deleted", {"destination": str(original_destination), "archiveName": None, **outcome.to_dict()}, outcome,
        )
        with (patch.object(self.backups.state, "recover_pending_retention", side_effect=(recovered, None)),
              patch.object(self.backups.state, "apply_retention", return_value=outcome)):
            self.backups._apply_retention(result, self.manifest.workspace_id, "88888888-8888-4888-8888-888888888888")
        event = self.backups.audit_recorder.repository.history("backup_retention", action="deleted")[0]
        self.assertEqual(event.after_snapshot["destination"], str(original_destination))
        self.assertEqual(event.occurred_at, datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC))

    def test_retention_reconciles_completed_deletions_when_state_save_fails(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        duplicate = result.archive_path.with_name("duplicate.epm-backup")
        duplicate.write_bytes(result.archive_path.read_bytes())
        state = self.backups.state.load()
        original = state.retention_inventory[0]
        self.backups.state.save(replace(state, retention_inventory=(original, replace(original, archive_name=duplicate.name))))
        original_save = self.backups.state.save
        saves = 0

        def fail_once_then_save(updated):
            nonlocal saves
            saves += 1
            if saves == 1:
                raise BackupError("state save failed")
            original_save(updated)

        with patch.object(self.backups.state, "save", side_effect=fail_once_then_save):
            with self.assertRaises(RetentionExecutionError) as raised:
                self.backups.state.apply_retention(self.manifest.workspace_id, result.archive_path.parent)
        self.assertEqual(raised.exception.result.deleted_count, 1)
        self.assertEqual(len(self.backups.state.load().retention_inventory), 1)
        self.assertTrue(self.backups.state.retention_journal_path.exists())

    def test_fresh_store_recovers_interrupted_retention_with_its_original_correlation_id(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        duplicate = result.archive_path.with_name("interrupted-duplicate.epm-backup")
        duplicate.write_bytes(result.archive_path.read_bytes())
        state = self.backups.state.load()
        original = state.retention_inventory[0]
        self.backups.state.save(replace(state, retention_inventory=(original, replace(original, archive_name=duplicate.name))))

        with patch.object(self.backups.state, "save", side_effect=BackupError("state save failed")):
            with self.assertRaises(RetentionExecutionError):
                self.backups.state.apply_retention(self.manifest.workspace_id, result.archive_path.parent,
                                                   correlation_id="55555555-5555-4555-8555-555555555555")
        self.assertTrue(self.backups.state.retention_journal_path.exists())

        recovered = BackupStateStore(self.workspace.paths.backups).recover_pending_retention()
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered.correlation_id, "55555555-5555-4555-8555-555555555555")
        self.assertEqual(recovered.result.deleted_count, 1)
        self.assertEqual(len(BackupStateStore(self.workspace.paths.backups).load().retention_inventory), 1)
        self.assertTrue(self.backups.state.retention_journal_path.exists())
        retried = BackupStateStore(self.workspace.paths.backups).recover_pending_retention()
        self.assertIsNotNone(retried)
        assert retried is not None
        self.assertEqual(retried.audit_event_id, recovered.audit_event_id)

    def test_recovery_audit_failure_keeps_journal_for_an_idempotent_retry(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        duplicate = result.archive_path.with_name("audit-retry-duplicate.epm-backup")
        duplicate.write_bytes(result.archive_path.read_bytes())
        state = self.backups.state.load()
        original = state.retention_inventory[0]
        self.backups.state.save(replace(state, retention_inventory=(original, replace(original, archive_name=duplicate.name))))
        with patch.object(self.backups.state, "save", side_effect=BackupError("state save failed")):
            with self.assertRaises(RetentionExecutionError):
                self.backups.state.apply_retention(self.manifest.workspace_id, result.archive_path.parent,
                                                   correlation_id="66666666-6666-4666-8666-666666666666")
        BackupStateStore(self.workspace.paths.backups).recover_pending_retention()

        with patch.object(self.backups.audit_recorder, "record_change", side_effect=sqlite3.DatabaseError("audit unavailable")):
            self.backups._apply_retention(result, self.manifest.workspace_id, "99999999-9999-4999-8999-999999999999")
        self.assertTrue(self.backups.state.retention_journal_path.exists())

        self.backups._apply_retention(result, self.manifest.workspace_id, "99999999-9999-4999-8999-999999999999")
        recovered_events = self.backups.audit_recorder.repository.history("backup_retention", action="deleted")
        self.assertEqual(len(recovered_events), 1)
        self.assertFalse(self.backups.state.retention_journal_path.exists())

    def test_recovery_audit_retry_after_commit_does_not_duplicate_the_event(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        duplicate = result.archive_path.with_name("committed-audit-duplicate.epm-backup")
        duplicate.write_bytes(result.archive_path.read_bytes())
        state = self.backups.state.load()
        original = state.retention_inventory[0]
        self.backups.state.save(replace(state, retention_inventory=(original, replace(original, archive_name=duplicate.name))))
        with patch.object(self.backups.state, "save", side_effect=BackupError("state save failed")):
            with self.assertRaises(RetentionExecutionError):
                self.backups.state.apply_retention(self.manifest.workspace_id, result.archive_path.parent,
                                                   correlation_id="77777777-7777-4777-8777-777777777777")
        BackupStateStore(self.workspace.paths.backups).recover_pending_retention()

        with patch.object(self.backups.state, "complete_retention_audit", side_effect=BackupError("interrupted after audit")):
            self.backups._apply_retention(result, self.manifest.workspace_id, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.assertTrue(self.backups.state.retention_journal_path.exists())

        self.backups._apply_retention(result, self.manifest.workspace_id, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        recovered_events = self.backups.audit_recorder.repository.history("backup_retention", action="deleted")
        self.assertEqual(len(recovered_events), 1)
        self.assertFalse(self.backups.state.retention_journal_path.exists())

    def test_recovery_failure_does_not_reverse_a_durable_backup(self) -> None:
        partial = RetentionResult(considered_count=1, retained_count=0, deleted_count=1,
                                  deleted_archives=("old.epm-backup",))
        with (patch.object(self.backups.state, "apply_retention", side_effect=RetentionExecutionError("retention failed", partial)),
              patch.object(self.backups.state, "recover_pending_retention", side_effect=(None, BackupError("journal unavailable")))):
            result = self.backups.create_backup(PASSPHRASE)
        self.assertTrue(result.archive_path.exists())

    def test_duplicate_audit_id_must_match_the_expected_recovery_event(self) -> None:
        event_id = "22222222-2222-4222-8222-222222222222"
        with sqlite3.connect(self.workspace.paths.database) as connection:
            self.backups.audit_recorder.record_change(
                connection, entity_type="other", entity_id=event_id, action="created", before=None,
                after={"unexpected": True}, actor_kind="system", reason="other", correlation_id="other",
                event_id=event_id,
            )
        with self.assertRaisesRegex(BackupError, "Operational audit"):
            self.backups._audit("backup_retention", event_id, "recovered", {"recovery": True},
                                "expected-correlation", event_id=event_id)

    def test_malformed_retention_journal_is_a_controlled_error(self) -> None:
        self.backups.state.retention_journal_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "Retention recovery journal"):
            self.backups.state.complete_retention_audit("anything")

    def test_unhashable_retention_journal_state_is_a_controlled_error(self) -> None:
        journal = {
            "auditEventId": "33333333-3333-4333-8333-333333333333",
            "archiveName": None,
            "destination": str(self.backup_path),
            "archiveNames": [],
            "consideredArchiveCount": 0,
            "correlationId": "44444444-4444-4444-8444-444444444444",
            "deletedArchiveCount": 0,
            "deletedArchiveNames": [],
            "operationAt": datetime.now(UTC).isoformat(),
            "retainedArchiveCount": 0,
            "state": [],
        }
        self.backups.state.retention_journal_path.write_text(json.dumps(journal), encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "Retention recovery journal"):
            self.backups.state.recover_pending_retention()

    def test_invalid_retention_journal_uuid_is_a_controlled_error(self) -> None:
        journal = {
            "auditEventId": "not-a-uuid",
            "archiveName": None,
            "destination": str(self.backup_path),
            "archiveNames": [],
            "consideredArchiveCount": 0,
            "correlationId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "deletedArchiveCount": 0,
            "deletedArchiveNames": [],
            "operationAt": datetime.now(UTC).isoformat(),
            "retainedArchiveCount": 0,
            "state": "audit_pending",
        }
        self.backups.state.retention_journal_path.write_text(json.dumps(journal), encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "invalid retention audit event ID"):
            self.backups.state.recover_pending_retention()

    def test_export_does_not_replace_last_successful_backup_time(self) -> None:
        self.backups.create_backup(PASSPHRASE)
        backup_time = self.backups.backup_status()["lastSuccessAt"]
        self.backups.create_backup(PASSPHRASE, package_type="export", output_path=self.root / "portfolio-export")
        self.assertEqual(self.backups.backup_status()["lastSuccessAt"], backup_time)

    def test_backup_and_export_failure_statuses_clear_only_after_their_own_success(self) -> None:
        with self.assertRaises(BackupError):
            self.backups.create_backup("too short")
        self.backups.create_backup(PASSPHRASE, package_type="export", output_path=self.root / "portfolio-export")
        self.assertIsNotNone(self.backups.backup_status()["lastFailure"])
        self.backups.create_backup(PASSPHRASE)
        self.assertIsNone(self.backups.backup_status()["lastFailure"])

    def test_successful_retention_clears_its_previous_failure_and_prunes_inventory(self) -> None:
        with patch.object(self.backups.state, "apply_retention", side_effect=BackupError("retention unavailable")):
            result = self.backups.create_backup(PASSPHRASE)
        self.assertIsNotNone(self.backups.backup_status()["lastRetentionFailure"])
        result.archive_path.unlink()
        self.backups.state.apply_retention(self.manifest.workspace_id, result.archive_path.parent)
        self.assertIsNone(self.backups.backup_status()["lastRetentionFailure"])
        self.assertEqual(self.backups.state.load().retention_inventory, ())

    def test_backup_retention_inventory_is_not_limited_by_operation_history(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        state = self.backups.state.load()
        exports = tuple(
            BackupOperationRecord.failure("export failed", "export")
            for _ in range(101)
        )
        self.backups.state.save(state.__class__(
            automatic_enabled=state.automatic_enabled,
            history=exports[:100],
            retention_inventory=state.retention_inventory,
            last_backup_failure=state.last_backup_failure,
            last_export_failure=exports[0],
            last_retention_failure=state.last_retention_failure,
            last_success_at=state.last_success_at,
            next_automatic_backup_at=state.next_automatic_backup_at,
        ))
        self.backups.state.apply_retention(self.manifest.workspace_id, result.archive_path.parent)
        self.assertTrue(result.archive_path.exists())
        self.assertEqual(len(self.backups.state.load().retention_inventory), 1)

    def test_retention_preserves_inventory_for_other_destinations(self) -> None:
        first = self.backups.create_backup(PASSPHRASE, output_path=self.root / "first-destination" / "first")
        second = self.backups.create_backup(PASSPHRASE, output_path=self.root / "second-destination" / "second")
        self.backups.state.apply_retention(self.manifest.workspace_id, second.archive_path.parent)
        inventory = self.backups.state.load().retention_inventory
        self.assertEqual({record.destination for record in inventory}, {first.archive_path.parent, second.archive_path.parent})

    def test_malformed_automatic_backup_state_is_a_controlled_error(self) -> None:
        self.backups.state.path.write_text(json.dumps({"version": 2, "automaticEnabled": True, "history": [], "nextAutomaticBackupAt": "2026-01-01T00:00:00"}), encoding="utf-8")
        with self.assertRaises(BackupError): self.backups.run_due_automatic_backup()

    @unittest.skipUnless(os.name == "posix", "POSIX permission modes are not available")
    def test_existing_backup_destination_permissions_are_not_changed(self) -> None:
        self.backup_path.mkdir()
        self.backup_path.chmod(0o755)

        with self.assertWarnsRegex(RuntimeWarning, "same volume"):
            self.backups.configure_destination(self.backup_path)

        self.assertEqual(self.backup_path.stat().st_mode & 0o777, 0o755)

    def test_workspace_operations_fail_fast_when_another_process_holds_the_lock(self) -> None:
        lock_path = self.workspace_path.parent / f".{self.workspace_path.name}.operations.lock"
        with WorkspaceOperationLock(lock_path):
            with self.assertRaises(BackupError):
                self.backups.create_backup(PASSPHRASE)

    def test_restore_does_not_require_the_configured_workspace_to_be_available(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        unavailable_workspace = self.root / "unavailable-workspace"
        self.workspace_path.replace(unavailable_workspace)

        restored_path = self.root / "restored-after-loss"
        restored = self.backups.restore(result.archive_path, PASSPHRASE, restored_path)

        self.assertEqual(restored.workspace_path, restored_path.resolve())
        self.assertTrue((restored_path / "database" / "property-management.sqlite").is_file())

    def test_restore_rejects_an_internal_destination_without_creating_lock_artifacts(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        destination = self.workspace.paths.files / "must-not-create"

        with self.assertRaises(BackupError):
            self.backups.restore(result.archive_path, PASSPHRASE, destination)

        self.assertFalse(destination.exists())

    def test_restore_respects_the_active_workspace_operation_lock_when_available(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        lock_path = self.workspace_path.parent / f".{self.workspace_path.name}.operations.lock"
        with WorkspaceOperationLock(lock_path):
            with self.assertRaises(BackupError):
                self.backups.restore(result.archive_path, PASSPHRASE, self.root / "restored-workspace")

    def test_restore_decrypts_the_archive_once(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        with patch(
            "app.modules.workspace.application.backup_service.decrypt_archive_to_zip",
            wraps=decrypt_archive_to_zip,
        ) as decrypt:
            self.backups.restore(result.archive_path, PASSPHRASE, self.root / "restored-workspace")

        self.assertEqual(decrypt.call_count, 1)

    def test_backup_validates_the_live_workspace_once(self) -> None:
        with patch.object(self.backups.archives, "validate_workspace", wraps=self.backups.archives.validate_workspace) as validate:
            self.backups.create_backup(PASSPHRASE)

        self.assertEqual(validate.call_count, 1)

    def test_failed_complete_validation_does_not_publish_an_archive(self) -> None:
        with patch.object(self.backups.archives, "validate_archive", side_effect=BackupError("validation failed")):
            with self.assertRaisesRegex(BackupError, "validation failed"):
                self.backups.create_backup(PASSPHRASE)

        self.assertEqual(list(self.backup_path.glob("*.epm-backup")), [])

    def test_post_publication_audit_failure_removes_the_archive(self) -> None:
        with patch.object(self.backups.audit_recorder, "record_change", side_effect=sqlite3.DatabaseError("audit unavailable")):
            with self.assertRaisesRegex(BackupError, "Operational audit"):
                self.backups.create_backup(PASSPHRASE)
        self.assertEqual(list(self.backup_path.glob("*.epm-backup")), [])

    def test_restore_audit_failure_keeps_destination_unpublished(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        self.backups.restored_audit_recorder = lambda database: _FailingAuditRecorder()
        destination = self.root / "restore-audit-failure"
        with self.assertRaisesRegex(BackupError, "audit"):
            self.backups.restore(result.archive_path, PASSPHRASE, destination)
        self.assertFalse(destination.exists())

    def test_archive_publication_never_clobbers_and_rejects_non_atomic_filesystems(self) -> None:
        payload = self.root / "payload.zip"
        with zipfile.ZipFile(payload, "w") as package:
            package.writestr("placeholder", b"payload")
        output = self.root / "existing.epm-backup"
        output.write_bytes(b"do not replace")
        with self.assertRaises(ArchiveError):
            write_encrypted_archive(payload, output, make_header(workspace_id=self.manifest.workspace_id, package_type="backup"),
                                    PASSPHRASE, validator=lambda _: None)
        self.assertEqual(output.read_bytes(), b"do not replace")

        fallback = self.root / "fallback.epm-backup"
        with patch("app.modules.workspace.infrastructure.encrypted_archive.os.link", side_effect=OSError("unsupported")):
            with self.assertRaisesRegex(ArchiveError, "atomic no-replace"):
                write_encrypted_archive(payload, fallback, make_header(workspace_id=self.manifest.workspace_id, package_type="backup"),
                                        PASSPHRASE, validator=lambda _: None)
        self.assertFalse(fallback.exists())

    def test_destination_configuration_rejects_filesystems_without_atomic_publication(self) -> None:
        with patch("app.modules.workspace.application.backup_policy.os.link", side_effect=OSError("unsupported")):
            with self.assertRaisesRegex(BackupError, "atomic archive publication"):
                self.backups.configure_destination(self.root / "unsupported-destination")
