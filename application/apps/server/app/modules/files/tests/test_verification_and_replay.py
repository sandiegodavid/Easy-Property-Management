"""Regression tests for S3 verification continuation (Finding 2) and upload replay rollback (Finding 3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.modules.files.application.service import FileService
from app.modules.files.application.verification import FileStorageVerificationService


@dataclass(frozen=True)
class _FakeRecord:
    id: str
    storage_provider: str = "s3"
    storage_state: str = "available"
    verified_at: str | None = None
    local_relative_path: str | None = None
    s3_bucket: str | None = "bucket"
    s3_object_key: str | None = "prefix/obj-1"
    s3_version_id: str | None = "v1"


class _FakeVerificationUoW:
    def __init__(self, records: list[_FakeRecord]) -> None:
        self._records = records
        self.updates = 0
        self.resolved = 0

    def files_for_verification(self):
        return list(self._records)

    def replace_storage_verification(self, *_args):
        self.updates += 1

    def record_cleanup_resolved(self, _correlation: str):
        self.resolved += 1


class _CountingS3Store:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.path_for_calls = 0
        self.reconcile_calls = 0

    def path_for(self, item: _FakeRecord) -> Path:
        self.path_for_calls += 1
        p = self.tmp_path / f"{item.id}.tmp"
        p.write_bytes(b"ok")
        return p

    def reconcile(self, retained, continuation=None):
        self.reconcile_calls += 1
        if continuation is None:
            return SimpleNamespace(
                referenced=set(),
                orphaned=set(),
                unverifiable=set(),
                continuation="page-2",
                incomplete=True,
            )
        return SimpleNamespace(
            referenced=set(retained),
            orphaned=set(),
            unverifiable=set(),
            continuation=None,
            incomplete=False,
        )


def test_s3_verification_continuation_does_not_rehash_files_on_subsequent_pages(tmp_path: Path):
    records = [
        _FakeRecord(id=str(uuid4()), s3_object_key="prefix/obj-1", s3_version_id="v1"),
        _FakeRecord(id=str(uuid4()), s3_object_key="prefix/obj-2", s3_version_id="v2"),
    ]
    uow = _FakeVerificationUoW(records)
    store = _CountingS3Store(tmp_path)
    verifier = FileStorageVerificationService(uow, {"s3": store})

    first = verifier.verify()
    assert first["complete"] is False
    assert first["continuation"] is not None
    assert store.path_for_calls == 2
    assert uow.updates == 2

    second = verifier.verify(continuation=first["continuation"])
    assert second["complete"] is True
    assert second["continuation"] is None
    # Per-file content verification must NOT re-run on continuation pages.
    assert store.path_for_calls == 2
    assert uow.updates == 2
    assert store.reconcile_calls == 2
    assert uow.resolved == 1


def test_upload_replay_rollback_failure_does_not_double_rollback_and_records_cleanup_attention(
    tmp_path: Path,
):
    rollback_calls = 0
    attention_recorded: list[object] = []

    class _FailingRollbackPublication:
        publication_id = "pub-1"
        storage_provider = "local"
        storage_state = "available"
        content_sha256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        size_bytes = 5
        local_relative_path = "objects/aa/bb"
        s3_bucket = None
        s3_object_key = None
        s3_version_id = None
        provider_etag = None

        def rollback(self):
            nonlocal rollback_calls
            rollback_calls += 1
            raise OSError("transient unlink failure")

        def commit(self):
            raise AssertionError("commit must not be called on replay")

    class _FakeStore:
        def store(self, *_args, **_kwargs):
            return _FailingRollbackPublication()

    class _FakeExistingReceipt:
        def replay(self, _action, _request):
            return {"id": "existing-file-id", "replayed": True}

    class _FakeTx:
        def operation_by_key(self, _key):
            return _FakeExistingReceipt()

    class _FakeUoW:
        def command_receipt(self, **_kwargs):
            return None

        def command(self, fn):
            return fn(_FakeTx())

    class _FakeValidator:
        entity_types = ("property",)
        allows_generic_upload = True

        def validate_create(self, *_args, **_kwargs):
            return None

        def validate_retained(self, *_args, **_kwargs):
            return None

    svc = FileService(
        SimpleNamespace(),
        _FakeStore(),
        _FakeUoW(),
        link_validators=(_FakeValidator(),),
    )
    svc._try_record_cleanup_attention = lambda err, corr: attention_recorded.append((err, corr))

    src = tmp_path / "front.png"
    src.write_bytes(b"hello")
    result = svc.upload(
        entity_type="property",
        entity_id=str(uuid4()),
        purpose="photo",
        original_name="front.png",
        media_type="image/png",
        source=src,
        idempotency_key=str(uuid4()),
    )
    assert result == {"id": "existing-file-id", "replayed": True}
    assert rollback_calls == 1
    assert len(attention_recorded) == 1
