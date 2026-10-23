"""Seven daily points, verified bytes, durable ordering and explicit retry failures."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.hosted_access.application.recovery_publication import (
    RecoveryPublicationService,
    RecoveryPublicationError,
)
from app.modules.hosted_access.infrastructure.recovery_publication import (
    FileRecoveryLedger,
    RecoveryConfiguration,
    R2RecoveryObjectStore,
)


class Ledger:
    def __init__(self):
        self.points, self.pending = [], False
        self.fail = False

    def load(self):
        return list(self.points), self.pending

    def save(self, points, *, retention_pending):
        if self.fail:
            raise RecoveryPublicationError("ledger unavailable")
        self.points, self.pending = list(points), retention_pending


class Store:
    def __init__(self, ledger):
        self.objects = {}
        self.ledger = ledger
        self.corrupt = False
        self.fail_delete = False

    def upload(self, key, source, size):
        self.objects[key] = source.read_bytes()

    def digest(self, key, size):
        return "0" * 64 if self.corrupt else sha256(self.objects[key]).hexdigest()

    def delete(self, key):
        assert self.ledger.pending  # Durable proof precedes even the first prune.
        if self.fail_delete:
            raise RecoveryPublicationError("prune failed")
        self.objects.pop(key, None)


@pytest.fixture
def publication(tmp_path):
    ledger = Ledger()
    store = Store(ledger)
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    service = RecoveryPublicationService(store, ledger, f"epm/{uuid4()}/{uuid4()}", now=lambda: now)
    return service, store, ledger, tmp_path, now


def publish(context, created, body=b"validated encrypted bytes"):
    service, _, _, root, _ = context
    source = root / "source.epm-backup"
    source.write_bytes(body)
    return service.publish(
        source, digest=sha256(body).hexdigest(), size=len(body), created_at=created
    )


def test_seven_successful_daily_points_and_same_day_retry_do_not_inflate_retention(publication):
    service, store, ledger, _, now = publication
    for day in range(9):
        publish(publication, now - timedelta(days=8 - day))
    assert len(ledger.points) == len(store.objects) == 7
    previous_keys = set(store.objects)
    publish(publication, now)
    assert set(store.objects) == previous_keys
    publish(publication, now, b"new same day validated bytes")
    assert len(ledger.points) == len(store.objects) == 7
    assert not ledger.pending
    assert service.status()["needsAttention"] is False


def test_bad_readback_never_changes_previous_proof_or_prunes(publication):
    _, store, ledger, _, now = publication
    publish(publication, now - timedelta(days=1))
    before = list(ledger.points)
    store.corrupt = True
    with pytest.raises(RecoveryPublicationError, match="checksum"):
        publish(publication, now)
    assert ledger.points == before
    assert before[0].key in store.objects


def test_ledger_failure_prevents_all_pruning(publication):
    _, store, ledger, _, now = publication
    publish(publication, now - timedelta(days=1))
    before = list(ledger.points)
    ledger.fail = True
    with pytest.raises(RecoveryPublicationError):
        publish(publication, now)
    assert ledger.points == before and before[0].key in store.objects


def test_failed_retention_keeps_new_proof_and_reports_attention(publication):
    service, store, ledger, _, now = publication
    for day in range(7):
        publish(publication, now - timedelta(days=7 - day))
    store.fail_delete = True
    point, pending = publish(publication, now)
    assert pending and ledger.pending and point in ledger.points
    assert point.key in store.objects and service.status()["needsAttention"]
    store.fail_delete = False
    publish(publication, now)
    assert len(ledger.points) == 7 and not ledger.pending


def test_old_seed_does_not_make_recovery_age_current(publication):
    service, _, _, _, now = publication
    publish(publication, now - timedelta(days=3))
    assert service.status()["recoveryAgeSeconds"] == 3 * 86400
    assert service.status()["needsAttention"]
    with pytest.raises(RecoveryPublicationError, match="predates"):
        publish(publication, now - timedelta(days=4))


def test_r2_readback_verifies_bytes_not_etag_and_closes_on_failure():
    client = Mock()
    stream = BytesIO(b"wrong bytes")
    client.get_object.return_value = {"ContentLength": 123, "Body": stream}
    with pytest.raises(RecoveryPublicationError):
        R2RecoveryObjectStore(client, "private-bucket").digest("key", 4)
    assert stream.closed
    client.delete_object.assert_not_called()


def test_private_file_ledger_round_trip_and_binding_validation(tmp_path):
    config = RecoveryConfiguration(
        deployment_id=uuid4(),
        workspace_id=uuid4(),
        endpoint="https://" + "a" * 32 + ".r2.cloudflarestorage.com",
        bucket="private-backups",
        access_key_id="never-record-this",
        secret_access_key="never-record-secret",
        ledger_path=tmp_path / "verification.json",
    )
    ledger = FileRecoveryLedger(config)
    ledger.save([], retention_pending=True)
    assert ledger.load() == ([], True)
    assert "never-record" not in config.ledger_path.read_text()
    foreign = FileRecoveryLedger(config.model_copy(update={"workspace_id": uuid4()}))
    with pytest.raises(RecoveryPublicationError):
        foreign.load()
